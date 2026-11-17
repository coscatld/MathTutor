"""Ephemeral storage must exercise production migrations and transaction semantics."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.memory_database import create_memory_engine
from mathtutor.infrastructure.migrate import MIGRATION_HEAD


@pytest.mark.asyncio
async def test_memory_database_is_migrated_isolated_and_never_creates_files(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    first, second = create_db_engine(":memory:"), create_memory_engine()
    try:
        async with first.begin() as conn:
            assert (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == MIGRATION_HEAD
            assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
            assert all(
                row[2] == "" for row in await conn.execute(text("PRAGMA database_list"))
            )
            await conn.execute(text("CREATE TABLE isolation_probe (value INTEGER)"))
            await conn.execute(text("INSERT INTO isolation_probe VALUES (1)"))
            assert (
                await conn.execute(text("SELECT count(*) FROM document_chunks_fts"))
            ).scalar_one() == 0
        async with second.connect() as conn:
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM sqlite_master WHERE name='isolation_probe'"
                    )
                )
            ).scalar_one() == 0
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            async with first.begin() as conn:
                await conn.execute(
                    text("""INSERT INTO solution_candidates
                    (candidate_id, problem_id, steps, final_answer, payload_hash, created_at)
                    VALUES ('orphan', 'missing-problem', '[]', '{}', 'hash', 'now')""")
                )
    finally:
        await first.dispose()
        await second.dispose()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_rollback_and_cancellation_cannot_undo_a_concurrent_commit(cancel):
    engine = create_memory_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE transaction_probe (value TEXT)"))
    acquired = asyncio.Event()
    release = asyncio.Event()
    waiting = asyncio.Event()

    async def failing_writer():
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO transaction_probe VALUES ('rollback')")
            )
            acquired.set()
            await release.wait()
            raise ValueError("rollback this writer only")

    async def successful_writer():
        waiting.set()
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO transaction_probe VALUES ('committed')")
            )

    first = asyncio.create_task(failing_writer())
    second = None
    try:
        await asyncio.wait_for(acquired.wait(), 2)
        second = asyncio.create_task(successful_writer())
        await waiting.wait()
        # Give a broken shared-connection pool time to lease the same transaction.
        await asyncio.sleep(0.03)
        assert not second.done()
        if cancel:
            first.cancel()
        else:
            release.set()
        with pytest.raises(asyncio.CancelledError if cancel else ValueError):
            await first
        await asyncio.wait_for(second, 2)
        async with engine.connect() as conn:
            assert (
                await conn.execute(text("SELECT value FROM transaction_probe"))
            ).scalars().all() == ["committed"]
    finally:
        first.cancel()
        if second is not None:
            second.cancel()
        await asyncio.gather(
            first, *([second] if second is not None else []), return_exceptions=True
        )
        await engine.dispose()
