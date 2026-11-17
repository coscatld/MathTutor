"""Ephemeral SQLite with the production schema and exclusive transaction leases.

An anchor keeps each named in-memory database alive. A one-connection async
queue pool serializes leases; unlike StaticPool, concurrent coroutines cannot
commit or roll back another coroutine's transaction. Dispose closes the pool
and anchor. No business tables, constraints or repository methods are mocked.
"""

from __future__ import annotations

import atexit
import sqlite3
from threading import RLock
from uuid import uuid4

from alembic import command
from sqlalchemy import create_engine, event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import AsyncAdaptedQueuePool, StaticPool

from mathtutor.infrastructure.migrate import alembic_config

_template = None
_template_lock = RLock()
_owned: set[AsyncEngine] = set()


def _copy_schema(target: sqlite3.Connection) -> None:
    global _template
    with _template_lock:
        if _template is None:
            template = create_engine(
                "sqlite://",
                poolclass=StaticPool,
                connect_args={"check_same_thread": False},
            )
            try:
                with template.begin() as connection:
                    cfg = alembic_config()
                    cfg.attributes["connection"] = connection
                    command.upgrade(cfg, "head")
            except BaseException:
                template.dispose()
                raise
            _template = template
            atexit.register(template.dispose)
        with _template.connect() as connection:
            connection.connection.driver_connection.backup(target)


def create_memory_engine() -> AsyncEngine:
    """Create an isolated, fully migrated database; the caller owns dispose()."""
    uri = f"file:mathtutor-{uuid4().hex}?mode=memory&cache=shared"
    anchor = sqlite3.connect(uri, uri=True, check_same_thread=False)
    try:
        _copy_schema(anchor)
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{uri}&uri=true",
            poolclass=AsyncAdaptedQueuePool,
            pool_size=1,
            max_overflow=0,
            connect_args={"check_same_thread": False},
        )
    except BaseException:
        anchor.close()
        raise
    engine.sync_engine._mathtutor_memory = True
    _owned.add(engine)

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(engine.sync_engine, "engine_disposed")
    def release(_engine):
        anchor.close()
        _owned.discard(engine)

    return engine


def is_memory_engine(engine) -> bool:
    return bool(
        engine is not None and getattr(engine.sync_engine, "_mathtutor_memory", False)
    )


async def dispose_memory_engines() -> None:
    """Close ephemeral runtimes owned by an embedding process or test fixture."""
    for engine in tuple(_owned):
        await engine.dispose()
