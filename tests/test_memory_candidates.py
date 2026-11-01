"""Bounded recent-update selection with no diagnostic body materialization."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import event

from mathtutor.application.context_assembler import PersonalMemorySourceProvider
from mathtutor.application.memory_context import MAX_MEMORY_CONTEXT_CHARS, select_memory_context
from mathtutor.application.personal_memory_service import PersonalMemoryService
from mathtutor.domain.memory import PersonalMemoryNode
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.schema import metadata, personal_memory_nodes
from mathtutor.repositories.memory_repository import InMemoryMemoryRepository
from mathtutor.repositories.sqlite_knowledge import SQLiteMemoryRepository
from mathtutor.repositories.sqlite_runtime import ensure_student
from mathtutor.security.scopes import student_uuid

pytestmark = pytest.mark.asyncio
TICK = datetime(2025, 1, 1, tzinfo=timezone.utc)


def node(i, *, owner="owner", oversized=False, enabled=True, source="USER_EXPLICIT"):
    return PersonalMemoryNode(memory_id=UUID(int=i), student_id=student_uuid(owner), memory_type="user_note",
        subject="synthetic", predicate="note", object_json={"text": "synthetic-big" * 1000 if oversized else f"value-{i}"},
        retrieval_enabled=enabled, source_type=source, created_at=TICK, updated_at=TICK + timedelta(microseconds=i))


async def seed(engine, nodes, owner="owner"):
    async with engine.begin() as conn:
        await ensure_student(conn, student_id=owner)
        await conn.execute(personal_memory_nodes.insert(), [{
            **n.model_dump(exclude={"student_id", "memory_id", "created_at", "updated_at", "deleted_at"}),
            "student_id": owner, "memory_id": str(n.memory_id), "created_at": n.created_at.isoformat(),
            "updated_at": n.updated_at.isoformat(), "deleted_at": None,
        } for n in nodes])


@pytest_asyncio.fixture
async def database(tmp_path):
    engine = create_db_engine(tmp_path / "candidates.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield engine, SQLiteMemoryRepository(engine)
    finally:
        await engine.dispose()


@pytest.mark.parametrize("scenario", ["healthy", "oversized", "disabled", "unconfirmed"])
async def test_ten_thousand_rows_have_bounded_materialization_and_aggregate_empty_diagnostics(database, monkeypatch, scenario):
    engine, repo = database
    records = [node(i, oversized=scenario == "oversized", enabled=scenario != "disabled",
                    source="MODEL_INFERRED" if scenario == "unconfirmed" else "USER_EXPLICIT") for i in range(1, 10001)]
    await seed(engine, records)
    materialized = []
    original = repo.list_recent_retrievable
    async def page(*args, **kwargs):
        rows = await original(*args, **kwargs)
        materialized.append(len(rows))
        assert len(rows) <= kwargs["limit"] <= 32
        return rows
    async def full_read(*args, **kwargs):
        raise AssertionError("provider must not materialize an unbounded list for diagnostics")
    monkeypatch.setattr(repo, "list_recent_retrievable", page)
    monkeypatch.setattr(repo, "list_nodes", full_read)
    monkeypatch.setattr(repo, "list_retrievable", full_read)
    limits = []
    def query(_conn, _cursor, statement, _params, context, _many):
        compiled = context.compiled
        if statement.startswith("SELECT") and "object_json" in statement:
            limit = compiled.statement._limit_clause
            assert limit is not None, "entity reads require a SQL limit"
            limits.append(limit.value)
            assert "retrieval_enabled" in statement and "deleted_at IS NULL" in statement and "source_type IN" in statement
    event.listen(engine.sync_engine, "before_cursor_execute", query)
    result = await PersonalMemorySourceProvider(repo).load_for_tutor(student_id="owner")
    stats = result.selection_stats
    assert stats.live_count == 10000 and stats.rows_read == sum(materialized) <= 256
    assert all(limit <= 32 for limit in limits) and stats.pages == len(materialized)
    assert "synthetic" not in str(asdict(stats)) and "value-" not in result.detail
    if scenario == "disabled":
        assert result.disabled_by_user and stats.enabled_count == stats.eligible_count == stats.rows_read == stats.pages == 0
    elif scenario == "unconfirmed":
        assert result.empty_data and not result.disabled_by_user and stats.eligible_count == stats.rows_read == 0
    elif scenario == "oversized":
        assert not result.payload.entries and stats.rows_read == 256 and stats.selection_scan_limited
    else:
        assert result.payload.entries[0].memory_id == UUID(int=10000)
        assert result.payload == select_memory_context(records)
        assert sum(len(entry.model_dump_json()) for entry in result.payload.entries) <= MAX_MEMORY_CONTEXT_CHARS


async def test_pages_skip_oversized_entries_and_prioritize_recent_edit(database):
    engine, repo = database
    records = [node(i, oversized=i > 80) for i in range(1, 151)]
    await seed(engine, records)
    changed = await PersonalMemoryService(repo).update("owner", records[0].memory_id,
        object_json={"text": "recently edited complete preference"}, expected_updated_at=records[0].updated_at)
    result = await PersonalMemorySourceProvider(repo).load_for_tutor(student_id="owner")
    assert result.payload.entries[0].memory_id == changed.memory_id
    assert result.selection_stats.pages > 2 and result.selection_stats.rows_read <= 256
    assert all(len(entry.model_dump_json()) <= 1600 for entry in result.payload.entries)
    assert result.payload == select_memory_context(await repo.list_retrievable("owner"))


async def test_keyset_ties_and_owner_filters_match_inmemory(database):
    engine, repo = database
    records = [node(i).model_copy(update={"updated_at": TICK}) for i in range(1, 11)]
    await seed(engine, records)
    await seed(engine, [node(20, owner="other")], owner="other")
    memory = InMemoryMemoryRepository()
    # Synthetic tied historical versions exercise the stable cursor suffixes.
    memory._nodes = {n.memory_id: n for n in records + [node(20, owner="other")]}
    for source in (repo, memory):
        result, before = [], None
        while True:
            page = await source.list_recent_retrievable("owner", source_types=("USER_EXPLICIT",), limit=3, before=before)
            if not page:
                break
            result.extend(n.memory_id for n in page)
            before = page[-1].updated_at, page[-1].created_at, page[-1].memory_id
        assert result == [UUID(int=i) for i in range(10, 0, -1)]


async def test_declared_scan_cap_is_explicit_and_never_truncates_a_record(database):
    engine, repo = database
    await seed(engine, [node(i, oversized=i > 10) for i in range(1, 80)])
    limited = await PersonalMemorySourceProvider(repo, page_size=8, max_candidates=32).load_for_tutor(student_id="owner")
    assert not limited.payload.entries
    assert limited.selection_stats.rows_read == 32 and limited.selection_stats.pages == 4
    assert limited.selection_stats.selection_scan_limited
    complete = await PersonalMemorySourceProvider(repo).load_for_tutor(student_id="owner")
    assert len(complete.payload.entries) == 10 and not complete.selection_stats.selection_scan_limited
