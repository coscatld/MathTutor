"""Programmatic Alembic migration entry for the product database.

``upgrade_db()`` is callable from startup code (the product app must migrate
before serving) and from ``python -m mathtutor.infrastructure.migrate``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config


# Frozen database contract for the 0.2.0 RC.  Keep this aligned with the
# Alembic head; release manifests and packaged smoke assert the exact value.
MIGRATION_HEAD = "010"


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
    command.upgrade(alembic_config(db_path), "head")


def downgrade_db(revision: str) -> None:
    command.downgrade(alembic_config(), revision)


if __name__ == "__main__":
    upgrade_db()
