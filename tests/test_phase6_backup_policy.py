"""Phase 6 second round — backup policy / retention / restore orchestration
tests (spec 5.7 / 5.8 / 5.9).

Covers: BackupPolicy validation, atomic sidecar manifests, listing with
corrupt/orphan annotation, retention (pattern-only deletion, newest N
kept, pairs deleted, foreign files untouched), verify_backup, the
restore_verified fail-closed orchestration (corrupt/hash-mismatch/unknown
alembic revision / active -wal target all refused, atomic copy, post-copy
re-check, upgrade_db idempotent + restart after restore), backup during a
concurrent WAL write workload (no torn snapshot), assert_engine_idle
advisory checks, and the BackupScheduler lifecycle (interval + wake,
on_startup, manual/disabled no-op).
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from mathtutor.infrastructure.backup import (
    BackupError,
    BackupManifest,
    BackupPolicy,
    BackupScheduler,
    BackupService,
)

pytestmark = pytest.mark.asyncio

# Encrypted exports plus manifest/retention checks can exceed ten seconds on
# a busy Windows runner. This is a deadlock guard, not a backup speed contract;
# the tests still synchronize on completed cycles and assert all their results.
BACKUP_CYCLE_TIMEOUT = 60.0


async def _seed_users(engine) -> None:
    from mathtutor.infrastructure.schema import users

    async with engine.begin() as conn:
        await conn.execute(
            users.insert().values(
                user_id="u-1", username="alice", role="student",
                created_at="2026-08-20T00:00:00+00:00",
            )
        )


def _integrity(path) -> str:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


class _ObservedBackupScheduler(BackupScheduler):
    """Observe completed backup + retention cycles, including slow exports."""

    def __init__(self, service: BackupService, policy: BackupPolicy) -> None:
        super().__init__(service, policy)
        self.completed_cycles: asyncio.Queue[BackupManifest | None] = asyncio.Queue()

    async def run_once(self) -> BackupManifest | None:
        manifest = await super().run_once()
        self.completed_cycles.put_nowait(manifest)
        return manifest

    async def next_cycle(self) -> BackupManifest:
        manifest = await asyncio.wait_for(self.completed_cycles.get(), timeout=BACKUP_CYCLE_TIMEOUT)
        assert manifest is not None, "scheduled backup failed"
        return manifest


# ------------------------------------------------------------ policy


async def test_policy_validation():
    with pytest.raises(ValueError, match="未知备份模式"):
        BackupPolicy(mode="hourly")
    with pytest.raises(ValueError, match="retention_limit"):
        BackupPolicy(mode="interval", retention_limit=0)
    with pytest.raises(ValueError, match="interval_seconds"):
        BackupPolicy(mode="interval", interval_seconds=0.0)
    policy = BackupPolicy(
        mode="interval", backup_dir="sub/bk", retention_limit=3,
        interval_seconds=60.0,
    )
    assert policy.backup_dir is not None
    assert policy.backup_dir == Path("sub/bk")
    assert BackupPolicy().mode == "manual"


# ------------------------------------------------- sidecar manifest


@pytest_asyncio.fixture()
async def db(tmp_path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "source.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def test_create_backup_writes_sidecar_manifest_atomically(db, tmp_path):
    await _seed_users(db)
    service = BackupService(db)
    backup = tmp_path / "snap.db"
    manifest = await service.create_backup(backup)

    sidecar = tmp_path / "snap.db.manifest.json"
    assert sidecar.is_file()
    assert json.loads(sidecar.read_text(encoding="utf-8")) == manifest.to_dict()
    # 原子写：目录里不允许残留 *.tmp-* 半成品。
    assert not list(tmp_path.glob("*.tmp-*"))
    assert BackupManifest.from_dict(json.loads(sidecar.read_text())) == manifest


async def test_create_backup_into_backup_dir_unique_names(db, tmp_path):
    """backup_dir 参数：默认命名 + 同秒冲突自动加序号，绝不覆盖。"""
    service = BackupService(db)
    directory = tmp_path / "bk"
    m1 = await service.create_backup(backup_dir=directory)
    m2 = await service.create_backup(backup_dir=directory)
    assert m1.backup_path != m2.backup_path
    assert Path(m1.backup_path).parent == directory.resolve()
    assert ".backup-" in Path(m1.backup_path).name
    assert Path(m1.backup_path).name.endswith(".db")
    assert (Path(m1.backup_path)).is_file() and (Path(m2.backup_path)).is_file()
    # 两者都带 sidecar manifest 且都能被 list 找到。
    entries = BackupService.list_backups(directory)
    assert len(entries) == 2
    assert all(e.status == "ok" for e in entries)

    with pytest.raises(ValueError, match="只能指定其一"):
        await service.create_backup(tmp_path / "x.db", backup_dir=directory)


# -------------------------------------------------- list + retention


@pytest.mark.parametrize(
    ("field", "value"),
    [("created_at", value) for value in (None, 42, True, [], {})]
    + [("sha256", None), ("sha256", 42), ("backup_path", None)],
)
async def test_list_backups_annotates_invalid_manifest_field_types(db, tmp_path, field, value):
    """Malformed JSON fields cannot hide the other backups from the user."""
    service = BackupService(db)
    directory = tmp_path / "bk"
    valid = await service.create_backup(backup_dir=directory)
    malformed = await service.create_backup(backup_dir=directory)
    sidecar = Path(f"{malformed.backup_path}.manifest.json")
    payload = malformed.to_dict()
    payload[field] = value
    sidecar.write_text(json.dumps(payload), encoding="utf-8")

    entries = {entry.backup_path: entry for entry in BackupService.list_backups(directory)}

    assert entries[Path(valid.backup_path)].status == "ok"
    entry = entries[Path(malformed.backup_path)]
    assert entry.status == "manifest_unreadable"
    assert entry.manifest is None
    assert entry.created_at == BackupService._mtime_iso(Path(malformed.backup_path))
    assert sidecar.is_file() and Path(malformed.backup_path).is_file()


@pytest.mark.parametrize(
    ("count", "orphan_indices", "limit", "retained_indices"),
    [(2, {1}, 1, {0}), (6, {1, 4, 5}, 2, {2, 3})],
    ids=["newest-orphan-keeps-only-backup", "multiple-orphans-do-not-use-slots"],
)
async def test_retention_orphans_do_not_displace_backups(
    db, tmp_path, count, orphan_indices, limit, retained_indices
):
    await _seed_users(db)
    service = BackupService(db)
    directory = tmp_path / "bk"
    manifests = []
    for index in range(count):
        backup = directory / f"b.backup-20261024T00000{index}Z.db"
        manifest = await service.create_backup(backup)
        # Explicit times make the intended order independent of disk speed.
        payload = manifest.to_dict()
        payload["created_at"] = f"2026-10-24T00:00:0{index}+00:00"
        manifest = BackupManifest.from_dict(payload)
        BackupService._write_manifest_atomic(backup, manifest)
        manifests.append(manifest)
        if index in orphan_indices:
            backup.unlink()
    foreign = directory / "notes.txt"
    foreign.write_text("keep me", encoding="utf-8")

    deleted = BackupService.apply_retention(directory, limit)

    retained = {Path(manifests[index].backup_path) for index in retained_indices}
    assert {entry.backup_path for entry in BackupService.list_backups(directory)} == retained
    for index, manifest in enumerate(manifests):
        backup = Path(manifest.backup_path)
        sidecar = Path(f"{backup}.manifest.json")
        assert backup.exists() == (index in retained_indices)
        assert sidecar.exists() == (index in retained_indices)
        if index in retained_indices:
            assert BackupService.verify_backup(backup, manifest) == (True, "ok")
    assert len(deleted) == 2 * (count - len(orphan_indices) - limit) + len(orphan_indices)
    assert foreign.read_text(encoding="utf-8") == "keep me"


@pytest.mark.parametrize(
    ("statuses", "limit", "retained_indices"),
    [(["ok", status], 1, {0, 1}) for status in (
        "manifest_unreadable", "size_mismatch", "no_manifest"
    )] + [
        (
            ["ok", "manifest_unreadable", "ok", "no_manifest", "ok",
             "size_mismatch", "manifest_unreadable", "no_manifest"],
            2,
            {2, 4, 6, 7},
        ),
        (["manifest_unreadable", "size_mismatch", "no_manifest"], 2, {1, 2}),
    ],
    ids=["newest-unreadable", "newest-size-mismatch", "newest-no-manifest",
         "mixed-backups-keep-two-regular-candidates", "all-abnormal-still-rotate"],
)
async def test_retention_preserves_regular_candidates_alongside_recent_backups(
    db, tmp_path, statuses, limit, retained_indices
):
    """Known metadata failures cannot evict every older normal candidate."""
    await _seed_users(db)
    service = BackupService(db)
    directory = tmp_path / "bk"
    manifests = []
    contents = []
    original_files = set()
    for index, status in enumerate(statuses):
        backup = directory / f"b.backup-20261024T00000{index}Z.db"
        manifest = await service.create_backup(backup)
        created = datetime(2026, 10, 24, 0, 0, index, tzinfo=timezone.utc)
        payload = manifest.to_dict()
        payload["created_at"] = created.isoformat()
        manifest = BackupManifest.from_dict(payload)
        manifests.append(manifest)
        contents.append(backup.read_bytes())
        sidecar = BackupService._write_manifest_atomic(backup, manifest)
        if status == "manifest_unreadable":
            sidecar.write_text("{not json", encoding="utf-8")
        elif status == "size_mismatch":
            payload["size_bytes"] += 1
            sidecar.write_text(json.dumps(payload), encoding="utf-8")
        elif status == "no_manifest":
            sidecar.unlink()
        # Unreadable/missing manifests sort by the backup's mtime.
        os.utime(backup, (created.timestamp(), created.timestamp()))
        original_files.add(backup)
        if sidecar.exists():
            original_files.add(sidecar)

    before = BackupService.list_backups(directory)
    assert [entry.status for entry in before] == list(reversed(statuses))
    deleted = BackupService.apply_retention(directory, limit)

    retained = {Path(manifests[index].backup_path) for index in retained_indices}
    remaining = BackupService.list_backups(directory)
    assert {entry.backup_path for entry in remaining} == retained
    assert len(remaining) <= 2 * limit
    for index in retained_indices:
        backup = Path(manifests[index].backup_path)
        assert backup.read_bytes() == contents[index]
        if statuses[index] == "ok":
            assert BackupService.verify_backup(backup, manifests[index]) == (True, "ok")
    remaining_files = set(directory.iterdir())
    assert set(deleted) == original_files - remaining_files
    for index, manifest in enumerate(manifests):
        backup = Path(manifest.backup_path)
        assert backup.exists() == (index in retained_indices)
        assert Path(f"{backup}.manifest.json").exists() == (
            index in retained_indices and statuses[index] != "no_manifest"
        )


async def test_list_backups_annotates_corrupt_orphan_and_ignores_foreign(
    db, tmp_path
):
    """损坏/孤儿单独标注；目录内不匹配命名模式的文件绝不出现。"""
    await _seed_users(db)
    service = BackupService(db)
    directory = tmp_path / "bk"
    directory.mkdir()
    b1 = directory / "a.backup-20260820T010000Z.db"
    b2 = directory / "a.backup-20260820T020000Z.db"
    b3 = directory / "a.backup-20260820T030000Z.db"
    await service.create_backup(b1)
    await service.create_backup(b2)
    await service.create_backup(b3)

    # b2 的 manifest 半损坏（写入垃圾）→ manifest_unreadable。
    Path(f"{b2}.manifest.json").write_text("{not json", encoding="utf-8")
    # b1 的备份文件被删（只剩 manifest）→ orphan_manifest。
    b1.unlink()
    # 目录里的外来文件：绝不出现、绝不被触碰。
    (directory / "notes.txt").write_text("keep me", encoding="utf-8")
    (directory / "unrelated.db").write_bytes(b"\x00" * 8)

    entries = BackupService.list_backups(directory)
    names = [e.backup_path.name for e in entries]
    assert names == [
        "a.backup-20260820T030000Z.db",
        "a.backup-20260820T020000Z.db",
        "a.backup-20260820T010000Z.db",
    ]  # 最新在前
    by_name = {e.backup_path.name: e for e in entries}
    assert by_name["a.backup-20260820T030000Z.db"].status == "ok"
    assert by_name["a.backup-20260820T020000Z.db"].status == "manifest_unreadable"
    orphan = by_name["a.backup-20260820T010000Z.db"]
    assert orphan.status == "orphan_manifest"
    assert orphan.manifest_path is not None
    assert all("notes.txt" not in n and "unrelated" not in n for n in names)

    # retention 只删本服务命名模式的文件：保留最新 1 个，其余连同 manifest 成对删，
    # 孤儿 manifest 一并清理，外来文件原封不动。
    deleted = BackupService.apply_retention(directory, limit=1)
    remaining = BackupService.list_backups(directory)
    assert [e.backup_path.name for e in remaining] == [
        "a.backup-20260820T030000Z.db"
    ]
    assert not Path(f"{b2}.manifest.json").exists()
    assert not Path(f"{b1}.manifest.json").exists()
    assert (directory / "notes.txt").read_text() == "keep me"
    assert (directory / "unrelated.db").exists()
    assert all(p.parent == directory for p in deleted)
    assert len(deleted) == 3  # b2.db + b2 manifest + b1 孤儿 manifest


async def test_apply_retention_keeps_newest_n_pairs(db, tmp_path):
    await _seed_users(db)
    service = BackupService(db)
    directory = tmp_path / "bk"
    directory.mkdir()
    for i, stamp in enumerate(
        ["T010000Z", "T020000Z", "T030000Z", "T040000Z"]
    ):
        await service.create_backup(directory / f"b.backup-20260820{stamp}.db")

    deleted = BackupService.apply_retention(directory, limit=2)
    remaining = BackupService.list_backups(directory)
    assert sorted(e.backup_path.name for e in remaining) == [
        "b.backup-20260820T030000Z.db",
        "b.backup-20260820T040000Z.db",
    ]
    # 最旧两个备份 + 其 manifest 成对删。
    assert Path(directory / "b.backup-20260820T010000Z.db").exists() is False
    assert Path(
        directory / "b.backup-20260820T010000Z.db.manifest.json"
    ).exists() is False
    assert len(deleted) == 4
    with pytest.raises(ValueError, match="retention limit"):
        BackupService.apply_retention(directory, limit=0)


# ---------------------------------------------------------- verify


async def test_verify_backup_ok_tampered_and_corrupt(db, tmp_path):
    await _seed_users(db)
    service = BackupService(db)
    backup = tmp_path / "v.db"
    manifest = await service.create_backup(backup)

    ok, detail = BackupService.verify_backup(backup, manifest)
    assert ok and detail == "ok"

    # 同大小篡改：sha256 与 manifest 不符 → 拒绝。
    data = bytearray(backup.read_bytes())
    data[len(data) // 2] ^= 0xFF
    backup.write_bytes(bytes(data))
    ok, detail = BackupService.verify_backup(backup, manifest)
    assert not ok and "sha256" in detail

    # 非数据库文件（无 manifest）：integrity_check 拒绝。
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"\x00GARBAGE" * 64)
    ok, detail = BackupService.verify_backup(garbage, None)
    assert not ok and "integrity_check" in detail

    ok, detail = BackupService.verify_backup(tmp_path / "missing.db", None)
    assert not ok and "不存在" in detail


# --------------------------------------------- restore orchestration


@pytest_asyncio.fixture()
async def migrated_db(tmp_path):
    """升级到 alembic head 的源库（含 alembic_version，可做 restore_verified）。"""
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db

    db_file = tmp_path / "migrated.db"
    upgrade_db(str(db_file))
    engine = create_db_engine(db_file)
    await _seed_users(engine)
    yield engine
    await engine.dispose()


async def test_restore_verified_ok_restart_and_upgrade_idempotent(
    migrated_db, tmp_path
):
    """restore_verified 全绿：sidecar 自动加载 → 版本兼容 → 原子复制 →
    目标复检 → upgrade_db 幂等 → 新引擎可读写（restart after restore）。"""
    service = BackupService(migrated_db)
    backup = tmp_path / "ok.db"
    manifest = await service.create_backup(backup)

    target = tmp_path / "restored.db"
    restored = await service.restore_verified(backup, target)  # 不传 manifest → 用 sidecar
    assert restored == target.resolve()
    assert _integrity(restored) == "ok"
    conn = sqlite3.connect(restored)
    try:
        assert conn.execute("select count(*) from users").fetchone()[0] == 1
    finally:
        conn.close()

    # 恢复后重启：upgrade_db 幂等 + 简单读写。
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db

    upgrade_db(str(restored))  # 已是 head → no-op
    engine2 = create_db_engine(restored)
    async with engine2.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO users (user_id, username, role, created_at) "
                "VALUES ('u-2', 'bob', 'student', '2026-08-20T00:00:00+00:00')"
            )
        )
        count = (
            await conn.execute(text("SELECT count(*) FROM users"))
        ).scalar_one()
    await engine2.dispose()
    assert count == 2


async def test_restore_verified_rejects_corrupt_hash_mismatch(migrated_db, tmp_path):
    service = BackupService(migrated_db)
    backup = tmp_path / "bad.db"
    await service.create_backup(backup)

    # 同大小篡改 → sidecar manifest sha256 不符 → 拒绝。
    data = bytearray(backup.read_bytes())
    data[128] ^= 0xFF
    backup.write_bytes(bytes(data))
    with pytest.raises(BackupError, match="sha256"):
        await service.restore_verified(backup, tmp_path / "never.db")
    assert not (tmp_path / "never.db").exists()  # 不留下任何半成品

    # 非数据库文件（显式伪造 manifest 哈希一致也过不了 integrity）→ 拒绝。
    garbage = tmp_path / "garbage.db"
    garbage.write_bytes(b"\x00GARBAGE" * 64)
    with pytest.raises(BackupError, match="完整性|integrity"):
        await service.restore_verified(garbage, tmp_path / "never2.db")

    # 缺失文件 → 拒绝。
    with pytest.raises(BackupError, match="不存在"):
        await service.restore_verified(tmp_path / "missing.db", tmp_path / "never3.db")


async def test_restore_verified_rejects_unknown_or_missing_alembic_revision(
    migrated_db, tmp_path
):
    """版本兼容 fail-closed：未知版本串 / 无 alembic_version 一律拒绝，
    绝不降级恢复。"""
    service = BackupService(migrated_db)
    # 手工构造一个结构完好、但 alembic_version 指向未知版本的备份。
    unknown = tmp_path / "unknown-rev.db"
    conn = sqlite3.connect(unknown)
    try:
        conn.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        conn.execute(
            "INSERT INTO alembic_version VALUES ('deadbeef-future-revision')"
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(BackupError, match="迁移链"):
        await service.restore_verified(unknown, tmp_path / "never.db")

    # 无 alembic_version 的库（metadata.create_all 生成）→ 版本未知 → 拒绝。
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    plain = create_db_engine(tmp_path / "plain.db")
    async with plain.begin() as conn:
        await conn.run_sync(metadata.create_all)
    plain_service = BackupService(plain)
    plain_backup = tmp_path / "plain-backup.db"
    await plain_service.create_backup(plain_backup)
    await plain.dispose()
    with pytest.raises(BackupError, match="alembic_version"):
        await service.restore_verified(plain_backup, tmp_path / "never2.db")


async def test_restore_verified_rejects_active_wal_target(migrated_db, tmp_path):
    """目标被活跃连接持有（-wal 内容 > 0）→ 拒绝并提示先停 runtime；
    关闭后可正常恢复。"""
    service = BackupService(migrated_db)
    backup = tmp_path / "wal.db"
    await service.create_backup(backup)

    target = tmp_path / "live-target.db"
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()  # -wal 有内容且连接仍持有
    with pytest.raises(BackupError, match="活跃 -wal"):
        await service.restore_verified(backup, target)
    conn.close()

    restored = await service.restore_verified(backup, target)
    assert _integrity(restored) == "ok"


# ------------------------------------------- concurrent WAL workload


@pytest.mark.parametrize("writer_delay", [0.0, 0.2])
async def test_backup_during_wal_workload_no_tear(tmp_path, writer_delay):
    """VACUUM INTO 时并发写不撕裂（spec 5.9）：线程持续写入 + 备份 +
    integrity_check ok；快照是某个时刻的 committed 前缀。"""
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db

    db_file = tmp_path / "workload.db"
    upgrade_db(str(db_file))
    engine = create_db_engine(db_file)

    first_commit = threading.Event()

    def _writer(db_path, stop, counter):
        # Exercise scheduling slower than the former 50 ms startup guess.
        stop.wait(writer_delay)
        conn = sqlite3.connect(str(db_path), timeout=5.0)
        i = 0
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            while not stop.is_set():
                next_row = i + 1
                conn.execute(
                    "INSERT INTO users (user_id, username, role, created_at) "
                    "VALUES (?, ?, ?, '2026-08-20T00:00:00+00:00')",
                    (f"w-{next_row}", f"writer-{next_row}", "student"),
                )
                conn.commit()
                i = next_row  # Count committed rows only.
                first_commit.set()
        except Exception as exc:
            counter["error"] = repr(exc)
        finally:
            conn.close()
            counter["rows"] = i

    stop = threading.Event()
    counter: dict = {}
    thread = threading.Thread(
        target=_writer, args=(db_file, stop, counter), daemon=True
    )
    thread.start()
    try:
        try:
            assert await asyncio.to_thread(first_commit.wait, 10.0), (
                f"writer did not commit its first row: {counter}"
            )
            assert thread.is_alive(), "writer stopped before the concurrent snapshot"
            service = BackupService(engine)
            backup = tmp_path / "workload-backup.db"
            manifest = await service.create_backup(backup)
        finally:
            stop.set()
            await asyncio.to_thread(thread.join, 5.0)
        assert not thread.is_alive()
        assert "error" not in counter, counter.get("error")
        assert counter.get("rows", 0) > 0

        ok, detail = BackupService.verify_backup(backup, manifest)
        assert ok, detail
        from mathtutor.infrastructure import db_crypto
        conn = db_crypto.connect(backup, key=db_crypto.key_for_file(backup))
        try:
            records = conn.execute("select user_id, username from users").fetchall()
        finally:
            conn.close()
        rows = len(records)
        # Keep the original nonempty/committed upper bound, and verify the
        # entire committed prefix rather than only the number of rows.
        assert 1 <= rows <= counter["rows"]
        assert set(records) == {(f"w-{i}", f"writer-{i}") for i in range(1, rows + 1)}
    finally:
        await engine.dispose()


# --------------------------------------------------- assert_engine_idle


async def test_assert_engine_idle(tmp_path):
    from mathtutor.infrastructure import create_db_engine

    engine = create_db_engine(tmp_path / "live.db")
    # 刚创建（无写入）→ idle。
    BackupService.assert_engine_idle(engine)

    # 写入后连接归还池但 -wal 仍有内容 → 拒绝（防御性提示）。
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE t (x INTEGER)"))
        await conn.execute(text("INSERT INTO t VALUES (1)"))
    with pytest.raises(BackupError, match="活跃 -wal"):
        BackupService.assert_engine_idle(engine)
    await engine.dispose()


# -------------------------------------------------------- scheduler


async def test_scheduler_interval_mode_backup_and_retention(migrated_db, tmp_path):
    """interval 模式：启动即备份一次，wake() 触发后续周期，retention 生效。"""
    service = BackupService(migrated_db)
    directory = tmp_path / "bk"
    policy = BackupPolicy(
        mode="interval",
        backup_dir=directory,
        retention_limit=2,
        interval_seconds=3600.0,  # 周期靠 wake 触发，不依赖真实时间
    )
    scheduler = _ObservedBackupScheduler(service, policy)
    scheduler.start()
    assert scheduler.is_running

    try:
        # A snapshot file exists before its manifest is written. Wait for the
        # complete cycle, including retention, instead of counting those files.
        first = Path((await scheduler.next_cycle()).backup_path)
        scheduler.wake()
        await scheduler.next_cycle()
        scheduler.wake()  # 第三个备份 → retention 保留最新 2 个
        await scheduler.next_cycle()

        entries = BackupService.list_backups(directory)
        assert len(service.manifests) == 3
        assert len(entries) == 2
        assert all(e.status == "ok" for e in entries)
        assert not first.exists()  # 最旧的那个被 retention 删除（成对删 manifest）
        assert not Path(f"{first}.manifest.json").exists()
    finally:
        await scheduler.stop(timeout=10.0)
    assert not scheduler.is_running
    await scheduler.stop()  # 幂等


async def test_scheduler_wake_during_unfinished_backup_is_preserved(
    migrated_db, tmp_path, monkeypatch
):
    """An early wake queues another cycle while the first manifest is pending."""
    service = BackupService(migrated_db)
    directory = tmp_path / "bk"
    snapshot_ready = asyncio.Event()
    finish_snapshot = asyncio.Event()
    journal_mode = service._journal_mode

    async def delayed_journal_mode():
        if not snapshot_ready.is_set():
            snapshot_ready.set()
            await finish_snapshot.wait()
        return await journal_mode()

    monkeypatch.setattr(service, "_journal_mode", delayed_journal_mode)
    scheduler = _ObservedBackupScheduler(
        service,
        BackupPolicy(mode="interval", backup_dir=directory, interval_seconds=3600.0),
    )
    scheduler.start()
    try:
        await asyncio.wait_for(snapshot_ready.wait(), timeout=BACKUP_CYCLE_TIMEOUT)
        entries = BackupService.list_backups(directory)
        assert len(entries) == 1
        assert entries[0].status == "no_manifest"
        assert service.manifests == []
        assert scheduler.completed_cycles.empty()

        scheduler.wake()
        finish_snapshot.set()
        await scheduler.next_cycle()
        await scheduler.next_cycle()

        assert len(service.manifests) == 2
        entries = BackupService.list_backups(directory)
        assert len(entries) == 2
        assert all(e.status == "ok" for e in entries)
    finally:
        finish_snapshot.set()
        await scheduler.stop(timeout=10.0)


async def test_scheduler_on_startup_mode_runs_once(migrated_db, tmp_path):
    service = BackupService(migrated_db)
    directory = tmp_path / "bk"
    scheduler = _ObservedBackupScheduler(
        service, BackupPolicy(mode="on_startup", backup_dir=directory)
    )
    scheduler.start()
    try:
        await scheduler.next_cycle()
        assert scheduler.task is not None and scheduler.task.done()
        entries = BackupService.list_backups(directory)
        assert len(entries) == 1
        assert entries[0].status == "ok"
    finally:
        await scheduler.stop(timeout=10.0)  # 任务已退出，stop 立即返回


async def test_scheduler_manual_or_disabled_is_noop(migrated_db, tmp_path):
    service = BackupService(migrated_db)
    for policy in (
        BackupPolicy(mode="manual", backup_dir=tmp_path / "bk1"),
        BackupPolicy(
            mode="interval", backup_dir=tmp_path / "bk2", enabled=False
        ),
    ):
        scheduler = BackupScheduler(service, policy)
        scheduler.start()
        assert scheduler.task is None
        assert not scheduler.is_running
        await scheduler.stop()  # 未启动也安全
    assert BackupService.list_backups(tmp_path / "bk1") == []
    assert BackupService.list_backups(tmp_path / "bk2") == []
