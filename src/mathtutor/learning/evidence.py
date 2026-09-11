"""Mastery evidence factory (Phase 4 learning loop, step 4).

Evidence is created ONLY from server-trusted facts: the persisted
assessment, the verified solution ref, the stable skill id, the assistance
ledger (:class:`CycleAssistance`) and (optionally) the misconception
observation of this attempt. Every input is a fact the server already
committed; the factory performs pure computation and never judges math
itself.

Hard invariants:

- UNDETERMINED assessments produce **None** — undetermined facts never
  become learning evidence;
- the idempotency key is a deterministic hash of the attempt identity
  (never random), and the ``evidence_id`` derives from it (uuid5), so the
  same attempt always yields byte-identical evidence — the database unique
  constraint on the key makes replays no-ops;
- evidence is append-only: there is no update path anywhere.

The assessment's verification-log id is issued by the repository at insert
time, so it is an *optional* factory input; the service binds it onto the
returned evidence (``model_copy``) inside the short commit transaction.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.hashing import content_hash
from mathtutor.domain.solution import VerifiedSolutionRef
from mathtutor.learning.attempt_verifier import AttemptAssessment, Correctness
from mathtutor.learning.diagnosis import MisconceptionObservation
from mathtutor.pedagogy.planner import CycleAssistance

EVIDENCE_VERSION = "mt-evidence-v1"

# uuid5 namespace for deterministic evidence ids.
_EVIDENCE_NAMESPACE = UUID("8b7a2c4e-1d3f-4a5b-9c6d-0e1f2a3b4c5d")

MAX_ASSISTANCE_LEVEL = 5


class LearningEvidence(BaseModel):
    """One append-only learning fact (frozen; mirrors the persisted row)."""

    model_config = ConfigDict(frozen=True)

    evidence_id: UUID
    student_id: UUID
    attempt_id: UUID
    attempt_assessment_log_id: UUID | None = None
    skill_id: str
    correctness: Literal["correct", "partial", "incorrect"]
    score: float = Field(ge=0.0, le=1.0)
    difficulty: int = Field(ge=1, le=5, default=1)
    effective_assistance_level: int = Field(ge=0, le=5, default=0)
    attempt_index: int = Field(ge=1)
    misconception_observation_ids: tuple[UUID, ...] = ()
    evidence_version: str = EVIDENCE_VERSION
    idempotency_key: str
    created_at: str = ""
    problem_id: str = ""


def idempotency_key_for(
    *,
    student_id: UUID,
    attempt_id: UUID,
    attempt_index: int,
    skill_id: str,
) -> str:
    """Deterministic idempotency key over the attempt identity.

    The same attempt can never yield two keys; the key does NOT include the
    assistance ledger or the observation, so re-judging with different
    metadata still de-duplicates to the one attempt.
    """
    return content_hash(
        {
            "student_id": str(student_id),
            "attempt_id": str(attempt_id),
            "attempt_index": attempt_index,
            "skill_id": skill_id,
        }
    )


class EvidenceFactory:
    """Builds :class:`LearningEvidence` from server-trusted facts (pure)."""

    def build_evidence(
        self,
        *,
        assessment: AttemptAssessment,
        verified_ref: VerifiedSolutionRef,
        skill_id: str,
        assistance: CycleAssistance,
        attempt_index: int,
        observation: MisconceptionObservation | None = None,
        attempt_assessment_log_id: UUID | None = None,
        idempotency_key: str = "",
        difficulty: int = 1,
    ) -> LearningEvidence | None:
        """Return evidence, or None when the attempt is UNDETERMINED.

        Raises ``ValueError`` when trusted facts contradict each other
        (verified ref bound to another problem/solution) — that is an
        internal consistency bug, never a student-input case.
        """
        if assessment.correctness is Correctness.UNDETERMINED:
            return None
        if verified_ref.problem_id != assessment.problem_id:
            raise ValueError("verified_ref 与 assessment 绑定的题目不一致")
        if verified_ref.solution_payload_hash != assessment.reference_solution_payload_hash:
            raise ValueError("verified_ref 与 assessment 引用的参考解不一致")

        correctness = assessment.correctness.value
        score = assessment.score
        if score is None:
            score = 1.0 if correctness == "correct" else 0.0 if correctness == "incorrect" else 0.5
        level = max(0, min(MAX_ASSISTANCE_LEVEL, assistance.max_level_issued))
        key = idempotency_key or idempotency_key_for(
            student_id=assessment.student_id,
            attempt_id=assessment.attempt_id,
            attempt_index=attempt_index,
            skill_id=skill_id,
        )
        return LearningEvidence(
            evidence_id=uuid5(_EVIDENCE_NAMESPACE, key),
            student_id=assessment.student_id,
            attempt_id=assessment.attempt_id,
            attempt_assessment_log_id=attempt_assessment_log_id,
            problem_id=str(assessment.problem_id),
            skill_id=skill_id,
            correctness=correctness,
            score=score,
            difficulty=max(1, min(5, difficulty)),
            effective_assistance_level=level,
            attempt_index=attempt_index,
            misconception_observation_ids=(
                (observation.observation_id,) if observation is not None else ()
            ),
            evidence_version=EVIDENCE_VERSION,
            idempotency_key=key,
        )


__all__ = [
    "EVIDENCE_VERSION",
    "EvidenceFactory",
    "LearningEvidence",
    "MAX_ASSISTANCE_LEVEL",
    "idempotency_key_for",
]
