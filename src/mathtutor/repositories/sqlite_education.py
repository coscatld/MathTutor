"""SQLite education-persistence repositories (Phase 1D — infrastructure).

Schema + repository + atomic-commit skeleton for attempt → assessment →
evidence → student-state → tutor-action → outbox. The Phase 4 BUSINESS
logic (structured attempt parsing/verification, misconception reduction,
estimator math) is not here — these functions only move validated data
into one transaction.

Everything is owner-scoped; evidence and assessments are append-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.infrastructure.schema import (
    attempt_assessments,
    attempt_submissions,
    attempts,
    assistance_issuances,
    mastery_evidence,
    math_problems,
    misconception_observations,
    student_state_projections,
    tutor_actions,
    verification_logs,
)

ATTEMPT_CLAIMS_SCHEMA_VERSION = "mt-attempt-claims-v1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


_STUDENT_UUID_NAMESPACE = UUID("3d7b1a5c-2e4f-4d6a-8b9c-0f1e2d3c4b5a")


def _student_uuid(student_id: str) -> UUID:
    """Persisted student ids are arbitrary owner strings; replay models need
    a UUID. UUID-shaped ids pass through, anything else maps to a stable
    uuid5 (deterministic across replays)."""
    try:
        return UUID(student_id)
    except (ValueError, AttributeError, TypeError):
        from uuid import uuid5

        return uuid5(_STUDENT_UUID_NAMESPACE, f"student:{student_id}")


async def insert_attempt_submission(
    conn: AsyncConnection,
    *,
    student_id: str,
    cycle_id: UUID,
    raw_text: str,
    idempotency_key: str = "",
    submission_id: UUID | None = None,
) -> UUID:
    submission_id = submission_id or uuid4()
    await conn.execute(
        attempt_submissions.insert().values(
            attempt_submission_id=str(submission_id),
            student_id=student_id,
            cycle_id=str(cycle_id),
            raw_text=raw_text,
            submitted_at=_now(),
            idempotency_key=idempotency_key,
        )
    )
    return submission_id


async def insert_attempt(
    conn: AsyncConnection,
    *,
    student_id: str,
    cycle_id: UUID,
    attempt_submission_id: UUID,
    parsed_steps: list[dict[str, Any]],
    attempt_index: int,
    payload_hash: str,
    attempt_id: UUID | None = None,
) -> UUID:
    attempt_id = attempt_id or uuid4()
    await conn.execute(
        attempts.insert().values(
            attempt_id=str(attempt_id),
            attempt_submission_id=str(attempt_submission_id),
            student_id=student_id,
            cycle_id=str(cycle_id),
            parsed_steps=parsed_steps,
            attempt_index=attempt_index,
            payload_hash=payload_hash,
            created_at=_now(),
        )
    )
    return attempt_id


async def insert_attempt_assessment(
    conn: AsyncConnection,
    *,
    student_id: str,
    attempt_id: UUID,
    cycle_id: UUID,
    problem_id: UUID,
    reference_solution_log_id: UUID,
    correctness: str,
    score: float | None,
    attestation_hash: str,
    policy_version: str = "",
    verified_claims: tuple[dict[str, Any], ...] = (),
    invalid_claims: tuple[dict[str, Any], ...] = (),
    remaining_requirements: tuple[dict[str, Any], ...] = (),
) -> UUID:
    """Append-only assessment row referencing the attempt's verification log.

    The verification log itself is created by the caller (XOR subject check
    enforced by the schema: candidate_id NULL, attempt_id set; problem_id is
    always bound — the verified problem of this cycle).
    """
    log_id = uuid4()
    await conn.execute(
        verification_logs.insert().values(
            log_id=str(log_id),
            candidate_id=None,
            attempt_id=str(attempt_id),
            problem_id=str(problem_id),
            verdict=correctness,
            # Versioned, deterministic verifier output only.  This envelope
            # deliberately has no free-form reasoning/transcript field.
            checks={
                "schema_version": ATTEMPT_CLAIMS_SCHEMA_VERSION,
                "policy_version": policy_version,
                "verified_claims": list(verified_claims),
                "invalid_claims": list(invalid_claims),
                "remaining_requirements": list(remaining_requirements),
            },
            attestation_hash=attestation_hash,
            created_at=_now(),
        )
    )
    await conn.execute(
        attempt_assessments.insert().values(
            verification_log_id=str(log_id),
            attempt_id=str(attempt_id),
            reference_solution_log_id=str(reference_solution_log_id),
            correctness=correctness,
            score=score,
            attestation_hash=attestation_hash,
        )
    )
    return log_id


async def insert_mastery_evidence(
    conn: AsyncConnection,
    *,
    student_id: str,
    attempt_id: UUID | None = None,
    skill_id: str = "",
    attempt_assessment_log_id: UUID,
    correctness: str,
    score: float,
    difficulty: int,
    effective_assistance_level: int,
    evidence_version: str,
    idempotency_key: str,
) -> UUID:
    """Append-only evidence. The unique idempotency key makes a replayed
    attempt a no-op at the database level (design doc §11.4)."""
    # Compatibility for repository callers predating migration 006: derive
    # the same immutable identities once at insert time.  The stored row is
    # self-contained afterwards; replay never re-derives them.
    if attempt_id is None or not skill_id:
        identity = (
            await conn.execute(
                select(
                    attempts.c.attempt_id,
                    attempts.c.student_id,
                    math_problems.c.problem_type,
                )
                .select_from(attempt_assessments)
                .join(attempts, attempts.c.attempt_id == attempt_assessments.c.attempt_id)
                .join(
                    verification_logs,
                    verification_logs.c.log_id
                    == attempt_assessments.c.verification_log_id,
                )
                .join(math_problems, math_problems.c.problem_id == verification_logs.c.problem_id)
                .where(
                    attempt_assessments.c.verification_log_id
                    == str(attempt_assessment_log_id)
                )
            )
        ).first()
        if identity is None or identity.student_id != student_id:
            raise ValueError("evidence assessment is missing or belongs to another student")
        attempt_id = attempt_id or UUID(identity.attempt_id)
        if not skill_id:
            from mathtutor.learning.skills import skill_for_problem_type

            skill_id = skill_for_problem_type(identity.problem_type)
    if not skill_id:
        raise ValueError("evidence skill_id is required")

    evidence_id = uuid4()
    await conn.execute(
        mastery_evidence.insert().values(
            evidence_id=str(evidence_id),
            student_id=student_id,
            attempt_id=str(attempt_id),
            skill_id=skill_id,
            attempt_assessment_log_id=str(attempt_assessment_log_id),
            problem_grounding_id=None,
            target_mapping_id=None,
            correctness=correctness,
            score=score,
            difficulty=difficulty,
            effective_assistance_level=effective_assistance_level,
            evidence_version=evidence_version,
            idempotency_key=idempotency_key,
            created_at=_now(),
        )
    )
    return evidence_id


async def insert_tutor_action(
    conn: AsyncConnection,
    *,
    student_id: str,
    cycle_id: UUID,
    action: str,
    effective_assistance_level: int,
    solution_visibility: str,
    target_step_index: int | None = None,
    policy_versions: dict[str, str] | None = None,
    action_id: UUID | None = None,
) -> UUID:
    action_id = action_id or uuid4()
    versions = policy_versions or {}
    await conn.execute(
        tutor_actions.insert().prefix_with("OR IGNORE").values(
            action_id=str(action_id),
            cycle_id=str(cycle_id),
            student_id=student_id,
            action=action,
            effective_assistance_level=effective_assistance_level,
            solution_visibility=solution_visibility,
            target_step_index=target_step_index,
            pedagogy_policy_version=versions.get("pedagogy", ""),
            stage_policy_version=versions.get("stage", ""),
            disclosure_policy_version=versions.get("disclosure", ""),
            created_at=_now(),
        )
    )
    return action_id


async def upsert_student_state(
    conn: AsyncConnection,
    *,
    student_id: str,
    estimator_version: str,
    projection_version: int,
    concept_mastery: list[dict[str, Any]],
    skill_mastery: list[dict[str, Any]],
    active_misconceptions: list[str],
) -> None:
    """Compare-and-set projection update: caller supplies the expected
    projection_version; a mismatch aborts (no silent overwrite)."""
    existing = (
        await conn.execute(
            select(student_state_projections).where(
                student_state_projections.c.student_id == student_id
            )
        )
    ).first()
    if existing is None:
        await conn.execute(
            student_state_projections.insert().values(
                student_id=student_id,
                curriculum_version_id=None,
                estimator_version=estimator_version,
                projection_version=projection_version,
                concept_mastery=concept_mastery,
                skill_mastery=skill_mastery,
                active_misconceptions=active_misconceptions,
                updated_at=_now(),
            )
        )
        return
    result = await conn.execute(
        student_state_projections.update()
        .where(student_state_projections.c.student_id == student_id)
        .where(student_state_projections.c.projection_version == projection_version - 1)
        .values(
            estimator_version=estimator_version,
            projection_version=projection_version,
            concept_mastery=concept_mastery,
            skill_mastery=skill_mastery,
            active_misconceptions=active_misconceptions,
            updated_at=_now(),
        )
    )
    if result.rowcount != 1:
        raise RuntimeError(
            f"student_state CAS failed: projection {projection_version - 1} not current"
        )


# ---------------------------------------------------------------------------
# Phase 4 learning loop: misconception observations + evidence replay
# ---------------------------------------------------------------------------


async def insert_misconception_observation(
    conn: AsyncConnection,
    *,
    student_id: str,
    attempt_id: UUID,
    rule_id: str,
    confidence: float,
    detail: dict[str, Any],
    observation_id: UUID | None = None,
) -> UUID:
    """Append-only observation row (one per attempt x rule — the unique
    constraint makes a replayed diagnosis a no-op at the database level)."""
    observation_id = observation_id or uuid4()
    await conn.execute(
        misconception_observations.insert().values(
            observation_id=str(observation_id),
            student_id=student_id,
            attempt_id=str(attempt_id),
            rule_id=rule_id,
            confidence=confidence,
            detail=detail,
            created_at=_now(),
        )
    )
    return observation_id


async def load_misconception_observations_for_student(
    conn: AsyncConnection, student_id: str
) -> list["MisconceptionObservation"]:
    """All observations of one student, in deterministic replay order
    (created_at, then observation_id). Owner-scoped."""
    from mathtutor.learning.diagnosis import MisconceptionObservation

    rows = (
        await conn.execute(
            select(misconception_observations)
            .where(misconception_observations.c.student_id == student_id)
            .order_by(
                misconception_observations.c.created_at,
                misconception_observations.c.observation_id,
            )
        )
    ).all()
    return [
        MisconceptionObservation(
            observation_id=UUID(row.observation_id),
            student_id=_student_uuid(row.student_id),
            attempt_id=UUID(row.attempt_id),
            rule_id=row.rule_id,
            confidence=float(row.confidence),
            detail=dict(row.detail or {}),
            created_at=row.created_at,
        )
        for row in rows
    ]


async def load_evidence_for_student(
    conn: AsyncConnection, student_id: str
) -> list["LearningEvidence"]:
    """Replay the append-only evidence of one student, in deterministic
    order (created_at, then evidence_id). Owner-scoped.

    ``attempt_id`` and ``skill_id`` are first-class evidence facts since
    migration 006.  Replay joins only the owned attempt for its immutable
    attempt_index; it no longer depends on assessment/log/problem rows to
    reconstruct evidence identity.
    """
    from mathtutor.learning.evidence import LearningEvidence

    rows = (
        await conn.execute(
            select(
                mastery_evidence,
                attempts.c.attempt_index,
                verification_logs.c.problem_id,
            )
            .select_from(mastery_evidence)
            .join(
                attempts,
                (attempts.c.attempt_id == mastery_evidence.c.attempt_id)
                & (attempts.c.student_id == mastery_evidence.c.student_id),
            )
            .outerjoin(verification_logs, (verification_logs.c.log_id == mastery_evidence.c.attempt_assessment_log_id)
                       & (verification_logs.c.attempt_id == mastery_evidence.c.attempt_id))
            .where(mastery_evidence.c.student_id == student_id)
            .order_by(mastery_evidence.c.created_at, mastery_evidence.c.evidence_id)
        )
    ).all()
    evidence: list[LearningEvidence] = []
    for row in rows:
        mapping = row._mapping
        evidence.append(
            LearningEvidence(
                evidence_id=UUID(mapping["evidence_id"]),
                student_id=_student_uuid(mapping["student_id"]),
                attempt_id=UUID(mapping["attempt_id"]),
                attempt_assessment_log_id=UUID(mapping["attempt_assessment_log_id"]),
                skill_id=mapping["skill_id"],
                problem_id=str(mapping["problem_id"] or ""),
                correctness=mapping["correctness"],
                score=float(mapping["score"]),
                difficulty=int(mapping["difficulty"]),
                effective_assistance_level=int(mapping["effective_assistance_level"]),
                attempt_index=int(mapping["attempt_index"]),
                evidence_version=mapping["evidence_version"],
                idempotency_key=mapping["idempotency_key"],
                created_at=mapping["created_at"],
            )
        )
    return evidence


async def load_student_projection(
    conn: AsyncConnection, student_id: str
) -> dict[str, Any] | None:
    """Current persisted projection of one student (or None). Owner-scoped."""
    row = (
        await conn.execute(
            select(student_state_projections).where(
                student_state_projections.c.student_id == student_id
            )
        )
    ).first()
    if row is None:
        return None
    return {
        "student_id": row.student_id,
        "estimator_version": row.estimator_version,
        "projection_version": int(row.projection_version),
        "concept_mastery": row.concept_mastery,
        "skill_mastery": row.skill_mastery,
        "active_misconceptions": row.active_misconceptions,
        "updated_at": row.updated_at,
    }


__all__ = [
    "ATTEMPT_CLAIMS_SCHEMA_VERSION",
    "insert_attempt",
    "insert_attempt_assessment",
    "insert_attempt_submission",
    "insert_mastery_evidence",
    "insert_misconception_observation",
    "insert_tutor_action",
    "load_evidence_for_student",
    "load_misconception_observations_for_student",
    "load_student_projection",
    "upsert_student_state",
]
