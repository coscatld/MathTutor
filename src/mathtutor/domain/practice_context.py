"""PracticeGenerationContext — the typed DTO for adaptive practice assembly.

The AdaptivePracticeService builds this DTO; the LLM practice generator
consumes it. Every field has a DEFINED source (documented per field) —
nothing is a raw SQLite row, and no consumer may query repositories
directly. The generation flow (design doc §24) is fixed:

    AdaptivePracticeService
        → Student Model REQUIRED / Misconception History REQUIRED
        → Recent Attempts REQUIRED / Curriculum REQUIRED
        → Personal Memory OPTIONAL / Documents OPTIONAL
        → PracticeGenerationContext → LLM → CandidateExercise
        → Parser → Solver → Verifier → Release Attestation
        → ExerciseRelease → PracticeOffer

Only VERIFIED releases may become offers; the personal KG and user
documents never bypass the release gate.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.assembled_context import (
    ContextProvenance,
    DocumentContextSelection,
    MemoryContextEntry,
)

PRACTICE_CONTEXT_VERSION = "mt-practice-context-v1"


class TargetEntry(BaseModel):
    """One target node of the practice (source: selector/pedagogy)."""

    model_config = ConfigDict(frozen=True)

    id: str
    kind: str  # skill / concept


class MasterySnapshotEntry(BaseModel):
    """Current mastery of one targeted skill (source: StudentStateProjection)."""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    mastery: float = Field(ge=0.0, le=1.0)


class ActiveMisconceptionEntry(BaseModel):
    """An ACTIVE/RESOLVING misconception (source: projection reducer)."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    confidence: float = Field(ge=0.0, le=1.0)


class ErrorPatternEntry(BaseModel):
    """One recurring error rule (source: misconception observation history)."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    occurrence_count: int = Field(ge=1)


class AttemptSummaryEntry(BaseModel):
    """One recent attempt summary (source: mastery_evidence replay)."""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    correctness: str
    effective_assistance_level: int = Field(ge=0, le=5)
    attempt_index: int = Field(ge=1)
    created_at: str = ""


class PersonalPreferenceContext(BaseModel):
    """Personal memory slice (source: personal_memory_nodes; OPTIONAL)."""

    model_config = ConfigDict(frozen=True)

    entries: tuple[MemoryContextEntry, ...] = ()


class PracticeGenerationContext(BaseModel):
    """Everything the practice generator may see — and nothing else."""

    model_config = ConfigDict(frozen=True)

    context_version: str = PRACTICE_CONTEXT_VERSION
    student_id: UUID

    # Targets (source: AdaptivePracticeService selector — pedagogy policy).
    target_skill_ids: tuple[str, ...] = ()
    target_concept_ids: tuple[str, ...] = ()

    # REQUIRED: Student Model (derived projection, never raw rows).
    current_mastery: tuple[MasterySnapshotEntry, ...] = ()

    # REQUIRED: misconception reducer projection + observation history.
    active_misconceptions: tuple[ActiveMisconceptionEntry, ...] = ()
    recent_error_patterns: tuple[ErrorPatternEntry, ...] = ()

    # REQUIRED: recent attempt stream (evidence replay, chronological).
    recent_attempt_summary: tuple[AttemptSummaryEntry, ...] = ()

    desired_difficulty: int = Field(ge=1, le=5, default=2)

    # OPTIONAL: personal preferences (router + user permission gated).
    personal_preferences: PersonalPreferenceContext | None = None

    # OPTIONAL: selected chunks of the student's own documents.
    document_context: DocumentContextSelection | None = None

    provenance: tuple[ContextProvenance, ...] = ()


__all__ = [
    "PRACTICE_CONTEXT_VERSION",
    "ActiveMisconceptionEntry",
    "AttemptSummaryEntry",
    "ErrorPatternEntry",
    "MasterySnapshotEntry",
    "PersonalPreferenceContext",
    "PracticeGenerationContext",
    "TargetEntry",
]
