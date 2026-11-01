"""Owner-scoped narrow writes, exact-version conflicts and permission races."""
import asyncio
import json
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy import event

from mathtutor.application.context_assembler import PersonalMemorySourceProvider
from mathtutor.application.personal_memory_service import PersonalMemoryService
from mathtutor.domain.memory import MemoryConflictError, MemoryNotFoundError
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole
from mathtutor.infrastructure.schema import metadata
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from mathtutor.repositories.memory_repository import InMemoryMemoryRepository
from mathtutor.repositories.sqlite_knowledge import SQLiteMemoryRepository
from test_tutor_output_contract_integration import Replies

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def pair(request, tmp_path):
    connections = set()
    engines = []
    if request.param == "memory":
        first = second = InMemoryMemoryRepository()
    else:
        path = tmp_path / "race.db"
        for _ in range(2):
            engine = create_db_engine(path)
            event.listen(engine.sync_engine, "connect", lambda dbapi, _: connections.add(id(dbapi)))
            engines.append(engine)
        async with engines[0].begin() as conn:
            await conn.run_sync(metadata.create_all)
        first, second = [SQLiteMemoryRepository(engine) for engine in engines]
    try:
        yield first, second, connections, request.param
    finally:
        for engine in engines:
            await engine.dispose()


async def add(service, inferred=False):
    if inferred:
        return await service.add_inference("owner", subject="synthetic", predicate="preference",
                                           object_json={"text": "permission-race-sentinel"})
    return await service.add_explicit("owner", memory_type="user_note", subject="synthetic",
                                     predicate="preference", object_json={"text": "permission-race-sentinel"})


@pytest.mark.parametrize("action", ["edit", "confirm"])
@pytest.mark.parametrize("enabled", [False, True])
async def test_paused_read_cannot_overwrite_explicit_toggle(pair, monkeypatch, action, enabled):
    first, second, connections, backend = pair
    a, b = PersonalMemoryService(first), PersonalMemoryService(second)
    original = await add(a, action == "confirm")
    if enabled:
        original = await b.set_retrieval_enabled("owner", original.memory_id, False,
                                                 expected_updated_at=original.updated_at)
    barrier, committed = asyncio.Barrier(2), asyncio.Event()
    get = first.get_node
    paused = False
    async def read_then_pause(*args, **kwargs):
        nonlocal paused
        row = await get(*args, **kwargs)
        if not paused:
            paused = True
            await barrier.wait()
            await committed.wait()
        return row
    monkeypatch.setattr(first, "get_node", read_then_pause)
    async def stale_write():
        if action == "edit":
            return await a.update("owner", original.memory_id, object_json={"text": "stale edit"})
        return await a.confirm("owner", original.memory_id)
    writing = asyncio.create_task(stale_write())
    await barrier.wait()
    newest = await b.set_retrieval_enabled("owner", original.memory_id, enabled,
                                          expected_updated_at=original.updated_at)
    committed.set()
    with pytest.raises(MemoryConflictError) as caught:
        await writing
    assert caught.value.latest == newest
    current = await get("owner", original.memory_id)
    assert current.retrieval_enabled is enabled
    assert current.object_json == original.object_json and current.source_type == original.source_type
    if backend == "sqlite":
        assert len(connections) == 2, "race must commit through two independent SQLite connections"
    if not enabled:
        outcome = await PersonalMemorySourceProvider(first).load_for_tutor(student_id="owner")
        assert outcome.disabled_by_user and outcome.payload is None
        provider = Replies("Equality compares values.")
        gateway = GenerativeModelGateway(InMemorySecretStore())
        gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        await TutorChatResponder(gateway).respond("Explain equality.", personal_memory=outcome.payload)
        assert provider.calls
        assert "permission-race-sentinel" not in json.dumps(provider.calls)


