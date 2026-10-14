"""Phase 6 — SQLite backup/restore tests (VACUUM INTO, WAL-consistent).

Covers: VACUUM INTO produces a usable standalone backup while the source
is in WAL mode with live connections; the manifest carries timestamp /
size / hash / integrity; restore yields a complete database; corrupted
backups and manifest-hash mismatches are rejected fail-closed.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from mathtutor.infrastructure.backup import (
    BackupError,
    BackupManifest,
    BackupService,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def db(tmp_path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "source.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def _seed(engine) -> None:
    from mathtutor.infrastructure.schema import curriculum_versions, users

    async with engine.begin() as conn:
        await conn.execute(
            users.insert().values(
                user_id="u-1", username="alice", role="student",
                created_at="2026-08-20T00:00:00+00:00",
            )
        )
        await conn.execute(
            curriculum_versions.insert().values(
                version_id=str(uuid4()), code="bk-v1", name="backup 课程",
                status="published", node_count=2, edge_count=1,
                released_at="2026-08-20T01:00:00+00:00",
                created_at="2026-08-20T00:00:00+00:00",
            )
        )


async def test_create_backup_wal_consistent_usable_and_manifest(db, tmp_path):
    """VACUUM INTO 在 WAL 活跃时产生一致快照；manifest 字段齐全。"""
    await _seed(db)  # 引擎连接仍打开（WAL 活跃）时备份
    service = BackupService(db)
    backup_path = tmp_path / "snapshot.db"
    manifest = await service.create_backup(backup_path)

    assert manifest.integrity == "ok"
    assert manifest.source_journal_mode == "wal"
    assert manifest.size_bytes > 0
    assert len(manifest.sha256) == 64
    datetime.fromisoformat(manifest.created_at)  # 可解析时间戳
    assert manifest.backup_path == str(backup_path.resolve())
    assert service.manifests[-1] == manifest

    # 备份文件是独立可用数据库（有密钥存储时加密），包含已提交数据。
    from mathtutor.infrastructure import db_crypto
    assert not db_crypto.is_plaintext_file(backup_path)
    conn = db_crypto.connect(backup_path, key=db_crypto.key_for_file(backup_path))
    try:
        assert conn.execute("select count(*) from users").fetchone()[0] == 1
        assert conn.execute("select code from curriculum_versions").fetchone()[0] == "bk-v1"
    finally:
        conn.close()


async def test_restore_valid_rejects_corrupt_and_mismatch(db, tmp_path):
    """restore 后数据完整；损坏文件 / 哈希不符 / 缺失文件全部被拒。"""
    await _seed(db)
    service = BackupService(db)
    backup = tmp_path / "snapshot.db"
    manifest = await service.create_backup(backup)

    target = tmp_path / "restored.db"
    restored = await service.restore(backup, target, manifest)
    conn = sqlite3.connect(restored)
    try:
        assert conn.execute("select count(*) from users").fetchone()[0] == 1
        assert conn.execute("select node_count from curriculum_versions").fetchone()[0] == 2
    finally:
        conn.close()

    # 损坏文件：即使文件存在也拒绝恢复（fail closed）。
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"\x00GARBAGE-not-a-sqlite-database\x00" * 64)
    with pytest.raises(BackupError):
        await service.restore(corrupt, tmp_path / "never.db")

    # 备份文件本身是有效数据库，但 hash 与 manifest 不符 → 拒绝。
    wrong = BackupManifest(
        backup_path=manifest.backup_path,
        created_at=manifest.created_at,
        size_bytes=1,
        sha256="0" * 64,
        integrity="ok",
        source_journal_mode="wal",
    )
    with pytest.raises(BackupError):
        await service.restore(backup, tmp_path / "never2.db", wrong)

    # 不存在的文件 → 拒绝。
    with pytest.raises(BackupError):
        await service.restore(tmp_path / "missing.db", tmp_path / "never3.db")
