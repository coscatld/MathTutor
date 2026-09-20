"""DEPRECATED (Route 2, docs/CURRENT_STATE_RAG_AUDIT.md §4.3).

``MetadataFirstRetriever`` / ``RetrievalItem`` / ``RetrievedResult`` have
ZERO production callers: the only importers are ``tests/`` and
``scripts/math_tutor_rc_benchmark.py``. The production retrieval kernel is
``DocumentIndexManager.search``, orchestrated by
``application/retrieval_orchestrator.py`` on top of real ``RetrievedChunk``
objects. ``NoOpReranker`` is superseded by ``application/rerank.py``.

Kept (not deleted) because ``tests/test_phase6_retrieval*.py`` still
exercise it and the deletion gate in the requirements allows a documented
DEPRECATED REMAINING. Do NOT wire any of this into a production path.
Metadata-first retrieval router (Phase 6 §9.2) — resolver, not a store.

The retrieval pipeline is:

    server-owned metadata filter
      → vector / lexical retrieval
      → local reranker
      → provenance projection

This module implements the RESOLVER part: given a candidate collection
(the caller — a service — loads candidates from owner-scoped repositories),
the router filters on server-owned metadata FIRST (owner scope,
stage/grade, skill/concept codes, mapping ids, ``retrieval_enabled``), then
decides whether a vector pass is possible, then reranks, then labels every
result with provenance for evaluation.

Design rules (verbatim from the invariants):

- INVARIANT F: a source with ``retrieval_enabled=false`` is NEVER
  retrieved, whatever the router or the LLM requests. There is no override
  flag — the filter is absolute.
- The vector path is ONLY enabled when the embedding runtime has a backend
  (``EmbeddingRuntime.backend()``). With no backend the router degrades to
  metadata/lexical results and marks every result
  ``vector: "unavailable"`` — the core never depends on embeddings.
- The router NEVER writes any storage; it is a pure in-memory resolver.
- Provenance (source + filter reasons) is attached to every result so the
  evaluation export can audit what reached an LLM consumer and why.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime

#: Provenance marker values for the vector pass.
VECTOR_USED = "used"
VECTOR_UNAVAILABLE = "unavailable"
VECTOR_SKIPPED = "skipped"  # caller declared no vectors are needed


class Reranker(Protocol):
    """Local reranker contract. Implementations must be usable without a
    model (the default :class:`NoOpReranker` is a pure identity)."""

    async def rerank(
        self,
        query_hint: str,
        candidates: Sequence[Any],
        limit: int,
    ) -> list[Any]: ...


class NoOpReranker:
    """Deterministic identity reranker — keeps candidate order, truncates.

    Usable with no model, no network and no weights: the degradation path
    for a missing/optional local reranker.
    """

    async def rerank(
        self,
        query_hint: str,
        candidates: Sequence[Any],
        limit: int,
    ) -> list[Any]:
        return list(candidates[:limit])


@dataclass(frozen=True, slots=True)
class RetrievalItem:
    """One candidate source record: text + server-owned metadata.

    ``owner_scope`` is the owning student/tenant identity; ``"global"``
    marks shared curriculum material. The router filters on these metadata
    fields BEFORE any text/vector consideration.
    """

    item_id: str
    text: str
    source_type: str  # curriculum | personal_memory | user_document | ...
    owner_scope: str
    retrieval_enabled: bool = True
    stage: str | None = None  # primary | middle | high
    grade: int | None = None
    skill_codes: tuple[str, ...] = ()
    concept_codes: tuple[str, ...] = ()
    mapping_ids: tuple[str, ...] = ()  # practice-side mapping ids (UUID str)
    extra: dict[str, Any] = field(default_factory=dict)  # page/section/license/...


@dataclass(frozen=True, slots=True)
class RetrievedResult:
    """One routed result with provenance for the evaluation export."""

    item: RetrievalItem
    score: float | None  # None on the pure-metadata path
    provenance: dict[str, Any]  # source + filter reasons + vector marker


class MetadataFirstRetriever:
    """Metadata-first resolver: filter, then (optionally) vector, then rerank.

    ``embedding_runtime`` is the infrastructure EmbeddingRuntime; ``None``
    (or a runtime without a backend) disables the vector path. ``reranker``
    defaults to :class:`NoOpReranker`.
    """

    def __init__(
        self,
        embedding_runtime: EmbeddingRuntime | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._embedding_runtime = embedding_runtime
        self._reranker = reranker or NoOpReranker()

    # ------------------------------------------------------------ filter

    def _metadata_filter(
        self,
        items: Sequence[RetrievalItem],
        *,
        owner_scope: str,
        stage: str | None,
        grade: int | None,
        skill_codes: Sequence[str],
        concept_codes: Sequence[str],
        mapping_ids: Sequence[str],
    ) -> list[tuple[RetrievalItem, list[str]]]:
        """Server-owned metadata pass; returns (item, matched-filters)."""
        wanted_skills = set(skill_codes)
        wanted_concepts = set(concept_codes)
        wanted_mappings = set(mapping_ids)
        kept: list[tuple[RetrievalItem, list[str]]] = []
        for item in items:
            matched: list[str] = []
            # Owner/visibility scope (INVARIANT: server-owned, never client).
            if not (item.owner_scope == owner_scope or item.owner_scope == "global"):
                continue
            matched.append("owner_scope")
            # INVARIANT F: disabled sources are ABSOLUTELY excluded.
            if not item.retrieval_enabled:
                continue
            matched.append("retrieval_enabled")
            if stage is not None:
                if item.stage != stage:
                    continue
                matched.append("stage")
            if grade is not None:
                if item.grade != grade:
                    continue
                matched.append("grade")
            if wanted_skills and not (set(item.skill_codes) & wanted_skills):
                continue
            if wanted_skills:
                matched.append("skill")
            if wanted_concepts and not (set(item.concept_codes) & wanted_concepts):
                continue
            if wanted_concepts:
                matched.append("concept")
            if wanted_mappings and not (set(item.mapping_ids) & wanted_mappings):
                continue
            if wanted_mappings:
                matched.append("mapping_id")
            kept.append((item, matched))
        return kept

    # ---------------------------------------------------------- retrieve

    async def retrieve(
        self,
        query_hint: str,
        items: Sequence[RetrievalItem],
        *,
        owner_scope: str,
        stage: str | None = None,
        grade: int | None = None,
        skill_codes: Sequence[str] = (),
        concept_codes: Sequence[str] = (),
        mapping_ids: Sequence[str] = (),
        limit: int = 10,
    ) -> list[RetrievedResult]:
        """Route ``items`` → filtered → (vector) → reranked results.

        Pure in-memory: never writes any storage. Provenance on every
        result records which metadata filters matched, the routing reason
        and the vector marker (``used`` / ``unavailable``).
        """
        filtered = self._metadata_filter(
            items,
            owner_scope=owner_scope,
            stage=stage,
            grade=grade,
            skill_codes=skill_codes,
            concept_codes=concept_codes,
            mapping_ids=mapping_ids,
        )
        if not filtered:
            return []

        status = self._embedding_runtime.status() if self._embedding_runtime else None
        vector_available = bool(status is not None and status.available)

        scored: list[tuple[RetrievalItem, list[str], float | None]] = []
        if vector_available:
            assert self._embedding_runtime is not None
            texts = [item.text for item, _ in filtered]
            vectors = await self._embedding_runtime.embed_texts(texts)
            query_vector = await self._embedding_runtime.embed_query(query_hint)
            for (item, matched), vector in zip(filtered, vectors):
                score = _cosine(query_vector, vector)
                scored.append((item, matched, score))
            scored.sort(key=lambda row: row[2] if row[2] is not None else -1.0, reverse=True)
        else:
            # Degraded path: metadata/lexical only, keep metadata order.
            scored = [(item, matched, None) for item, matched in filtered]

        candidates = [row[0] for row in scored]
        ranked = await self._reranker.rerank(query_hint, candidates, limit)
        ranked_ids = {item.item_id for item in ranked}
        ranked_map = {row[0].item_id: row for row in scored}

        results: list[RetrievedResult] = []
        for item in ranked:
            _item, matched, score = ranked_map[item.item_id]
            provenance: dict[str, Any] = {
                "source_type": item.source_type,
                "source_id": item.item_id,
                "matched_metadata": matched,
                "reason": "vector_match" if vector_available else "metadata_lexical",
                "vector": VECTOR_USED if vector_available else VECTOR_UNAVAILABLE,
                "reranker": type(self._reranker).__name__,
            }
            if vector_available and status is not None and status.descriptor is not None:
                provenance["embedding_backend"] = status.descriptor.backend_id
            results.append(RetrievedResult(item=item, score=score, provenance=provenance))
        assert len(results) <= limit and len(ranked_ids) == len(results)
        return results


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity (deterministic, dependency-free)."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (norm_a * norm_b)


__all__ = [
    "MetadataFirstRetriever",
    "NoOpReranker",
    "Reranker",
    "RetrievalItem",
    "RetrievedResult",
    "VECTOR_UNAVAILABLE",
    "VECTOR_USED",
]
