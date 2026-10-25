"""SQLite-backed knowledge repositories (personal memory + documents).

Implements :class:`MemoryRepository` and :class:`DocumentRepository` over
short UoW transactions (READ → COMPUTE → COMMIT) — the same discipline as
``SQLiteSessionStore``: each method is its own transaction, never a
transaction spanning parsing/embedding/LLM work. Row logic lives in
repositories/sqlite_memory.py and repositories/sqlite_documents.py; these
classes are thin connection-scope adapters.

Owner isolation and user-permission enforcement are inside the row
functions (every statement carries the owner; retrieval reads filter
``retrieval_enabled`` + soft-delete).
"""

from __future__ import annotations

from typing import Any, Sequence
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
from mathtutor.domain.memory import PersonalMemoryEdge, PersonalMemoryNode
from mathtutor.repositories import sqlite_documents as sd
from mathtutor.repositories import sqlite_memory as sm
from mathtutor.repositories.uow import MathTutorUow


class SQLiteMemoryRepository:
    """MemoryRepository over the product database (short transactions)."""

    def __init__(self, engine: Any) -> None:
        self.uow = MathTutorUow(engine)

    async def add_node(self, student_id: str, node: PersonalMemoryNode) -> PersonalMemoryNode:
        async with self.uow.transaction() as conn:
            await sm.insert_personal_memory_node(conn, student_id=student_id, node=node)
        return node

    async def get_node(
        self, student_id: str, memory_id: UUID, *, include_deleted: bool = False
    ) -> PersonalMemoryNode | None:
        async with self.uow.transaction() as conn:
            return await sm.select_personal_memory_node(
                conn,
                student_id=student_id,
                memory_id=memory_id,
                include_deleted=include_deleted,
            )

    async def update_node(
        self, student_id: str, node: PersonalMemoryNode
    ) -> PersonalMemoryNode | None:
        async with self.uow.transaction() as conn:
            return await sm.update_personal_memory_node(conn, student_id=student_id, node=node)

    async def soft_delete_node(self, student_id: str, memory_id: UUID) -> bool:
        async with self.uow.transaction() as conn:
            return await sm.soft_delete_personal_memory_node(
                conn, student_id=student_id, memory_id=memory_id
            )

    async def set_retrieval_enabled(
        self, student_id: str, memory_id: UUID, enabled: bool
    ) -> PersonalMemoryNode | None:
        async with self.uow.transaction() as conn:
            return await sm.set_memory_retrieval_enabled(
                conn, student_id=student_id, memory_id=memory_id, enabled=enabled
            )

    async def list_nodes(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]:
        async with self.uow.transaction() as conn:
            return await sm.list_personal_memory_nodes(
                conn,
                student_id=student_id,
                memory_type=memory_type,
                include_deleted=include_deleted,
                limit=limit,
            )

    async def list_retrievable(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        source_types: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]:
        async with self.uow.transaction() as conn:
            return await sm.list_retrievable_personal_memory_nodes(
                conn,
                student_id=student_id,
                memory_type=memory_type,
                source_types=source_types,
                limit=limit,
            )

    async def add_edge(self, student_id: str, edge: PersonalMemoryEdge) -> PersonalMemoryEdge:
        async with self.uow.transaction() as conn:
            await sm.insert_personal_memory_edge(conn, student_id=student_id, edge=edge)
        return edge

    async def list_edges(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[PersonalMemoryEdge]:
        async with self.uow.transaction() as conn:
            return await sm.list_personal_memory_edges(
                conn, student_id=student_id, include_deleted=include_deleted
            )


class SQLiteDocumentRepository:
    """DocumentRepository over the product database (short transactions)."""

    def __init__(self, engine: Any) -> None:
        self.uow = MathTutorUow(engine)

    async def add_document(self, student_id: str, doc: UserDocument) -> UserDocument:
        async with self.uow.transaction() as conn:
            await sd.insert_user_document(conn, student_id=student_id, doc=doc)
        return doc

    async def get_document(
        self, student_id: str, document_id: UUID, *, include_deleted: bool = False
    ) -> UserDocument | None:
        async with self.uow.transaction() as conn:
            return await sd.select_user_document(
                conn,
                student_id=student_id,
                document_id=document_id,
                include_deleted=include_deleted,
            )

    async def find_by_content_hash(
        self, student_id: str, content_hash: str
    ) -> UserDocument | None:
        async with self.uow.transaction() as conn:
            return await sd.find_user_document_by_hash(
                conn, student_id=student_id, content_hash=content_hash
            )

    async def update_document(
        self, student_id: str, doc: UserDocument
    ) -> UserDocument | None:
        async with self.uow.transaction() as conn:
            return await sd.update_user_document(conn, student_id=student_id, doc=doc)

    async def set_retrieval_enabled(
        self, student_id: str, document_id: UUID, enabled: bool
    ) -> UserDocument | None:
        async with self.uow.transaction() as conn:
            return await sd.set_document_retrieval_enabled(
                conn, student_id=student_id, document_id=document_id, enabled=enabled
            )

    async def soft_delete_document(self, student_id: str, document_id: UUID) -> bool:
        async with self.uow.transaction() as conn:
            return await sd.soft_delete_user_document(
                conn, student_id=student_id, document_id=document_id
            )

    async def list_documents(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[UserDocument]:
        async with self.uow.transaction() as conn:
            return await sd.list_user_documents(
                conn, student_id=student_id, include_deleted=include_deleted
            )

    async def replace_chunks(
        self, student_id: str, document_id: UUID, chunks: Sequence[DocumentChunk]
    ) -> None:
        async with self.uow.transaction() as conn:
            await sd.replace_document_chunks(
                conn, student_id=student_id, document_id=document_id, chunks=chunks
            )

    async def publish_parse_result(
        self, student_id: str, doc: UserDocument, chunks: Sequence[DocumentChunk]
    ) -> UserDocument | None:
        async with self.uow.transaction() as conn:
            current = await sd.select_user_document(
                conn, student_id=student_id, document_id=doc.document_id
            )
            if current is None:
                return None
            await sd.replace_document_chunks(
                conn, student_id=student_id, document_id=doc.document_id, chunks=chunks
            )
            updated = await sd.update_user_document(conn, student_id=student_id, doc=doc)
            if updated is None:
                # Also roll back chunks/FTS/vectors if a concurrent deletion
                # won before the metadata write.
                raise ValueError(f"document not found: {doc.document_id}")
            return updated

    async def list_chunks(
        self, student_id: str, document_id: UUID
    ) -> list[DocumentChunk]:
        async with self.uow.transaction() as conn:
            return await sd.list_document_chunks(
                conn, student_id=student_id, document_id=document_id
            )

    async def list_retrievable_chunks(
        self, student_id: str, document_id: UUID
    ) -> list[DocumentChunk]:
        async with self.uow.transaction() as conn:
            return await sd.list_retrievable_chunks(
                conn, student_id=student_id, document_id=document_id
            )

    async def list_chunk_neighbourhood(
        self,
        student_id: str,
        document_id: UUID,
        *,
        sequence_start: int,
        sequence_end: int,
        chunk_ids: Sequence[UUID] = (),
    ) -> list[DocumentChunk]:
        async with self.uow.transaction() as conn:
            return await sd.list_chunk_neighbourhood(
                conn,
                student_id=student_id,
                document_id=document_id,
                sequence_start=sequence_start,
                sequence_end=sequence_end,
                chunk_ids=chunk_ids,
            )

    async def replace_vectors(
        self,
        student_id: str,
        document_id: UUID,
        vectors: Sequence[tuple[UUID, EmbeddingDescriptor, EmbeddingVector]],
    ) -> None:
        async with self.uow.transaction() as conn:
            await sd.replace_chunk_vectors(
                conn, student_id=student_id, document_id=document_id, vectors=vectors
            )

    async def get_vectors(
        self, student_id: str, document_id: UUID
    ) -> dict[UUID, tuple[EmbeddingDescriptor, EmbeddingVector]]:
        async with self.uow.transaction() as conn:
            return await sd.get_chunk_vectors(
                conn, student_id=student_id, document_id=document_id
            )

    async def get_index_build(
        self, student_id: str, document_id: UUID
    ) -> IndexBuildRecord | None:
        async with self.uow.transaction() as conn:
            return await sd.get_index_build(
                conn, student_id=student_id, document_id=document_id
            )

    async def record_index_build(
        self, student_id: str, document_id: UUID, record: IndexBuildRecord
    ) -> None:
        async with self.uow.transaction() as conn:
            await sd.record_index_build(
                conn, student_id=student_id, document_id=document_id, record=record
            )

    async def publish_index(
        self,
        student_id: str,
        document_id: UUID,
        vectors: Sequence[tuple[UUID, EmbeddingDescriptor, EmbeddingVector]],
        record: IndexBuildRecord,
        *,
        expected_chunk_ids: Sequence[UUID],
    ) -> None:
        async with self.uow.transaction() as conn:
            await sd.publish_chunk_index(
                conn,
                student_id=student_id,
                document_id=document_id,
                vectors=vectors,
                record=record,
                expected_chunk_ids=expected_chunk_ids,
            )

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
        async with self.uow.transaction() as conn:
            return await sd.search_document_chunks(
                conn,
                student_id=student_id,
                query=query,
                query_tokens=query_tokens,
                limit=limit,
                document_ids=document_ids,
                vector=vector,
                embedding_backend_id=embedding_backend_id,
                index_version=index_version,
            )


__all__ = ["SQLiteDocumentRepository", "SQLiteMemoryRepository"]
