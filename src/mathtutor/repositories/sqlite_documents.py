"""SQLite user-document persistence (Phase 5/6 — infrastructure).

Same contract and invariants as repositories/document_repository.py:
owner scope on every statement, retrieval reads see only
``retrieval_enabled AND deleted_at IS NULL AND status in
('ready', 'ready_with_warnings')`` documents (user permission wins over
the Router; needs_ocr / failed never match), chunk TEXT is a fact
while vectors are a derived projection, and the index build row makes
rebuild decisions deterministic.

Retrieval runs metadata-filtered SQL first (owner + visibility), scores
candidates in pure Python (lexical fraction + optional cosine fusion) —
no vector-DB extension, no network. With ``vector=None`` the search is
lexical-only (degraded mode: no embedding backend required).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.domain.documents import (
    DocumentChunk,
    DocumentQueryResult,
    IndexBuildRecord,
    RETRIEVABLE_DOCUMENT_STATUSES,
    RetrievedChunk,
    UserDocument,
)
from mathtutor.domain.embedding import (
    EmbeddingDescriptor,
    EmbeddingVector,
)
from mathtutor.infrastructure.lexical import lexical_score
from mathtutor.infrastructure.schema import (
    document_chunk_vectors,
    document_chunks,
    document_index_builds,
    user_documents,
)
from mathtutor.repositories.document_repository import (
    cosine_similarity,
    fuse_retrieval_scores,
)
from mathtutor.repositories.sqlite_runtime import ensure_student
from mathtutor.security.scopes import student_uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _document_from_row(row: Any) -> UserDocument:
    return UserDocument(
        document_id=UUID(row.document_id),
        student_id=student_uuid(row.student_id),  # stored raw, modeled as UUID
        filename=row.filename,
        mime_type=row.mime_type,
        content_hash=row.content_hash,
        storage_ref=row.storage_ref,
        status=row.status,
        size_bytes=int(row.size_bytes),
        parser_version=row.parser_version or "",
        retrieval_enabled=bool(row.retrieval_enabled),
        parse_error=row.parse_error or "",
        page_count=int(getattr(row, "page_count", 0) or 0),
        chunk_count=int(getattr(row, "chunk_count", 0) or 0),
        image_count=int(getattr(row, "image_count", 0) or 0),
        empty_page_count=int(getattr(row, "empty_page_count", 0) or 0),
        parse_warning=getattr(row, "parse_warning", None) or "",
        created_at=_parse_dt(row.created_at) or datetime.now(timezone.utc),
        deleted_at=_parse_dt(row.deleted_at),
    )


def _chunk_from_row(row: Any) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=UUID(row.chunk_id),
        document_id=UUID(row.document_id),
        student_id=student_uuid(row.student_id),
        sequence=int(row.sequence),
        page=row.page,
        section=row.section or "",
        text=row.text,
        content_hash=row.content_hash,
        metadata_json=row.metadata_json or {},
        chunker_version=row.chunker_version or "",
    )


def _build_from_row(row: Any) -> IndexBuildRecord:
    return IndexBuildRecord(
        student_id=student_uuid(row.student_id),
        document_id=UUID(row.document_id),
        index_version=int(row.index_version),
        embedding_backend_id=row.embedding_backend_id,
        embedding_model_id=row.embedding_model_id,
        embedding_model_version=row.embedding_model_version,
        embedding_dimension=int(row.embedding_dimension),
        chunker_version=row.chunker_version,
        parser_version=row.parser_version,
        built_at=_parse_dt(row.built_at) or datetime.now(timezone.utc),
    )


# -------------------------------------------------------------- documents

async def insert_user_document(
    conn: AsyncConnection, *, student_id: str, doc: UserDocument
) -> UUID:
    await ensure_student(conn, student_id=student_id)
    await conn.execute(
        user_documents.insert().values(
            document_id=str(doc.document_id),
            student_id=student_id,
            filename=doc.filename,
            mime_type=doc.mime_type,
            content_hash=doc.content_hash,
            storage_ref=doc.storage_ref,
            status=doc.status,
            size_bytes=doc.size_bytes,
            parser_version=doc.parser_version,
            retrieval_enabled=1 if doc.retrieval_enabled else 0,
            parse_error=doc.parse_error,
            page_count=doc.page_count,
            chunk_count=doc.chunk_count,
            image_count=doc.image_count,
            empty_page_count=doc.empty_page_count,
            parse_warning=doc.parse_warning,
            created_at=_now(),
            deleted_at=None,
        )
    )
    return doc.document_id


async def select_user_document(
    conn: AsyncConnection,
    *,
    student_id: str,
    document_id: UUID,
    include_deleted: bool = False,
) -> UserDocument | None:
    stmt = select(user_documents).where(
        user_documents.c.document_id == str(document_id),
        user_documents.c.student_id == student_id,
    )
    if not include_deleted:
        stmt = stmt.where(user_documents.c.deleted_at.is_(None))
    row = (await conn.execute(stmt)).first()
    return _document_from_row(row) if row is not None else None


async def find_user_document_by_hash(
    conn: AsyncConnection, *, student_id: str, content_hash: str
) -> UserDocument | None:
    stmt = select(user_documents).where(
        user_documents.c.student_id == student_id,
        user_documents.c.content_hash == content_hash,
        user_documents.c.deleted_at.is_(None),
    )
    row = (await conn.execute(stmt)).first()
    return _document_from_row(row) if row is not None else None


async def list_user_documents(
    conn: AsyncConnection, *, student_id: str, include_deleted: bool = False
) -> list[UserDocument]:
    stmt = select(user_documents).where(
        user_documents.c.student_id == student_id
    )
    if not include_deleted:
        stmt = stmt.where(user_documents.c.deleted_at.is_(None))
    stmt = stmt.order_by(user_documents.c.created_at)
    rows = (await conn.execute(stmt)).all()
    return [_document_from_row(row) for row in rows]


async def update_user_document(
    conn: AsyncConnection, *, student_id: str, doc: UserDocument
) -> UserDocument | None:
    """Owner-scoped update of mutable metadata (status/parser/…)."""
    result = await conn.execute(
        user_documents.update()
        .where(
            user_documents.c.document_id == str(doc.document_id),
            user_documents.c.student_id == student_id,
            user_documents.c.deleted_at.is_(None),
        )
        .values(
            filename=doc.filename,
            mime_type=doc.mime_type,
            status=doc.status,
            parser_version=doc.parser_version,
            retrieval_enabled=1 if doc.retrieval_enabled else 0,
            parse_error=doc.parse_error,
            page_count=doc.page_count,
            chunk_count=doc.chunk_count,
            image_count=doc.image_count,
            empty_page_count=doc.empty_page_count,
            parse_warning=doc.parse_warning,
        )
    )
    if result.rowcount == 0:
        return None
    return await select_user_document(
        conn, student_id=student_id, document_id=doc.document_id
    )


async def set_document_retrieval_enabled(
    conn: AsyncConnection, *, student_id: str, document_id: UUID, enabled: bool
) -> UserDocument | None:
    result = await conn.execute(
        user_documents.update()
        .where(
            user_documents.c.document_id == str(document_id),
            user_documents.c.student_id == student_id,
            user_documents.c.deleted_at.is_(None),
        )
        .values(retrieval_enabled=1 if enabled else 0)
    )
    if result.rowcount == 0:
        return None
    return await select_user_document(
        conn, student_id=student_id, document_id=document_id
    )


async def soft_delete_user_document(
    conn: AsyncConnection, *, student_id: str, document_id: UUID
) -> bool:
    result = await conn.execute(
        user_documents.update()
        .where(
            user_documents.c.document_id == str(document_id),
            user_documents.c.student_id == student_id,
            user_documents.c.deleted_at.is_(None),
        )
        .values(deleted_at=_now())
    )
    return result.rowcount > 0


# ----------------------------------------------------------------- chunks

async def replace_document_chunks(
    conn: AsyncConnection, *, student_id: str, document_id: UUID, chunks: Sequence[DocumentChunk]
) -> None:
    """Delete + insert all chunks for a document (caller owns the txn)."""
    await ensure_student(conn, student_id=student_id)
    await conn.execute(
        document_chunks.delete().where(
            document_chunks.c.document_id == str(document_id),
            document_chunks.c.student_id == student_id,
        )
    )
    for chunk in chunks:
        await conn.execute(
            document_chunks.insert().values(
                chunk_id=str(chunk.chunk_id),
                document_id=str(document_id),
                student_id=student_id,
                sequence=chunk.sequence,
                page=chunk.page,
                section=chunk.section,
                text=chunk.text,
                content_hash=chunk.content_hash,
                metadata_json=chunk.metadata_json,
                chunker_version=chunk.chunker_version,
            )
        )


async def list_document_chunks(
    conn: AsyncConnection, *, student_id: str, document_id: UUID
) -> list[DocumentChunk]:
    stmt = (
        select(document_chunks)
        .where(
            document_chunks.c.document_id == str(document_id),
            document_chunks.c.student_id == student_id,
        )
        .order_by(document_chunks.c.sequence)
    )
    rows = (await conn.execute(stmt)).all()
    return [_chunk_from_row(row) for row in rows]


# ---------------------------------------------------------------- vectors

async def replace_chunk_vectors(
    conn: AsyncConnection,
    *,
    student_id: str,
    document_id: UUID,
    vectors: Sequence[tuple[UUID, EmbeddingDescriptor, EmbeddingVector]],
) -> None:
    await ensure_student(conn, student_id=student_id)
    await conn.execute(
        document_chunk_vectors.delete().where(
            document_chunk_vectors.c.document_id == str(document_id),
            document_chunk_vectors.c.student_id == student_id,
        )
    )
    for chunk_id, descriptor, vector in vectors:
        await conn.execute(
            document_chunk_vectors.insert().values(
                chunk_id=str(chunk_id),
                document_id=str(document_id),
                student_id=student_id,
                embedding_backend_id=descriptor.backend_id,
                embedding_model_id=descriptor.model_id,
                embedding_model_version=descriptor.model_version,
                embedding_dimension=descriptor.dimension,
                vector=json.dumps(list(vector)),
                created_at=_now(),
            )
        )


async def get_chunk_vectors(
    conn: AsyncConnection, *, student_id: str, document_id: UUID
) -> dict[UUID, tuple[EmbeddingDescriptor, EmbeddingVector]]:
    stmt = select(document_chunk_vectors).where(
        document_chunk_vectors.c.document_id == str(document_id),
        document_chunk_vectors.c.student_id == student_id,
    )
    rows = (await conn.execute(stmt)).all()
    result: dict[UUID, tuple[EmbeddingDescriptor, EmbeddingVector]] = {}
    for row in rows:
        descriptor = EmbeddingDescriptor(
            backend_id=row.embedding_backend_id,
            model_id=row.embedding_model_id,
            model_version=row.embedding_model_version,
            dimension=int(row.embedding_dimension),
            normalization="l2",
        )
        vector = tuple(float(value) for value in json.loads(row.vector))
        result[UUID(row.chunk_id)] = (descriptor, vector)
    return result


# ------------------------------------------------------------ index build

async def get_index_build(
    conn: AsyncConnection, *, student_id: str, document_id: UUID
) -> IndexBuildRecord | None:
    stmt = select(document_index_builds).where(
        document_index_builds.c.student_id == student_id,
        document_index_builds.c.document_id == str(document_id),
    )
    row = (await conn.execute(stmt)).first()
    return _build_from_row(row) if row is not None else None


async def record_index_build(
    conn: AsyncConnection, *, student_id: str, document_id: UUID, record: IndexBuildRecord
) -> None:
    """Upsert the CURRENT build row (one per student+document)."""
    await ensure_student(conn, student_id=student_id)
    values = dict(
        student_id=student_id,
        document_id=str(document_id),
        index_version=record.index_version,
        embedding_backend_id=record.embedding_backend_id,
        embedding_model_id=record.embedding_model_id,
        embedding_model_version=record.embedding_model_version,
        embedding_dimension=record.embedding_dimension,
        chunker_version=record.chunker_version,
        parser_version=record.parser_version,
        built_at=_now(),
    )
    await conn.execute(document_index_builds.delete().where(
        document_index_builds.c.student_id == student_id,
        document_index_builds.c.document_id == str(document_id),
    ))
    await conn.execute(document_index_builds.insert().values(**values))


# -------------------------------------------------------------- retrieval

async def search_document_chunks(
    conn: AsyncConnection,
    *,
    student_id: str,
    query: str,
    query_tokens: Sequence[str],
    limit: int = 5,
    document_ids: Sequence[UUID] | None = None,
    vector: EmbeddingVector | None = None,
    embedding_backend_id: str = "",
    index_version: int | None = None,
) -> DocumentQueryResult:
    """Metadata-filtered candidate fetch + python scoring (+ optional vector).

    Visibility filter (owner + user permission) is SQL-level: chunks of
    disabled/soft-deleted/not-ready documents can never be candidates.
    With ``vector=None`` only lexically matching chunks are fetched;
    with a vector every visible chunk is scored and fused (naive scan —
    fine for the local desktop MVP; a future retrieval-infrastructure
    round may add an ANN index behind the same contract).
    """
    tokens = list(query_tokens)

    doc_where = (
        (user_documents.c.student_id == student_id)
        & (user_documents.c.retrieval_enabled == 1)
        & (user_documents.c.deleted_at.is_(None))
        & (user_documents.c.status.in_(tuple(RETRIEVABLE_DOCUMENT_STATUSES)))
    )
    if document_ids is not None:
        doc_where = doc_where & user_documents.c.document_id.in_(
            [str(doc_id) for doc_id in document_ids]
        )
    visible = (
        select(user_documents.c.document_id, user_documents.c.filename)
        .where(doc_where)
        .subquery()
    )

    chunk_stmt = (
        select(document_chunks, visible.c.filename)
        .join(visible, document_chunks.c.document_id == visible.c.document_id)
        .where(document_chunks.c.student_id == student_id)
    )
    if vector is None and tokens:
        # Lexical pre-filter: at least one query token present.
        conditions = []
        for token in tokens:
            conditions.append(document_chunks.c.text.like(f"%{token}%"))
        chunk_stmt = chunk_stmt.where(or_(*conditions))
    rows = (await conn.execute(chunk_stmt)).all()

    # Vectors for every visible document involved (when fusing).
    vectors_by_chunk: dict[UUID, tuple[EmbeddingDescriptor, EmbeddingVector]] = {}
    if vector is not None:
        involved = {str(row.document_id) for row in rows}
        for doc_id in involved:
            stmt = select(document_chunk_vectors).where(
                document_chunk_vectors.c.document_id == doc_id,
                document_chunk_vectors.c.student_id == student_id,
            )
            for vrow in (await conn.execute(stmt)).all():
                descriptor = EmbeddingDescriptor(
                    backend_id=vrow.embedding_backend_id,
                    model_id=vrow.embedding_model_id,
                    model_version=vrow.embedding_model_version,
                    dimension=int(vrow.embedding_dimension),
                    normalization="l2",
                )
                stored_vector = tuple(float(value) for value in json.loads(vrow.vector))
                vectors_by_chunk[UUID(vrow.chunk_id)] = (descriptor, stored_vector)

    hits: list[RetrievedChunk] = []
    for row in rows:
        chunk = _chunk_from_row(row)
        lexical = lexical_score(chunk.text, tokens)
        if lexical <= 0.0 and vector is None:
            continue  # lexical-only mode: unmatched chunks are invisible
        vector_score: float | None = None
        if vector is not None:
            stored = vectors_by_chunk.get(chunk.chunk_id)
            if stored is not None:
                _, stored_vector = stored
                vector_score = cosine_similarity(vector, stored_vector)
        hits.append(
            RetrievedChunk(
                chunk=chunk,
                document_id=chunk.document_id,
                filename=row.filename,
                score=fuse_retrieval_scores(lexical, vector_score),
                lexical_score=lexical,
                vector_score=vector_score,
            )
        )
    hits.sort(key=lambda hit: (-hit.score, hit.chunk.sequence))
    return DocumentQueryResult(
        query=query,
        hits=tuple(hits[:limit]),
        vector_used=vector is not None,
        embedding_backend_id=embedding_backend_id,
        index_version=index_version,
        degraded=vector is None,
    )


__all__ = [
    "find_user_document_by_hash",
    "get_chunk_vectors",
    "get_index_build",
    "insert_user_document",
    "list_document_chunks",
    "list_user_documents",
    "record_index_build",
    "replace_chunk_vectors",
    "replace_document_chunks",
    "search_document_chunks",
    "select_user_document",
    "set_document_retrieval_enabled",
    "soft_delete_user_document",
    "update_user_document",
]
