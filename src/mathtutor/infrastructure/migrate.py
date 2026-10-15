"""Programmatic Alembic migration entry for the product database.

``upgrade_db()`` is callable from startup code (the product app must migrate
before serving) and from ``python -m mathtutor.infrastructure.migrate``.
"""

from __future__ import annotations

from pathlib import Path
from contextlib import closing
import logging

from alembic import command
from alembic.config import Config

from mathtutor.infrastructure.migration_lock import migration_lock

logger = logging.getLogger(__name__)


# Frozen database contract for the 0.2.0 RC.  Keep this aligned with the
# Alembic head; release manifests and packaged smoke assert the exact value.
MIGRATION_HEAD = "024"


def alembic_config(db_path: str | None = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    # Optional explicit path (tests/app factory); otherwise env.py resolves
    # via MATHTUTOR_DB_PATH / MATHTUTOR_DATA_ROOT (production entry).
    if db_path is not None:
        cfg.attributes["db_path"] = db_path
    return cfg


def _backup_before_upgrade(path: Path, key: str | None) -> Path:
    from datetime import datetime, timezone
    from mathtutor.infrastructure import db_crypto

    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"{path.stem}-pre-{MIGRATION_HEAD}-{stamp}.sqlite3"
    backup_key = db_crypto.backup_key()
    # All live-source readers are closed before snapshot can switch SQLite builds.
    db_crypto.snapshot(path, key, target, backup_key)
    target.chmod(0o600)
    if db_crypto.integrity(target, backup_key) != "ok":
        raise RuntimeError("迁移前备份校验失败，原数据库未修改。")
    return target


def _version_rows(connection) -> list[str]:
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
    return [str(row[0]) for row in connection.execute("SELECT version_num FROM alembic_version")] if exists else []


def _validate_recovery_schema(connection) -> None:
    """Require the complete current table contract before removing an ancestor."""
    from sqlalchemy.dialects.sqlite import dialect
    from mathtutor.infrastructure.schema import metadata

    def affinity(type_name):
        name = type_name.upper()
        if "INT" in name:
            return "INTEGER"
        if any(part in name for part in ("CHAR", "CLOB", "TEXT")):
            return "TEXT"
        if not name or "BLOB" in name:
            return "BLOB"
        if any(part in name for part in ("REAL", "FLOA", "DOUB")):
            return "REAL"
        return "NUMERIC"

    problems = []
    for table in metadata.tables.values():
        # Names originate only from the bundled SQLAlchemy metadata.
        columns = connection.execute(f'PRAGMA table_info("{table.name}")').fetchall()
        actual = {row[1]: row for row in columns}
        for column in table.columns:
            row = actual.get(column.name)
            if row is None or affinity(row[2]) != affinity(str(column.type.compile(dialect=dialect()))):
                problems.append(f"{table.name}.{column.name}")
            elif not column.nullable and not row[3]:
                problems.append(f"{table.name}.{column.name} NOT NULL")
        primary_key = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        if primary_key != [column.name for column in table.primary_key.columns]:
            problems.append(f"{table.name} PRIMARY KEY")
        actual_fks = {(row[3], row[2], row[4]) for row in connection.execute(f'PRAGMA foreign_key_list("{table.name}")')}
        for column in table.columns:
            for fk in column.foreign_keys:
                if (column.name, fk.column.table.name, fk.column.name) not in actual_fks:
                    problems.append(f"{table.name}.{column.name} FOREIGN KEY")
    if connection.execute("SELECT name FROM sqlite_master WHERE name='document_chunks_fts'").fetchone() is None:
        problems.append("document_chunks_fts")
    if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
        problems.append("integrity_check")
    if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
        problems.append("foreign_key_check")
    if problems:
        raise RuntimeError("数据库版本记录异常，结构校验未通过，已保留原数据和备份：" + ", ".join(problems[:8]))


def _recover_concurrent_heads(path: Path, key: str | None, backup: Path) -> None:
    from mathtutor.infrastructure import db_crypto

    with closing(db_crypto.connect(path, key=key)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            if sorted(_version_rows(connection)) != ["023", "024"]:
                raise RuntimeError("数据库版本记录在恢复前发生变化，请关闭其他 MathTutor 进程后重试。")
            _validate_recovery_schema(connection)
            # 023 is an ancestor of the fully validated 024, not another branch.
            connection.execute("DELETE FROM alembic_version WHERE version_num = '023'")
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    logger.warning("Recovered concurrent migration revisions 023/024; backup: %s", backup)


def upgrade_db(db_path: str | None = None) -> None:
    """Serialize startup migrations, back up upgrades and recover the known race."""
    from mathtutor.infrastructure import db_crypto
    from mathtutor.infrastructure.db import resolve_db_path

    path = Path(db_path).resolve() if db_path else resolve_db_path().resolve()
    with migration_lock(path):
        if path.exists() and path.stat().st_size:
            key = db_crypto.db_key(path)
            with closing(db_crypto.connect(path, key=key, readonly=True)) as source:
                revisions = _version_rows(source)
            if revisions != [MIGRATION_HEAD]:
                backup = _backup_before_upgrade(path, key)
                if len(revisions) > 1:
                    if sorted(revisions) != ["023", "024"]:
                        raise RuntimeError("数据库存在无法自动恢复的多条版本记录，已保留原数据和备份，请提供启动日志。")
                    _recover_concurrent_heads(path, key, backup)
        command.upgrade(alembic_config(str(path)), "head")


def downgrade_db(revision: str) -> None:
    from mathtutor.infrastructure.db import resolve_db_path

    path = resolve_db_path().resolve()
    with migration_lock(path):
        command.downgrade(alembic_config(str(path)), revision)


if __name__ == "__main__":
    upgrade_db()
