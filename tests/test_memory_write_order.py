"""Recent memory writes must stay ordered with a frozen or reversed clock."""

import asyncio
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio

from mathtutor.application.context_assembler import PersonalMemorySourceProvider
from mathtutor.application.personal_memory_service import PersonalMemoryService
from mathtutor.domain.memory import PersonalMemoryNode
from mathtutor.domain.retrieval_policy import RetrievalIntent
from mathtutor.infrastructure import create_db_engine
from mathtutor.infrastructure.schema import metadata
from mathtutor.repositories import memory_repository as memory
from mathtutor.repositories import sqlite_memory as sqlite
from mathtutor.repositories.sqlite_knowledge import SQLiteMemoryRepository
from mathtutor.security.scopes import student_uuid

pytestmark = pytest.mark.asyncio
TICK = datetime(2025, 1, 1, tzinfo=timezone.utc)
MICROSECOND = timedelta(microseconds=1)


def node(owner, number, *, text="saved preference", inferred=False):
    return PersonalMemoryNode(
        memory_id=UUID(int=number), student_id=student_uuid(owner),
        memory_type="ai_inference" if inferred else "user_note",
        subject="数学", predicate="备注", object_json={"text": text},
        source_type="MODEL_INFERRED" if inferred else "USER_EXPLICIT",
        created_at=TICK, updated_at=TICK,
    )


def freeze_clocks(monkeypatch):
    clock = [TICK]
    monkeypatch.setattr(memory, "_now", lambda: clock[0])
    monkeypatch.setattr(sqlite, "_now", lambda: clock[0].isoformat())
    return clock


async def database(path):
    engine = create_db_engine(path)
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    return engine


@pytest_asyncio.fixture(params=("memory", "sqlite"))
async def repository(request, tmp_path, monkeypatch):
    clock = freeze_clocks(monkeypatch)
    engine = None
    if request.param == "memory":
        repo = memory.InMemoryMemoryRepository()
    else:
        engine = await database(tmp_path / "memory-order.db")
        repo = SQLiteMemoryRepository(engine)
    try:
        yield repo, clock
    finally:
        if engine is not None:
            await engine.dispose()


async def first_context_id(repo, owner):
    result = await PersonalMemorySourceProvider(repo).load(
        student_id=owner, intent=RetrievalIntent.REQUEST_HINT,
    )
    return result.payload.entries[0].memory_id


async def test_same_tick_add_edit_confirm_and_retrieval_controls_are_ordered(repository):
    repo, _ = repository
    service = PersonalMemoryService(repo)
    originals = [node("owner", i) for i in range(1, 26)]
    originals.append(node("owner", 26, text="whole oversized condition" * 1000))
    for original in originals:
        await repo.add_node("owner", original)
    stored = [await repo.get_node("owner", original.memory_id) for original in originals]
    assert [n.updated_at for n in stored] == [TICK + i * MICROSECOND for i in range(26)]

    edited = await service.update("owner", originals[0].memory_id,
                                  object_json={"text": "刚刚修改的重要偏好"})
    assert edited.updated_at == TICK + 26 * MICROSECOND
    assert edited.created_at == stored[0].created_at
    assert await first_context_id(repo, "owner") == edited.memory_id

    disabled = await service.set_retrieval_enabled("owner", edited.memory_id, False)
    assert disabled.updated_at == edited.updated_at + MICROSECOND
    assert edited.memory_id not in {n.memory_id for n in await repo.list_retrievable("owner")}
    enabled = await service.set_retrieval_enabled("owner", edited.memory_id, True)
    assert enabled.updated_at == disabled.updated_at + MICROSECOND
    assert await first_context_id(repo, "owner") == edited.memory_id

    inferred = node("owner", 27, inferred=True)
    await repo.add_node("owner", inferred)
    before = await repo.get_node("owner", inferred.memory_id)
    assert before.updated_at == enabled.updated_at + MICROSECOND
    confirmed = await service.confirm("owner", inferred.memory_id)
    assert confirmed.updated_at == before.updated_at + MICROSECOND
    assert confirmed.created_at == before.created_at
    assert await first_context_id(repo, "owner") == inferred.memory_id
    assert (await service.confirm("owner", inferred.memory_id)).updated_at == confirmed.updated_at


