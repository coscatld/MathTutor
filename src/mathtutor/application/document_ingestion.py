"""User Document ingestion + index lifecycle (Phase 5/6 application layer).

Pipeline (design §14, strictly local, staged):

    PickedFile (explicit user pick only — never a disk scan)
        → validate (extension allowlist / MIME / size / safe name)
        → content hash → duplicate check (same owner+bytes → same doc)
        → store bytes under MathTutor-controlled storage
        → parse (never executes the document)
        → chunk (deterministic, versioned)
        → optional vector index (embedding backend; NEVER required —
          a document is usable lexically without any embedding model)

The ingestion service owns documents; :class:`DocumentIndexManager` owns
the derived vector projection and its versioned lifecycle. Index rebuilds
re-embed EXISTING chunks — original files are never re-imported.

Generative models never receive whole documents from this pipeline; the
ContextAssembler projects retrieved chunk selections only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol, Sequence
from uuid import UUID, uuid4

from mathtutor.application.desktop_files import PickedFile
from mathtutor.domain.documents import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ALLOWED_DOCUMENT_MIME_TYPES,
    MAX_DOCUMENT_BYTES,
    DocumentChunk,
    DocumentQueryResult,
    IndexBuildRecord,
    ParsedTextDocument,
    RETRIEVABLE_DOCUMENT_STATUSES,
    UserDocument,
)
from mathtutor.domain.embedding import EmbeddingUnavailableError, validate_vector
from mathtutor.infrastructure.chunking import CHUNKER_VERSION, TextChunker
from mathtutor.infrastructure.lexical import build_fts_text
from mathtutor.infrastructure.document_parser import (
    DocumentParser,
    LocalDocumentParser,
    NO_TEXT_FILE_WARNING,
    NO_TEXT_LAYER_WARNING,
)
from mathtutor.infrastructure.document_storage import (
    DocumentStorage,
    sanitize_filename,
)
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime
from mathtutor.infrastructure.lexical import tokenize_lexical
from mathtutor.repositories.document_repository import DocumentRepository
from mathtutor.security.scopes import student_uuid


class DocumentValidationError(ValueError):
    """Import rejected by the security allowlist (fail closed)."""


class DocumentBusyError(ValueError):
    """Reparse refused because the document is still importing/parsing."""


def ingest_outcome_from_parse(
    parsed: ParsedTextDocument,
    chunk_count: int,
    *,
    filename: str,
) -> dict:
    """Map parser stats onto persisted document fields.

    extractable_chars == 0 (or zero chunks) is never ``ready``:
    scanned PDFs become ``needs_ocr``, other empty files become ``failed``.
    Mixed PDFs with a high empty-page ratio become ``ready_with_warnings``.
    ``image_count`` is the number of extracted original images (0 when
    none were saved). Empty text still never becomes ``ready``.
    """
    warning = parsed.parse_warning
    empty = parsed.extractable_chars <= 0 or chunk_count <= 0
    image_count = parsed.image_count
    if empty:
        is_pdf = Path(filename).suffix.lower() == ".pdf"
        status = "needs_ocr" if is_pdf else "failed"
        message = warning or (NO_TEXT_LAYER_WARNING if is_pdf else NO_TEXT_FILE_WARNING)
        return {
            "status": status,
            "retrieval_enabled": False,
            "parse_error": message,
            "page_count": parsed.total_pages,
            "chunk_count": chunk_count,
            "image_count": image_count,
            "empty_page_count": parsed.empty_pages,
            "parse_warning": message,
        }
    status = "ready_with_warnings" if warning and parsed.parse_mode == "mixed" else "ready"
    return {
        "status": status,
        "retrieval_enabled": True,
        "parse_error": "",
        "page_count": parsed.total_pages,
        "chunk_count": chunk_count,
        "image_count": image_count,
        "empty_page_count": parsed.empty_pages,
        "parse_warning": warning,
    }


def validate_import(filename: str, mime_type: str, size_bytes: int) -> str:
    """Return the canonical lower-case extension; raise on any violation.

    Fail-closed order: extension allowlist, then size, then MIME. An empty
    MIME from the picker is tolerated ONLY when the extension is allowed —
    the extension is the binding check.
    """
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise DocumentValidationError(
            f"不支持的文件类型 {extension!r}（允许："
            f"{', '.join(sorted(ALLOWED_DOCUMENT_EXTENSIONS))}）"
        )
    if size_bytes <= 0 or size_bytes > MAX_DOCUMENT_BYTES:
        raise DocumentValidationError(
            f"文件大小 {size_bytes} 超出限制（最大 {MAX_DOCUMENT_BYTES} 字节）"
        )
    if mime_type and mime_type not in ALLOWED_DOCUMENT_MIME_TYPES:
        raise DocumentValidationError(
            f"MIME 类型 {mime_type!r} 不在允许列表中"
        )
    return extension


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _chunk_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _metadata_from_draft(draft: dict, *, parent_chunk_id) -> dict:
    """Always persist a non-empty metadata_json with structure fields."""
    metadata = dict(draft.get("metadata") or {})
    metadata["chunk_type"] = draft.get("chunk_type") or metadata.get("chunk_type") or "paragraph"
    heading = draft.get("heading_path")
    if heading is None:
        heading = metadata.get("heading_path") or []
    metadata["heading_path"] = list(heading)
    metadata["page_start"] = draft.get("page_start", metadata.get("page_start"))
    metadata["page_end"] = draft.get("page_end", metadata.get("page_end"))
    if parent_chunk_id is not None:
        metadata["parent_chunk_id"] = str(parent_chunk_id)
    return metadata


class DocumentIngestionService:
    """Validate → store → parse → chunk → (optional index) for one owner."""

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        storage: DocumentStorage,
        parser: DocumentParser | None = None,
        chunker: TextChunker | None = None,
        index_manager: "DocumentIndexManager | None" = None,
    ) -> None:
        self._repo = repository
        self._storage = storage
        self._parser = parser if parser is not None else LocalDocumentParser()
        self._chunker = chunker if chunker is not None else TextChunker()
        self._index = index_manager

    async def ingest(self, student_id: str, picked: PickedFile) -> UserDocument:
        """Import ONE explicitly picked file. Idempotent per (owner, hash)."""
        validate_import(picked.filename, picked.mime_type, len(picked.data))
        content_hash = _content_hash(picked.data)

        existing = await self._repo.find_by_content_hash(student_id, content_hash)
        if existing is not None:
            return existing  # duplicate import semantics: same owner+bytes → same doc

        safe_name = sanitize_filename(picked.filename)
        document_id = uuid4()
        storage_ref = self._storage.ref_for(student_uuid(student_id), document_id, safe_name)
        await self._storage.store_bytes(storage_ref, picked.data)

        doc = UserDocument(
            document_id=document_id,
            student_id=student_uuid(student_id),
            filename=safe_name,
            mime_type=picked.mime_type,
            content_hash=content_hash,
            storage_ref=storage_ref,
            status="importing",
            size_bytes=len(picked.data),
        )
        doc = await self._repo.add_document(student_id, doc)

        # Parse + chunk. A parse failure does NOT delete the import — the
        # document stays visible as failed (user can delete it). Empty
        # extracts are persisted as needs_ocr/failed, never ready.
        try:
            await self._repo.update_document(
                student_id, doc.model_copy(update={"status": "parsing"})
            )
            parsed = await self._parse_stored(student_id, document_id, storage_ref)
            chunks = self._build_chunks(student_id, document_id, parsed)
            doc = await self._persist_parse_result(
                student_id, doc, parsed, chunks, preserve_retrieval=False
            )
        except Exception as error:  # parse layer failure — mark, never crash the import
            doc = await self._repo.update_document(
                student_id,
                doc.model_copy(
                    update={
                        "status": "failed",
                        "parse_error": str(error)[:500],
                        "retrieval_enabled": False,
                    }
                ),
            )
            return doc

        await self._maybe_build_index(student_id, document_id, doc)
        return doc

    async def reparse(self, student_id: str, document_id: UUID) -> UserDocument:
        """Re-run parse + chunk on stored bytes (same status machine as ingest)."""
        doc = await self._repo.get_document(student_id, document_id)
        if doc is None:
            raise ValueError(f"document not found: {document_id}")
        if doc.status in {"importing", "parsing"}:
            raise DocumentBusyError("文档正在处理中，请稍后再试。")

        doc = await self._repo.update_document(
            student_id, doc.model_copy(update={"status": "parsing"})
        )
        if doc is None:
            raise ValueError(f"document not found: {document_id}")
        try:
            parsed = await self._parse_stored(student_id, document_id, doc.storage_ref)
            chunks = self._build_chunks(student_id, document_id, parsed)
            doc = await self._persist_parse_result(
                student_id, doc, parsed, chunks, preserve_retrieval=True
            )
        except Exception as error:
            doc = await self._repo.update_document(
                student_id,
                doc.model_copy(
                    update={
                        "status": "failed",
                        "parse_error": str(error)[:500],
                        "retrieval_enabled": False,
                    }
                ),
            )
            if doc is None:
                raise ValueError(f"document not found: {document_id}") from error
            return doc

        await self._maybe_build_index(student_id, document_id, doc)
        if doc is None:
            raise ValueError(f"document not found: {document_id}")
        return doc

    async def _persist_parse_result(
        self,
        student_id: str,
        doc: UserDocument,
        parsed: ParsedTextDocument,
        chunks: list[DocumentChunk],
        *,
        preserve_retrieval: bool,
    ) -> UserDocument:
        await self._repo.replace_chunks(student_id, doc.document_id, chunks)
        outcome = ingest_outcome_from_parse(
            parsed, len(chunks), filename=doc.filename
        )
        outcome["parser_version"] = self._parser.parser_version()
        if (
            preserve_retrieval
            and outcome["status"] in RETRIEVABLE_DOCUMENT_STATUSES
        ):
            outcome["retrieval_enabled"] = doc.retrieval_enabled
        updated = await self._repo.update_document(
            student_id, doc.model_copy(update=outcome)
        )
        if updated is None:
            raise ValueError(f"document not found: {doc.document_id}")
        return updated

    async def _maybe_build_index(
        self, student_id: str, document_id: UUID, doc: UserDocument | None
    ) -> None:
        # Vector index is OPTIONAL and best-effort: without an embedding
        # backend the document stays fully usable (lexical retrieval).
        # Zero-text documents are never indexed.
        if self._index is None or doc is None or not doc.can_enable_retrieval():
            return
        try:
            await self._index.build_index(student_id, document_id)
        except (EmbeddingUnavailableError, ValueError):
            pass  # degraded mode — no backend provisioned

    async def _parse_stored(
        self, student_id: str, document_id: UUID, storage_ref: str
    ) -> ParsedTextDocument:
        owner = student_uuid(student_id)
        asset_dir = self._storage.assets_dir(owner, document_id)
        prefix = self._storage.assets_ref_prefix(owner, document_id)
        return await self._parser.parse(
            path=str(self._storage.resolve(storage_ref)),
            asset_dir=str(asset_dir),
            asset_ref_prefix=prefix,
        )

    def _build_chunks(self, student_id: str, document_id: UUID, parsed) -> list[DocumentChunk]:
        drafts = self._chunker.chunk(parsed.blocks)
        chunk_ids = [uuid4() for _ in drafts]
        chunks: list[DocumentChunk] = []
        for index, draft in enumerate(drafts):
            parent_index = draft.get("parent_index")
            parent_id = (
                chunk_ids[parent_index]
                if isinstance(parent_index, int) and 0 <= parent_index < len(chunk_ids)
                else None
            )
            heading = tuple(draft.get("heading_path") or ())
            page_start = draft.get("page_start", draft.get("page"))
            page_end = draft.get("page_end", page_start)
            metadata = _metadata_from_draft(draft, parent_chunk_id=parent_id)
            section = draft.get("section") or (heading[-1] if heading else "")
            body = draft["text"]
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_ids[index],
                    document_id=document_id,
                    student_id=student_uuid(student_id),
                    sequence=index,
                    page=page_start,
                    section=section,
                    text=body,
                    content_hash=_chunk_text_hash(body),
                    chunk_type=str(draft.get("chunk_type") or "paragraph"),
                    heading_path=heading,
                    page_start=page_start,
                    page_end=page_end,
                    parent_chunk_id=parent_id,
                    metadata_json=metadata,
                    chunker_version=CHUNKER_VERSION,
                    fts_text=build_fts_text(
                        body,
                        heading_path=heading,
                        section=section,
                        metadata=metadata,
                    ),
                )
            )
        return chunks

    async def delete(self, student_id: str, document_id: UUID) -> bool:
        """Soft delete + controlled-storage removal (immediate retention)."""
        doc = await self._repo.get_document(student_id, document_id)
        if doc is None:
            return False
        deleted = await self._repo.soft_delete_document(student_id, document_id)
        if deleted:
            await self._storage.remove(doc.storage_ref)  # best effort
        return deleted

    async def set_retrieval_enabled(
        self, student_id: str, document_id: UUID, enabled: bool
    ) -> UserDocument:
        current = await self._repo.get_document(student_id, document_id)
        if current is None:
            raise ValueError(f"document not found: {document_id}")
        if enabled and not current.can_enable_retrieval():
            enabled = False
        doc = await self._repo.set_retrieval_enabled(student_id, document_id, enabled)
        if doc is None:
            raise ValueError(f"document not found: {document_id}")
        return doc

    async def list_documents(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[UserDocument]:
        return await self._repo.list_documents(student_id, include_deleted=include_deleted)

    async def get_document(
        self, student_id: str, document_id: UUID, *, include_deleted: bool = False
    ) -> UserDocument | None:
        return await self._repo.get_document(
            student_id, document_id, include_deleted=include_deleted
        )


class DocumentIndexManager:
    """Versioned lifecycle of the derived vector projection.

    - build decision is signature-based and deterministic: the persisted
      build row must match (embedding descriptor, chunker version, parser
      version); any mismatch → rebuild from EXISTING chunks;
    - rebuild NEVER re-imports or re-parses the original file;
    - with no embedding backend the manager raises
      :class:`EmbeddingUnavailableError` on build and serves lexical-only
      search (degraded) — the product never blocks on embeddings.
    """

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        embedding_runtime: EmbeddingRuntime,
    ) -> None:
        self._repo = repository
        self._runtime = embedding_runtime

    def backend_available(self) -> bool:
        return self._runtime.status().available

    async def is_current(self, student_id: str, document_id: UUID) -> bool:
        status = self._runtime.status()
        if not status.available:
            return False
        doc = await self._repo.get_document(student_id, document_id)
        build = await self._repo.get_index_build(student_id, document_id)
        if doc is None or build is None:
            return False
        return build.matches_signature(
            status.descriptor, CHUNKER_VERSION, doc.parser_version
        )

    async def build_index(
        self, student_id: str, document_id: UUID, *, force: bool = False
    ) -> IndexBuildRecord | None:
        """Embed existing chunks and record the build. Idempotent when
        the current build matches the live signature. Returns None when
        the document has no chunks to index."""
        status = self._runtime.status()
        if not status.available:
            raise EmbeddingUnavailableError(status.reason)
        doc = await self._repo.get_document(student_id, document_id)
        if doc is None:
            raise ValueError(f"document not found: {document_id}")
        chunks = await self._repo.list_chunks(student_id, document_id)
        if not chunks:
            return None

        existing = await self._repo.get_index_build(student_id, document_id)
        descriptor = status.descriptor
        if (
            not force
            and existing is not None
            and existing.matches_signature(descriptor, CHUNKER_VERSION, doc.parser_version)
        ):
            return existing  # idempotent — nothing changed

        vectors = await self._runtime.embed_texts([chunk.text for chunk in chunks])
        # A remote OpenAI-compatible model may discover its dimension on the
        # first response. Re-read the descriptor before validation/persist so
        # a placeholder dimension can never be written into the index.
        refreshed = self._runtime.status()
        if not refreshed.available or refreshed.descriptor is None:
            raise EmbeddingUnavailableError(refreshed.reason)
        descriptor = refreshed.descriptor
        for vector in vectors:
            validate_vector(descriptor, vector)  # fail closed on mismatches
        await self._repo.replace_vectors(
            student_id,
            document_id,
            [
                (chunk.chunk_id, descriptor, vector)
                for chunk, vector in zip(chunks, vectors)
            ],
        )
        record = IndexBuildRecord(
            student_id=student_uuid(student_id),
            document_id=document_id,
            index_version=(existing.index_version + 1) if existing is not None else 1,
            embedding_backend_id=descriptor.backend_id,
            embedding_model_id=descriptor.model_id,
            embedding_model_version=descriptor.model_version,
            embedding_dimension=descriptor.dimension,
            chunker_version=CHUNKER_VERSION,
            parser_version=doc.parser_version,
        )
        await self._repo.record_index_build(student_id, document_id, record)
        return record

    async def search(
        self,
        student_id: str,
        *,
        query: str,
        limit: int = 5,
        document_ids: Sequence[UUID] | None = None,
    ) -> DocumentQueryResult:
        """Lexical + optional vector search over the student's own documents.

        The metadata filter (owner + retrieval_enabled + not deleted +
        retrievable status) is enforced by the repository — user
        permission wins over the Router at the data layer.
        """
        tokens = tokenize_lexical(query)
        vector = None
        backend_id = ""
        index_version: int | None = None
        status = self._runtime.status()
        if status.available:
            try:
                vector = await self._runtime.embed_query(query)
                refreshed = self._runtime.status()
                if not refreshed.available or refreshed.descriptor is None:
                    raise EmbeddingUnavailableError(refreshed.reason)
                validate_vector(refreshed.descriptor, vector)
                backend_id = refreshed.descriptor.backend_id
                if document_ids is not None and len(document_ids) == 1:
                    build = await self._repo.get_index_build(
                        student_id, document_ids[0]
                    )
                    if build is not None:
                        index_version = build.index_version
            except EmbeddingUnavailableError:
                vector = None  # degraded lexical-only
        return await self._repo.search_chunks(
            student_id,
            query=query,
            query_tokens=tokens,
            limit=limit,
            document_ids=document_ids,
            vector=vector,
            embedding_backend_id=backend_id,
            index_version=index_version,
        )


class DocumentSearchable(Protocol):
    """The capability the ContextAssembler needs from documents."""

    async def search(
        self,
        student_id: str,
        *,
        query: str,
        limit: int = 5,
        document_ids: Sequence[UUID] | None = None,
    ) -> DocumentQueryResult: ...


__all__ = [
    "DocumentBusyError",
    "DocumentIndexManager",
    "DocumentIngestionService",
    "DocumentSearchable",
    "DocumentValidationError",
    "ingest_outcome_from_parse",
    "validate_import",
]