@pytest.mark.parametrize("action", ["edit", "confirm"])
async def test_delete_between_read_and_write_is_not_a_conflict_or_resurrection(pair, monkeypatch, action):
    first, second, _, _ = pair
    service = PersonalMemoryService(first)
    node = await add(service, action == "confirm")
    get, entered, release = first.get_node, asyncio.Event(), asyncio.Event()
    once = False
    async def read_then_pause(*args, **kwargs):
        nonlocal once
        row = await get(*args, **kwargs)
        if not once:
            once = True
            entered.set()
            await release.wait()
        return row
    monkeypatch.setattr(first, "get_node", read_then_pause)
    task = asyncio.create_task(service.update("owner", node.memory_id, predicate="changed") if action == "edit"
                               else service.confirm("owner", node.memory_id))
    await entered.wait()
    assert await second.soft_delete_node("owner", node.memory_id)
    release.set()
    with pytest.raises(MemoryNotFoundError):
        await task
    assert await get("owner", node.memory_id) is None
    assert (await get("owner", node.memory_id, include_deleted=True)).deleted_at is not None


async def test_same_snapshot_double_edit_has_one_winner_and_owner_scoped_latest(pair):
    first, second, _, _ = pair
    a, b = PersonalMemoryService(first), PersonalMemoryService(second)
    node = await add(a)
    gate = asyncio.Barrier(2)
    async def update(service, text):
        await gate.wait()
        return await service.update("owner", node.memory_id, object_json={"text": text},
                                    expected_updated_at=node.updated_at)
    results = await asyncio.gather(update(a, "first"), update(b, "second"), return_exceptions=True)
    winners = [x for x in results if not isinstance(x, Exception)]
    conflicts = [x for x in results if isinstance(x, MemoryConflictError)]
    assert len(winners) == len(conflicts) == 1 and conflicts[0].latest == winners[0]
    with pytest.raises(MemoryNotFoundError):
        await b.update("someone-else", node.memory_id, predicate="wrong owner", expected_updated_at=winners[0].updated_at)
    assert await second.patch_node("someone-else", node.memory_id,
                                  expected_updated_at=winners[0].updated_at, predicate="wrong owner") is None


async def test_edit_then_confirm_conflicts_and_confirmed_retry_is_idempotent(pair):
    first, second, _, _ = pair
    service = PersonalMemoryService(first)
    node = await add(service, True)
    edited = await service.update("owner", node.memory_id, object_json={"text": "new inference"},
                                  expected_updated_at=node.updated_at)
    with pytest.raises(MemoryConflictError) as caught:
        await PersonalMemoryService(second).confirm("owner", node.memory_id, expected_updated_at=node.updated_at)
    assert caught.value.latest == edited and edited.source_type == "MODEL_INFERRED"
    disabled = await service.set_retrieval_enabled("owner", node.memory_id, False, expected_updated_at=edited.updated_at)
    confirmed = await service.confirm("owner", node.memory_id, expected_updated_at=disabled.updated_at)
    assert confirmed.source_type == "USER_CONFIRMED" and not confirmed.retrieval_enabled
    again = await service.confirm("owner", node.memory_id, expected_updated_at=node.updated_at)
    assert again == confirmed
    with pytest.raises(MemoryConflictError):
        await service.set_retrieval_enabled("owner", node.memory_id, True, expected_updated_at=node.updated_at)


async def test_legacy_full_node_surface_is_content_only_with_cas(pair):
    first, _, _, _ = pair
    service = PersonalMemoryService(first)
    node = await add(service, True)
    disabled = await service.set_retrieval_enabled("owner", node.memory_id, False)
    stale = node.model_copy(update={"retrieval_enabled": True})
    with pytest.raises(MemoryConflictError):
        await first.update_node("owner", stale)
    crafted = disabled.model_copy(update={"retrieval_enabled": True, "source_type": "USER_CONFIRMED",
        "memory_type": "interest", "subject": "replacement", "created_at": disabled.created_at + timedelta(days=1),
        "predicate": "edited content", "object_json": {"text": "content"}})
    result = await first.update_node("owner", crafted)
    assert not result.retrieval_enabled and result.source_type == "MODEL_INFERRED"
    assert result.memory_type == disabled.memory_type and result.subject == disabled.subject
    assert result.created_at == disabled.created_at and result.predicate == "edited content"
