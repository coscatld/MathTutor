"""SQLite online backup + restore (Phase 6 productionization).

Backup uses ``VACUUM INTO`` (SQLite ≥ 3.27): the engine's DBAPI connection
runs it OUTSIDE any transaction, so it takes a consistent snapshot of the
whole database — WAL-safe, never a raw ``cp`` of the active ``-wal`` file
(which would produce a torn/inconsistent backup).

Flow:

- ``create_backup`` → PRAGMA integrity_check on the SOURCE, then
  ``VACUUM INTO <path>`` (off the event loop), then a manifest
  (timestamp / size / sha256 / integrity) returned to the caller AND
  written to a sidecar ``<backup>.manifest.json`` (atomic tmp + replace —
  a half-written manifest can never exist).
- ``restore`` → validates the BACKUP file's integrity (and, when a
  manifest is supplied, its sha256), then copies it to the target path and
  returns the path of a usable engine target. A corrupted backup is
  rejected with :class:`BackupError` — fail closed, never restore garbage.
- ``restore_verified`` (spec 5.8) → full fail-closed restore orchestration:
  sha256 + integrity on the backup, alembic-version compatibility (never a
  downgrade restore), active ``-wal``/``-shm`` pre-check on the target,
  atomic tmp+replace copy, then a post-copy integrity re-check. Any failure
  raises :class:`BackupError` and leaves no half-written target.

Phase 6 second round — policy/scheduler (spec 5.7):

- :class:`BackupPolicy` (frozen dataclass): mode (manual / on_startup /
  interval), backup dir, retention limit, interval, enabled.
- :class:`BackupService.list_backups` scans the service naming pattern
  (``*.backup-*.db`` + same-name ``.manifest.json``) with corrupt/orphan
  entries annotated; files NOT matching the pattern are never listed and
  never touched.
- :class:`BackupService.verify_backup` re-checks sha256 + integrity.
- :class:`BackupService.apply_retention` deletes only pattern-matching
  backup+manifest pairs, retaining the newest N backup files plus the newest
  N with readable manifests and matching sizes (at most 2N total).
- :class:`BackupScheduler` runs create_backup + apply_retention on a policy
  (interval loop / one-shot at startup), start/stop in the same graceful
  cancellable style as the outbox relay loop.

Restore contract (for MAIN wiring): ``restore_verified`` provides pure
FILE-LEVEL safety only. The caller MUST stop the write runtime and dispose
the engine before restoring, then rebuild the engine on the returned target
(``assert_engine_idle`` is a best-effort advisory check; the real
orchestration belongs to the API layer).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

#: Service backup naming pattern (list/retention only manage these files).
_BACKUP_FILE_GLOB = "*.backup-*.db"
#: Sidecar manifest suffix: ``<backup>.manifest.json``.
_MANIFEST_SUFFIX = ".manifest.json"
#: Sidecar manifest glob (built from the suffix, not string-glob concat).
_MANIFEST_GLOB = "*.backup-*.db.manifest.json"


class BackupError(Exception):
    """Backup or restore failed (integrity check refused, I/O, ...)."""


@dataclass(frozen=True, slots=True)
class BackupManifest:
    """Verification record for one backup file."""

    backup_path: str
    created_at: str
    size_bytes: int
    sha256: str
    integrity: str  # "ok" | "unknown" (checked before the snapshot)
    source_journal_mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "backup_path": self.backup_path,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "integrity": self.integrity,
            "source_journal_mode": self.source_journal_mode,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BackupManifest":
        """Rebuild from the sidecar JSON (raises KeyError/TypeError when the
        payload is not a manifest — callers annotate it unreadable)."""
        for field in ("backup_path", "created_at", "sha256"):
            if not isinstance(data[field], str):
                raise TypeError(f"manifest {field} must be a string")
        return cls(
            backup_path=data["backup_path"],
            created_at=data["created_at"],
            size_bytes=int(data["size_bytes"]),
            sha256=data["sha256"],
            integrity=data.get("integrity", "unknown"),
            source_journal_mode=data.get("source_journal_mode", "unknown"),
        )


@dataclass(frozen=True, slots=True)
class BackupPolicy:
    """Backup scheduling policy (spec 5.7).

    - ``mode``: "manual" (no automatic runs), "on_startup" (one backup when
      the scheduler starts), "interval" (backup every ``interval_seconds``).
    - ``backup_dir``: directory for scheduler-created backups (None → next
      to the source database, the create_backup default).
    - ``retention_limit``: keep the newest N backup files plus the newest N
      with readable manifests and matching sizes (at most 2N). Normal
      directories keep N; known metadata problems cannot displace every
      older normal candidate. Hash/integrity verification is separate.
    - ``interval_seconds``: interval mode period.
    - ``enabled``: global switch (disabled → scheduler never runs).
    """

    mode: str = "manual"
    backup_dir: Path | None = None
    retention_limit: int = 5
    interval_seconds: float = 3600.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.mode not in ("manual", "on_startup", "interval"):
            raise ValueError(
                f"未知备份模式: {self.mode!r}（应为 manual | on_startup | interval）"
            )
        if self.retention_limit < 1:
            raise ValueError("retention_limit 必须 >= 1")
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds 必须 > 0")
        if self.backup_dir is not None:
            object.__setattr__(self, "backup_dir", Path(self.backup_dir))


@dataclass(frozen=True, slots=True)
class BackupEntry:
    """One row of :meth:`BackupService.list_backups`.

    ``status``: "ok" | "no_manifest" | "manifest_unreadable" |
    "size_mismatch" | "orphan_manifest" (a manifest whose backup file is
    gone). ``created_at`` is the sort key (manifest timestamp, else file
    mtime). Corrupt/orphan entries are ANNOTATED here, never deleted by
    listing. ``ok`` only means readable metadata and matching file size;
    it does not imply hash or SQLite integrity verification.
    """

    backup_path: Path
    manifest_path: Path | None
    manifest: BackupManifest | None
    created_at: str
    status: str
    detail: str = ""


class BackupService:
    """Online backup/restore over one SQLite engine (product database)."""

    def __init__(self, engine: AsyncEngine | None = None) -> None:
        from mathtutor.infrastructure.db import create_db_engine

        self._engine = engine or create_db_engine()
        #: History of manifests created by this service instance.
        self.manifests: list[BackupManifest] = []
        self._owned_workers: set[asyncio.Task] = set()
        self._closing = False

    async def _run_owned(self, function, *args):
        if self._closing:
            raise RuntimeError("Backup service is shutting down")
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        self._owned_workers.add(task)
        try:
            return await asyncio.shield(task)
        finally:
            if task.done():
                self._owned_workers.discard(task)

    async def shutdown(self):
        self._closing = True
        if self._owned_workers:
            done, pending = await asyncio.wait(self._owned_workers, timeout=5.0)
            self._owned_workers.difference_update(done)
            for task in done:
                task.result()
            if pending:
                raise RuntimeError("Backup workers still own database connections")

    # ------------------------------------------------------------ backup

    async def create_backup(
        self,
        backup_path: Path | None = None,
        *,
        backup_dir: Path | None = None,
    ) -> BackupManifest:
        """Integrity-check the source, then VACUUM INTO a snapshot file.

        ``backup_path``: explicit target file. ``backup_dir``: directory in
        which a default-named file (``<db>.backup-<utc timestamp>.db``) is
        created — the two are mutually exclusive. Default (both None):
        next to the source database (unchanged legacy behavior).

        The backup is taken off the event loop (``asyncio.to_thread``) since
        the DBAPI backup is blocking. A sidecar manifest is written
        atomically (tmp + ``os.replace``) next to the backup file.
        """
        if backup_path is not None and backup_dir is not None:
            raise ValueError("backup_path 与 backup_dir 只能指定其一")
        if backup_dir is not None:
            directory = Path(backup_dir).resolve()
            directory.mkdir(parents=True, exist_ok=True)
            path = self._unique_default_path(directory)
        elif backup_path is not None:
            path = Path(backup_path).resolve()
        else:
            path = self._unique_default_path(self._db_path().parent)
        path.parent.mkdir(parents=True, exist_ok=True)

        integrity = await self._source_integrity_check()
        if integrity != "ok":
            raise BackupError(
                f"源数据库完整性检查未通过（{integrity!r}），拒绝备份"
            )

        await self._run_owned(self._vacuum_into, path)
        if not path.is_file() or path.stat().st_size == 0:
            raise BackupError(f"备份文件未生成或为空: {path}")

        manifest = BackupManifest(
            backup_path=str(path),
            created_at=_now(),
            size_bytes=path.stat().st_size,
            sha256=_sha256(path),
            integrity=integrity,
            source_journal_mode=await self._journal_mode(),
        )
        self._write_manifest_atomic(path, manifest)
        self.manifests.append(manifest)
        return manifest

    async def _source_integrity_check(self) -> str:
        async with self._engine.connect() as conn:
            row = (await conn.execute(text("PRAGMA integrity_check"))).first()
            return str(row[0]) if row is not None else "missing"

    async def _journal_mode(self) -> str:
        async with self._engine.connect() as conn:
            row = (await conn.execute(text("PRAGMA journal_mode"))).first()
            return str(row[0]) if row is not None else "unknown"

    def _vacuum_into(self, path: Path) -> None:
        """Blocking VACUUM INTO via the stdlib sqlite3 module (no transaction).

        The engine's async DBAPI can't run blocking VACUUM outside the
        greenlet, so we open the SAME database file directly with sqlite3:
        a fresh connection sees every committed row through the WAL, and
        ``VACUUM INTO`` copies a consistent snapshot into the target file
        (safe with other readers/writers open). The filename is bound as a
        parameter (SQLite ≥ 3.27).
        """
        import sqlite3

        from mathtutor.infrastructure import db_crypto
        source = self._db_path()
        key, backup_key = db_crypto.db_key(source), db_crypto.backup_key()
        if key is not None or backup_key is not None:
            # Encrypted backup (SQLCipher, backup key); readable only with that key.
            db_crypto.snapshot(source, key, path, backup_key)
            return
        conn = sqlite3.connect(str(source), timeout=5.0)
        try:
            conn.execute("VACUUM INTO ?", (str(path),))
        finally:
            conn.close()

    def _db_path(self) -> Path:
        database = self._engine.url.database
        assert database is not None, "backup requires a file-backed SQLite engine"
        return Path(database)

    def _default_filename(self) -> str:
        return (
            f"{self._db_path().name}.backup-"
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
        )

    def _unique_default_path(self, directory: Path) -> Path:
        """Default-named path that does not collide with an existing file
        (timestamp granularity is 1s; VACUUM INTO refuses to overwrite)."""
        base = self._default_filename()
        path = directory / base
        counter = 2
        while path.exists():
            path = directory / f"{base[: -len('.db')]}-{counter}.db"
            counter += 1
        return path

    @staticmethod
    def _write_manifest_atomic(
        backup_path: Path, manifest: BackupManifest
    ) -> Path:
        """Atomically write the sidecar manifest (tmp + os.replace): a
        half-written manifest can never be observed."""
        sidecar = Path(f"{backup_path}{_MANIFEST_SUFFIX}")
        tmp = sidecar.with_name(f"{sidecar.name}.tmp-{uuid4().hex}")
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(manifest.to_dict(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp, sidecar)
        finally:
            tmp.unlink(missing_ok=True)
        return sidecar

    # ------------------------------------------- listing / verify / retention

    @staticmethod
    def list_backups(backup_dir: Path | str) -> list[BackupEntry]:
        """Scan ``backup_dir`` for this service's backup files
        (``*.backup-*.db``) and their same-name manifests.

        Returns entries sorted newest-first (by manifest timestamp, else
        file mtime). Corrupt/orphan states are ANNOTATED via ``status``:
        "no_manifest", "manifest_unreadable", "size_mismatch",
        "orphan_manifest". Files not matching the service pattern are never
        listed and never touched.
        """
        directory = Path(backup_dir).resolve()
        if not directory.is_dir():
            return []
        entries: list[BackupEntry] = []
        seen: set[Path] = set()
        for backup in sorted(directory.glob(_BACKUP_FILE_GLOB)):
            seen.add(backup)
            manifest_path = Path(f"{backup}{_MANIFEST_SUFFIX}")
            manifest, status, detail = BackupService._load_entry_manifest(
                manifest_path, backup
            )
            created = (
                manifest.created_at
                if manifest is not None
                else BackupService._mtime_iso(backup)
            )
            entries.append(
                BackupEntry(
                    backup_path=backup,
                    manifest_path=manifest_path if manifest_path.is_file() else None,
                    manifest=manifest,
                    created_at=created,
                    status=status,
                    detail=detail,
                )
            )
        for sidecar in sorted(directory.glob(_MANIFEST_GLOB)):
            backup = sidecar.with_name(sidecar.name[: -len(_MANIFEST_SUFFIX)])
            if backup in seen:
                continue  # 成对的 manifest 已处理
            manifest, _, detail = BackupService._load_entry_manifest(sidecar, backup)
            created = (
                manifest.created_at
                if manifest is not None
                else BackupService._mtime_iso(sidecar)
            )
            entries.append(
                BackupEntry(
                    backup_path=backup,
                    manifest_path=sidecar,
                    manifest=manifest,
                    created_at=created,
                    status="orphan_manifest",
                    detail=f"备份文件缺失: {detail}",
                )
            )
        entries.sort(key=lambda e: (e.created_at, str(e.backup_path)), reverse=True)
        return entries

    @staticmethod
    def _load_entry_manifest(
        manifest_path: Path, backup_path: Path
    ) -> tuple[BackupManifest | None, str, str]:
        if not manifest_path.is_file():
            return None, "no_manifest", "缺少 manifest 文件"
        try:
            manifest = BackupManifest.from_dict(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
        except Exception as exc:  # noqa: BLE001 - 半损坏 manifest 标注而非崩溃
            return None, "manifest_unreadable", str(exc)
        if backup_path.is_file() and manifest.size_bytes != backup_path.stat().st_size:
            return manifest, "size_mismatch", "文件大小与 manifest 不符"
        return manifest, "ok", ""

    @staticmethod
    def _mtime_iso(path: Path) -> str:
        try:
            return datetime.fromtimestamp(
                path.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        except OSError:
            return "1970-01-01T00:00:00+00:00"

    @staticmethod
    def verify_backup(
        backup_path: Path | str, manifest: BackupManifest | None, recovery_key: str | None = None
    ) -> tuple[bool, str]:
        """Re-verify a backup: size + sha256 against the manifest (when
        given) and PRAGMA integrity_check. Returns ``(ok, detail)``.

        Blocking I/O (sync) — callers wrap in ``asyncio.to_thread`` where
        needed. False means the backup must not be restored.
        """
        path = Path(backup_path)
        if not path.is_file():
            return False, f"备份文件不存在: {path}"
        if manifest is not None:
            if manifest.size_bytes != path.stat().st_size:
                return False, "文件大小与 manifest 不符"
            if manifest.sha256 != _sha256(path):
                return False, "sha256 与 manifest 不符"
        integrity = BackupService._verify_backup_file(path, recovery_key)
        if integrity != "ok":
            return False, f"integrity_check 未通过（{integrity!r}）"
        return True, "ok"

    @staticmethod
    def apply_retention(backup_dir: Path | str, limit: int) -> list[Path]:
        """Retain recent backups and protect older normal metadata candidates.

        Keep the union of the newest ``limit`` existing backups and the
        newest ``limit`` entries with status ``ok``. This retains at most
        twice the limit when recent backups have known metadata problems;
        a normal directory still keeps only the limit. Status ``ok`` is a
        metadata/size check, not proof of hash or SQLite integrity. Older
        entries outside both sets are deleted with their manifests, so
        abnormal files do not suspend retention indefinitely.

        Only files matching the service pattern (``*.backup-*.db`` and
        ``*.backup-*.db.manifest.json``) are ever deleted — any other file
        in the directory is untouched. Orphan manifests (backup already
        gone) are cleaned up regardless of age and never count toward the
        number of retained backups. Returns the deleted paths.
        """
        if limit < 1:
            raise ValueError("retention limit 必须 >= 1")
        entries = BackupService.list_backups(backup_dir)
        deleted: list[Path] = []
        backups = [entry for entry in entries if entry.status != "orphan_manifest"]
        retained = {entry.backup_path for entry in backups[:limit]}
        normal = [entry for entry in backups if entry.status == "ok"]
        retained.update(entry.backup_path for entry in normal[:limit])
        drop = [entry for entry in backups if entry.backup_path not in retained]
        for entry in drop:
            if entry.backup_path.is_file():
                entry.backup_path.unlink(missing_ok=True)
                deleted.append(entry.backup_path)
            if entry.manifest_path is not None and entry.manifest_path.is_file():
                entry.manifest_path.unlink(missing_ok=True)
                deleted.append(entry.manifest_path)
        for entry in entries:
            if entry.status != "orphan_manifest":
                continue
            if entry.manifest_path is not None and entry.manifest_path.is_file():
                entry.manifest_path.unlink(missing_ok=True)
                deleted.append(entry.manifest_path)
        return deleted

    # ----------------------------------------------------------- restore

    async def restore(
        self,
        backup_path: Path,
        target_path: Path,
        manifest: BackupManifest | None = None,
    ) -> Path:
        """Validate the backup file, then copy it to ``target_path``.

        Validation is fail-closed:

        - the file must exist and be a real SQLite database;
        - ``PRAGMA integrity_check`` on the BACKUP file must be ``ok``;
        - if a manifest is supplied its sha256 must match (guards against
          a corrupted/truncated snapshot that still parses).

        Returns the target path — the caller creates its engine on it.
        """
        backup_path = Path(backup_path).resolve()
        if not backup_path.is_file():
            raise BackupError(f"备份文件不存在: {backup_path}")
        if manifest is not None and manifest.sha256 != _sha256(backup_path):
            raise BackupError("备份文件哈希与 manifest 不符，拒绝恢复")

        integrity = await asyncio.to_thread(self._verify_backup_file, backup_path)
        if integrity != "ok":
            raise BackupError(
                f"备份文件完整性校验未通过（{integrity!r}），拒绝恢复: {backup_path}"
            )

        target = Path(target_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(BackupService._restore_into, backup_path, target)
        return target

    async def restore_verified(
        self,
        backup_path: Path,
        target_path: Path,
        manifest: BackupManifest | None = None,
        recovery_key: str | None = None,
    ) -> Path:
        """Fail-closed verified restore (spec 5.8). Orchestration:

        1. sha256 + integrity_check on the BACKUP (manifest given, else the
           sidecar ``<backup>.manifest.json`` when present — an unreadable
           sidecar rejects; no manifest at all falls back to
           integrity-only);
        2. alembic-version compatibility: the backup's ``alembic_version``
           must exist and every revision must belong to the migration chain
           bundled with THIS codebase — a backup from a newer/unknown
           version is refused, a downgrade restore can never happen;
        3. active ``-wal``/``-shm`` pre-check on the TARGET (size > 0 →
           refuse: a live connection still holds the target);
        4. atomic copy (tmp + ``os.replace``) — a half-written target can
           never exist;
        5. post-copy integrity_check on the TARGET; on failure the target
           is removed (no half product) and ``BackupError`` is raised.

        Returns the target path. CALLING CONTRACT (MAIN wiring): the write
        runtime MUST be stopped and the engine disposed before this call;
        this method provides file-level safety only (see
        :meth:`assert_engine_idle` for the advisory check — the API layer
        owns the stop → dispose → restore → rebuild orchestration).
        """
        backup_path = Path(backup_path).resolve()
        if not backup_path.is_file():
            raise BackupError(f"备份文件不存在: {backup_path}")
        if manifest is None:
            sidecar = Path(f"{backup_path}{_MANIFEST_SUFFIX}")
            if sidecar.is_file():
                try:
                    manifest = BackupManifest.from_dict(
                        json.loads(sidecar.read_text(encoding="utf-8"))
                    )
                except Exception as exc:  # noqa: BLE001 - fail closed
                    raise BackupError(
                        f"备份 sidecar manifest 无法解析（{exc}），拒绝恢复"
                    ) from exc
        if manifest is not None:
            ok, detail = await asyncio.to_thread(
                BackupService.verify_backup, backup_path, manifest, recovery_key
            )
            if not ok:
                raise BackupError(f"备份验证失败，拒绝恢复: {detail}")
        else:
            integrity = await asyncio.to_thread(
                self._verify_backup_file, backup_path, recovery_key
            )
            if integrity != "ok":
                raise BackupError(
                    f"备份文件完整性校验未通过（{integrity!r}），拒绝恢复: {backup_path}"
                )

        await asyncio.to_thread(
            BackupService._check_backup_revision_compatible, backup_path, recovery_key
        )

        target = Path(target_path).resolve()
        BackupService._reject_active_wal_shm(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(BackupService._restore_into, backup_path, target, recovery_key)
        after = await asyncio.to_thread(self._verify_backup_file, target)
        if after != "ok":
            target.unlink(missing_ok=True)
            raise BackupError(
                f"恢复后目标复检未通过（{after!r}），已删除目标文件: {target}"
            )
        logger.info("restore_verified ok: %s -> %s", backup_path, target)
        return target

    @staticmethod
    def _check_backup_revision_compatible(backup_path: Path, recovery_key: str | None = None) -> None:
        """Refuse backups whose alembic version is unknown to this codebase
        (newer-version backups, non-alembic databases) — fail closed, never
        a downgrade restore. A backup from an OLDER revision is fine:
        ``upgrade_db`` brings it forward after restore."""
        import sqlite3

        from mathtutor.infrastructure import db_crypto
        try:
            key = db_crypto.key_for_file(backup_path, recovery_key=recovery_key)
        except db_crypto.EncryptionUnavailable as exc:
            raise BackupError(f"{exc}，拒绝恢复") from exc
        conn = db_crypto.connect(backup_path, key=key, readonly=True)
        try:
            try:
                rows = conn.execute(
                    "SELECT version_num FROM alembic_version"
                ).fetchall()
            except (sqlite3.DatabaseError, Exception) as exc:
                raise BackupError(
                    f"备份无法读取 alembic_version（{exc}），拒绝恢复"
                ) from exc
        finally:
            conn.close()
        revisions = [str(row[0]) for row in rows]
        if not revisions:
            raise BackupError(
                "备份缺少 alembic_version，版本未知，拒绝恢复"
            )
        known = BackupService._known_revision_ids()
        unknown = [rev for rev in revisions if rev not in known]
        if unknown:
            raise BackupError(
                f"备份版本 {unknown} 不在当前迁移链中（备份来自更新版本或未知来源），拒绝恢复"
            )

    @staticmethod
    def _known_revision_ids() -> set[str]:
        """All revision ids in the migration chain bundled with THIS code."""
        from alembic.script import ScriptDirectory

        from mathtutor.infrastructure.migrate import alembic_config

        script = ScriptDirectory.from_config(alembic_config())
        return {revision.revision for revision in script.walk_revisions()}

    @staticmethod
    def _reject_active_wal_shm(target: Path) -> None:
        """Refuse to overwrite a target that still has an active
        ``-wal``/``-shm`` (size > 0 → a live connection likely holds it).
        Overwriting a running SQLite file is a dangerous semantic even on
        unix; the caller must stop the runtime first."""
        for suffix in ("-wal", "-shm"):
            side = Path(f"{target}{suffix}")
            if side.exists() and side.stat().st_size > 0:
                raise BackupError(
                    f"目标库仍有活跃 {suffix} 文件（可能被运行中的连接持有）——"
                    f"请先停止 runtime 并 dispose engine 后再恢复: {side}"
                )

    @staticmethod
    def _restore_into(backup: Path, target: Path, recovery_key: str | None = None) -> None:
        """Write the backup into ``target`` in the target's own mode.

        Same key on both sides is a byte copy; otherwise the backup is
        exported (decrypted or re-keyed) into a temporary file first.
        """
        from mathtutor.infrastructure import db_crypto
        source_key = db_crypto.key_for_file(backup, recovery_key=recovery_key)
        target_key = db_crypto.db_key(target)
        if source_key == target_key:
            BackupService._copy_atomic(backup, target)
            return
        tmp = target.with_name(f"{target.name}.tmp-{uuid4().hex}")
        try:
            db_crypto.export(backup, source_key, tmp, target_key)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def _copy_atomic(source: Path, target: Path) -> None:
        """tmp + os.replace copy: the target is never half-written."""
        tmp = target.with_name(f"{target.name}.tmp-{uuid4().hex}")
        try:
            shutil.copy2(source, tmp)
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

    @staticmethod
    def assert_engine_idle(engine: AsyncEngine) -> None:
        """Best-effort advisory check before restore (NOT the full contract).

        Raises :class:`BackupError` when the engine's pool still has
        checked-out connections or the database file has an active
        ``-wal``/``-shm``. The real contract belongs to MAIN's orchestration:
        stop runtime → dispose engine → :meth:`restore_verified` → rebuild
        engine.
        """
        try:
            checked_out = engine.pool.checkedout()
        except Exception:  # noqa: BLE001 - 已 dispose/探测不到视为 idle
            checked_out = 0
        if checked_out > 0:
            raise BackupError(
                f"engine 连接池仍有 {checked_out} 个在用连接——请先停止 runtime 并 dispose engine"
            )
        database = engine.url.database
        if database:
            BackupService._reject_active_wal_shm(Path(database))

    @staticmethod
    def _verify_backup_file(path: Path, recovery_key: str | None = None) -> str:
        """PRAGMA integrity_check on a standalone (possibly encrypted) file."""
        import sqlite3

        from mathtutor.infrastructure import db_crypto
        try:
            key = db_crypto.key_for_file(Path(path), recovery_key=recovery_key)
        except db_crypto.EncryptionUnavailable as exc:
            return f"encrypted: {exc}"
        if key is not None:
            return db_crypto.integrity(Path(path), key)
        try:
            conn = sqlite3.connect(str(path))
            try:
                row = conn.execute("PRAGMA integrity_check").fetchone()
                return str(row[0]) if row is not None else "missing"
            finally:
                conn.close()
        except sqlite3.DatabaseError as exc:
            return f"not-a-database: {exc}"


class BackupScheduler:
    """Runs create_backup + apply_retention on a :class:`BackupPolicy`
    (spec 5.7).

    - mode "interval": resident asyncio loop — backup immediately, then
      every ``interval_seconds`` (``wake()`` triggers an early run);
    - mode "on_startup": one backup when ``start()`` is called, then the
      task exits;
    - mode "manual" or ``enabled=False``: ``start()`` is a no-op
      (:meth:`run_once` remains available for manual triggers).

    A failed scheduled backup is logged and does NOT kill the loop.
    ``start``/``stop`` mirror the outbox relay's graceful cancellable
    style.
    """

    def __init__(self, service: BackupService, policy: BackupPolicy) -> None:
        self.service = service
        self.policy = policy
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()

    @property
    def task(self) -> asyncio.Task[Any] | None:
        return self._task

    @property
    def is_running(self) -> bool:
        task = self._task
        return task is not None and not task.done()

    def start(self) -> None:
        """Idempotent start per policy (must run inside a running loop)."""
        if not self.policy.enabled or self.policy.mode == "manual":
            return
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        if self.policy.mode == "interval":
            self._task = asyncio.create_task(
                self._run_interval_loop(), name="backup-scheduler-loop"
            )
        else:  # on_startup
            self._task = asyncio.create_task(
                self.run_once(), name="backup-scheduler-once"
            )

    def wake(self) -> None:
        """Trigger an early backup run (interval mode; best-effort)."""
        self._wake_event.set()

    async def run_once(self) -> BackupManifest | None:
        """One backup + retention cycle. Failures are logged, not raised
        (a schedule must not die on one bad backup); returns the manifest
        or None on failure. Cancellation still propagates."""
        try:
            manifest = await self.service.create_backup(
                backup_dir=self.policy.backup_dir
            )
            await asyncio.to_thread(
                BackupService.apply_retention,
                self.policy.backup_dir or _backup_dir_of(self.service),
                self.policy.retention_limit,
            )
            return manifest
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 调度容错
            logger.exception("scheduled backup failed")
            return None

    async def _run_interval_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                await self.run_once()
                try:
                    await asyncio.wait_for(
                        self._wake_event.wait(),
                        timeout=self.policy.interval_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
                self._wake_event.clear()
        except asyncio.CancelledError:
            raise

    async def stop(self, timeout: float = 5.0) -> None:
        """Graceful bounded shutdown, same style as the relay loop."""
        self._stop_event.set()
        self.wake()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "backup scheduler did not stop within %.1fs; force-cancelling",
                timeout,
            )
            task.cancel()
            await self._await_cancelled(task)
        except asyncio.CancelledError:
            task.cancel()
            await self._await_cancelled(task)
            raise
        except Exception:  # noqa: BLE001 - shutdown must never hang
            logger.exception("backup scheduler exited with an error")
            raise
        self._task = None

    @staticmethod
    async def _await_cancelled(task: asyncio.Task[Any]) -> None:
        _, pending = await asyncio.wait({task}, timeout=5.0)
        if pending:
            raise RuntimeError("Owned background task did not finish cancellation")
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - teardown must not raise
            logger.exception("backup scheduler raised during force-cancel")
            raise


def _backup_dir_of(service: BackupService) -> Path:
    """Default retention directory: the source database's directory."""
    return service._db_path().parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "BackupError",
    "BackupManifest",
    "BackupService",
    "BackupPolicy",
    "BackupEntry",
    "BackupScheduler",
]
