"""Phase 1 SQLite persistence: 1A infrastructure, 1B runtime (CAS/owner/
resume), 1C math facts, 1D educational transaction + outbox (§2/§4/§5/§6
of the Phase 1 storage decision)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio

from mathtutor.application.state_machine import (
    CycleCommand,
    TutoringSession,
    VersionConflictError,
)
from mathtutor.domain.solution import VerificationDecision
from mathtutor.infrastructure import check_db_health, create_db_engine
from mathtutor.repositories.session_store import InMemorySessionStore
from mathtutor.repositories.sqlite_math_facts import (
    SQLiteProblemRepository,
    SQLiteSolutionRepository,
)
from mathtutor.repositories.sqlite_runtime import (
    create_cycle,
    ensure_student,
    load_cycle,
    persist_transition,
)
from mathtutor.repositories.sqlite_store import SQLiteSessionStore
from mathtutor.repositories.uow import MathTutorUow, append_outbox_events
from mathtutor.solving import parse_problem, solve_problem, verify

pytestmark = pytest.mark.asyncio

_STUDENT_A = "student-a"
_STUDENT_B = "student-b"


@pytest_asyncio.fixture()
async def db(tmp_path: Path):
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "math_tutor.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def _prepare_cycle(db, student_id: str, client_session_id: str) -> tuple:
    uow = MathTutorUow(db)
    async with uow.transaction() as conn:
        await ensure_student(conn, student_id=student_id)
        snapshot = await create_cycle(conn, student_id=student_id, client_session_id=client_session_id)
    return uow, snapshot


def _owner(student_id: str):
    from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

    return StudentOwnerScope(
        principal=PrincipalScope(user_id=student_id, username=student_id, role="user"),
        student_id=student_id,
    )


async def _run_first_turn(db, student_id: str, client_session_id: str) -> None:
    """Drive submit_problem → verified through the SQLite store."""
    from mathtutor.capabilities.math_tutor import MathTutorCapability

    store = SQLiteSessionStore(db)
    capability = MathTutorCapability(store=store)
    from deeptutor.core.context import UnifiedContext

    context = UnifiedContext(
        session_id=client_session_id,
        user_message='{"command": "submit_problem", "payload": {"text": "2x + 3 = 7"}}',
        active_capability="math_tutor",
        metadata={"student_owner": _owner(student_id)},
    )
    events: list = []
    from deeptutor.core.stream_bus import StreamBus

    bus = StreamBus()
    async with _collect_events(bus, events):
        await capability.run(context, bus)


class _collect_events:
    def __init__(self, bus, events):
        self.bus = bus
        self.events = events

    async def __aenter__(self):
        import asyncio

        async def _consume():
            async for event in self.bus.subscribe():
                self.events.append(event)

        self._task = asyncio.get_event_loop().create_task(_consume())

    async def __aexit__(self, *exc):
        await self.bus.close()
        await self._task


class TestInfrastructure:
    async def test_migration_creates_all_tables(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        db_file = tmp_path / "migrated.db"
        monkeypatch.setenv("MATHTUTOR_DB_PATH", str(db_file))
        from mathtutor.infrastructure.migrate import upgrade_db

        upgrade_db()
        import sqlite3

        conn = sqlite3.connect(db_file)
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not r[0].startswith("alembic")
        }
        conn.close()
        assert "tutoring_cycles" in tables
        assert "cycle_transitions" in tables
        assert "domain_outbox" in tables
        assert "mastery_evidence" in tables
        # Idempotent: a second upgrade is a no-op.
        upgrade_db()

    async def test_pragmas_wal_and_foreign_keys(self, db) -> None:
        health = await check_db_health(db)
        assert health["status"] == "ok"
        assert health["journal_mode"] == "wal"
        assert health["foreign_keys"] == "on"


class TestRuntimePersistence:
    async def test_create_load_resume(self, db) -> None:
        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        assert snapshot.state == "problem_received"
        assert snapshot.state_version == 0

        async with uow.transaction() as conn:
            loaded = await load_cycle(conn, student_id=_STUDENT_A, client_session_id="s1")
        assert loaded is not None and loaded.cycle_id == snapshot.cycle_id

        # "Restart": a fresh store reads the same authoritative record.
        new_store = SQLiteSessionStore(db)
        session = await new_store.load(_STUDENT_A, "s1")
        assert session is not None
        assert session.state.value == "problem_received"
        assert session.version == 0

    async def test_transition_cas_and_replay_rejected(self, db) -> None:
        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        session = TutoringSession.restore(
            cycle_id=snapshot.cycle_id,
            student_id=_uuid_for(_STUDENT_A),
            session_id=snapshot.session_id,
            state=snapshot.state,
            state_version=snapshot.state_version,
        )
        transition = session.step(CycleCommand.SUBMIT_PROBLEM)
        async with uow.transaction() as conn:
            await persist_transition(
                conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, transition=transition
            )
        # Replaying the SAME transition (stale prior_version) must fail CAS.
        with pytest.raises(VersionConflictError):
            async with uow.transaction() as conn:
                await persist_transition(
                    conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, transition=transition
                )

    async def test_owner_isolation_same_session_name(self, db) -> None:
        await _prepare_cycle(db, _STUDENT_A, "shared")
        async with MathTutorUow(db).transaction() as conn:
            loaded_b = await load_cycle(conn, student_id=_STUDENT_B, client_session_id="shared")
        assert loaded_b is None  # B never sees A's cycle under the same name

    async def test_cross_owner_cas_write_rejected(self, db) -> None:
        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        session = TutoringSession.restore(
            cycle_id=snapshot.cycle_id,
            student_id=_uuid_for(_STUDENT_A),
            session_id=snapshot.session_id,
            state=snapshot.state,
            state_version=snapshot.state_version,
        )
        transition = session.step(CycleCommand.SUBMIT_PROBLEM)
        # B attempts to write A's cycle: owner WHERE clause fails → CAS error.
        with pytest.raises(VersionConflictError):
            async with uow.transaction() as conn:
                await persist_transition(
                    conn, student_id=_STUDENT_B, cycle_id=snapshot.cycle_id, transition=transition
                )


class TestMathFactsPersistence:
    async def test_attestation_roundtrip(self, db) -> None:
        uow = MathTutorUow(db)
        problems = SQLiteProblemRepository(uow)
        solutions = SQLiteSolutionRepository(uow)

        parsed = parse_problem("2x + 3 = 7").problem
        from mathtutor.domain.problem import MathProblem

        problem = await problems.get_or_create(
            MathProblem.canonicalize(
                problem_type=parsed.problem_type,
                normalized_ast=parsed.normalized_ast,
                display_latex=parsed.display_latex,
            )
        )
        solved = solve_problem(problem, parsed)
        decision = verify(problem, solved.candidate)
        assert decision.verdict == "VERIFIED"

        ref = await solutions.issue_attestation(problem, solved.candidate, decision)
        reloaded = await solutions.get_attestation_for_problem(problem.problem_id)
        assert reloaded is not None
        assert reloaded.attestation_hash == ref.attestation_hash
        assert reloaded.problem_content_hash == problem.content_hash

    async def test_attestation_refused_for_failed_decision(self, db) -> None:
        from mathtutor.repositories.solution_repository import AttestationDeniedError

        uow = MathTutorUow(db)
        problems = SQLiteProblemRepository(uow)
        solutions = SQLiteSolutionRepository(uow)
        parsed = parse_problem("2x + 3 = 7").problem
        from mathtutor.domain.problem import MathProblem

        problem = await problems.get_or_create(
            MathProblem.canonicalize(
                problem_type=parsed.problem_type,
                normalized_ast=parsed.normalized_ast,
                display_latex=parsed.display_latex,
            )
        )
        solved = solve_problem(problem, parsed)
        decision = verify(problem, solved.candidate)
        forged = decision.model_copy(update={"verdict": "FAILED"})
        with pytest.raises(AttestationDeniedError):
            await solutions.issue_attestation(problem, solved.candidate, forged)

    async def test_canonical_dedup_by_content_hash(self, db) -> None:
        uow = MathTutorUow(db)
        problems = SQLiteProblemRepository(uow)
        parsed = parse_problem("x^2 = 5").problem
        from mathtutor.domain.problem import MathProblem

        first = await problems.get_or_create(
            MathProblem.canonicalize(
                problem_type=parsed.problem_type,
                normalized_ast=parsed.normalized_ast,
                display_latex=parsed.display_latex,
            )
        )
        second = await problems.get_or_create(
            MathProblem.canonicalize(
                problem_type=parsed.problem_type,
                normalized_ast=parsed.normalized_ast,
                display_latex=parsed.display_latex,
            )
        )
        assert first.problem_id == second.problem_id


class TestEducationalTransaction:
    async def test_atomic_commit_all_or_nothing(self, db) -> None:
        """attempt + assessment + evidence + action + transition + outbox
        commit together; an exception mid-way rolls EVERYTHING back (§2)."""
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_assessment,
            insert_attempt_submission,
            insert_mastery_evidence,
            insert_tutor_action,
        )
        from mathtutor.infrastructure.schema import (
            attempt_assessments,
            attempts,
            domain_outbox,
            mastery_evidence,
            tutor_actions,
        )
        from sqlalchemy import func, select

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        # Move the cycle into AWAITING_ATTEMPT so the education rows bind a
        # real verified problem.
        from mathtutor.domain.problem import MathProblem

        parsed = parse_problem("2x + 3 = 7").problem
        problem = MathProblem.canonicalize(
            problem_type=parsed.problem_type,
            normalized_ast=parsed.normalized_ast,
            display_latex=parsed.display_latex,
        )
        async with uow.transaction() as conn:
            from mathtutor.repositories.sqlite_math_facts import upsert_math_problem

            await upsert_math_problem(conn, problem)

        reference_log_id = await _verified_solution_log(uow, problem, parsed)

        # Attempt the full educational commit, failing mid-transaction.
        with pytest.raises(RuntimeError):
            async with uow.transaction() as conn:
                submission_id = await insert_attempt_submission(
                    conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, raw_text="2"
                )
                attempt_id = await insert_attempt(
                    conn,
                    student_id=_STUDENT_A,
                    cycle_id=snapshot.cycle_id,
                    attempt_submission_id=submission_id,
                    parsed_steps=[],
                    attempt_index=1,
                    payload_hash="h",
                )
                assessment_log_id = await insert_attempt_assessment(
                    conn,
                    student_id=_STUDENT_A,
                    attempt_id=attempt_id,
                    cycle_id=snapshot.cycle_id,
                    problem_id=problem.problem_id,
                    reference_solution_log_id=reference_log_id,
                    correctness="correct",
                    score=1.0,
                    attestation_hash="att-h",
                )
                await insert_mastery_evidence(
                    conn,
                    student_id=_STUDENT_A,
                    attempt_assessment_log_id=assessment_log_id,
                    correctness="correct",
                    score=1.0,
                    difficulty=1,
                    effective_assistance_level=0,
                    evidence_version="v1",
                    idempotency_key="idem-1",
                )
                await insert_tutor_action(
                    conn,
                    student_id=_STUDENT_A,
                    cycle_id=snapshot.cycle_id,
                    action="SHOW_SOLUTION",
                    effective_assistance_level=5,
                    solution_visibility="full",
                )
                await append_outbox_events(
                    conn,
                    [
                        {
                            "aggregate_type": "attempt",
                            "aggregate_id": str(attempt_id),
                            "aggregate_version": 1,
                            "event_sequence": 1,
                            "event_type": "attempt_assessed",
                            "audience": "student",
                            "payload": {},
                        }
                    ],
                )
                raise RuntimeError("simulated crash before COMMIT")

        # EVERYTHING rolled back.
        async with uow.transaction() as conn:
            for table in (attempts, attempt_assessments, mastery_evidence, tutor_actions, domain_outbox):
                count = (await conn.execute(select(func.count()).select_from(table))).scalar_one()
                assert count == 0, table.name

    async def test_successful_commit_persists_all_rows(self, db) -> None:
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_assessment,
            insert_attempt_submission,
            insert_mastery_evidence,
        )
        from mathtutor.infrastructure.schema import domain_outbox
        from sqlalchemy import func, select

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        parsed = parse_problem("2x + 3 = 7").problem
        from mathtutor.domain.problem import MathProblem

        problem = MathProblem.canonicalize(
            problem_type=parsed.problem_type,
            normalized_ast=parsed.normalized_ast,
            display_latex=parsed.display_latex,
        )
        from mathtutor.repositories.sqlite_math_facts import upsert_math_problem

        async with uow.transaction() as conn:
            await upsert_math_problem(conn, problem)
        reference_log_id = await _verified_solution_log(uow, problem, parsed)
        async with uow.transaction() as conn:
            submission_id = await insert_attempt_submission(
                conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, raw_text="2"
            )
            attempt_id = await insert_attempt(
                conn,
                student_id=_STUDENT_A,
                cycle_id=snapshot.cycle_id,
                attempt_submission_id=submission_id,
                parsed_steps=[],
                attempt_index=1,
                payload_hash="h",
            )
            assessment_log_id = await insert_attempt_assessment(
                conn,
                student_id=_STUDENT_A,
                attempt_id=attempt_id,
                cycle_id=snapshot.cycle_id,
                problem_id=problem.problem_id,
                reference_solution_log_id=reference_log_id,
                correctness="correct",
                score=1.0,
                attestation_hash="att-h",
            )
            await insert_mastery_evidence(
                conn,
                student_id=_STUDENT_A,
                attempt_assessment_log_id=assessment_log_id,
                correctness="correct",
                score=1.0,
                difficulty=1,
                effective_assistance_level=0,
                evidence_version="v1",
                idempotency_key="idem-2",
            )
            await append_outbox_events(
                conn,
                [
                    {
                        "aggregate_type": "attempt",
                        "aggregate_id": str(attempt_id),
                        "aggregate_version": 1,
                        "event_sequence": 1,
                        "event_type": "attempt_assessed",
                        "audience": "student",
                        "payload": {},
                    }
                ],
            )
        async with uow.transaction() as conn:
            outbox_count = (await conn.execute(select(func.count()).select_from(domain_outbox))).scalar_one()
        assert outbox_count == 1

    async def test_outbox_event_unique_per_aggregate_version(self, db) -> None:
        uow, _snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        event = {
            "aggregate_type": "cycle",
            "aggregate_id": "c1",
            "aggregate_version": 1,
            "event_sequence": 1,
            "event_type": "transition_committed",
            "audience": "student",
            "payload": {},
        }
        async with uow.transaction() as conn:
            await append_outbox_events(conn, [event])
        # Duplicate (same aggregate/version/sequence) must be rejected by the
        # unique constraint — replay is safe at the DB level.
        import sqlalchemy.exc

        with pytest.raises(sqlalchemy.exc.IntegrityError):
            async with uow.transaction() as conn:
                await append_outbox_events(conn, [event])

    async def test_student_state_cas(self, db) -> None:
        from mathtutor.repositories.sqlite_education import upsert_student_state

        uow, _snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        async with uow.transaction() as conn:
            await upsert_student_state(
                conn,
                student_id=_STUDENT_A,
                estimator_version="rules-v1",
                projection_version=1,
                concept_mastery=[],
                skill_mastery=[],
                active_misconceptions=[],
            )
        # Stale/racing writer skipping a version (current 1, submits 3):
        # CAS fails, no silent overwrite (design doc §11.4).
        with pytest.raises(RuntimeError):
            async with uow.transaction() as conn:
                await upsert_student_state(
                    conn,
                    student_id=_STUDENT_A,
                    estimator_version="rules-v1",
                    projection_version=3,
                    concept_mastery=[],
                    skill_mastery=[],
                    active_misconceptions=[],
                )
        # The correct next version (2) commits.
        async with uow.transaction() as conn:
            await upsert_student_state(
                conn,
                student_id=_STUDENT_A,
                estimator_version="rules-v1",
                projection_version=2,
                concept_mastery=[],
                skill_mastery=[],
                active_misconceptions=[],
            )


class TestEndToEndDurableTurns:
    async def test_restart_resumes_cycle(self, db) -> None:
        """Full capability turn persisted; a NEW capability+store instance
        (simulated restart) resumes the same cycle state/version."""
        store1 = SQLiteSessionStore(db)
        await _run_first_turn(db, _STUDENT_A, "s-e2e")

        # Simulated restart: fresh store object, same database file.
        store2 = SQLiteSessionStore(db)
        session = await store2.load(_STUDENT_A, "s-e2e")
        assert session is not None
        assert session.state.value == "awaiting_attempt"
        assert session.version == 3  # submit → grounding_ok → verification_verified
        assert session.problem_id is not None

    async def test_stale_version_rejected_over_ws_style(self, db) -> None:
        from mathtutor.capabilities.math_tutor import MathTutorCapability
        from deeptutor.core.context import UnifiedContext
        from deeptutor.core.stream_bus import StreamBus

        store = SQLiteSessionStore(db)
        capability = MathTutorCapability(store=store)
        await _run_first_turn(db, _STUDENT_A, "s-stale")

        bus = StreamBus()
        events: list = []
        async with _collect_events(bus, events):
            await capability.run(
                UnifiedContext(
                    session_id="s-stale",
                    user_message=(
                        '{"command": "submit_attempt", "payload": {"answer": "2"}, '
                        '"expected_cycle_version": 0}'
                    ),
                    active_capability="math_tutor",
                    metadata={"student_owner": _owner(_STUDENT_A)},
                ),
                bus,
            )
        errors = [e for e in events if e.type == "error"]
        assert errors and "版本" in errors[0].content


async def _verified_solution_log(uow, problem, parsed):
    """Issue a real solution attestation; return its verification log id."""
    from mathtutor.repositories.sqlite_math_facts import SQLiteSolutionRepository

    solutions = SQLiteSolutionRepository(uow)
    solved = solve_problem(problem, parsed)
    decision = verify(problem, solved.candidate)
    ref = await solutions.issue_attestation(problem, solved.candidate, decision)
    return ref.verification_log_id


def _uuid_for(student_id: str):
    import hashlib
    from uuid import UUID

    return UUID(hex=hashlib.sha256(student_id.encode("utf-8")).hexdigest()[:32])
