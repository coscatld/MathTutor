"""Exercise catalog: exercises, releases and revocation.

A release is immutable and snapshots problem/solution/policy/verifier/
license/provenance hashes; any change to the bound artifacts produces a
new release, never an in-place edit. Students reach a problem only through
a :class:`~mathtutor.domain.tutoring.PracticeOffer` bound to an
exact release (design doc §11.3, Phase 5).

Phase 5 (verified adaptive practice, §7.1): ``Exercise`` carries its
provenance explicitly — ``source_type`` is a *claim*, never a trust grant.
BANK/TEMPLATE/LLM candidates ALL pass the identical Parser → Solver →
Verifier → Release Attestation gate before a release exists. An
``ExerciseRelease`` additionally binds the exact ``solution_candidate_id``
and ``verification_log_id`` it was issued against, so judging in a child
cycle always uses the release's own snapshot — never "whatever is newest"
(design doc §11.3, exact-snapshot invariant).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.hashing import content_hash

ReleaseStatus = Literal["draft", "released", "revoked", "superseded"]
SourceType = Literal["BANK", "TEMPLATE", "LLM"]


def exercise_content_hash(
    *,
    problem_statement: str,
    problem_id: UUID,
    difficulty: int,
    source_type: str,
) -> str:
    """Content identity of an exercise (design doc §7.1).

    Binds the problem STATEMENT, the canonical problem id, the difficulty
    and the source type. Two releases with identical content identity are
    the same exercise; any change to the statement yields a new exercise.
    Server-owned: clients never compute this.
    """
    return content_hash(
        {
            "problem_statement": problem_statement,
            "problem_id": str(problem_id),
            "difficulty": difficulty,
            "source_type": source_type,
        }
    )


class Exercise(BaseModel):
    """One catalogued exercise (problem + grounding, no solution)."""

    model_config = ConfigDict(frozen=True)

    exercise_id: UUID = Field(default_factory=uuid4)
    problem_id: UUID
    problem_grounding_id: UUID
    display_latex: str
    difficulty: int = Field(ge=1, le=5)
    target_mapping_ids: tuple[UUID, ...] = ()
    license_ref: str = ""
    # Phase 5 provenance + content identity (§7.1). source_type is a claim,
    # never a trust grant — every candidate still passes the full release gate.
    source_type: SourceType
    content_hash: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # Public problem surface (the student-facing statement — NOT an answer key).
    problem_statement: str = ""


class ExerciseRelease(BaseModel):
    """Immutable release attestation of one exercise snapshot."""

    model_config = ConfigDict(frozen=True)

    release_id: UUID = Field(default_factory=uuid4)
    exercise_id: UUID
    problem_hash: str
    solution_hash: str
    verification_policy_hash: str
    verifier_hash: str
    solution_candidate_hash: str
    license_hash: str
    provenance_hash: str
    status: ReleaseStatus = "draft"
    released_at: datetime | None = None
    # Exact-snapshot binding (Phase 5): the candidate + verification log this
    # release was issued against. Judging a child cycle uses THESE bytes,
    # never a newer attestation of the same problem.
    solution_candidate_id: UUID | None = None
    verification_log_id: UUID | None = None


__all__ = [
    "Exercise",
    "ExerciseRelease",
    "SourceType",
    "ReleaseStatus",
    "exercise_content_hash",
]
