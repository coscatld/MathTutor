"""User Document Knowledge repository contract.

Data-layer invariants (identical in BOTH implementations — the security
boundary, never a UI concern):

- owner scope: every query carries the owner; another student's document
  or chunk is structurally unreachable;
- retrieval reads only see documents with ``retrieval_enabled`` AND no
  ``deleted_at`` AND a retrievable status (``ready`` /
  ``ready_with_warnings``) — user permission wins over the Router (a
  disabled or zero-text document is never returned to the assembler);
- chunk TEXT is a fact (append/replace only through the ingestion
  pipeline); vectors are a derived projection the index manager replaces;
- duplicate-import semantics: (student_id, content_hash) is unique.

Ranking: the repository returns candidates with BOTH scores (lexical
fraction + optional vector similarity). Fusion is deterministic and
shared (:func:`fuse_retrieval_scores`): lexical always participates, so
retrieval works with NO embedding backend (degraded mode). The caller
passes ``vector=None`` to request lexical-only.

The SQLite implementation lives in repositories/sqlite_documents.py with
the same contract.
"""

from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from mathtutor.domain.documents import (
    DocumentChunk,
    DocumentQueryResult,
    IndexBuildRecord,
    UserDocument,
)
from mathtutor.domain.embedding import (
    EmbeddingDescriptor,
    EmbeddingVector,
)
from mathtutor.infrastructure.lexical import lexical_score


class StaleIndexGenerationError(ValueError):
    """Vectors were computed against chunks that have since been replaced."""


# Weight of the vector score inside the fused score (lexical weight = 1.0).
# Lexical always participates; the vector term only adds signal when a
# backend exists. Tuned so a strong lexical match still wins over a weak
# semantic one — math terms are keyword-dense by nature.
VECTOR_FUSION_WEIGHT = 0.5
# FTS5 bm25 mapped to (0, 1]; lexical remains the primary term so a
# missing embedding backend never blocks ranking.
FTS_FUSION_WEIGHT = 0.5


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product for two L2-normalized vectors, clamped to [-1, 1]."""
    if len(a) != len(b):
        return 0.0
    product = sum(x * y for x, y in zip(a, b))
    return max(-1.0, min(1.0, product))


def fuse_retrieval_scores(lexical: float, vector_similarity: float | None) -> float:
    """Deterministic rank fusion: lexical (weight 1) + optional vector."""
    if vector_similarity is None:
        return lexical
    return lexical + VECTOR_FUSION_WEIGHT * vector_similarity


class DocumentRepository(Protocol):
    """Async document persistence contract (owner-scoped)."""

    # documents ----------------------------------------------------------

    async def add_document(
        self, student_id: str, doc: UserDocument
    ) -> UserDocument: ...

    async def get_document(
        self, student_id: str, document_id: UUID, *, include_deleted: bool = False
    ) -> UserDocument | None: ...

    async def find_by_content_hash(
        self, student_id: str, content_hash: str
    ) -> UserDocument | None: ...

    async def update_document(
        self, student_id: str, doc: UserDocument
    ) -> UserDocument | None: ...

    async def set_retrieval_enabled(
        self, student_id: str, document_id: UUID, enabled: bool
    ) -> UserDocument | None: ...

    async def soft_delete_document(
        self, student_id: str, document_id: UUID
    ) -> bool: ...

    async def list_documents(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[UserDocument]: ...

    # chunks -------------------------------------------------------------

    async def replace_chunks(
        self, student_id: str, document_id: UUID, chunks: Sequence[DocumentChunk]
    ) -> None: ...

    async def publish_parse_result(
        self, student_id: str, doc: UserDocument, chunks: Sequence[DocumentChunk]
    ) -> UserDocument | None:
        """Atomically replace complete chunks, vectors and parse metadata."""
        ...

    async def list_chunks(
        self, student_id: str, document_id: UUID
    ) -> list[DocumentChunk]: ...

    async def list_chunk_neighbourhood(
        self,
        student_id: str,
        document_id: UUID,
        *,
        sequence_start: int,
        sequence_end: int,
        chunk_ids: Sequence[UUID] = (),
    ) -> list[DocumentChunk]:
        """Chunks within an inclusive ``sequence`` window or by explicit id,
        visibility-gated.

        Adjacency for context expansion is resolved from
        ``(document_id, sequence)`` at read time; no prev/next columns exist.
        """
        ...

    async def list_retrievable_chunks(
        self, student_id: str, document_id: UUID
    ) -> list[DocumentChunk]:
        """Owner-scoped chunk read that ALSO enforces the visibility gate.

        ``list_chunks`` is owner-scoped only: it is the right primitive for
        versioning (``snapshot``) and index building, which must see the
        document even while it is disabled. Anything that feeds retrieved
        text to a model must use this method instead, so visibility no
        longer depends on the caller having pre-filtered correctly.
        """
        ...

    # vectors (derived projection; replaced on rebuild) -------------------

    async def replace_vectors(
        self,
        student_id: str,
        document_id: UUID,
        vectors: Sequence[tuple[UUID, EmbeddingDescriptor, EmbeddingVector]],
    ) -> None: ...

    async def get_vectors(
        self, student_id: str, document_id: UUID
    ) -> dict[UUID, tuple[EmbeddingDescriptor, EmbeddingVector]]: ...

    # index lifecycle -----------------------------------------------------

    async def get_index_build(
        self, student_id: str, document_id: UUID
    ) -> IndexBuildRecord | None: ...

    async def record_index_build(
        self, student_id: str, document_id: UUID, record: IndexBuildRecord
    ) -> None: ...

    async def publish_index(
        self,
        student_id: str,
        document_id: UUID,
        vectors: Sequence[tuple[UUID, EmbeddingDescriptor, EmbeddingVector]],
        record: IndexBuildRecord,
        *,
        expected_chunk_ids: Sequence[UUID],
    ) -> None:
        """Atomically publish vectors + build row if live chunks still match.

        Embedding stays outside the transaction. A reparse that lands while
        vectors were computing must not commit the expired generation, and
        must not reset ``index_version`` back to 1.
        """
        ...

    # retrieval -----------------------------------------------------------

    async def search_chunks(
        self,
        student_id: str,
        *,
        query: str,
        query_tokens: Sequence[str],
        limit: int = 5,
        document_ids: Sequence[UUID] | None = None,
        vector: EmbeddingVector | None = None,
        embedding_backend_id: str = "",
        index_version: int | None = None,
    ) -> DocumentQueryResult: ...


def _lexical_fraction(text: str, query_tokens: Sequence[str]) -> float:
    return lexical_score(text, query_tokens)


__all__ = [
    "DocumentRepository",
    "FTS_FUSION_WEIGHT",
    "StaleIndexGenerationError",
    "VECTOR_FUSION_WEIGHT",
    "cosine_similarity",
    "fuse_retrieval_scores",
]
