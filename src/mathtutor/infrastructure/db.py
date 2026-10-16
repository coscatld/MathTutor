"""SQLite engine factory for the MathTutor product (Phase 1A).

One database file (``data/math_tutor.db``) holds runtime, education and
outbox tables together so attempt/assessment/evidence/state/transition/outbox
commit in ONE atomic transaction.

Every connection gets the production PRAGMA set (WAL + FK + busy_timeout):
WAL keeps concurrent readers unblocked during short write transactions;
``foreign_keys=ON`` is per-connection in SQLite and must be re-armed on
every connect.
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Single-writer database: writers wait instead of failing immediately.
_BUSY_TIMEOUT_MS = 5000


def resolve_db_path() -> Path:
    """Resolve the product database path.

    Priority: ``MATHTUTOR_DB_PATH`` > ``<MATHTUTOR_DATA_ROOT>/math_tutor.db``
    > deprecated ``<DEEPTUTOR_HOME>/data/math_tutor.db`` >
    ``./data/math_tutor.db``. Tests inject a tmp path explicitly.
    """
    env_path = os.environ.get("MATHTUTOR_DB_PATH", "").strip()
    if env_path:
        return Path(env_path)
    data_root = os.environ.get("MATHTUTOR_DATA_ROOT", "").strip()
    if data_root:
        return Path(data_root) / "math_tutor.db"
    legacy_home = os.environ.get("DEEPTUTOR_HOME", "").strip()
    if legacy_home:
        return Path(legacy_home) / "data" / "math_tutor.db"
    return Path("data") / "math_tutor.db"


def create_db_engine(db_path: Path | None = None) -> AsyncEngine:
    """Create the async SQLite engine with the production PRAGMA set."""
    path = Path(db_path) if db_path is not None else resolve_db_path()
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    from mathtutor.infrastructure import db_crypto
    key = db_crypto.db_key(path)
    if key is None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True)
    else:
        import aiosqlite

        async def open_encrypted():
            # aiosqlite drives a SQLCipher connection on its worker thread.
            return await aiosqlite.Connection(
                lambda: db_crypto.connect(path, key=key, check_same_thread=False, isolation_level=None),
                iter_chunk_size=64)

        engine = create_async_engine(f"sqlite+aiosqlite:///{path}", future=True, async_creator=open_encrypted)
    from mathtutor.infrastructure.lifecycle_trace import trace
    for event_name in ("connect", "checkout", "checkin", "close"):
        def record(connection, record, *args, stage=event_name):
            trace(id(engine), "pool_" + stage, connection=id(connection))
        event.listen(engine.sync_engine, event_name, record)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover - dbapi callback
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA foreign_keys = ON;")
        cursor.execute("PRAGMA synchronous = NORMAL;")
        cursor.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS};")
        cursor.close()

    return engine


async def check_db_health(engine: AsyncEngine | None = None) -> dict[str, str]:
    """Readiness probe: file reachable, WAL active, schema present."""
    owns_engine = engine is None
    if engine is None:
        engine = create_db_engine()
    try:
        async with engine.connect() as conn:
            ok = (await conn.execute(text("SELECT 1"))).scalar_one()
            journal_mode = (await conn.execute(text("PRAGMA journal_mode"))).scalar_one()
            fk = (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one()
        return {
            "status": "ok" if ok == 1 else "failed",
            "journal_mode": str(journal_mode),
            "foreign_keys": "on" if fk else "off",
        }
    finally:
        # Returning a connection to a private pool still retains its SQLite
        # handle. Borrowed pools belong to the runtime and must stay open.
        if owns_engine:
            await engine.dispose()


__all__ = ["check_db_health", "create_db_engine", "resolve_db_path"]
