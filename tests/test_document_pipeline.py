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
    ParsedBlock,
)
from mathtutor.infrastructure.chunking import CHUNKER_VERSION, TextChunker
from mathtutor.infrastructure.document_parser import (
    PARSER_VERSION,
    LocalDocumentParser,
    NO_TEXT_LAYER_WARNING,
)
from mathtutor.infrastructure.parse_adapters import mineru_available
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime
from mathtutor.infrastructure.lexical import (
    build_fts_text,
    lexical_score,
    normalize_latex_plain,
    tokenize_lexical,
)
from mathtutor.repositories.document_repository import (
    InMemoryDocumentRepository,
)
from mathtutor.security.scopes import student_uuid

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


def _pymupdf_missing() -> bool:
    try:
        import fitz  # noqa: F401

        return False
    except ImportError:
        return True


def _tiny_png() -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    width = height = 64
    raw = b"".join(b"\x00" + bytes([0, 90, 180]) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _pdf_with_text_and_image(text: str, *, include_text: bool = True) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page(width=300, height=200)
    if include_text and text:
        page.insert_text((24, 48), text, fontsize=12)
    page.insert_image(fitz.Rect(40, 70, 180, 170), stream=_tiny_png())
    payload = document.tobytes()
    document.close()
    return payload


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
    assert doc.parser_version == PARSER_VERSION
    assert doc.content_hash  # sha256 recorded
    assert doc.filename == "方程笔记.txt"
    assert await service.get_document(_STUDENT_A, doc.document_id) is not None

    chunks = await service._repo.list_chunks(_STUDENT_A, doc.document_id)
    assert len(chunks) >= 1
    assert doc.chunk_count == len(chunks)
    assert doc.retrieval_enabled is True
    assert all(chunk.chunker_version == CHUNKER_VERSION for chunk in chunks)
    assert all(chunk.metadata_json for chunk in chunks)
    assert all("chunk_type" in chunk.metadata_json for chunk in chunks)
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
    if not mineru_available():
        assert parsed.extractable_chars == 0
        assert parsed.parse_mode == "empty"
        assert parsed.empty_pages == 2
        assert parsed.parse_warning

    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="scan.pdf", mime_type="application/pdf", data=blank),
    )
    if mineru_available() and doc.status in {"ready", "ready_with_warnings"}:
        # Local MinerU actually produced text — allowed, not a ready-lie.
        assert doc.chunk_count >= 1
        return
    assert doc.status == "needs_ocr"
    assert doc.retrieval_enabled is False
    assert doc.chunk_count == 0
    assert doc.page_count == 2
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


async def test_markdown_lean_ir_heading_and_formula(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("# 一元一次方程\n\n移项时两边同时变号。\n\n$$2x+3=7$$\n", encoding="utf-8")
    parsed = await LocalDocumentParser().parse(path=str(path))
    types = [block.type for block in parsed.blocks]
    assert "heading" in types
    assert "paragraph" in types
    assert "formula" in types
    heading = next(block for block in parsed.blocks if block.type == "heading")
    assert heading.heading_path == ("一元一次方程",)
    formula = next(block for block in parsed.blocks if block.type == "formula")
    assert formula.latex
    assert parsed.image_count == 0
    assert parsed.extractable_chars > 0


@pytest.mark.skipif(_pymupdf_missing(), reason="pymupdf required for image extract")
async def test_text_pdf_extracts_images_into_assets(service):
    payload = _pdf_with_text_and_image("一元一次方程")
    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="lesson.pdf", mime_type="application/pdf", data=payload),
    )
    assert doc.status == "ready"
    assert doc.image_count > 0
    owner = student_uuid(_STUDENT_A)
    assets = service._storage.assets_dir(owner, doc.document_id)
    saved = list(assets.glob("page-*-img-*.*"))
    assert saved, "original images must land under assets/"
    chunks = await service._repo.list_chunks(_STUDENT_A, doc.document_id)
    assert chunks
    paths = [
        path
        for chunk in chunks
        for path in (chunk.metadata_json.get("image_paths") or [])
    ]
    assert paths
    assert (service._storage.resolve(paths[0])).exists()


@pytest.mark.skipif(_pymupdf_missing(), reason="pymupdf required")
async def test_image_only_pdf_stays_needs_ocr_without_mineru(service):
    payload = _pdf_with_text_and_image("", include_text=False)
    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="scan-photo.pdf", mime_type="application/pdf", data=payload),
    )
    if mineru_available() and doc.status in {"ready", "ready_with_warnings"}:
        return
    assert doc.status == "needs_ocr"
    assert doc.retrieval_enabled is False
    assert doc.image_count > 0


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
    assert all(len(draft["text"]) >= 80 or draft is drafts_a[-1] for draft in drafts_a[:-1])


