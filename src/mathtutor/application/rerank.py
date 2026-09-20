"""ProductionReranker — deterministic, model-free reranking of real hits.

Reranks the retrieval kernel's own output (:class:`RetrievedChunk`), not an
adapter type. The audit found the opposite arrangement: `LexicalScoreReranker`
took ``Sequence[Any]`` and read ``getattr(candidate, "text", "")``, which is
empty for a :class:`RetrievedChunk` (its text lives at
``candidate.chunk.text``) — so the tested reranker silently scored everything
zero on real hits, and the only reranking that actually ran was a one-line
inline bump in ``KnowledgeService.search``.

This module consolidates both into one named, testable stage:

    fused retrieval score            (from DocumentIndexManager.search)
  + token-coverage signal            (shared with the lexical retrievers)
  + exact-phrase / section signals   (the previously inline, unnamed bump)

Every weight below is a named constant with a test pinning it, because the
inline version's ``1.0`` / ``.25`` were untested magic numbers.

No network, no model, no randomness: same input, same output.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from mathtutor.domain.documents import RetrievedChunk
from mathtutor.infrastructure.lexical import lexical_score, tokenize_lexical

#: Weight of the token-coverage signal. Kept below the fused retrieval score's
#: own scale so reranking corrects ordering without overriding a strong
#: lexical/FTS match.
COVERAGE_WEIGHT = 0.5

#: The query appears verbatim in the chunk text (not just as tokens).
EXACT_PHRASE_BONUS = 1.0

#: The query appears in the chunk's section title — a strong topical hint.
SECTION_MATCH_BONUS = 0.25

#: Below this the candidate is dropped entirely rather than shipped as noise.
MIN_RERANK_SCORE = 0.0


@dataclass(frozen=True, slots=True)
class RerankedHit:
    """A hit plus the breakdown that produced its final ordering."""

    hit: RetrievedChunk
    rerank_score: float
    coverage: float
    exact_phrase: bool
    section_match: bool

    @property
    def chunk_text(self) -> str:
        return self.hit.chunk.text


class ProductionReranker:
    """Deterministic reordering over :class:`RetrievedChunk`.

    ``limit`` truncates; it never invents or duplicates candidates.
    """

    def __init__(
        self,
        *,
        coverage_weight: float = COVERAGE_WEIGHT,
        exact_phrase_bonus: float = EXACT_PHRASE_BONUS,
        section_match_bonus: float = SECTION_MATCH_BONUS,
    ) -> None:
        self.coverage_weight = coverage_weight
        self.exact_phrase_bonus = exact_phrase_bonus
        self.section_match_bonus = section_match_bonus

    def rerank(
        self,
        query: str,
        hits: Sequence[RetrievedChunk],
        limit: int | None = None,
    ) -> list[RerankedHit]:
        tokens = tokenize_lexical(query)
        folded = (query or "").strip().casefold()

        scored: list[tuple[float, int, RerankedHit]] = []
        for index, hit in enumerate(hits):
            text = hit.chunk.text or ""
            coverage = lexical_score(text, tokens) if tokens else 0.0
            exact = bool(folded) and folded in text.casefold()
            section = bool(query) and bool(hit.chunk.section) and query in hit.chunk.section

            score = (
                hit.score
                + self.coverage_weight * coverage
                + (self.exact_phrase_bonus if exact else 0.0)
                + (self.section_match_bonus if section else 0.0)
            )
            if score <= MIN_RERANK_SCORE and not text.strip():
                continue
            scored.append(
                (
                    score,
                    index,
                    RerankedHit(
                        hit=hit,
                        rerank_score=score,
                        coverage=coverage,
                        exact_phrase=exact,
                        section_match=section,
                    ),
                )
            )

        # -score, then input index: a stable, fully determined ordering.
        scored.sort(key=lambda row: (-row[0], row[1]))
        ordered = [row[2] for row in scored]
        return ordered[:limit] if limit is not None else ordered


__all__ = [
    "COVERAGE_WEIGHT",
    "EXACT_PHRASE_BONUS",
    "MIN_RERANK_SCORE",
    "ProductionReranker",
    "RerankedHit",
    "SECTION_MATCH_BONUS",
]