async def test_reversed_clock_preserves_order_and_creation_history(repository):
    repo, clock = repository
    oldest, newest = node("owner", 1), node("owner", 2)
    await repo.add_node("owner", oldest)
    await repo.add_node("owner", newest)
    stored = await repo.get_node("owner", oldest.memory_id)
    clock[0] -= timedelta(days=1)
    edited = await PersonalMemoryService(repo).update(
        "owner", oldest.memory_id, object_json={"text": "edited after clock reversal"},
    )
    assert edited.updated_at == TICK + 2 * MICROSECOND
    assert edited.created_at == stored.created_at
    await repo.add_node("owner", node("owner", 3))
    added = await repo.get_node("owner", UUID(int=3))
    assert added.updated_at == edited.updated_at + MICROSECOND
    assert await first_context_id(repo, "owner") == added.memory_id


async def test_logical_clock_is_owner_scoped(repository):
    repo, clock = repository
    clock[0] = TICK + timedelta(days=1)
    await repo.add_node("other-owner", node("other-owner", 1))
    clock[0] = TICK
    await repo.add_node("owner", node("owner", 2))
    own = await repo.get_node("owner", UUID(int=2))
    assert own.updated_at == TICK
    edited = await PersonalMemoryService(repo).update(
        "owner", own.memory_id, object_json={"text": "owner update"},
    )
    assert edited.updated_at == TICK + MICROSECOND
    assert await repo.get_node("owner", UUID(int=1)) is None
    assert (await repo.get_node("other-owner", UUID(int=1))).updated_at == TICK + timedelta(days=1)


async def test_sqlite_write_clock_survives_engine_restart(tmp_path, monkeypatch):
    clock = freeze_clocks(monkeypatch)
    path = tmp_path / "restart.db"
    engine = await database(path)
    try:
        repo = SQLiteMemoryRepository(engine)
        await repo.add_node("owner", node("owner", 1))
        await repo.add_node("owner", node("owner", 2))
        original = await repo.get_node("owner", UUID(int=1))
    finally:
        await engine.dispose()
    clock[0] -= timedelta(days=1)
    reopened = create_db_engine(path)
    try:
        repo = SQLiteMemoryRepository(reopened)
        edited = await PersonalMemoryService(repo).update(
            "owner", UUID(int=1), object_json={"text": "edited after reopening"},
        )
        assert edited.updated_at == TICK + 2 * MICROSECOND
        assert edited.created_at == original.created_at
        assert await first_context_id(repo, "owner") == edited.memory_id
    finally:
        await reopened.dispose()


async def test_sqlite_first_insert_clock_reversal_cannot_precede_creation(tmp_path, monkeypatch):
    ticks = iter((TICK, TICK - timedelta(days=1)))
    monkeypatch.setattr(sqlite, "_now", lambda: next(ticks).isoformat())
    engine = await database(tmp_path / "first-insert.db")
    try:
        repo = SQLiteMemoryRepository(engine)
        await repo.add_node("owner", node("owner", 1))
        stored = await repo.get_node("owner", UUID(int=1))
        assert stored.created_at == TICK
        assert stored.updated_at == TICK
    finally:
        await engine.dispose()


async def test_sqlite_same_owner_parallel_connections_serialize_clock(tmp_path, monkeypatch):
    freeze_clocks(monkeypatch)
    engine = await database(tmp_path / "concurrent.db")
    connection_ids = set()
    try:
        # Both transactions and connections exist before either write starts.
        barrier = asyncio.Barrier(2)

        async def insert(original):
            async with engine.begin() as conn:
                connection_ids.add(id((await conn.get_raw_connection()).driver_connection))
                await barrier.wait()
                await sqlite.insert_personal_memory_node(conn, student_id="owner", node=original)

        await asyncio.gather(insert(node("owner", 1)), insert(node("owner", 2)))
        assert len(connection_ids) == 2
        repo = SQLiteMemoryRepository(engine)
        stored = await repo.list_nodes("owner")
        assert sorted(n.updated_at for n in stored) == [TICK, TICK + MICROSECOND]

        barrier = asyncio.Barrier(2)
        connection_ids.clear()

        async def update(original):
            async with engine.begin() as conn:
                connection_ids.add(id((await conn.get_raw_connection()).driver_connection))
                await barrier.wait()
                return await sqlite.update_personal_memory_node(
                    conn, student_id="owner",
                    node=original.model_copy(update={"object_json": {"text": "concurrent edit"}}),
                )

        updated = await asyncio.gather(*(update(original) for original in stored))
        assert len(connection_ids) == 2
        assert sorted(n.updated_at for n in updated) == [TICK + 2 * MICROSECOND, TICK + 3 * MICROSECOND]
        assert {n.created_at for n in await repo.list_nodes("owner")} == {TICK}
    finally:
        await engine.dispose()