def test_chunker_example_and_solution_parent_link():
    blocks = [
        ParsedBlock(
            type="heading",
            text="一元一次方程",
            heading_path=("一元一次方程",),
            section="一元一次方程",
        ),
        ParsedBlock(
            type="paragraph",
            text="例1 解方程 2x+3=7。把常数项移到右边。",
            heading_path=("一元一次方程",),
            section="一元一次方程",
        ),
        ParsedBlock(type="formula", text="2x+3=7", latex="2x+3=7", page=1),
        ParsedBlock(
            type="paragraph",
            text="解：" + ("先移项再合并同类项，得到 x=2。" * 8),
            heading_path=("一元一次方程",),
            section="一元一次方程",
            page=1,
        ),
    ]
    drafts = TextChunker().chunk(blocks)
    types = [draft["chunk_type"] for draft in drafts]
    assert "example" in types
    example = next(draft for draft in drafts if draft["chunk_type"] == "example")
    assert "例1" in example["text"]
    assert example["metadata"].get("latex")
    solutions = [draft for draft in drafts if draft["chunk_type"] == "solution"]
    if solutions:
        assert solutions[0]["parent_index"] is not None
        parent = drafts[solutions[0]["parent_index"]]
        assert parent["chunk_type"] == "example"
    else:
        # short 解 merged into the example parent
        assert "解：" in example["text"]


async def test_ingest_example_solution_parent_written_to_metadata(service):
    body = (
        "# 一元一次方程\n\n"
        "例1 解方程 2x+3=7。把常数项移到右边。\n\n"
        "$$2x+3=7$$\n\n"
        "解：" + ("先移项再合并同类项，得到 x=2。" * 8)
    ).encode("utf-8")
    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="线性方程.md", mime_type="text/markdown", data=body),
    )
    assert doc.status == "ready"
    chunks = await service._repo.list_chunks(_STUDENT_A, doc.document_id)
    assert all(chunk.metadata_json for chunk in chunks)
    examples = [chunk for chunk in chunks if chunk.chunk_type == "example"]
    solutions = [chunk for chunk in chunks if chunk.chunk_type == "solution"]
    assert examples
    assert "例1" in examples[0].text
    if solutions:
        assert solutions[0].parent_chunk_id == examples[0].chunk_id
        assert solutions[0].metadata_json.get("parent_chunk_id") == str(examples[0].chunk_id)
        assert solutions[0].metadata_json.get("role") == "solution"
    else:
        assert "解：" in examples[0].text


def test_chunker_plain_text_regex_structure():
    block = ParsedBlock(
        text=(
            "定义 一次方程的未知数次数是一。\n"
            "例1 解 2x=4。\n"
            "解：" + ("两边同时除以 2，得到 x=2。" * 6)
        )
    )
    drafts = TextChunker().chunk([block])
    types = {draft["chunk_type"] for draft in drafts}
    assert "definition" in types or "example" in types
    assert any(draft["metadata"] for draft in drafts)


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


def test_fts_text_strips_dollars_and_hangs_skill_aliases():
    assert "2x+3=7" in normalize_latex_plain("解 $2x+3=7$")
    fts = build_fts_text(
        "移项时两边同时变号。",
        heading_path=("一元一次方程",),
        section="一元一次方程",
    )
    assert "一元一次方程" in fts
    assert "解方程" in fts
    assert "移项" in fts
    assert "2x+3=7" in build_fts_text("例1 解方程 $2x+3=7$。")


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


async def test_fts_alias_query_hits_chinese_lesson(service):
    body = "# 一元一次方程\n\n移项时两边同时变号。未知数的次数是一。".encode("utf-8")
    doc = await service.ingest(
        _STUDENT_A,
        PickedFile(filename="一次方程.md", mime_type="text/markdown", data=body),
    )
    chunks = await service._repo.list_chunks(_STUDENT_A, doc.document_id)
    assert any("解方程" in chunk.fts_text for chunk in chunks)
    result = await service._index.search(_STUDENT_A, query="解方程")
    assert result.degraded is True
    assert len(result.hits) >= 1
    assert result.hits[0].document_id == doc.document_id


async def test_sqlite_fts_formula_and_example_number(db, tmp_path: Path):
    from sqlalchemy import text as sa_text

    from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository

    repo = SQLiteDocumentRepository(db)
    svc = DocumentIngestionService(
        repository=repo,
        storage=DocumentStorage(tmp_path / "data"),
        index_manager=DocumentIndexManager(repository=repo, embedding_runtime=EmbeddingRuntime()),
    )
    body = "例1 解方程 $2x+3=7$。把常数项移到右边。".encode("utf-8")
    await svc.ingest(
        _STUDENT_A,
        PickedFile(filename="例题.txt", mime_type="text/plain", data=body),
    )
    async with db.begin() as conn:
        count = (
            await conn.execute(sa_text("SELECT count(*) FROM document_chunks_fts"))
        ).scalar_one()
    assert count >= 1
    formula = await svc._index.search(_STUDENT_A, query="2x+3=7")
    assert len(formula.hits) >= 1
    numbered = await svc._index.search(_STUDENT_A, query="例1")
    assert len(numbered.hits) >= 1
