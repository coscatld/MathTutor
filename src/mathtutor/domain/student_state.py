"""Mastery evidence and the StudentState projection.

Evidence is append-only and created only by the server ``EvidenceFactory``
from *persisted* facts (design doc §8.3). ``StudentState`` is a projection
— not raw facts — and must be recomputable offline from the immutable
evidence plus the estimator version. Single mistakes never become
long-term labels.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

EvidenceCorrectness = Literal["correct", "partial", "incorrect"]
EVIDENCE_VERSION = "mt-evidence-v1"


class MasteryEvidence(BaseModel):
    """Deprecated Phase-0 evidence shape; retained for import compatibility.

    New code must use ``learning.evidence.LearningEvidence``, the sole
    authoritative persisted/replay contract.  This legacy DTO intentionally
    remains in the domain module (rather than importing learning back into
    domain and inverting the dependency direction), but it is no longer
    exported from :mod:`mathtutor.domain`.
    """

    model_config = ConfigDict(frozen=True)

    evidence_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    attempt_assessment_log_id: UUID
    problem_grounding_id: UUID
    target_mapping_id: UUID
    assistance_issuance_ids: tuple[UUID, ...] = ()
    misconception_observation_ids: tuple[UUID, ...] = ()
    correctness: EvidenceCorrectness
    score: float = Field(ge=0.0, le=1.0)
    difficulty: int = Field(ge=1, le=5)
    effective_assistance_level: int = Field(ge=0, le=5)
    evidence_version: str = EVIDENCE_VERSION
    idempotency_key: str


class StudentState(BaseModel):
    """Estimator projection of a student's mastery (design doc §8.4)."""

    model_config = ConfigDict(frozen=True)

    student_id: UUID
    enrollment_id: UUID
    curriculum_version_id: UUID
    estimator_version: str
    projection_version: int = Field(ge=0)
    concept_mastery: tuple[dict[str, Any], ...] = ()
    skill_mastery: tuple[dict[str, Any], ...] = ()
    active_misconceptions: tuple[UUID, ...] = ()


__all__ = ["EVIDENCE_VERSION", "StudentState"]
