"""ConversationRetrievalOrchestrator — the turn-level retrieval pipeline.

Route 2 (docs/CURRENT_STATE_RAG_AUDIT.md §4.3): the retrieval KERNEL already
exists and is shared by all three consumers. What was missing is orchestration:

    decide  →  scope  →  rewrite  →  kernel.search  →  rerank  →  expand  →  pack

This module adds exactly that, and nothing below it. It does not re-implement
retrieval: ``DocumentIndexManager.search`` remains the single kernel, and its
SQL keeps applying the owner / conversation / visibility filter before scoring.

Why ``document_ids`` is a REQUIRED argument
-------------------------------------------
Audit D1: ``current_document_scope()`` used to default to ``None``, and the
repository reads ``None`` as "no filter" — i.e. every document the owner has.
That made "scope not set" and "all documents" the same value. Here the scope is
an ordinary required parameter, so an unset scope cannot be expressed at all;
the caller must pass a concrete (possibly empty) list, and an empty list is a
NONE decision, never a widened search.
"""

from __future__ import annotations

import re
import time
from hashlib import sha256
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, Sequence
from uuid import UUID

from mathtutor.application.context_expansion import ContextExpander, ExpandedHit
from mathtutor.application.rerank import ProductionReranker, RerankedHit
from mathtutor.domain.documents import DocumentQueryResult
from mathtutor.domain.evidence import (
    Evidence,
    EvidencePack,
    RetrievalExecution,
    RetrievalHop,
    build_evidence_pack,
    make_source_id,
    text_hash,
)
from mathtutor.infrastructure.lexical import tokenize_lexical

#: Candidates pulled from the kernel before reranking. Retrieval is cheap
#: (metadata-filtered SQL + FTS), so the funnel is wide at this end.
DEFAULT_CANDIDATE_LIMIT = 20
#: Candidates surviving rerank into the pack.
DEFAULT_EVIDENCE_LIMIT = 8

# Degraded-reason codes. Machine-readable prefixes, never free prose, so
# telemetry can group them without parsing sentences.
REASON_EMBEDDING_UNAVAILABLE = "embedding_runtime_unavailable"
REASON_EMPTY_SCOPE = "empty_conversation_scope"
REASON_NO_QUERY = "no_query_hint"
REASON_SMALL_TALK = "decision_none_small_talk"
REASON_HINTS_ONLY = "decision_none_hints_only"

#: Short messages that carry no retrieval intent. Deliberately narrow: a
#: substantive question of any length still retrieves.
_SMALL_TALK = re.compile(
    r"^\s*(?:你好|您好|hi|hello|嗨|在吗|谢谢|多谢|好的|收到|嗯|ok|okay|明白|知道了)\s*[!！。.~]*\s*$",
    re.IGNORECASE,
)

#: Pronoun-style references that need recent turns to become a usable query.
#: Includes the forms the requirement doc names explicitly ("这一步为什么错"):
#: such a turn carries no topical token at all, so without absorbing context
#: the lexical index has nothing to match on.
_REFERENTIAL = re.compile(
    r"这个|这份|这些|这一步|这步|这题|这道|那条|那个|上述|刚才|上一|继续"
    r"|里面|它|该文档|该文件|该题|文中|图中"
)


class RetrievalDecision(StrEnum):
    NONE = "none"
    CONVERSATION_DOCUMENTS = "conversation_documents"


class RetrievalKernel(Protocol):
    """The only retrieval capability the orchestrator depends on."""

    async def search(
        self,
        student_id: str,
        *,
        query: str,
        limit: int = 5,
        document_ids: Sequence[UUID] | None = None,
    ) -> DocumentQueryResult: ...


class RetrievalMetricsSink(Protocol):
    """Where one turn's retrieval facts go. Implemented by MathTutorMetrics."""

    def record_retrieval(
        self,
        execution: object,
        *,
        latency_ms: float | None = None,
        rerank_ms: float | None = None,
        context_chars: int = 0,
    ) -> None: ...


