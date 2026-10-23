"""EvidencePack — the immutable, bounded evidence projection for one turn.

Design (audit §4.5, Route 2):

    ConversationRetrievalOrchestrator   decide + scope + rewrite + orchestrate
    DocumentIndexManager                the only retrieval kernel
    ProductionReranker                  rank
    ContextExpander                     restore neighbouring/parent context
    EvidencePackBuilder                 this file: the public projection

Why a separate type instead of appending search hits to the prompt:

- **Bounded by construction.** ``MAX_EVIDENCE_ITEMS`` / ``MAX_EVIDENCE_CHARS``
  are enforced at build time, so "top-K = 20 → 20 chunks into the model"
  cannot happen by accident.
- **Immutable.** Frozen pydantic models; nothing downstream — the LLM
  included — can mutate what was retrieved.
- **Traceable.** Every item carries document id, chunk id, sequence, page,
  section path and scores, so a claim can be walked back to the exact slice.
- **Honest about degradation.** ``RetrievalExecution`` records what actually
  happened (lexical vs hybrid, whether a reranker ran, why not) rather than
  collapsing to a single label that hides the reason.

``retrieval_mode`` deliberately keeps ``hybrid`` in its domain even though the
shipped runtime only ever produces ``lexical`` (no embedding backend ships —
see docs/CURRENT_STATE_RAG_AUDIT.md §6.1). The observed default must not
freeze the architecture's capability.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RetrievalMode = Literal["lexical", "hybrid"]

#: Hard caps. A pack is never unbounded, whatever the retrieval returned.
MAX_EVIDENCE_ITEMS = 8
MAX_EVIDENCE_CHARS = 12000
MAX_PER_ITEM_CHARS = 2000

#: Context expansion budget, expressed in characters because that is the unit
#: the existing chat projection already budgets in. Expansion must never turn
#: a bounded top-K into a whole-document read.
MAX_EXPANDED_ITEMS = 4
MAX_EXPANSION_CHARS = 2400


class RetrievalHop(BaseModel):
    """One retrieval step in a turn.

    Hop 1 is the system-guaranteed initial retrieval; hops ≥ 2 are the agent
    asking for more. This is deliberately the MINIMUM needed to make
    "did the agent have to go looking?" observable — not a GraphRAG planner.

    ``query_fingerprint`` is a hash, never the query text: telemetry must not
    carry what the student typed.
    """

    model_config = ConfigDict(frozen=True)

    hop_index: int = Field(ge=1)
    kind: str = "INITIAL"          # INITIAL | AGENT_SEARCH
    result_count: int = Field(ge=0, default=0)
    query_fingerprint: str = ""


class EvidenceCoverage(BaseModel):
    """Structural metadata about how much of the candidate set survived.

    NOT a statement about answer completeness — nothing here knows what the
    question requires. It reports what retrieval did with what it found.
    """

    model_config = ConfigDict(frozen=True)

    retrieved_count: int = Field(ge=0, default=0)
    selected_count: int = Field(ge=0, default=0)
    source_count: int = Field(ge=0, default=0)
    expansion_used: bool = False
    #: True when selection was cut by a budget rather than by lack of
    #: candidates. This is the ONLY thing that makes a pack partial.
    truncated: bool = False

    @property
    def partial(self) -> bool:
        return self.truncated


class RetrievalExecution(BaseModel):
    """What the retrieval stack actually did this turn.

    Telemetry reads this instead of inferring capability from configuration:
    "vector requested but unavailable" and "vector not requested" are
    different facts and must stay distinguishable.
    """

    model_config = ConfigDict(frozen=True)

    mode: RetrievalMode = "lexical"
    retrieval_ran: bool = False
    reranker_used: bool = False
    expansion_used: bool = False
    candidates_considered: int = Field(ge=0, default=0)
    items_returned: int = Field(ge=0, default=0)
    #: Machine-readable reasons, e.g. ``embedding_runtime_unavailable``,
    #: ``empty_conversation_scope``, ``no_query_hint``. Prefixed, never free
    #: prose, so telemetry can group them.
    degraded_reasons: tuple[str, ...] = ()
    decision: str = ""
    #: Stage latency in milliseconds. ``None`` = not measured in this path.
    retrieval_ms: float | None = None
    rerank_ms: float | None = None
    context_ms: float | None = None
    hops: tuple[RetrievalHop, ...] = ()
    coverage: EvidenceCoverage = Field(default_factory=EvidenceCoverage)

    @property
    def degraded(self) -> bool:
        return bool(self.degraded_reasons)

    @property
    def hop_count(self) -> int:
        return len(self.hops)

    @property
    def second_retrieval_used(self) -> bool:
        return any(hop.kind == "AGENT_SEARCH" for hop in self.hops)


class Evidence(BaseModel):
    """One retrieved slice, projected for a model consumer.

    ``text`` may be wider than the matched chunk when context expansion pulled
    in neighbours; ``expanded_from`` records which chunks were merged so the
    projection never silently looks like a single original chunk.
    """

    model_config = ConfigDict(frozen=True)

    source_id: str
    document_id: UUID
    filename: str
    chunk_id: UUID
    sequence: int = Field(ge=0)
    page: int | None = None
    page_start: int | None = None
    page_end: int | None = None
    section: str = ""
    heading_path: tuple[str, ...] = ()
    text: str
    #: sha256 over ``text`` as projected. The integrity anchor available to
    #: every path, including ones with no versioned snapshot.
    text_hash: str = ""
    #: Populated only where the caller holds a versioned snapshot (the
    #: knowledge path). None never means "version 1".
    document_version: int | None = None
    body_hash: str | None = None
    score: float = 0.0
    lexical_score: float = 0.0
    vector_score: float | None = None
    rerank_score: float | None = None
    #: Chunk ids merged into ``text`` by context expansion. Empty = verbatim
    #: single-chunk projection.
    expanded_from: tuple[UUID, ...] = ()
    retriever: str = "lexical"
    matched_text: str = ""
    parent_text: str = ""
    neighbour_texts: tuple[str, ...] = ()

    @property
    def expanded(self) -> bool:
        return bool(self.expanded_from)


class EvidencePack(BaseModel):
    """Immutable evidence for one turn, plus how it was produced."""

    model_config = ConfigDict(frozen=True)

    query: str = ""
    rewritten_query: str = ""
    #: Hash of the query actually used. Telemetry never carries query text.
    query_fingerprint: str = ""
    evidences: tuple[Evidence, ...] = ()
    execution: RetrievalExecution = Field(default_factory=RetrievalExecution)

    @property
    def partial(self) -> bool:
        """True only when a BUDGET cut the selection.

        Not "we used top-K": a pack that returned everything available is
        complete even though it is a top-K slice. Conflating the two would
        make `partial` carry no information.
        """
        return self.execution.coverage.truncated

    @property
    def empty(self) -> bool:
        return not self.evidences

    def chars(self) -> int:
        return sum(len(item.text) for item in self.evidences)

    def source_ids(self) -> tuple[str, ...]:
        return tuple(item.source_id for item in self.evidences)

    def public_projection(self) -> dict:
        """The shape a model consumer may see.

        Drops nothing today, but exists so a future internal-only field does
        not leak into a prompt by default.
        """
        return {
            "query": self.query,
            "rewritten_query": self.rewritten_query,
            "retrieval": {
                "mode": self.execution.mode,
                "reranker_used": self.execution.reranker_used,
                "expansion_used": self.execution.expansion_used,
                "degraded_reasons": list(self.execution.degraded_reasons),
            },
            "evidences": [
                {
                    "source_id": item.source_id,
                    # Exposed so the model can name the document when calling
                    # read_source. It is an identifier, never a capability: the
                    # tool still accepts only ranges that were actually
                    # surfaced, so knowing the id grants nothing on its own.
                    "document_id": str(item.document_id),
                    "title": item.filename,
                    "section": item.section,
                    "page": item.page,
                    "sequence": item.sequence,
                    "text": item.text,
                    "expanded": item.expanded,
                }
                for item in self.evidences
            ],
        }


def text_hash(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def make_source_id(document_id: UUID, chunk_id: UUID) -> str:
    """Server-generated, stable, and never model-supplied."""
    return "e-" + sha256(f"{document_id}:{chunk_id}".encode()).hexdigest()[:24]


def build_evidence_pack(
    *,
    query: str,
    rewritten_query: str = "",
    evidences: list[Evidence],
    execution: RetrievalExecution | None = None,
    fingerprint_of: str | None = None,
) -> EvidencePack:
    """Truncate to the hard caps and freeze.

    Truncation happens HERE rather than at each call site so the bound holds
    for every consumer, including ones added later. It is also where
    ``coverage.truncated`` is decided — the only place that knows whether a
    candidate was dropped for budget rather than for absence.
    """
    kept: list[Evidence] = []
    budget = MAX_EVIDENCE_CHARS
    truncated = False
    for item in evidences:
        if len(kept) >= MAX_EVIDENCE_ITEMS or budget <= 0:
            truncated = True
            continue
        if item.parent_text:
            group = "\n".join(part for part in (item.parent_text, item.matched_text) if part)
            if not group.strip():
                continue
            if len(group) > MAX_PER_ITEM_CHARS or len(group) > budget:
                truncated = True
                continue
            parts = [group]
            used = len(group)
            for neighbour in item.neighbour_texts:
                extra = 1 + len(neighbour)
                if used + extra > min(MAX_PER_ITEM_CHARS, budget):
                    truncated = True
                    continue
                parts.append(neighbour)
                used += extra
            text = "\n".join(parts)
        else:
            text = item.text[:MAX_PER_ITEM_CHARS]
            if not text.strip():
                continue  # empty evidence is dropped, not shipped as noise
            if len(text) < len(item.text):
                truncated = True  # per-item truncation is also a budget cut
            used = len(text)
        budget -= used
        kept.append(item.model_copy(update={"text": text}))

    base = execution or RetrievalExecution()
    coverage = base.coverage.model_copy(
        update={
            "retrieved_count": len(evidences),
            "selected_count": len(kept),
            "source_count": len({item.document_id for item in kept}),
            "expansion_used": any(item.expanded for item in kept),
            "truncated": truncated,
        }
    )
    return EvidencePack(
        query=query,
        rewritten_query=rewritten_query,
        query_fingerprint=(
            fingerprint_of
            if fingerprint_of is not None
            else (sha256(query.encode("utf-8")).hexdigest()[:16] if query else "")
        ),
        evidences=tuple(kept),
        execution=base.model_copy(
            update={"items_returned": len(kept), "coverage": coverage}
        ),
    )


__all__ = [
    "Evidence",
    "EvidenceCoverage",
    "EvidencePack",
    "MAX_EVIDENCE_CHARS",
    "MAX_EVIDENCE_ITEMS",
    "MAX_EXPANDED_ITEMS",
    "MAX_EXPANSION_CHARS",
    "MAX_PER_ITEM_CHARS",
    "RetrievalExecution",
    "RetrievalHop",
    "RetrievalMode",
    "build_evidence_pack",
    "make_source_id",
    "text_hash",
]
