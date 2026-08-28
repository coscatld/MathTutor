"""AssembledContext — the ONLY typed context LLM consumers may receive.

The ContextAssembler resolves the RetrievalPolicy, loads REQUIRED sources,
optionally retrieves OPTIONAL sources (router + user permission), projects
each source into a typed context, enforces the token budget and records
provenance. TutorWriter / practice generators consume THIS — they never
query repositories directly and never see raw DB rows.

Provenance is part of the contract: every source present (or absent) in
the assembled context carries a record explaining WHY (loaded / disabled
by the user / trimmed by budget / forbidden / unavailable), so tests and
audits can prove no consumer smuggled in raw state.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.retrieval_policy import (
    RetrievalIntent,
    RetrievalPlan,
    RetrievalSource,
)

SourceStatus = Literal[
    "loaded",  # projected and included
    "disabled_by_user",  # retrieval_enabled=false or deleted — permission wins
    "unavailable",  # loader failed or backend missing (optional sources only)
    "budget_trimmed",  # optional source dropped by token budget
    "forbidden",  # policy says FORBIDDEN — never loaded
    "router_skipped",  # router chose not to retrieve an OPTIONAL source
    "empty",  # loaded successfully but holds no items
]


class ContextProvenance(BaseModel):
    """One source's presence/absence record in an assembled context."""

    model_config = ConfigDict(frozen=True)

    source: RetrievalSource
    status: SourceStatus
    item_count: int = 0
    schema_version: str = ""
    detail: str = ""


# ------------------------------------------------------------- typed slices


class MasteryEntry(BaseModel):
    """projected mastery of one skill (source: student_state_projections)."""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    mastery: float = Field(ge=0.0, le=1.0)


class StudentModelContext(BaseModel):
    """Projection slice of the authoritative student state (derived)."""

    model_config = ConfigDict(frozen=True)

    estimator_version: str
    projection_version: int = Field(ge=0)
    concept_mastery: tuple[MasteryEntry, ...] = ()
    skill_mastery: tuple[MasteryEntry, ...] = ()
    active_misconception_rule_ids: tuple[str, ...] = ()


class CurriculumNodeRef(BaseModel):
    """Curriculum node reference (source: curriculum version)."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    code: str
    kind: str  # chapter / concept / skill
    title: str
    stage: str | None = None


class CurriculumContext(BaseModel):
    """Curriculum slice: what the system knows about the math itself."""

    model_config = ConfigDict(frozen=True)

    version_code: str = ""
    nodes: tuple[CurriculumNodeRef, ...] = ()


class MisconceptionEntry(BaseModel):
    """One rule in the misconception history (observation aggregate)."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    observation_count: int = Field(ge=0)


class MisconceptionContext(BaseModel):
    """Misconception observation history slice (source: observations)."""

    model_config = ConfigDict(frozen=True)

    entries: tuple[MisconceptionEntry, ...] = ()


class AttemptSummaryEntry(BaseModel):
    """One attempt's summary (source: mastery_evidence replay — the
    per-attempt educational fact stream; NOT raw SQLite rows)."""

    model_config = ConfigDict(frozen=True)

    skill_id: str
    correctness: str  # correct / partial / incorrect
    effective_assistance_level: int = Field(ge=0, le=5)
    attempt_index: int = Field(ge=1)
    created_at: str = ""


class RecentAttemptsContext(BaseModel):
    """Recent attempt summary slice (chronological, oldest first)."""

    model_config = ConfigDict(frozen=True)

    entries: tuple[AttemptSummaryEntry, ...] = ()


class MemoryContextEntry(BaseModel):
    """One personal memory node (source: personal_memory_nodes)."""

    model_config = ConfigDict(frozen=True)

    memory_id: UUID
    memory_type: str
    subject: str
    predicate: str
    object_json: dict
    source_type: str  # USER_EXPLICIT / MODEL_INFERRED / USER_CONFIRMED
    confidence: float = Field(ge=0.0, le=1.0)


class PersonalMemoryContext(BaseModel):
    """Personal memory slice — non-authoritative preferences only."""

    model_config = ConfigDict(frozen=True)

    entries: tuple[MemoryContextEntry, ...] = ()


class DocumentChunkRef(BaseModel):
    """One retrieved chunk reference (source: user documents)."""

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID
    document_id: UUID
    sequence: int
    page: int | None = None
    text: str
    score: float = Field(ge=0.0)
    retriever: str = "lexical"  # lexical / lexical+vector


class DocumentContextSelection(BaseModel):
    """Selected chunks of the student's own documents (projected, capped)."""

    model_config = ConfigDict(frozen=True)

    document_id: UUID
    filename: str
    chunks: tuple[DocumentChunkRef, ...] = ()


class AssembledContext(BaseModel):
    """The complete typed context handed to an LLM consumer.

    Every optional field is None when the source was not loaded; the
    provenance tuple explains exactly why for each source.
    """

    model_config = ConfigDict(frozen=True)

    intent: RetrievalIntent
    student_id: UUID
    policy_version: str
    plan: RetrievalPlan
    student_model: StudentModelContext | None = None
    curriculum: CurriculumContext | None = None
    misconception_history: MisconceptionContext | None = None
    recent_attempts: RecentAttemptsContext | None = None
    personal_memory: PersonalMemoryContext | None = None
    user_documents: tuple[DocumentContextSelection, ...] = ()
    provenance: tuple[ContextProvenance, ...] = ()

    def provenance_for(self, source: RetrievalSource) -> ContextProvenance | None:
        for entry in self.provenance:
            if entry.source is source:
                return entry
        return None


__all__ = [
    "AssembledContext",
    "AttemptSummaryEntry",
    "ContextProvenance",
    "CurriculumContext",
    "CurriculumNodeRef",
    "DocumentChunkRef",
    "DocumentContextSelection",
    "MasteryEntry",
    "MemoryContextEntry",
    "MisconceptionContext",
    "MisconceptionEntry",
    "PersonalMemoryContext",
    "RecentAttemptsContext",
    "SourceStatus",
    "StudentModelContext",
]
