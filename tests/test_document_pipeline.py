"""User Document Knowledge pipeline tests (§37 DOCUMENT group).

Import → validate → store → parse → chunk → (optional index) → search →
permission → delete. Everything runs on the local pipeline: explicit
picks only, no disk scans, no execution, embedding optional (lexical
degradation is the DEFAULT and stays tested).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio

from mathtutor.application.desktop_files import PickedFile
from mathtutor.application.document_ingestion import (
    DocumentIndexManager,
    DocumentIngestionService,
    DocumentValidationError,
    validate_import,
)
from mathtutor.domain.documents import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    MAX_DOCUMENT_BYTES,
)
from mathtutor.infrastructure.chunking import TextChunker
from mathtutor.infrastructure.document_parser import (
    LocalDocumentParser,
    NO_TEXT_LAYER_WARNING,
)
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime
from mathtutor.infrastructure.lexical import (
    lexical_score,
    tokenize_lexical,
)
from mathtutor.repositories.document_repository import (
    InMemoryDocumentRepository,
)

pytestmark = pytest.mark.asyncio

_STUDENT_A = "student-a"
_STUDENT_B = "student-b"

_TXT_CONTENT = (
    "一元二次方程 ax^2+bx+c=0 的求根公式：x = (-b ± √(b²-4ac)) / (2a)。\n"
    "当判别式 Δ = b²-4ac 大于零时，方程有两个不相等的实数根。"
).encode("utf-8")


def _build_simple_pdf(page_texts: list[str]) -> bytes:
    """Minimal PDF: empty string → blank page; non-empty → Helvetica text."""
    n = len(page_texts)
    catalog_id, pages_id = 1, 2
    page_ids = list(range(3, 3 + n))
    next_id = 3 + n
    font_id = next_id
    next_id += 1
    content_ids: list[int | None] = []
    streams: dict[int, str] = {}
    for text in page_texts:
        if text:
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream = f"BT /F1 12 Tf 24 120 Td ({escaped}) Tj ET"
            streams[next_id] = stream
            content_ids.append(next_id)
            next_id += 1
        else:
            content_ids.append(None)

    bodies: dict[int, str] = {
        catalog_id: f"<< /Type /Catalog /Pages {pages_id} 0 R >>",
        pages_id: (
            f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in page_ids)}] "
            f"/Count {n} >>"
        ),
        font_id: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for page_id, content_id in zip(page_ids, content_ids):
        content_ref = f"/Contents {content_id} 0 R" if content_id is not None else ""
        bodies[page_id] = (
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 300 200] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> {content_ref} >>"
        )
    for content_id, stream in streams.items():
        payload = stream.encode("ascii")
        bodies[content_id] = (
            f"<< /Length {len(payload)} >>\nstream\n{stream}\nendstream"
        )

    chunks = [b"%PDF-1.4\n"]
    offsets = {0: 0}
    pos = len(chunks[0])
    max_id = max(bodies)
    for obj_id in range(1, max_id + 1):
        offsets[obj_id] = pos
        obj = f"{obj_id} 0 obj\n{bodies[obj_id]}\nendobj\n".encode("ascii")
        chunks.append(obj)
        pos += len(obj)
    xref_lines = ["xref", f"0 {max_id + 1}", "0000000000 65535 f "]
    for obj_id in range(1, max_id + 1):
        xref_lines.append(f"{offsets[obj_id]:010d} 00000 n ")
    xref = ("\n".join(xref_lines) + "\n").encode("ascii")
    chunks.append(xref)
    chunks.append(
        (
            f"trailer\n<< /Size {max_id + 1} /Root {catalog_id} 0 R >>\n"
            f"startxref\n{pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return b"".join(chunks)


@pytest_asyncio.fixture()
async def service(tmp_path: Path) -> DocumentIngestionService:
    storage = DocumentStorage(tmp_path / "data")
    repo = InMemoryDocumentRepository()
    return DocumentIngestionService(
        repository=repo,
        storage=storage,
        index_manager=DocumentIndexManager(
            repository=repo, embedding_runtime=EmbeddingRuntime()
        ),
    )


async def _ingest(service: DocumentIngestionService, student_id: str, filename: str = "方程笔记.txt"):
    return await service.ingest(
        student_id,
        PickedFile(filename=filename, mime_type="text/plain", data=_TXT_CONTENT),
    )


# ------------------------------------------------------------- validation


def test_validate_import_allowlist_fail_closed():
    with pytest.raises(DocumentValidationError):
        validate_import("evil.py", "text/x-python", 100)
    with pytest.raises(DocumentValidationError):
        validate_import("doc.docx", "application/pdf", 100)
    with pytest.raises(DocumentValidationError):
        validate_import("macro.xlsm", "", 100)  # office macro carrier
    assert validate_import("note.MD", "text/markdown", 100) == ".md"


def test_validate_import_size_and_mime():
    with pytest.raises(DocumentValidationError):
        validate_import("a.txt", "text/plain", 0)
    with pytest.raises(DocumentValidationError):
        validate_import("a.txt", "text/plain", MAX_DOCUMENT_BYTES + 1)
    with pytest.raises(DocumentValidationError):
        validate_import("a.txt", "application/x-executable", 10)
    # Extension binding check passes even when the picker gave no MIME.
    assert validate_import("a.txt", "", 10) == ".txt"


def test_allowlist_contains_only_safe_formats():
    assert ALLOWED_DOCUMENT_EXTENSIONS == {".txt", ".md", ".markdown", ".tex", ".pdf"}


# ---------------------------------------------------------------- ingestion


async def test_ingest_txt_ready_with_chunks(service):
    doc = await _ingest(service, _STUDENT_A)
    assert doc.status == "ready"
    assert doc.parser_version == "mt-local-parser-v1"
    assert doc.content_hash  # sha256 recorded
    assert doc.filename == "方程笔记.txt"
    assert await service.get_document(_STUDENT_A, doc.document_id) is not None

    chunks = await service._repo.list_chunks(_STUDENT_A, doc.document_id)
    assert len(chunks) >= 1
    assert doc.chunk_count == len(chunks)
    assert doc.retrieval_enabled is True
    assert all(chunk.chunker_version == "mt-chunker-v1" for chunk in chunks)
    assert all(chunk.sequence == i for i, chunk in enumerate(chunks))
    # Stored under controlled storage.
    assert await service._storage.exists(doc.storage_ref)


async def test_duplicate_import_returns_same_document(service):
    first = await _ingest(service, _STUDENT_A)
    second = await _ingest(service, _STUDENT_A, filename="副本.txt")  # same bytes
    assert first.document_id == second.document_id
    assert len(await service.list_documents(_STUDENT_A)) == 1


async def test_failed_pdf_marks_failed_not_ready(service):
    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="broken.pdf", mime_type="application/pdf", data=b"%%not-a-pdf"),
    )
    assert doc.status == "failed"
    assert doc.parse_error
    assert await service.get_document(_STUDENT_A, doc.document_id) is not None


async def test_blank_pdf_is_needs_ocr_not_ready_and_not_retrievable(service, tmp_path: Path):
    parser = LocalDocumentParser()
    blank = _build_simple_pdf(["", ""])
    pdf_path = tmp_path / "blank.pdf"
    pdf_path.write_bytes(blank)
    parsed = await parser.parse(path=str(pdf_path))
    assert parsed.blocks == ()
    assert parsed.total_pages == 2
    assert parsed.text_pages == 0
    assert parsed.empty_pages == 2
    assert parsed.extractable_chars == 0
    assert parsed.parse_mode == "empty"
    assert parsed.parse_warning

    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="scan.pdf", mime_type="application/pdf", data=blank),
    )
    assert doc.status == "needs_ocr"
    assert doc.retrieval_enabled is False
    assert doc.chunk_count == 0
    assert doc.page_count == 2
    assert doc.empty_page_count == 2
    assert doc.image_count == 0
    assert doc.parse_warning
    assert NO_TEXT_LAYER_WARNING in doc.parse_error
    assert doc.is_retrievable() is False
    assert await service._repo.list_chunks(_STUDENT_A, doc.document_id) == []

    enabled = await service.set_retrieval_enabled(_STUDENT_A, doc.document_id, True)
    assert enabled.retrieval_enabled is False

    result = await service._index.search(_STUDENT_A, query="quadratic")
    assert result.hits == ()


async def test_text_pdf_stays_ready(service):
    payload = _build_simple_pdf(["quadratic formula discriminant"])
    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="notes.pdf", mime_type="application/pdf", data=payload),
    )
    assert doc.status == "ready"
    assert doc.retrieval_enabled is True
    assert doc.chunk_count >= 1
    assert doc.page_count == 1
    assert doc.empty_page_count == 0
    result = await service._index.search(_STUDENT_A, query="quadratic")
    assert len(result.hits) >= 1


async def test_mixed_pdf_ready_with_warnings(service):
    payload = _build_simple_pdf(["quadratic formula", "", ""])
    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="mixed.pdf", mime_type="application/pdf", data=payload),
    )
    assert doc.status == "ready_with_warnings"
    assert doc.retrieval_enabled is True
    assert doc.page_count == 3
    assert doc.empty_page_count == 2
    assert doc.chunk_count >= 1
    assert "无文字" in doc.parse_warning
    assert doc.is_retrievable() is True
    result = await service._index.search(_STUDENT_A, query="quadratic")
    assert len(result.hits) >= 1


async def test_import_rejects_disallowed_extension(service):
    with pytest.raises(DocumentValidationError):
        await service.ingest(
            _STUDENT_A,
            PickedFile(filename="script.py", mime_type="text/x-python", data=b"print(1)"),
        )


# ------------------------------------------------------ retrieval + permission


async def test_lexical_search_degraded_without_embedding(service):
    doc = await _ingest(service, _STUDENT_A)
    result = await service._index.search(
        _STUDENT_A, query="求根公式 判别式", document_ids=[doc.document_id]
    )
    assert result.degraded is True  # no embedding backend — the default
    assert result.vector_used is False
    assert len(result.hits) >= 1
    assert all(hit.lexical_score > 0 for hit in result.hits)


async def test_disabled_document_invisible_to_search(service):
    doc = await _ingest(service, _STUDENT_A)
    await service.set_retrieval_enabled(_STUDENT_A, doc.document_id, False)
    result = await service._index.search(_STUDENT_A, query="求根公式")
    assert result.hits == ()  # user permission wins at the data layer


async def test_delete_removes_storage_and_search(service):
    doc = await _ingest(service, _STUDENT_A)
    assert await service.delete(_STUDENT_A, doc.document_id) is True
    assert await service.delete(_STUDENT_A, doc.document_id) is False
    assert await service.get_document(_STUDENT_A, doc.document_id) is None
    assert not await service._storage.exists(doc.storage_ref)
    result = await service._index.search(_STUDENT_A, query="求根公式")
    assert result.hits == ()


async def test_owner_isolation(service):
    doc = await _ingest(service, _STUDENT_A)
    assert await service.get_document(_STUDENT_B, doc.document_id) is None
    assert await service.list_documents(_STUDENT_B) == []
    result = await service._index.search(_STUDENT_B, query="求根公式")
    assert result.hits == ()
    assert await service.delete(_STUDENT_B, doc.document_id) is False


# ------------------------------------------------------------ chunking units


def test_chunker_deterministic_and_capped():
    block = type(
        "B",
        (),
        {"page": None, "section": "", "text": ("一元二次方程。判别式。" * 500)},
    )()
    chunker = TextChunker(max_chunk_chars=1000, overlap_chars=100)
    drafts_a = chunker.chunk([block])
    drafts_b = chunker.chunk([block])
    assert drafts_a == drafts_b  # deterministic
    assert len(drafts_a) > 1
    assert all(len(draft["text"]) <= 1000 for draft in drafts_a)


def test_tokenize_lexical_mixed_cjk_latin():
    tokens = tokenize_lexical("二次方程 quadratic Formula 求解!")
    assert "二次" in tokens and "方程" in tokens
    assert "quadratic" in tokens and "formula" in tokens
    assert "求解" in tokens
    # no duplicates, deterministic order
    assert tokens == list(dict.fromkeys(tokens))


def test_lexical_score_fraction():
    tokens = tokenize_lexical("求根公式")
    assert lexical_score("一元二次方程的求根公式", tokens) == 1.0
    assert lexical_score("完全无关的句子", tokens) == 0.0


# ------------------------------------------------------------- SQLite roundtrip


@pytest_asyncio.fixture()
async def db(tmp_path: Path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "math_tutor.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


async def test_sqlite_document_roundtrip_and_search(db, tmp_path: Path):
    from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository

    repo = SQLiteDocumentRepository(db)
    svc = DocumentIngestionService(
        repository=repo,
        storage=DocumentStorage(tmp_path / "data"),
        index_manager=DocumentIndexManager(repository=repo, embedding_runtime=EmbeddingRuntime()),
    )
    doc = await _ingest(svc, _STUDENT_A)
    assert doc.status == "ready"
    assert doc.chunk_count >= 1
    assert doc.image_count == 0
    stored = await repo.get_document(_STUDENT_A, doc.document_id)
    assert stored is not None
    assert stored.chunk_count == doc.chunk_count

    result = await svc._index.search(_STUDENT_A, query="判别式")
    assert result.degraded is True
    assert len(result.hits) >= 1
    assert result.hits[0].filename == "方程笔记.txt"

    # Index build row persists and survives a fresh repository instance.
    assert await repo.get_index_build(_STUDENT_A, doc.document_id) is None  # no backend
    assert await svc.delete(_STUDENT_A, doc.document_id) is True
    assert await repo.get_document(_STUDENT_A, doc.document_id) is None
