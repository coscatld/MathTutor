"""Programmatic Alembic migration entry for the product database.

``upgrade_db()`` is callable from startup code (the product app must migrate
before serving) and from ``python -m mathtutor.infrastructure.migrate``.
"""

from __future__ import annotations

from pathlib import Path
from contextlib import closing

from alembic import command
from alembic.config import Config


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


def upgrade_db(db_path: str | None = None) -> None:
    """Apply all pending migrations (idempotent, safe to call every startup)."""
    import sqlite3
    from datetime import datetime, timezone
    from mathtutor.infrastructure.db import resolve_db_path
    path = Path(db_path).resolve() if db_path else resolve_db_path().resolve()
    if path.exists() and path.stat().st_size:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source:
            exists = source.execute("SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
            version = source.execute("SELECT version_num FROM alembic_version").fetchone() if exists else None
            if version is None or version[0] != MIGRATION_HEAD:
                backup_dir = path.parent / "backups"
                backup_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
                backup_path = backup_dir / f"{path.stem}-pre-{MIGRATION_HEAD}-{stamp}.sqlite3"
                with closing(sqlite3.connect(backup_path)) as target:
                    source.backup(target)
                backup_path.chmod(0o600)
    command.upgrade(alembic_config(db_path), "head")


def downgrade_db(revision: str) -> None:
    command.downgrade(alembic_config(), revision)


if __name__ == "__main__":
    upgrade_db()