class _NullSink:
    """Default sink: recording is opt-in, never a precondition for retrieval."""

    def record_retrieval(self, execution, *, latency_ms=None, rerank_ms=None, context_chars=0):
        return None


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    """The query actually sent to the kernel, plus how it was derived."""

    original: str
    text: str
    tokens: tuple[str, ...] = ()
    referential: bool = False
    context_used: tuple[str, ...] = field(default=())


def decide_retrieval(
    user_query: str,
    *,
    document_ids: Sequence[UUID],
    hints_only: bool = False,
) -> tuple[RetrievalDecision, tuple[str, ...]]:
    """Deterministic first-pass decision. Returns (decision, reasons).

    Only ``NONE`` and ``CONVERSATION_DOCUMENTS`` exist today because those are
    the only sources wired; a decision naming an unwired source would be a
    claim the system cannot honour.

    On ambiguity this RETRIEVES. Starving a grounded-answer system of its
    evidence is the more damaging error, and the scope check already bounds
    what "retrieve" can reach.
    """
    query = (user_query or "").strip()
    if hints_only:
        return RetrievalDecision.NONE, (REASON_HINTS_ONLY,)
    if not query:
        return RetrievalDecision.NONE, (REASON_NO_QUERY,)
    if not document_ids:
        return RetrievalDecision.NONE, (REASON_EMPTY_SCOPE,)
    if _SMALL_TALK.match(query):
        return RetrievalDecision.NONE, (REASON_SMALL_TALK,)
    return RetrievalDecision.CONVERSATION_DOCUMENTS, ()


def rewrite_query(
    user_query: str,
    *,
    history: Sequence[dict] = (),
    problem_text: str = "",
    max_history_chars: int = 190,
) -> RetrievalQuery:
    """Turn a bare follow-up into something the lexical index can match.

    A pronoun-only turn ("这一步为什么错") has nothing for FTS to key on, so a
    referential message absorbs the last student turns. The result is a
    bounded query string — never the whole transcript.
    """
    query = (user_query or "").strip()
    referential = bool(_REFERENTIAL.search(query))
    used: list[str] = []
    parts = [query]

    if problem_text.strip():
        parts.append(problem_text.strip()[:200])

    if referential and history:
        previous = [
            str(message.get("content", ""))
            for message in history[-6:]
            if message.get("role") == "student" and str(message.get("content", "")) != user_query
        ]
        tail = " ".join(previous[-2:])[:max_history_chars]
        if tail.strip():
            used.append(tail)
            parts.append(tail)

    text = " ".join(part for part in parts if part).strip()
    return RetrievalQuery(
        original=user_query,
        text=text,
        tokens=tuple(tokenize_lexical(text)),
        referential=referential,
        context_used=tuple(used),
    )


