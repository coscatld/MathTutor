"""Phase 3 restart-safety: the pedagogy state (_verified/_assistance) is
restored from the store at turn start — the capability holds no process
state that outlives a restart (dev-record priority #1).

Acceptance: student requests L1 hint → restart → next hint must CONTINUE
the ladder (L2), never restart from L1; the verified chain is restored so
L3+ projection and SHOW_SOLUTION gating keep working.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio

from mathtutor.capabilities.math_tutor import MathTutorCapability
from mathtutor.infrastructure import create_db_engine
from mathtutor.pedagogy.planner import CycleAssistance
from mathtutor.repositories.session_store import InMemorySessionStore
from mathtutor.repositories.sqlite_store import SQLiteSessionStore
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

pytestmark = pytest.mark.asyncio

_OWNER = StudentOwnerScope(
    principal=PrincipalScope(user_id="student-a", username="a", role="user"),
    student_id="student-a",
)


@pytest_asyncio.fixture()
async def db(tmp_path: Path):
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "math_tutor.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def _turn(capability, session_id: str, message: str) -> list[dict]:
    from deeptutor.core.context import UnifiedContext
    from deeptutor.core.stream_bus import StreamBus

    bus = StreamBus()
    events: list[dict] = []

    async def _consume() -> None:
        async for event in bus.subscribe():
            metadata = event.metadata or {}
            events.append(
                {
                    "type": event.type,
                    "content": event.content,
                    "state": metadata.get("cycle_state", ""),
                    "level": metadata.get("effective_assistance_level"),
                    "action": metadata.get("action", ""),
                }
            )

    task = __import__("asyncio").get_event_loop().create_task(_consume())
    await capability.run(
        UnifiedContext(
            session_id=session_id,
            user_message=message,
            metadata={"student_owner": _OWNER},
        ),
        bus,
    )
    await bus.close()
    await task
    return events


def _hint_level(events: list[dict]) -> int | None:
    levels = [e["level"] for e in events if e["level"] is not None]
    return levels[-1] if levels else None


def _envelope(command: str, payload: dict, session_id: str) -> str:
    return json.dumps(
        {"command": command, "payload": payload, "session_id": session_id},
        ensure_ascii=False,
    )


async def _submit_problem(capability, session_id: str, text: str = "2x + 3 = 7") -> None:
    await _turn(capability, session_id, _envelope("submit_problem", {"text": text}, session_id))


class TestInMemoryStoreRestoresPedagogy:
    async def test_assistance_ledger_survives_capability_rebuild(self) -> None:
        """Same store, NEW capability instance (simulated restart): the
        hint ladder continues instead of restarting from L1."""
        store = InMemorySessionStore()
        cap1 = MathTutorCapability(store=store)
        await _submit_problem(cap1, "s1")
        first = await _turn(cap1, "s1", _envelope("request_hint", {}, "s1"))
        assert _hint_level(first) == 1  # primary policy starts at L1

        # "Restart": fresh capability over the same store.
        cap2 = MathTutorCapability(store=store)
        second = await _turn(cap2, "s1", _envelope("request_hint", {}, "s1"))
        assert _hint_level(second) == 2  # ladder continued, not reset

    async def test_verified_chain_restored_for_projection(self) -> None:
        store = InMemorySessionStore()
        cap1 = MathTutorCapability(store=store)
        await _submit_problem(cap1, "s1")
        cap2 = MathTutorCapability(store=store)
        # Restored verified chain: L3 hint (needs the candidate) works after
        # the "restart" without re-submitting the problem.
        events = await _turn(cap2, "s1", _envelope("request_hint", {}, "s1"))
        assert _hint_level(events) == 1
        events = await _turn(cap2, "s1", _envelope("request_hint", {}, "s1"))
        assert _hint_level(events) == 2
        events = await _turn(cap2, "s1", _envelope("request_hint", {}, "s1"))
        # Primary ladder reaches L3 on the third hint; projection needs the
        # restored candidate — no DisclosurePolicyViolation must surface.
        assert _hint_level(events) == 3


def _sqlite_capability(db):
    """Product-style assembly: store AND math-fact repositories share the
    same SQLite file (mirrors api/product_state.py)."""
    from mathtutor.application.math_tutor_service import MathTutorApplicationService
    from mathtutor.repositories.sqlite_math_facts import (
        SQLiteProblemRepository,
        SQLiteSolutionRepository,
    )
    from mathtutor.repositories.uow import MathTutorUow

    uow = MathTutorUow(db)
    service = MathTutorApplicationService(
        problems=SQLiteProblemRepository(uow),
        solutions=SQLiteSolutionRepository(uow),
    )
    return MathTutorCapability(store=SQLiteSessionStore(db), service=service)


class TestSQLiteStoreRestoresPedagogy:
    async def test_hint_ladder_survives_sqlite_restart(self, db) -> None:
        """THE acceptance case: L1 hint → real restart (new engine-backed
        store) → next hint is L2."""
        cap1 = _sqlite_capability(db)
        await _submit_problem(cap1, "s-durable")
        first = await _turn(cap1, "s-durable", _envelope("request_hint", {}, "s-durable"))
        assert _hint_level(first) == 1

        cap2 = _sqlite_capability(db)  # new store/service: simulated restart
        second = await _turn(cap2, "s-durable", _envelope("request_hint", {}, "s-durable"))
        assert _hint_level(second) == 2
        third = await _turn(cap2, "s-durable", _envelope("request_hint", {}, "s-durable"))
        assert _hint_level(third) == 3

    async def test_assistance_projection_rebuilds_from_actions(self, db) -> None:
        store = SQLiteSessionStore(db)
        cap = _sqlite_capability(db)
        await _submit_problem(cap, "s-proj")
        await _turn(cap, "s-proj", _envelope("request_hint", {}, "s-proj"))
        await _turn(cap, "s-proj", _envelope("request_hint", {}, "s-proj"))
        await _turn(cap, "s-proj", _envelope("request_explanation", {}, "s-proj"))

        session = await store.load("student-a", "s-proj")
        assistance = await store.load_assistance("student-a", session.cycle.cycle_id)
        assert assistance == CycleAssistance(
            hints_issued=2, explanations_issued=1, max_level_issued=2
        )

    async def test_verified_restored_after_sqlite_restart(self, db) -> None:
        cap1 = _sqlite_capability(db)
        await _submit_problem(cap1, "s-verify")
        store1 = SQLiteSessionStore(db)
        session = await store1.load("student-a", "s-verify")
        restored = await store1.load_verified("student-a", session.cycle.cycle_id)
        assert restored is not None
        problem, candidate, ref = restored
        assert problem.problem_type == "linear"
        assert ref.problem_id == problem.problem_id
        assert candidate.problem_id == problem.problem_id
        assert ref.attestation_hash

    async def test_verified_restored_owner_scoped(self, db) -> None:
        cap = _sqlite_capability(db)
        await _submit_problem(cap, "s-owner")
        store = SQLiteSessionStore(db)
        session = await store.load("student-a", "s-owner")
        # Another student asking for the same cycle gets nothing.
        restored = await store.load_verified("student-b", session.cycle.cycle_id)
        assert restored is None
