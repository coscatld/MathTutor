"""Canonical problems, curriculum mappings and groundings.

Data-evolution chain (design doc §6.1): a student-owner-scoped
``ProblemSubmission`` parses into a canonical :class:`MathProblem`; the
mapping to the curriculum is a versioned :class:`ProblemGrounding`. The
canonical problem stores only normalized mathematical facts and a content
hash — never the student's original text or source spans (those live in the
owner-scoped submission and its parse attestation).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.hashing import content_hash

STAGE = Literal["primary", "middle", "high"]
MAPPING_KIND = Literal["concept", "skill"]
MAPPING_STATUS = Literal["approved", "candidate", "rejected"]

SCHEMA_VERSION = "mt-1"
CANONICALIZATION_VERSION = "mt-c1"


class MathProblem(BaseModel):
    """Canonical mathematical problem (one per distinct canonical form)."""

    model_config = ConfigDict(frozen=True)

    problem_id: UUID = Field(default_factory=uuid4)
    schema_version: str = SCHEMA_VERSION
    canonicalization_version: str = CANONICALIZATION_VERSION
    problem_type: Literal["arithmetic", "polynomial", "linear", "quadratic"]
    normalized_ast: dict[str, Any]
    display_latex: str
    content_hash: str = ""

    @classmethod
    def canonicalize(cls, problem_type: str, normalized_ast: dict[str, Any], display_latex: str) -> "MathProblem":
        """Build the problem and bind its content hash (server-owned)."""
        payload = {
            "schema_version": cls.model_fields["schema_version"].default,
            "canonicalization_version": cls.model_fields["canonicalization_version"].default,
            "problem_type": problem_type,
            "normalized_ast": normalized_ast,
        }
        return cls(
            problem_type=problem_type,
            normalized_ast=normalized_ast,
            display_latex=display_latex,
            content_hash=content_hash(payload),
        )


class ProblemMappingRef(BaseModel):
    """A curriculum mapping with review status — never a client-writable field."""

    model_config = ConfigDict(frozen=True)

    mapping_id: UUID = Field(default_factory=uuid4)
    mapping_hash: str = ""
    curriculum_version_id: UUID
    node_id: UUID
    kind: MAPPING_KIND
    confidence: float = Field(ge=0.0, le=1.0)
    review_status: MAPPING_STATUS = "candidate"

    @classmethod
    def canonicalize(
        cls,
        curriculum_version_id: UUID,
        node_id: UUID,
        kind: MAPPING_KIND,
        confidence: float,
        review_status: MAPPING_STATUS = "candidate",
    ) -> "ProblemMappingRef":
        mapping = cls(
            curriculum_version_id=curriculum_version_id,
            node_id=node_id,
            kind=kind,
            confidence=confidence,
            review_status=review_status,
        )
        payload = {
            "curriculum_version_id": curriculum_version_id,
            "node_id": node_id,
            "kind": kind,
            "confidence": confidence,
            "review_status": review_status,
        }
        object.__setattr__(mapping, "mapping_hash", content_hash(payload))
        return mapping


class ProblemGrounding(BaseModel):
    """Versioned binding of a canonical problem to the curriculum."""

    model_config = ConfigDict(frozen=True)

    grounding_id: UUID = Field(default_factory=uuid4)
    grounding_hash: str = ""
    problem_id: UUID
    curriculum_version_id: UUID
    stage: STAGE
    grade: int = Field(ge=1, le=12)
    difficulty: int = Field(ge=1, le=5)
    mappings: tuple[ProblemMappingRef, ...] = ()

    @classmethod
    def canonicalize(
        cls,
        problem_id: UUID,
        curriculum_version_id: UUID,
        stage: STAGE,
        grade: int,
        difficulty: int,
        mappings: tuple[ProblemMappingRef, ...] = (),
    ) -> "ProblemGrounding":
        grounding = cls(
            problem_id=problem_id,
            curriculum_version_id=curriculum_version_id,
            stage=stage,
            grade=grade,
            difficulty=difficulty,
            mappings=mappings,
        )
        payload = {
            "problem_id": problem_id,
            "curriculum_version_id": curriculum_version_id,
            "stage": stage,
            "grade": grade,
            "difficulty": difficulty,
            "mappings": [m.model_dump() for m in mappings],
        }
        object.__setattr__(grounding, "grounding_hash", content_hash(payload))
        return grounding


__all__ = ["CANONICALIZATION_VERSION", "SCHEMA_VERSION", "MathProblem", "ProblemGrounding", "ProblemMappingRef"]
