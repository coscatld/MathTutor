"""Student attempt submissions and their assessment attestations.

``Correctness`` is an independent enum (design doc §8.1): string similarity,
keyword coverage or an LLM self-report boolean are never math judges.
Assessment attestations are append-only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.hashing import content_hash

ATTEMPT_PAYLOAD_SCHEMA_VERSION = "mt-attempt-1"
Correctness = Literal["correct", "partial", "incorrect", "undetermined"]


class AttemptSubmission(BaseModel):
    """Owner-scoped raw attempt text (encrypted in production storage)."""

    model_config = ConfigDict(frozen=True)

    attempt_submission_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    cycle_id: UUID
    raw_text: str
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StudentAttempt(BaseModel):
    """Typed, parsed student attempt bound to its submission and payload hash."""

    model_config = ConfigDict(frozen=True)

    attempt_id: UUID = Field(default_factory=uuid4)
    attempt_submission_id: UUID
    student_id: UUID
    cycle_id: UUID
    parsed_steps: tuple[dict[str, Any], ...]
    attempt_index: int = Field(ge=1)
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload_schema_version: str = ATTEMPT_PAYLOAD_SCHEMA_VERSION
    payload_hash: str = ""

    @classmethod
    def canonicalize(
        cls,
        attempt_submission_id: UUID,
        student_id: UUID,
        cycle_id: UUID,
        parsed_steps: tuple[dict[str, Any], ...],
        attempt_index: int,
    ) -> "StudentAttempt":
        attempt = cls(
            attempt_submission_id=attempt_submission_id,
            student_id=student_id,
            cycle_id=cycle_id,
            parsed_steps=parsed_steps,
            attempt_index=attempt_index,
        )
        payload = {
            "attempt_submission_id": attempt_submission_id,
            "student_id": student_id,
            "cycle_id": cycle_id,
            "parsed_steps": parsed_steps,
            "attempt_index": attempt_index,
            "payload_schema_version": ATTEMPT_PAYLOAD_SCHEMA_VERSION,
        }
        object.__setattr__(attempt, "payload_hash", content_hash(payload))
        return attempt


class AttemptAssessmentRef(BaseModel):
    """Attestation of one attempt assessment (append-only, design doc §10)."""

    model_config = ConfigDict(frozen=True)

    verification_log_id: UUID
    attempt_id: UUID
    attempt_payload_hash: str
    reference_solution_verification_log_id: UUID
    correctness: Correctness
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    attestation_hash: str = ""


__all__ = ["ATTEMPT_PAYLOAD_SCHEMA_VERSION", "AttemptAssessmentRef", "AttemptSubmission", "StudentAttempt"]
