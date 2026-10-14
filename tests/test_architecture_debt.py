"""Pre-RC architecture-debt closure regression tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

from alembic import command
import pytest
import pytest_asyncio
from sqlalchemy import select
import sqlalchemy.exc

from mathtutor.application.state_machine import CycleCommand, CycleState
from mathtutor.domain.problem import MathProblem
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.migrate import alembic_config, upgrade_db
from mathtutor.infrastructure.schema import metadata, mastery_evidence, verification_logs
from mathtutor.learning.skills import SKILL_LINEAR_EQUATION
from mathtutor.pedagogy.disclosure import SolutionDisclosureProjector
from mathtutor.pedagogy.exceptions import DisclosurePolicyViolation
from mathtutor.pedagogy.planner import CycleAssistance, PedagogyPlanner
from mathtutor.pedagogy.stage_policy import PRIMARY_POLICY
from mathtutor.pedagogy.tutor_writer import PublicProblemView, TemplateTutorWriter
from mathtutor.repositories import sqlite_education as education
from mathtutor.repositories.sqlite_math_facts import (
    SQLiteSolutionRepository,
    upsert_math_problem,
)
from mathtutor.repositories.sqlite_runtime import create_cycle, ensure_student
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.solving import parse_problem, solve_problem, verify


@pytest_asyncio.fixture()
async def db(tmp_path: Path):
    engine = create_db_engine(tmp_path / "debt.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def _education_chain(db):
    student_id = "debt-student"
    uow = MathTutorUow(db)
    async with uow.transaction() as conn:
        await ensure_student(conn, student_id=student_id)
        cycle = await create_cycle(conn, student_id=student_id, client_session_id="debt")
    parsed = parse_problem("2x + 3 = 7").problem
    problem = MathProblem.canonicalize(
        parsed.problem_type, parsed.normalized_ast, parsed.display_latex
    )
    async with uow.transaction() as conn:
        await upsert_math_problem(conn, problem)
    solved = solve_problem(problem, parsed)
    decision = verify(problem, solved.candidate)
    reference = await SQLiteSolutionRepository(uow).issue_attestation(
        problem, solved.candidate, decision
    )
    async with uow.transaction() as conn:
        submission_id = await education.insert_attempt_submission(
            conn, student_id=student_id, cycle_id=cycle.cycle_id, raw_text="2"
        )
        attempt_id = await education.insert_attempt(
            conn,
            student_id=student_id,
            cycle_id=cycle.cycle_id,
            attempt_submission_id=submission_id,
            parsed_steps=[],
            attempt_index=1,
            payload_hash="attempt-hash",
        )
        log_id = await education.insert_attempt_assessment(
            conn,
            student_id=student_id,
            attempt_id=attempt_id,
            cycle_id=cycle.cycle_id,
            problem_id=problem.problem_id,
            reference_solution_log_id=reference.verification_log_id,
            correctness="partial",
            score=0.5,
            attestation_hash="assessment-hash",
            policy_version="mt-attempt-verifier-v1",
            verified_claims=({"claim": "equivalent_equation"},),
            invalid_claims=(),
            remaining_requirements=({"requirement": "state_roots"},),
        )
        await education.insert_mastery_evidence(
            conn,
            student_id=student_id,
            attempt_id=attempt_id,
            skill_id=SKILL_LINEAR_EQUATION,
            attempt_assessment_log_id=log_id,
            correctness="partial",
            score=0.5,
            difficulty=1,
            effective_assistance_level=2,
            evidence_version="mt-evidence-v1",
            idempotency_key="debt-evidence-1",
        )
    return uow, student_id, attempt_id, log_id


@pytest.mark.asyncio
async def test_evidence_identity_and_attempt_claims_roundtrip(db) -> None:
    uow, student_id, attempt_id, log_id = await _education_chain(db)
    async with uow.transaction() as conn:
        row = (
            await conn.execute(
                select(mastery_evidence).where(mastery_evidence.c.student_id == student_id)
            )
        ).one()
        log = (
            await conn.execute(
                select(verification_logs).where(verification_logs.c.log_id == str(log_id))
            )
        ).one()
        replay = await education.load_evidence_for_student(conn, student_id)

    assert row.attempt_id == str(attempt_id)
    assert row.skill_id == SKILL_LINEAR_EQUATION
    assert log.checks == {
        "schema_version": education.ATTEMPT_CLAIMS_SCHEMA_VERSION,
        "policy_version": "mt-attempt-verifier-v1",
        "verified_claims": [{"claim": "equivalent_equation"}],
        "invalid_claims": [],
        "remaining_requirements": [{"requirement": "state_roots"}],
    }
    assert "reasoning" not in log.checks
    assert [(item.attempt_id, item.skill_id) for item in replay] == [
        (attempt_id, SKILL_LINEAR_EQUATION)
    ]


@pytest.mark.asyncio
async def test_evidence_composite_fk_rejects_cross_owner(db) -> None:
    uow, _student_id, attempt_id, log_id = await _education_chain(db)
    async with uow.transaction() as conn:
        await ensure_student(conn, student_id="other-student")
    with pytest.raises(sqlalchemy.exc.IntegrityError):
        async with uow.transaction() as conn:
            await education.insert_mastery_evidence(
                conn,
                student_id="other-student",
                attempt_id=attempt_id,
                skill_id=SKILL_LINEAR_EQUATION,
                attempt_assessment_log_id=log_id,
                correctness="partial",
                score=0.5,
                difficulty=1,
                effective_assistance_level=2,
                evidence_version="mt-evidence-v1",
                idempotency_key="cross-owner",
            )


def test_migration_006_backfills_old_rows_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "old-005.db"
    command.upgrade(alembic_config(str(db_path)), "005")
    conn = sqlite3.connect(db_path)
    # 001 uses current metadata, so reshape just this table to the real 005
    # layout before seeding a legacy row.
    conn.executescript(
        """
        PRAGMA foreign_keys=OFF;
        ALTER TABLE mastery_evidence RENAME TO mastery_evidence_new_shape;
        CREATE TABLE mastery_evidence (
          evidence_id VARCHAR(64) PRIMARY KEY NOT NULL,
          student_id VARCHAR(64) NOT NULL,
          attempt_assessment_log_id VARCHAR(64) NOT NULL,
          problem_grounding_id VARCHAR(64), target_mapping_id VARCHAR(64),
          correctness VARCHAR(16) NOT NULL, score FLOAT NOT NULL,
          difficulty INTEGER NOT NULL, effective_assistance_level INTEGER NOT NULL,
          evidence_version TEXT NOT NULL, idempotency_key VARCHAR(128) NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );
        INSERT INTO users VALUES ('s','s','user','t');
        INSERT INTO student_profiles VALUES ('s','s','t');
        INSERT INTO learning_sessions VALUES ('sess','client','s','t');
        INSERT INTO tutoring_cycles
          (cycle_id,session_id,student_id,state,state_version,created_at)
          VALUES ('cycle','sess','s','awaiting_attempt',1,'t');
        INSERT INTO attempt_submissions VALUES ('sub','s','cycle','2','t','k');
        INSERT INTO attempts VALUES ('att','sub','s','cycle','[]',1,'h','t');
        INSERT INTO math_problems VALUES
          ('prob','1','1','linear','{}','x=2','problem-hash');
        INSERT INTO verification_logs
          (log_id,attempt_id,problem_id,verdict,checks,created_at)
          VALUES ('log','att','prob','correct','{}','t');
        INSERT INTO attempt_assessments VALUES ('log','att','log','correct',1.0,'a');
        INSERT INTO mastery_evidence VALUES
          ('ev','s','log',NULL,NULL,'correct',1.0,1,0,'mt-evidence-v1','idem','t');
        DROP TABLE mastery_evidence_new_shape;
        """
    )
    conn.commit()
    conn.close()

    upgrade_db(str(db_path))
    upgrade_db(str(db_path))
    conn = sqlite3.connect(db_path)
    columns = {row[1]: row[3] for row in conn.execute("PRAGMA table_info(mastery_evidence)")}
    row = conn.execute(
        "SELECT attempt_id, skill_id, idempotency_key FROM mastery_evidence"
    ).fetchone()
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    conn.close()
    assert columns["attempt_id"] == 1 and columns["skill_id"] == 1
    assert row == ("att", SKILL_LINEAR_EQUATION, "idem")
    assert version == "024"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    ["1/2 + 1/3", "2y + 3 = 7", "(x+1)(x+2)", "x^2 - 5x + 6 = 0"],
)
async def test_l5_projection_is_friendly_display_only(text: str) -> None:
    parsed = parse_problem(text).problem
    problem = MathProblem.canonicalize(
        parsed.problem_type, parsed.normalized_ast, parsed.display_latex
    )
    solved = solve_problem(problem, parsed)
    decision = verify(problem, solved.candidate)
    from mathtutor.domain.solution import VerifiedSolutionRef
    from mathtutor.domain.tutoring import TutorAction

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
    action = TutorAction(
        action="SHOW_SOLUTION", effective_assistance_level=5, solution_visibility="full"
    )
    disclosed = SolutionDisclosureProjector().project(ref, solved.candidate, action)
    assert disclosed.full_solution is not None
    assert all(set(step) == {"display_text", "display_latex"} for step in disclosed.full_solution["steps"])
    assert set(disclosed.full_solution["final_answer"]) == {"display_text", "display_latex"}
    rendered = await TemplateTutorWriter().write(
        problem_view=PublicProblemView.of(problem),
        disclosure=disclosed,
        policy=PRIMARY_POLICY,
        action=action,
    )
    assert "完整解答" in rendered.text and "答案" in rendered.text
    assert "{'" not in rendered.text and '"kind"' not in rendered.text


def test_unverified_solution_rejection_is_actionable_and_hides_thresholds() -> None:
    with pytest.raises(DisclosurePolicyViolation) as exc:
        PedagogyPlanner().plan(
            state=CycleState.AWAITING_ATTEMPT,
            command=CycleCommand.SOLUTION_SHOWN_PERMITTED,
            policy=PRIMARY_POLICY,
            assistance=CycleAssistance(),
            verified_ref=None,
        )
    message = str(exc.value)
    assert "验证" in message and "提示" in message
    assert not any(character.isdigit() for character in message)
    assert "requires" not in message and "received" not in message


def test_legacy_mastery_evidence_is_not_a_public_domain_contract() -> None:
    import mathtutor.domain as domain
    from mathtutor.domain import student_state

    assert "MasteryEvidence" not in domain.__all__
    assert not hasattr(domain, "MasteryEvidence")
    assert "MasteryEvidence" not in student_state.__all__
    assert "Deprecated" in (student_state.MasteryEvidence.__doc__ or "")
