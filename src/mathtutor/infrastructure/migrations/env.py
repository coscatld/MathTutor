"""Alembic environment for the MathTutor product database.

Programmatic config (no alembic.ini file): the URL comes from the product
db resolver, so `python -m mathtutor.migrate` / `upgrade_db()`
always migrate the same file the app opens.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from alembic import context

logger = logging.getLogger("alembic.env")

target_metadata = None  # migrations use schema.metadata directly (see 001)

config = context.config


def _database_url() -> str:
    from pathlib import Path

    explicit = config.attributes.get("db_path")
    if explicit:
        path = Path(str(explicit)).resolve()
    else:
        from mathtutor.infrastructure.db import resolve_db_path

        path = resolve_db_path().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from sqlalchemy import create_engine

    from pathlib import Path

    from mathtutor.infrastructure import db_crypto

    url = _database_url()
    path = Path(url.split("sqlite:///", 1)[1]) if url.startswith("sqlite:///") else None
    key = db_crypto.db_key(path) if path is not None else None
    if key is None:
        engine = create_engine(url, future=True)
    else:
        engine = create_engine(url, future=True, creator=lambda: db_crypto.connect(path, key=key))
    try:
        with engine.connect() as connection:
            do_run_migrations(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
