"""User Document Knowledge repository contract + in-memory implementation.

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

from datetime import datetime, timezone
from typing import Protocol, Sequence
from uuid import UUID

from mathtutor.domain.documents import (
    DocumentChunk,
    DocumentQueryResult,
    IndexBuildRecord,
    RetrievedChunk,
    UserDocument,
)
from mathtutor.domain.embedding import (
    EmbeddingDescriptor,
    EmbeddingVector,
)
from mathtutor.infrastructure.lexical import lexical_score
from mathtutor.security.scopes import student_uuid

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

    async def soft_delete_document(self, student_id: str, document_id: UUID) -> bool: ...

    async def list_documents(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[UserDocument]: ...

    # chunks -------------------------------------------------------------

    async def replace_chunks(
        self, student_id: str, document_id: UUID, chunks: Sequence[DocumentChunk]
    ) -> None: ...

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


class InMemoryDocumentRepository:
    """Process-local document store (dev/tests). Same invariants."""

    def __init__(self) -> None:
        self._documents: dict[UUID, UserDocument] = {}
        self._chunks: dict[UUID, list[DocumentChunk]] = {}
        self._vectors: dict[UUID, dict[UUID, tuple[EmbeddingDescriptor, EmbeddingVector]]] = {}
        self._builds: dict[tuple[UUID, UUID], IndexBuildRecord] = {}

    # ----------------------------------------------------------- documents

    async def add_document(self, student_id: str, doc: UserDocument) -> UserDocument:
        owner = student_uuid(student_id)
        stored = doc.model_copy(update={"student_id": owner})
        self._documents[stored.document_id] = stored
        return stored

    async def get_document(
        self, student_id: str, document_id: UUID, *, include_deleted: bool = False
    ) -> UserDocument | None:
        doc = self._documents.get(document_id)
        if doc is None or doc.student_id != student_uuid(student_id):
            return None
        if doc.deleted_at is not None and not include_deleted:
            return None
        return doc

    async def find_by_content_hash(
        self, student_id: str, content_hash: str
    ) -> UserDocument | None:
        owner = student_uuid(student_id)
        for doc in self._documents.values():
            if (
                doc.student_id == owner
                and doc.deleted_at is None
                and doc.content_hash == content_hash
            ):
                return doc
        return None

    async def update_document(self, student_id: str, doc: UserDocument) -> UserDocument | None:
        owner = student_uuid(student_id)
        current = self._documents.get(doc.document_id)
        if current is None or current.student_id != owner or current.deleted_at is not None:
            return None
        stored = doc.model_copy(update={"student_id": owner})
        self._documents[stored.document_id] = stored
        return stored

    async def set_retrieval_enabled(
        self, student_id: str, document_id: UUID, enabled: bool
    ) -> UserDocument | None:
        owner = student_uuid(student_id)
        current = self._documents.get(document_id)
        if current is None or current.student_id != owner or current.deleted_at is not None:
            return None
        stored = current.model_copy(update={"retrieval_enabled": enabled})
        self._documents[document_id] = stored
        return stored

    async def soft_delete_document(self, student_id: str, document_id: UUID) -> bool:
        owner = student_uuid(student_id)
        current = self._documents.get(document_id)
        if current is None or current.student_id != owner or current.deleted_at is not None:
            return False
        self._documents[document_id] = current.model_copy(
            update={"deleted_at": datetime.now(timezone.utc)}
        )
        return True

    async def list_documents(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[UserDocument]:
        owner = student_uuid(student_id)
        rows = [
            doc
            for doc in self._documents.values()
            if doc.student_id == owner and (include_deleted or doc.deleted_at is None)
        ]
        rows.sort(key=lambda doc: doc.created_at)
        return rows

    # ------------------------------------------------------------- chunks

    async def replace_chunks(
        self, student_id: str, document_id: UUID, chunks: Sequence[DocumentChunk]
    ) -> None:
        owner = student_uuid(student_id)
        stored = [chunk.model_copy(update={"student_id": owner}) for chunk in chunks]
        stored.sort(key=lambda chunk: chunk.sequence)
        self._chunks[document_id] = stored

    async def list_chunks(
        self, student_id: str, document_id: UUID
    ) -> list[DocumentChunk]:
        owner = student_uuid(student_id)
        chunks = self._chunks.get(document_id, [])
        return [chunk for chunk in chunks if chunk.student_id == owner]

    async def list_retrievable_chunks(
        self, student_id: str, document_id: UUID
    ) -> list[DocumentChunk]:
        owner = student_uuid(student_id)
        doc = self._documents.get(document_id)
        if doc is None or doc.student_id != owner or not doc.is_retrievable():
            return []
        chunks = self._chunks.get(document_id, [])
        return [chunk for chunk in chunks if chunk.student_id == owner]

    async def list_chunk_neighbourhood(
        self,
        student_id: str,
        document_id: UUID,
        *,
        sequence_start: int,
        sequence_end: int,
        chunk_ids: Sequence[UUID] = (),
    ) -> list[DocumentChunk]:
        owner = student_uuid(student_id)
        doc = self._documents.get(document_id)
        if doc is None or doc.student_id != owner or not doc.is_retrievable():
            return []
        wanted = {str(c) for c in chunk_ids}
        return [
            chunk
            for chunk in self._chunks.get(document_id, [])
            if chunk.student_id == owner
            and (
                sequence_start <= chunk.sequence <= sequence_end
                or str(chunk.chunk_id) in wanted
            )
        ]

    # ------------------------------------------------------------- vectors

    async def replace_vectors(
        self,
        student_id: str,
        document_id: UUID,
        vectors: Sequence[tuple[UUID, EmbeddingDescriptor, EmbeddingVector]],
    ) -> None:
        self._vectors[document_id] = {chunk_id: (descriptor, vector) for chunk_id, descriptor, vector in vectors}

    async def get_vectors(
        self, student_id: str, document_id: UUID
    ) -> dict[UUID, tuple[EmbeddingDescriptor, EmbeddingVector]]:
        return dict(self._vectors.get(document_id, {}))

    # -------------------------------------------------------- index build

    async def get_index_build(
        self, student_id: str, document_id: UUID
    ) -> IndexBuildRecord | None:
        return self._builds.get((student_uuid(student_id), document_id))

    async def record_index_build(
        self, student_id: str, document_id: UUID, record: IndexBuildRecord
    ) -> None:
        self._builds[(student_uuid(student_id), document_id)] = record

    # ---------------------------------------------------------- retrieval

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
    ) -> DocumentQueryResult:
        owner = student_uuid(student_id)
        wanted = set(document_ids) if document_ids is not None else None

        visible = [
            doc
            for doc in self._documents.values()
            if doc.student_id == owner
            and doc.is_retrievable()
            and (wanted is None or doc.document_id in wanted)
        ]
        tokens = list(query_tokens)
        hits: list[RetrievedChunk] = []
        used_any_vector = False
        for doc in visible:
            for chunk in self._chunks.get(doc.document_id, []):
                blob = " ".join(part for part in (chunk.text, chunk.fts_text) if part)
                lexical = _lexical_fraction(blob, tokens)
                if lexical <= 0.0 and vector is None:
                    continue  # lexical-only mode: unmatched chunks are invisible
                vector_score: float | None = None
                if vector is not None:
                    stored = self._vectors.get(doc.document_id, {}).get(chunk.chunk_id)
                    if stored is not None:
                        descriptor, stored_vector = stored
                        if (
                            descriptor.backend_id == embedding_backend_id
                            and descriptor.dimension == len(vector)
                        ):
                            vector_score = cosine_similarity(vector, stored_vector)
                            used_any_vector = True
                if lexical <= 0.0 and vector_score is None:
                    continue
                hits.append(
                    RetrievedChunk(
                        chunk=chunk,
                        document_id=doc.document_id,
                        filename=doc.filename,
                        score=fuse_retrieval_scores(lexical, vector_score),
                        lexical_score=lexical,
                        vector_score=vector_score,
                    )
                )
        hits.sort(key=lambda hit: (-hit.score, hit.chunk.sequence))
        return DocumentQueryResult(
            query=query,
            hits=tuple(hits[:limit]),
            vector_used=used_any_vector,
            embedding_backend_id=embedding_backend_id,
            index_version=index_version,
            degraded=not used_any_vector,
        )


def _lexical_fraction(text: str, query_tokens: Sequence[str]) -> float:
    return lexical_score(text, query_tokens)


__all__ = [
    "DocumentRepository",
    "InMemoryDocumentRepository",
    "FTS_FUSION_WEIGHT",
    "VECTOR_FUSION_WEIGHT",
    "cosine_similarity",
    "fuse_retrieval_scores",
]
