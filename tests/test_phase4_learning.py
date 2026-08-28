"""Phase 4 learning loop: parse -> verify -> diagnose -> evidence ->
estimate -> project (deterministic, no LLM), plus the persistence contract
(append-only evidence, misconception observations, CAS projection, atomic
commit with outbox, owner isolation, replay/restart determinism).

Acceptance targets (design doc C17):

1  equivalent spellings -> CORRECT (4/2, 2.0, 2=x, x=2 for 2x+3=7)
2  valid intermediate step -> PARTIAL (2x=4)
3  definite error -> INCORRECT
4  unparseable -> UNDETERMINED
5  UNDETERMINED never becomes evidence
6  missing root detected (quadratic, one root of two)
7  extraneous root detected (a claimed root fails substitution)
8  assistance metadata comes from the CycleAssistance ledger
9  L0 > L2 > L4 mastery gain ordering
10 a single misconception observation never activates a long-term label
11 repeated observations raise projection confidence / enter ACTIVE
12 subsequent correct attempts lower then clear the misconception
13 evidence is append-only (no update path; DB unique key rejects replays)
14 StudentState CAS via upsert_student_state inside the projection flow
15 evidence replay -> identical projection
16 restart semantics: fresh estimator + DB-loaded evidence -> same result
17 duplicate submission (same idempotency key) -> one evidence row
18 owner isolation (another student loads nothing)
19 mid-transaction exception rolls back EVERYTHING (incl. observation)
20 outbox commits in the SAME transaction as the education rows
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from mathtutor.domain.attempt import StudentAttempt
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import VerifiedSolutionRef
from mathtutor.learning import (
    Correctness,
    EvidenceFactory,
    LearningEvidence,
    MasteryEstimator,
    MisconceptionObservation,
    diagnose,
    parse_student_attempt,
    project_student_state,
    verify_attempt,
)
from mathtutor.learning.attempt_parser import interpret_attempt
from mathtutor.learning.skills import SKILL_LINEAR_EQUATION, SKILL_QUADRATIC_EQUATION
from mathtutor.pedagogy.planner import CycleAssistance
from mathtutor.solving import parse_problem, solve_problem, verify

pytestmark = pytest.mark.asyncio

_STUDENT_A = "student-a"
_STUDENT_B = "student-b"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid_for(seed: str) -> UUID:
    return UUID(hex=hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32])


def _verified_chain(text: str):
    """parse -> canonicalize -> solve -> verify; returns
    (problem, parsed, verified candidate, verified ref)."""
    parsed = parse_problem(text).problem
    problem = MathProblem.canonicalize(
        problem_type=parsed.problem_type,
        normalized_ast=parsed.normalized_ast,
        display_latex=parsed.display_latex,
    )
    solved = solve_problem(problem, parsed)
    decision = verify(problem, solved.candidate)
    assert decision.verdict == "VERIFIED"
    ref = VerifiedSolutionRef(
        verification_log_id=decision.decision_id,
        problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash,
        solution_candidate_id=solved.candidate.candidate_id,
        solution_payload_hash=solved.candidate.payload_hash,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        attestation_hash="test",
    )
    return problem, parsed, solved.candidate, ref


def _answer_attempt(raw: str, attempt_index: int = 1) -> StudentAttempt:
    return parse_student_attempt(
        attempt_submission_id=uuid4(),
        student_id=_uuid_for("student"),
        cycle_id=uuid4(),
        raw_text=raw,
        attempt_index=attempt_index,
    )


def _assessment(raw: str, problem_text: str) -> tuple:
    """Parse an answer against a verified problem; return
    (problem, attempt, assessment)."""
    problem, _parsed, candidate, _ref = _verified_chain(problem_text)
    attempt = _answer_attempt(raw)
    return problem, attempt, verify_attempt(attempt, problem, candidate)


def _evidence(
    *,
    correctness: str = "correct",
    score: float = 1.0,
    level: int = 0,
    skill: str = SKILL_LINEAR_EQUATION,
    attempt_index: int = 1,
    created_at: str = "",
) -> LearningEvidence:
    from uuid import uuid5

    from mathtutor.learning.evidence import idempotency_key_for

    attempt_id = uuid4()
    student_id = _uuid_for("student")
    key = idempotency_key_for(
        student_id=student_id,
        attempt_id=attempt_id,
        attempt_index=attempt_index,
        skill_id=skill,
    )
    return LearningEvidence(
        evidence_id=uuid5(UUID("8b7a2c4e-1d3f-4a5b-9c6d-0e1f2a3b4c5d"), key),
        student_id=student_id,
        attempt_id=attempt_id,
        skill_id=skill,
        correctness=correctness,
        score=score,
        difficulty=1,
        effective_assistance_level=level,
        attempt_index=attempt_index,
        idempotency_key=key,
        created_at=created_at,
    )


def _observation(
    rule_id: str,
    *,
    attempt_seed: str = "",
    skill: str = SKILL_LINEAR_EQUATION,
    created_at: str = "",
    confidence: float = 0.75,
) -> MisconceptionObservation:
    attempt_id = uuid4() if not attempt_seed else _uuid_for(attempt_seed)
    return MisconceptionObservation(
        observation_id=uuid4(),
        student_id=_uuid_for("student"),
        attempt_id=attempt_id,
        rule_id=rule_id,
        confidence=confidence,
        detail={"skill_id": skill},
        created_at=created_at,
    )


@pytest_asyncio.fixture()
async def db(tmp_path: Path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "math_tutor.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def _prepare_cycle(db, student_id: str, client_session_id: str):
    from mathtutor.repositories.sqlite_runtime import create_cycle, ensure_student
    from mathtutor.repositories.uow import MathTutorUow

    uow = MathTutorUow(db)
    async with uow.transaction() as conn:
        await ensure_student(conn, student_id=student_id)
        snapshot = await create_cycle(
            conn, student_id=student_id, client_session_id=client_session_id
        )
    return uow, snapshot


async def _verified_solution_log(uow, problem, parsed):
    """Issue a real solution attestation; return its verification log id."""
    from mathtutor.repositories.sqlite_math_facts import SQLiteSolutionRepository

    solutions = SQLiteSolutionRepository(uow)
    solved = solve_problem(problem, parsed)
    decision = verify(problem, solved.candidate)
    ref = await solutions.issue_attestation(problem, solved.candidate, decision)
    return ref.verification_log_id


# ===========================================================================
# 1) Attempt verification
# ===========================================================================


class TestAttemptVerification:
    async def test_equivalent_spellings_are_correct(self) -> None:
        """Item 1: x=2 / 4/2 / 2.0 / 2=x all CORRECT for 2x+3=7."""
        problem, _parsed, candidate, _ref = _verified_chain("2x + 3 = 7")
        for raw in ("x=2", "4/2", "2.0", "2=x", "x=4/2"):
            attempt = _answer_attempt(raw)
            assessment = verify_attempt(attempt, problem, candidate)
            assert assessment.correctness is Correctness.CORRECT, raw
            assert assessment.score == 1.0

    async def test_valid_intermediate_step_is_partial(self) -> None:
        """Item 2: 2x=4 is an equivalent equation but not the final value."""
        problem, _parsed, candidate, _ref = _verified_chain("2x + 3 = 7")
        attempt = _answer_attempt("2x=4")
        assessment = verify_attempt(attempt, problem, candidate)
        assert assessment.correctness is Correctness.PARTIAL
        assert assessment.score == 0.5
        assert "equivalent_equation" in assessment.signals
        assert assessment.verified_claims
        assert assessment.remaining_requirements

    async def test_definite_error_is_incorrect(self) -> None:
        """Item 3: a wrong value with no valid claim is INCORRECT."""
        problem, _parsed, candidate, _ref = _verified_chain("2x + 3 = 7")
        attempt = _answer_attempt("3")
        assessment = verify_attempt(attempt, problem, candidate)
        assert assessment.correctness is Correctness.INCORRECT
        assert assessment.score == 0.0
        assert "wrong_value" in assessment.signals
        assert assessment.invalid_claims

    async def test_unparseable_is_undetermined(self) -> None:
        """Item 4: parse failure is UNDETERMINED, never an exception."""
        problem, _parsed, candidate, _ref = _verified_chain("2x + 3 = 7")
        for raw in ("???", "x==2", ""):
            attempt = _answer_attempt(raw)
            parsed = interpret_attempt(attempt)
            assert parsed.kind == "undeterminable"
            assessment = verify_attempt(attempt, problem, candidate)
            assert assessment.correctness is Correctness.UNDETERMINED
            assert assessment.score is None

    async def test_missing_root_is_partial_with_signal(self) -> None:
        """Item 6: x^2=4 answered 'x=2' -> PARTIAL + missing_root."""
        problem, _parsed, candidate, _ref = _verified_chain("x^2 = 4")
        attempt = _answer_attempt("x=2")
        assessment = verify_attempt(attempt, problem, candidate)
        assert assessment.correctness is Correctness.PARTIAL
        assert "missing_root" in assessment.signals
        assert assessment.score == 0.5
        assert assessment.remaining_requirements

    async def test_wrong_root_is_incorrect(self) -> None:
        """Quadratic policy: a wrong root is INCORRECT (never partial)."""
        problem, _parsed, candidate, _ref = _verified_chain("x^2 = 4")
        attempt = _answer_attempt("x=3")
        assessment = verify_attempt(attempt, problem, candidate)
        assert assessment.correctness is Correctness.INCORRECT
        assert "wrong_value" in assessment.signals

    async def test_extraneous_root_is_incorrect(self) -> None:
        """Item 7: (x-2)(x+3)=0 claims roots {2, -3}; -3 fails
        substitution -> INCORRECT with extraneous_root (policy: 增根)."""
        problem, _parsed, candidate, _ref = _verified_chain("x^2 = 4")
        attempt = _answer_attempt("(x-2)(x+3)=0")
        assessment = verify_attempt(attempt, problem, candidate)
        assert assessment.correctness is Correctness.INCORRECT
        assert "extraneous_root" in assessment.signals

    async def test_sign_flip_and_transposition_signals(self) -> None:
        problem, _parsed, candidate, _ref = _verified_chain("2x + 3 = 7")
        flip = verify_attempt(_answer_attempt("x=-2"), problem, candidate)
        assert flip.correctness is Correctness.INCORRECT
        assert "sign_flip" in flip.signals
        # Same x coefficient, wrong constant: the transposition slip 2x=10.
        transposition = verify_attempt(_answer_attempt("2x=10"), problem, candidate)
        assert transposition.correctness is Correctness.INCORRECT
        assert "wrong_operation" in transposition.signals

    async def test_empty_root_set_answers(self) -> None:
        # No real roots: "无实数解" is the complete, correct answer.
        problem, _parsed, candidate, _ref = _verified_chain("x^2 + 1 = 0")
        correct = verify_attempt(_answer_attempt("无实数解"), problem, candidate)
        assert correct.correctness is Correctness.CORRECT
        # ...but wrong when the equation has real roots.
        problem2, _p2, candidate2, _r2 = _verified_chain("x^2 = 4")
        wrong = verify_attempt(_answer_attempt("无解"), problem2, candidate2)
        assert wrong.correctness is Correctness.INCORRECT

    async def test_arithmetic_and_polynomial_families(self) -> None:
        a_problem, _ap, a_candidate, _ar = _verified_chain("1/2 + 1/3")
        assert verify_attempt(_answer_attempt("5/6"), a_problem, a_candidate).correctness is Correctness.CORRECT
        assert verify_attempt(_answer_attempt("1"), a_problem, a_candidate).correctness is Correctness.INCORRECT

        p_problem, _pp, p_candidate, _pr = _verified_chain("(x+1)(x+1)")
        assert verify_attempt(_answer_attempt("x^2+2x+1"), p_problem, p_candidate).correctness is Correctness.CORRECT
        wrong = verify_attempt(_answer_attempt("x^2+2x+2"), p_problem, p_candidate)
        assert wrong.correctness is Correctness.INCORRECT
        assert "wrong_value" in wrong.signals
        family = verify_attempt(_answer_attempt("x=1"), p_problem, p_candidate)
        assert family.correctness is Correctness.INCORRECT
        assert "wrong_family" in family.signals


# ===========================================================================
# 2) Diagnosis rules
# ===========================================================================


class TestDiagnosis:
    async def test_sign_error_rule(self) -> None:
        problem, attempt, assessment = _assessment("x=-2", "2x + 3 = 7")
        observation = diagnose(assessment=assessment, problem=problem, attempt=attempt)
        assert observation is not None
        assert observation.rule_id == "miscon-sign-error"
        assert observation.confidence == 0.8
        assert observation.detail["skill_id"] == SKILL_LINEAR_EQUATION

    async def test_missing_root_rule(self) -> None:
        problem, attempt, assessment = _assessment("x=2", "x^2 = 4")
        observation = diagnose(assessment=assessment, problem=problem, attempt=attempt)
        assert observation is not None
        assert observation.rule_id == "miscon-missing-root"

    async def test_transposition_rule(self) -> None:
        problem, attempt, assessment = _assessment("2x=10", "2x + 3 = 7")
        observation = diagnose(assessment=assessment, problem=problem, attempt=attempt)
        assert observation is not None
        assert observation.rule_id == "miscon-transposition-error"

    async def test_no_observation_for_correct_undetermined_or_valid_step(self) -> None:
        # CORRECT never diagnoses.
        problem, attempt, assessment = _assessment("2", "2x + 3 = 7")
        assert diagnose(assessment=assessment, problem=problem, attempt=attempt) is None
        # UNDETERMINED never diagnoses.
        problem, attempt, assessment = _assessment("???", "2x + 3 = 7")
        assert diagnose(assessment=assessment, problem=problem, attempt=attempt) is None
        # A valid equivalent step is not a misconception.
        problem, attempt, assessment = _assessment("2x=4", "2x + 3 = 7")
        assert diagnose(assessment=assessment, problem=problem, attempt=attempt) is None

    async def test_observation_is_deterministic_per_attempt(self) -> None:
        problem, attempt, assessment = _assessment("x=-2", "2x + 3 = 7")
        first = diagnose(assessment=assessment, problem=problem, attempt=attempt)
        second = diagnose(assessment=assessment, problem=problem, attempt=attempt)
        assert first == second
        assert first.observation_id == second.observation_id


# ===========================================================================
# 3) Evidence factory
# ===========================================================================


class TestEvidenceFactory:
    def _factory_chain(self, raw: str, problem_text: str, assistance: CycleAssistance):
        problem, _parsed, candidate, ref = _verified_chain(problem_text)
        attempt = _answer_attempt(raw)
        assessment = verify_attempt(attempt, problem, candidate)
        return problem, attempt, assessment, ref

    async def test_undetermined_produces_no_evidence(self) -> None:
        """Item 5 (hard invariant): UNDETERMINED -> None, never evidence."""
        problem, _parsed, candidate, ref = _verified_chain("2x + 3 = 7")
        assessment = verify_attempt(_answer_attempt("???"), problem, candidate)
        assert assessment.correctness is Correctness.UNDETERMINED
        evidence = EvidenceFactory().build_evidence(
            assessment=assessment,
            verified_ref=ref,
            skill_id=SKILL_LINEAR_EQUATION,
            assistance=CycleAssistance(),
            attempt_index=1,
        )
        assert evidence is None

    async def test_assistance_ledger_shapes_evidence(self) -> None:
        """Item 8: the same attempt under different assistance ledgers
        yields DIFFERENT effective_assistance_level but the SAME
        idempotency key (one attempt == one evidence row)."""
        problem, _parsed, candidate, ref = _verified_chain("2x + 3 = 7")
        assessment = verify_attempt(_answer_attempt("2"), problem, candidate)
        factory = EvidenceFactory()
        independent = factory.build_evidence(
            assessment=assessment,
            verified_ref=ref,
            skill_id=SKILL_LINEAR_EQUATION,
            assistance=CycleAssistance(),
            attempt_index=1,
        )
        helped = factory.build_evidence(
            assessment=assessment,
            verified_ref=ref,
            skill_id=SKILL_LINEAR_EQUATION,
            assistance=CycleAssistance(hints_issued=1, max_level_issued=4),
            attempt_index=1,
        )
        assert independent is not None and helped is not None
        assert independent.effective_assistance_level == 0
        assert helped.effective_assistance_level == 4
        assert independent.idempotency_key == helped.idempotency_key
        assert independent.evidence_id == helped.evidence_id
        assert helped.correctness == "correct"

    async def test_same_inputs_same_output(self) -> None:
        """Item 17: the factory is fully deterministic (same key -> same
        evidence, including the evidence id)."""
        problem, _parsed, candidate, ref = _verified_chain("2x + 3 = 7")
        assessment = verify_attempt(_answer_attempt("2"), problem, candidate)
        factory = EvidenceFactory()
        kwargs = dict(
            assessment=assessment,
            verified_ref=ref,
            skill_id=SKILL_LINEAR_EQUATION,
            assistance=CycleAssistance(),
            attempt_index=1,
        )
        first = factory.build_evidence(**kwargs)
        second = factory.build_evidence(**kwargs)
        assert first is not None
        assert first == second

    async def test_observation_bound_into_evidence(self) -> None:
        problem, attempt, assessment, ref = self._factory_chain("x=-2", "2x + 3 = 7", CycleAssistance())
        observation = diagnose(assessment=assessment, problem=problem, attempt=attempt)
        assert observation is not None
        evidence = EvidenceFactory().build_evidence(
            assessment=assessment,
            verified_ref=ref,
            skill_id=SKILL_LINEAR_EQUATION,
            assistance=CycleAssistance(),
            attempt_index=1,
            observation=observation,
        )
        assert evidence is not None
        assert evidence.misconception_observation_ids == (observation.observation_id,)

    async def test_verified_ref_mismatch_raises(self) -> None:
        problem, _parsed, candidate, ref = _verified_chain("2x + 3 = 7")
        assessment = verify_attempt(_answer_attempt("2"), problem, candidate)
        forged = ref.model_copy(update={"problem_id": uuid4()})
        with pytest.raises(ValueError):
            EvidenceFactory().build_evidence(
                assessment=assessment,
                verified_ref=forged,
                skill_id=SKILL_LINEAR_EQUATION,
                assistance=CycleAssistance(),
                attempt_index=1,
            )


# ===========================================================================
# 4) Estimator
# ===========================================================================


class TestEstimator:
    async def test_gain_ordering_l0_gt_l2_gt_l4(self) -> None:
        """Item 9: same correctness, different max_level_issued ->
        L0 gain > L2 gain > L4 gain."""
        estimator = MasteryEstimator()
        deltas = [
            estimator.delta_for(_evidence(correctness="correct", level=level))
            for level in (0, 2, 4)
        ]
        assert deltas == [1.0, 0.6, 0.2]
        assert deltas[0] > deltas[1] > deltas[2]

    async def test_incorrect_penalty_and_mastery_clamps(self) -> None:
        estimator = MasteryEstimator()
        correct = _evidence(correctness="correct", level=0)
        wrong = _evidence(correctness="incorrect", level=0)
        # Correct twice from 0: capped at MAX_MASTERY.
        assert estimator.apply(0.0, correct) == 1.0
        assert estimator.apply(1.0, correct) == 1.0
        # Incorrect reduces but never below MIN_MASTERY.
        assert estimator.apply(0.5, wrong) == pytest.approx(0.3)
        assert estimator.apply(0.0, wrong) == 0.0

    async def test_partial_is_proportional_to_score(self) -> None:
        estimator = MasteryEstimator()
        half = _evidence(correctness="partial", score=0.5, level=0)
        full = _evidence(correctness="partial", score=1.0, level=0)
        assert estimator.apply(0.0, half) == 0.5
        assert estimator.apply(0.0, full) == 1.0


# ===========================================================================
# 5) Projection (pure, replayable)
# ===========================================================================


class TestProjection:
    async def test_replay_same_projection(self) -> None:
        """Item 15: the same sequences recomputed twice give the SAME
        projection (fresh estimator instances)."""
        evidence = [
            _evidence(correctness="incorrect", level=0, created_at="t1"),
            _evidence(correctness="correct", level=0, created_at="t2"),
        ]
        observations = [
            _observation("miscon-sign-error", attempt_seed="a1", created_at="t1"),
        ]
        student = _uuid_for("student")
        first = project_student_state(student_id=student, evidence=evidence, observations=observations)
        second = project_student_state(
            student_id=student,
            evidence=evidence,
            observations=observations,
            estimator=MasteryEstimator(),
        )
        assert first == second
        assert first.projection_version == 2
        # And the projection is stable across model serialization.
        assert first.model_dump() == second.model_dump()

    async def test_skill_mastery_tracks_only_its_skill(self) -> None:
        evidence = [_evidence(correctness="correct", level=0, skill=SKILL_QUADRATIC_EQUATION)]
        projection = project_student_state(student_id=_uuid_for("student"), evidence=evidence)
        by_skill = {item["skill_id"]: item["mastery"] for item in projection.skill_mastery}
        assert by_skill[SKILL_QUADRATIC_EQUATION] == 1.0
        assert by_skill[SKILL_LINEAR_EQUATION] == 0.0
        assert projection.projection_version == 1

    async def test_single_observation_never_activates(self) -> None:
        """Item 10: one observation stays a CANDIDATE — nothing projected."""
        observations = [_observation("miscon-sign-error", attempt_seed="a1", created_at="t1")]
        projection = project_student_state(
            student_id=_uuid_for("student"), evidence=(), observations=observations
        )
        assert projection.active_misconceptions == ()

    async def test_two_observations_activate_and_confidence_grows(self) -> None:
        """Item 11: >=2 observations on DISTINCT attempts -> ACTIVE; more
        observations raise the confidence."""
        student = _uuid_for("student")
        two = [
            _observation("miscon-sign-error", attempt_seed="a1", created_at="t1"),
            _observation("miscon-sign-error", attempt_seed="a2", created_at="t2"),
        ]
        active = project_student_state(student_id=student, observations=two).active_misconceptions
        assert len(active) == 1
        assert active[0]["status"] == "active"
        assert active[0]["confidence"] == pytest.approx(0.75)
        three = two + [_observation("miscon-sign-error", attempt_seed="a3", created_at="t3")]
        stronger = project_student_state(student_id=student, observations=three).active_misconceptions
        assert stronger[0]["confidence"] == pytest.approx(0.85)

    async def test_repeated_same_attempt_does_not_activate(self) -> None:
        """The reducer counts DISTINCT attempts: one attempt observed twice
        is still a single observation."""
        same = [
            _observation("miscon-sign-error", attempt_seed="a1", created_at="t1"),
            _observation("miscon-sign-error", attempt_seed="a1", created_at="t2"),
        ]
        projection = project_student_state(
            student_id=_uuid_for("student"), observations=same
        )
        assert projection.active_misconceptions == ()

    async def test_correct_attempts_lower_then_clear(self) -> None:
        """Item 12: correct attempts after activation decay the projection
        (RESOLVING) and finally clear it (RESOLVED, dropped)."""
        student = _uuid_for("student")
        observations = [
            _observation("miscon-sign-error", attempt_seed="a1", created_at="t1"),
            _observation("miscon-sign-error", attempt_seed="a2", created_at="t2"),
        ]
        no_correction = project_student_state(
            student_id=student, observations=observations
        ).active_misconceptions
        assert no_correction[0]["status"] == "active"

        one_correct = project_student_state(
            student_id=student,
            evidence=[
                _evidence(correctness="correct", level=0, created_at="t3"),
            ],
            observations=observations,
        ).active_misconceptions
        assert len(one_correct) == 1
        assert one_correct[0]["status"] == "resolving"
        assert one_correct[0]["confidence"] < no_correction[0]["confidence"]

        two_correct = project_student_state(
            student_id=student,
            evidence=[
                _evidence(correctness="correct", level=0, created_at="t3"),
                _evidence(correctness="correct", level=0, created_at="t4"),
            ],
            observations=observations,
        ).active_misconceptions
        assert two_correct == ()

    async def test_reinforcement_rearms_after_correction(self) -> None:
        """A new observation after corrections re-arms the rule: the
        correct attempts before the latest observation no longer decay it
        (the reducer replays the full history, reinforcement included)."""
        student = _uuid_for("student")
        observations = [
            _observation("miscon-sign-error", attempt_seed="a1", created_at="t1"),
            _observation("miscon-sign-error", attempt_seed="a2", created_at="t2"),
            _observation("miscon-sign-error", attempt_seed="a3", created_at="t5"),
        ]
        evidence = [
            _evidence(correctness="correct", level=0, created_at="t3"),
            _evidence(correctness="correct", level=0, created_at="t4"),
        ]
        projection = project_student_state(
            student_id=student, evidence=evidence, observations=observations
        )
        assert len(projection.active_misconceptions) == 1
        # 3 distinct observations -> 0.85; the correct attempts predate the
        # latest observation, so nothing decays.
        assert projection.active_misconceptions[0]["confidence"] == pytest.approx(0.85)


# ===========================================================================
# 6) Persistence contract
# ===========================================================================


class TestMigration002:
    async def test_migration_creates_misconception_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_file = tmp_path / "migrated.db"
        monkeypatch.setenv("MATHTUTOR_DB_PATH", str(db_file))
        from mathtutor.infrastructure.migrate import upgrade_db

        upgrade_db()
        conn = sqlite3.connect(db_file)
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if not row[0].startswith("alembic")
        }
        conn.close()
        assert "misconception_observations" in tables
        # The 001 tables are still there.
        assert "tutoring_cycles" in tables
        assert "mastery_evidence" in tables
        # Idempotent: a second upgrade is a no-op.
        upgrade_db()


class TestPersistenceContract:
    async def test_evidence_append_only_and_unique_key(self, db) -> None:
        """Item 13 + 17: no update path exists; the unique idempotency key
        rejects a duplicate at the database level."""
        import sqlalchemy.exc

        from mathtutor.repositories import sqlite_education as edu
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_assessment,
            insert_attempt_submission,
            insert_mastery_evidence,
        )
        from mathtutor.infrastructure.schema import mastery_evidence
        from mathtutor.repositories.sqlite_math_facts import upsert_math_problem

        # Append-only: the repository exposes NO update function for evidence.
        assert not any(
            "update" in name.lower() and "evidence" in name.lower() for name in dir(edu)
        )

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        problem, parsed, _candidate, _ref = _verified_chain("2x + 3 = 7")
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
                evidence_version="mt-evidence-v1",
                idempotency_key="idem-dup",
            )

        # The same key again: the database itself refuses.
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            async with uow.transaction() as conn:
                await insert_mastery_evidence(
                    conn,
                    student_id=_STUDENT_A,
                    attempt_assessment_log_id=assessment_log_id,
                    correctness="correct",
                    score=1.0,
                    difficulty=1,
                    effective_assistance_level=0,
                    evidence_version="mt-evidence-v1",
                    idempotency_key="idem-dup",
                )
        async with uow.transaction() as conn:
            count = (
                await conn.execute(select(func.count()).select_from(mastery_evidence))
            ).scalar_one()
        assert count == 1

    async def test_observation_unique_per_attempt_and_rule(self, db) -> None:
        import sqlalchemy.exc

        from mathtutor.infrastructure.schema import misconception_observations
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_submission,
            insert_misconception_observation,
        )

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        async with uow.transaction() as conn:
            submission_id = await insert_attempt_submission(
                conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, raw_text="x=-2"
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
            await insert_misconception_observation(
                conn,
                student_id=_STUDENT_A,
                attempt_id=attempt_id,
                rule_id="miscon-sign-error",
                confidence=0.8,
                detail={"skill_id": SKILL_LINEAR_EQUATION},
            )
        # A replayed diagnosis of the same attempt+rule is refused by the
        # unique constraint (in its own transaction; the first row survives).
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            async with uow.transaction() as conn:
                await insert_misconception_observation(
                    conn,
                    student_id=_STUDENT_A,
                    attempt_id=attempt_id,
                    rule_id="miscon-sign-error",
                    confidence=0.8,
                    detail={"skill_id": SKILL_LINEAR_EQUATION},
                )
        async with uow.transaction() as conn:
            count = (
                await conn.execute(
                    select(func.count()).select_from(misconception_observations)
                )
            ).scalar_one()
        assert count == 1

    async def test_owner_isolation(self, db) -> None:
        """Item 18: another student loads no evidence and no observations."""
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_assessment,
            insert_attempt_submission,
            insert_mastery_evidence,
            insert_misconception_observation,
            load_evidence_for_student,
            load_misconception_observations_for_student,
        )
        from mathtutor.repositories.sqlite_math_facts import upsert_math_problem

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        problem, parsed, _candidate, _ref = _verified_chain("2x + 3 = 7")
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
            await insert_misconception_observation(
                conn,
                student_id=_STUDENT_A,
                attempt_id=attempt_id,
                rule_id="miscon-sign-error",
                confidence=0.8,
                detail={"skill_id": SKILL_LINEAR_EQUATION},
            )
            await insert_mastery_evidence(
                conn,
                student_id=_STUDENT_A,
                attempt_assessment_log_id=assessment_log_id,
                correctness="correct",
                score=1.0,
                difficulty=1,
                effective_assistance_level=0,
                evidence_version="mt-evidence-v1",
                idempotency_key="idem-owner",
            )
        async with uow.transaction() as conn:
            assert await load_evidence_for_student(conn, _STUDENT_B) == []
            assert await load_misconception_observations_for_student(conn, _STUDENT_B) == []

    async def test_student_state_cas_in_projection_flow(self, db) -> None:
        """Item 14: the projection flow persists through the existing CAS
        upsert — stale writers are rejected, the next version commits."""
        from mathtutor.repositories.sqlite_education import upsert_student_state

        uow, _snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        evidence = [_evidence(correctness="correct", level=0)]
        projection = project_student_state(student_id=_uuid_for("student"), evidence=evidence)
        assert projection.projection_version == 1
        async with uow.transaction() as conn:
            await upsert_student_state(
                conn,
                student_id=_STUDENT_A,
                estimator_version=projection.estimator_version,
                projection_version=projection.projection_version,
                concept_mastery=list(projection.concept_mastery),
                skill_mastery=list(projection.skill_mastery),
                active_misconceptions=list(projection.active_misconceptions),
            )
        # A stale writer skipping a version is rejected (no silent overwrite).
        with pytest.raises(RuntimeError):
            async with uow.transaction() as conn:
                await upsert_student_state(
                    conn,
                    student_id=_STUDENT_A,
                    estimator_version=projection.estimator_version,
                    projection_version=3,
                    concept_mastery=[],
                    skill_mastery=[],
                    active_misconceptions=[],
                )
        # The correct next version (2) commits.
        second = project_student_state(
            student_id=_uuid_for("student"), evidence=evidence + [_evidence(correctness="correct")]
        )
        assert second.projection_version == 2
        async with uow.transaction() as conn:
            await upsert_student_state(
                conn,
                student_id=_STUDENT_A,
                estimator_version=second.estimator_version,
                projection_version=second.projection_version,
                concept_mastery=list(second.concept_mastery),
                skill_mastery=list(second.skill_mastery),
                active_misconceptions=list(second.active_misconceptions),
            )

    async def test_db_replay_restart_semantics(self, db) -> None:
        """Item 16: a fresh estimator/projection instance replayed over
        DB-loaded evidence yields the SAME projection every time."""
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_assessment,
            insert_attempt_submission,
            insert_mastery_evidence,
            insert_misconception_observation,
            load_evidence_for_student,
            load_misconception_observations_for_student,
        )
        from mathtutor.repositories.sqlite_math_facts import upsert_math_problem

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        problem, parsed, _candidate, _ref = _verified_chain("2x + 3 = 7")
        async with uow.transaction() as conn:
            await upsert_math_problem(conn, problem)
        reference_log_id = await _verified_solution_log(uow, problem, parsed)
        async with uow.transaction() as conn:
            submission_id = await insert_attempt_submission(
                conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, raw_text="x=-2"
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
                correctness="incorrect",
                score=0.0,
                attestation_hash="att-h",
            )
            await insert_misconception_observation(
                conn,
                student_id=_STUDENT_A,
                attempt_id=attempt_id,
                rule_id="miscon-sign-error",
                confidence=0.8,
                detail={"skill_id": SKILL_LINEAR_EQUATION},
            )
            await insert_mastery_evidence(
                conn,
                student_id=_STUDENT_A,
                attempt_assessment_log_id=assessment_log_id,
                correctness="incorrect",
                score=0.0,
                difficulty=1,
                effective_assistance_level=0,
                evidence_version="mt-evidence-v1",
                idempotency_key="idem-replay",
            )

        async def replay() -> tuple:
            async with uow.transaction() as conn:
                loaded_evidence = await load_evidence_for_student(conn, _STUDENT_A)
                loaded_observations = await load_misconception_observations_for_student(
                    conn, _STUDENT_A
                )
            projection = project_student_state(
                student_id=_uuid_for("student"),
                evidence=loaded_evidence,
                observations=loaded_observations,
                estimator=MasteryEstimator(),  # simulated restart: fresh instance
            )
            return (loaded_evidence, loaded_observations, projection)

        first_evidence, first_observations, first_projection = await replay()
        assert len(first_evidence) == 1
        assert len(first_observations) == 1
        # The join re-derived the skill and the attempt identity.
        assert first_evidence[0].skill_id == SKILL_LINEAR_EQUATION
        assert first_evidence[0].attempt_id is not None
        assert first_evidence[0].attempt_index == 1
        # Misconception stays a candidate: one observation, one incorrect.
        assert first_projection.active_misconceptions == ()
        assert first_projection.projection_version == 1

        second_evidence, second_observations, second_projection = await replay()
        assert first_evidence == second_evidence
        assert first_observations == second_observations
        assert first_projection == second_projection

    async def test_atomic_rollback_includes_observation(self, db) -> None:
        """Item 19: attempt + assessment + observation + evidence + state +
        outbox written together; an exception rolls EVERYTHING back."""
        from mathtutor.infrastructure.schema import (
            attempt_assessments,
            attempts,
            domain_outbox,
            mastery_evidence,
            misconception_observations,
            student_state_projections,
        )
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_assessment,
            insert_attempt_submission,
            insert_mastery_evidence,
            insert_misconception_observation,
            upsert_student_state,
        )
        from mathtutor.repositories.sqlite_math_facts import upsert_math_problem
        from mathtutor.repositories.uow import append_outbox_events

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        problem, parsed, _candidate, _ref = _verified_chain("2x + 3 = 7")
        async with uow.transaction() as conn:
            await upsert_math_problem(conn, problem)
        reference_log_id = await _verified_solution_log(uow, problem, parsed)

        with pytest.raises(RuntimeError):
            async with uow.transaction() as conn:
                submission_id = await insert_attempt_submission(
                    conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, raw_text="x=-2"
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
                    correctness="incorrect",
                    score=0.0,
                    attestation_hash="att-h",
                )
                await insert_misconception_observation(
                    conn,
                    student_id=_STUDENT_A,
                    attempt_id=attempt_id,
                    rule_id="miscon-sign-error",
                    confidence=0.8,
                    detail={"skill_id": SKILL_LINEAR_EQUATION},
                )
                await insert_mastery_evidence(
                    conn,
                    student_id=_STUDENT_A,
                    attempt_assessment_log_id=assessment_log_id,
                    correctness="incorrect",
                    score=0.0,
                    difficulty=1,
                    effective_assistance_level=0,
                    evidence_version="mt-evidence-v1",
                    idempotency_key="idem-atomic",
                )
                await upsert_student_state(
                    conn,
                    student_id=_STUDENT_A,
                    estimator_version="mt-estimator-v1",
                    projection_version=1,
                    concept_mastery=[],
                    skill_mastery=[],
                    active_misconceptions=[],
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

        async with uow.transaction() as conn:
            for table in (
                attempts,
                attempt_assessments,
                misconception_observations,
                mastery_evidence,
                student_state_projections,
                domain_outbox,
            ):
                count = (
                    await conn.execute(select(func.count()).select_from(table))
                ).scalar_one()
                assert count == 0, table.name

    async def test_outbox_commits_with_education_rows(self, db) -> None:
        """Item 20: on the success path the outbox row lands in the SAME
        transaction as the education rows."""
        from mathtutor.infrastructure.schema import domain_outbox
        from mathtutor.repositories.sqlite_education import (
            insert_attempt,
            insert_attempt_assessment,
            insert_attempt_submission,
            insert_mastery_evidence,
            insert_misconception_observation,
        )
        from mathtutor.repositories.sqlite_math_facts import upsert_math_problem
        from mathtutor.repositories.uow import append_outbox_events

        uow, snapshot = await _prepare_cycle(db, _STUDENT_A, "s1")
        problem, parsed, _candidate, _ref = _verified_chain("2x + 3 = 7")
        async with uow.transaction() as conn:
            await upsert_math_problem(conn, problem)
        reference_log_id = await _verified_solution_log(uow, problem, parsed)

        async with uow.transaction() as conn:
            submission_id = await insert_attempt_submission(
                conn, student_id=_STUDENT_A, cycle_id=snapshot.cycle_id, raw_text="x=-2"
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
                correctness="incorrect",
                score=0.0,
                attestation_hash="att-h",
            )
            await insert_misconception_observation(
                conn,
                student_id=_STUDENT_A,
                attempt_id=attempt_id,
                rule_id="miscon-sign-error",
                confidence=0.8,
                detail={"skill_id": SKILL_LINEAR_EQUATION},
            )
            await insert_mastery_evidence(
                conn,
                student_id=_STUDENT_A,
                attempt_assessment_log_id=assessment_log_id,
                correctness="incorrect",
                score=0.0,
                difficulty=1,
                effective_assistance_level=0,
                evidence_version="mt-evidence-v1",
                idempotency_key="idem-outbox",
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
            outbox_count = (
                await conn.execute(select(func.count()).select_from(domain_outbox))
            ).scalar_one()
        assert outbox_count == 1