class ConversationRetrievalOrchestrator:
    """decide + scope + rewrite + orchestrate. Owns no storage and no SQL."""

    def __init__(
        self,
        *,
        kernel: RetrievalKernel,
        reranker: ProductionReranker | None = None,
        expander: ContextExpander | None = None,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
        evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
        metrics: RetrievalMetricsSink | None = None,
    ) -> None:
        self._kernel = kernel
        self._reranker = reranker or ProductionReranker()
        self._expander = expander
        self.candidate_limit = candidate_limit
        self.evidence_limit = evidence_limit
        self._metrics = metrics or _NullSink()

    async def retrieve_for_turn(
        self,
        owner: str,
        document_ids: Sequence[UUID],
        user_query: str,
        *,
        history: Sequence[dict] = (),
        problem_text: str = "",
        hints_only: bool = False,
    ) -> EvidencePack:
        decision, reasons = decide_retrieval(
            user_query, document_ids=document_ids, hints_only=hints_only
        )
        if decision is RetrievalDecision.NONE:
            skipped = build_evidence_pack(
                query=user_query,
                evidences=[],
                execution=RetrievalExecution(
                    mode="lexical",
                    retrieval_ran=False,
                    degraded_reasons=reasons,
                    decision=decision.value,
                ),
            )
            # Recorded even when nothing was retrieved: "we chose not to
            # search" is exactly the fact that makes the empty-retrieval and
            # second-retrieval rates interpretable.
            self._metrics.record_retrieval(skipped.execution, context_chars=0)
            return skipped

        query = rewrite_query(user_query, history=history, problem_text=problem_text)
        started = time.monotonic()
        result = await self._kernel.search(
            owner,
            query=query.text,
            limit=self.candidate_limit,
            document_ids=list(document_ids),
        )
        retrieval_ms = (time.monotonic() - started) * 1000.0

        degradation = list(reasons)
        if not result.vector_used:
            # Observed, not assumed: the kernel reports whether a vector pass
            # actually contributed. Chat/dense retrieval is unavailable, not
            # disabled — the distinction matters for telemetry.
            degradation.append(REASON_EMBEDDING_UNAVAILABLE)

        rerank_started = time.monotonic()
        ranked = self._reranker.rerank(query.text, result.hits, self.evidence_limit)
        rerank_ms = (time.monotonic() - rerank_started) * 1000.0
        expanded = await self._expand(owner, ranked)
        evidences = self._project(ranked, expanded)

        execution = RetrievalExecution(
            mode="hybrid" if result.vector_used else "lexical",
            retrieval_ran=True,
            reranker_used=bool(ranked),
            expansion_used=any(item.expanded for item in expanded),
            candidates_considered=len(result.hits),
            items_returned=len(evidences),
            degraded_reasons=tuple(dict.fromkeys(degradation)),
            decision=decision.value,
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            context_ms=(time.monotonic() - rerank_started) * 1000.0 - rerank_ms,
            hops=(
                RetrievalHop(
                    hop_index=1,
                    kind="INITIAL",
                    result_count=len(result.hits),
                    # A hash, never the query: telemetry must not carry what
                    # the student typed.
                    query_fingerprint=sha256(
                        query.text.encode("utf-8")
                    ).hexdigest()[:16],
                ),
            ),
        )
        pack = build_evidence_pack(
            query=user_query,
            rewritten_query=query.text,
            evidences=evidences,
            execution=execution,
        )
        self._metrics.record_retrieval(
            pack.execution,
            latency_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            context_chars=pack.chars(),
        )
        return pack

    async def _expand(
        self, owner: str, ranked: Sequence[RerankedHit]
    ) -> list[ExpandedHit]:
        hits = [row.hit for row in ranked]
        if self._expander is None:
            return [ExpandedHit(hit=hit, text=hit.chunk.text or "") for hit in hits]
        return await self._expander.expand(owner, hits)

    def _project(
        self, ranked: Sequence[RerankedHit], expanded: Sequence[ExpandedHit]
    ) -> list[Evidence]:
        """Pair each expanded hit with the rerank breakdown that ordered it.

        ``ContextExpander.expand`` returns one entry per input hit in input
        order, so the two sequences are positionally aligned. The length check
        makes that contract fail loudly rather than mis-attribute a score.
        """
        if len(ranked) != len(expanded):
            raise ValueError(
                f"expander returned {len(expanded)} entries for {len(ranked)} hits"
            )
        evidences: list[Evidence] = []
        for row, item in zip(ranked, expanded):
            chunk = item.hit.chunk
            evidences.append(
                Evidence(
                    source_id=make_source_id(item.hit.document_id, chunk.chunk_id),
                    document_id=item.hit.document_id,
                    filename=item.hit.filename,
                    chunk_id=chunk.chunk_id,
                    sequence=chunk.sequence,
                    page=chunk.page,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section=chunk.section,
                    heading_path=chunk.heading_path,
                    text=item.text,
                    text_hash=text_hash(item.text),
                    score=item.hit.score,
                    lexical_score=item.hit.lexical_score,
                    vector_score=item.hit.vector_score,
                    rerank_score=row.rerank_score,
                    expanded_from=item.expanded_from,
                    retriever=(
                        "lexical+vector" if item.hit.vector_score is not None else "lexical"
                    ),
                )
            )
        return evidences


__all__ = [
    "ConversationRetrievalOrchestrator",
    "DEFAULT_CANDIDATE_LIMIT",
    "DEFAULT_EVIDENCE_LIMIT",
    "RetrievalDecision",
    "RetrievalKernel",
    "RetrievalMetricsSink",
    "RetrievalQuery",
    "decide_retrieval",
    "rewrite_query",
]
