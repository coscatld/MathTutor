"""Phase B acceptance — PDF baseline parsing, page profiling, classification.

D19 Option B (frozen): pypdf is the GUARANTEED baseline parser; PyMuPDF is an
OPTIONAL rich parser that the shipped runtime does not carry. Consequently:

- classification states only what a baseline parser can prove about the TEXT
  LAYER. A page with no extractable text is NO_EXTRACTABLE_TEXT, never
  "scanned" — a parser cannot tell a scan from a blank, figure-only, vector-art
  or undecodable-font page.
- MinerU reachability must NOT depend on PyMuPDF (audit D20).
- recovered text must not be labelled ``text_layer`` (audit D7).

PyMuPDF-specific expectations live in the environment-gated section at the end
and are OPTIONAL. Their skips are NOT evidence of product capability.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import pytest_asyncio

from mathtutor.application.desktop_files import PickedFile
from mathtutor.application.document_ingestion import DocumentIngestionService
from mathtutor.domain.documents import (
    DocumentParseError,
    PdfPageProfile,
    classify_pdf,
)
from mathtutor.infrastructure.chunking import TextChunker
from mathtutor.infrastructure.document_parser import LocalDocumentParser, PARSER_VERSION
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.repositories.document_repository import InMemoryDocumentRepository

pytestmark = pytest.mark.asyncio

_MATH = "Quadratic formula x = (-b + sqrt(b^2 - 4ac)) / 2a"


# --------------------------------------------------------------- fixtures


def _pdf_with_pages(page_texts: list[str]) -> bytes:
    """Build an N-page PDF; an empty string yields a page with no text layer.

    Written in raw PDF syntax so the fixture is identical in every runtime —
    in particular it still works when PyMuPDF is absent, which is the shipped
    configuration under test.
    """
    # Object ids: 1 catalog, 2 pages, then (content, page) per page, then font.
    # The font id must be reserved up front — computing it per page made the
    # first page point at the second page's content stream.
    page_count = len(page_texts)
    font_id = 3 + 2 * page_count
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]

    page_object_ids = [4 + 2 * index for index in range(page_count)]
    kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {page_count} >>".encode())

    for index, text in enumerate(page_texts):
        content_id = 3 + 2 * index
        page_id = content_id + 1
        stream = b""
        if text:
            stream = f"BT /F1 12 Tf 72 700 Td ({_escape(text)}) Tj ET".encode("latin-1")
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + payload + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _cjk_pdf(text: str) -> bytes:
    """One-page PDF with a CJK text layer that pypdf can extract.

    The base-14 fonts carry no CJK glyphs, so this builds a Type0/Identity-H
    font with a ToUnicode CMap — that CMap, not the glyphs, is what extraction
    reads. Round-tripping real Chinese through the PDF path is the point: the
    structural chunker's role markers (例 / 解 / 定义 …) live in the text, so a
    parser that mangled the encoding would silently disable them.
    """
    codes: dict[str, int] = {}
    for character in text:
        codes.setdefault(character, len(codes) + 1)
    hex_string = "".join(f"{codes[c]:04X}" for c in text)
    content = f"BT /F1 12 Tf 72 700 Td <{hex_string}> Tj ET".encode("ascii")

    entries = "".join(
        f"<{codes[c]:04X}> <{ord(c):04X}>\n" for c in sorted(codes, key=lambda k: codes[k])
    )
    cmap = (
        "/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
        "1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n"
        f"{len(codes)} beginbfchar\n{entries}endbfchar\nendcmap\nend\nend"
    ).encode("ascii")

    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        4: b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        5: (
            b"<< /Type /Font /Subtype /Type0 /BaseFont /MT-CJK /Encoding /Identity-H "
            b"/DescendantFonts [6 0 R] /ToUnicode 8 0 R >>"
        ),
        6: (
            b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /MT-CJK "
            b"/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> "
            b"/FontDescriptor 7 0 R /DW 1000 >>"
        ),
        7: (
            b"<< /Type /FontDescriptor /FontName /MT-CJK /Flags 4 /FontBBox [0 0 1000 1000] "
            b"/ItalicAngle 0 /Ascent 800 /Descent -200 /CapHeight 700 /StemV 80 >>"
        ),
        8: b"<< /Length " + str(len(cmap)).encode() + b" >>\nstream\n" + cmap + b"\nendstream",
    }

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for number in range(1, max(objects) + 1):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {max(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for number in range(1, max(objects) + 1):
        out += f"{offsets[number]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {max(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


def _encrypted_pdf() -> bytes:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_pdf_with_pages([_MATH]))))
    writer.encrypt("pw")
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest_asyncio.fixture()
async def service(tmp_path: Path) -> DocumentIngestionService:
    return DocumentIngestionService(
        repository=InMemoryDocumentRepository(),
        storage=DocumentStorage(tmp_path / "data"),
    )


async def _parse(payload: bytes, tmp_path: Path, name: str = "doc.pdf"):
    target = tmp_path / name
    target.write_bytes(payload)
    return await LocalDocumentParser().parse(path=str(target))


# ------------------------------------------- B1 baseline is real and named


async def test_baseline_parser_identity_is_recorded(tmp_path):
    """B1/B10: which parser ran is persisted, not inferred later."""
    doc = await _parse(_pdf_with_pages([_MATH]), tmp_path)
    try:
        import fitz  # noqa: F401

        expected = "pymupdf"
    except ImportError:
        expected = "pypdf"
    assert doc.parser_id == expected
    assert PARSER_VERSION == "mt-local-parser-v4"


async def test_pypdf_baseline_extracts_a_text_layer(tmp_path, monkeypatch):
    """B1: the baseline must produce usable text with PyMuPDF forced absent."""
    import mathtutor.infrastructure.document_parser as parser_module

    monkeypatch.setattr(parser_module, "_pymupdf", lambda: None)
    doc = await _parse(_pdf_with_pages([_MATH]), tmp_path)

    assert doc.parser_id == "pypdf"
    assert doc.extractable_chars > 0
    assert doc.classification == "TEXT_PDF"
    assert any(_MATH.split()[0] in block.text for block in doc.blocks)


# --------------------------------------------------- B2 per-page profiling


async def test_per_page_profile_records_extractable_text_chars(tmp_path):
    doc = await _parse(_pdf_with_pages([_MATH, "", _MATH]), tmp_path)

    assert [page.page_number for page in doc.pages] == [1, 2, 3]
    assert [page.text_layer for page in doc.pages] == [
        "TEXT_LAYER",
        "NO_EXTRACTABLE_TEXT",
        "TEXT_LAYER",
    ]
    assert doc.pages[0].extractable_text_chars > 0
    assert doc.pages[1].extractable_text_chars == 0


async def test_page_profile_does_not_fabricate_measurements(tmp_path, monkeypatch):
    """B2: a baseline parser must not invent image/layout measurements."""
    import mathtutor.infrastructure.document_parser as parser_module

    monkeypatch.setattr(parser_module, "_pymupdf", lambda: None)
    doc = await _parse(_pdf_with_pages([_MATH]), tmp_path)
    assert doc.parser_id == "pypdf"
    page = doc.pages[0]
    # None means "not measured", never "zero images".
    assert page.image_count is None
    assert not hasattr(page, "text_blocks")
    assert not hasattr(page, "image_coverage")


# ------------------------------------------------- B3 classification facts


@pytest.mark.parametrize(
    "page_texts,expected",
    [
        ([_MATH], "TEXT_PDF"),
        (["", ""], "NO_TEXT_LAYER_PDF"),
        ([_MATH, ""], "MIXED_TEXT_LAYER_PDF"),
    ],
)
async def test_classification_from_observable_page_facts(tmp_path, page_texts, expected):
    doc = await _parse(_pdf_with_pages(page_texts), tmp_path)
    assert doc.classification == expected


def test_classifier_never_claims_a_page_is_scanned():
    """The state names must describe the text layer, not guess at its cause."""
    empty = PdfPageProfile(page_number=1)
    assert empty.text_layer == "NO_EXTRACTABLE_TEXT"
    assert empty.has_extractable_text is False

    # A blank page, a figure-only page and a real scan are indistinguishable to
    # a text-layer parser, so they must produce the SAME state.
    assert classify_pdf([empty]) == classify_pdf([PdfPageProfile(page_number=2)]) == "NO_TEXT_LAYER_PDF"

    for value in ("SCAN_PDF", "SCANNED_PAGE", "IMAGE_PAGE"):
        assert value not in classify_pdf([empty])


# ------------------------------------------- B4 encrypted / corrupted split


async def test_encrypted_pdf_is_classified_not_generic_failure(tmp_path):
    with pytest.raises(DocumentParseError) as caught:
        await _parse(_encrypted_pdf(), tmp_path, "locked.pdf")
    assert caught.value.classification == "ENCRYPTED_PDF"


async def test_corrupted_pdf_is_classified_not_generic_failure(tmp_path):
    with pytest.raises(DocumentParseError) as caught:
        await _parse(b"%PDF-1.4\nthis is not a pdf body", tmp_path, "broken.pdf")
    assert caught.value.classification == "CORRUPTED_PDF"


async def test_encrypted_upload_lands_failed_with_classification(service):
    """B4: the distinction must survive into the persisted document."""
    doc = await service.ingest(
        "student-b",
        PickedFile(filename="locked.pdf", mime_type="application/pdf", data=_encrypted_pdf()),
    )
    assert doc.status == "failed"
    assert doc.classification == "ENCRYPTED_PDF"
    assert doc.retrieval_enabled is False
    assert "加密" in doc.parse_error


# ------------------------------------------- B5 no text layer -> needs_ocr


async def test_no_text_layer_pdf_becomes_needs_ocr_not_ready(service):
    doc = await service.ingest(
        "student-b",
        PickedFile(
            filename="scanned.pdf",
            mime_type="application/pdf",
            data=_pdf_with_pages(["", ""]),
        ),
    )
    assert doc.status == "needs_ocr"
    assert doc.retrieval_enabled is False
    assert doc.classification == "NO_TEXT_LAYER_PDF"
    assert doc.is_retrievable() is False


async def test_partial_text_layer_is_retrievable_with_warning(service):
    doc = await service.ingest(
        "student-b",
        PickedFile(
            filename="mixed.pdf",
            mime_type="application/pdf",
            data=_pdf_with_pages([_MATH, "", ""]),
        ),
    )
    assert doc.status == "ready_with_warnings"
    assert doc.classification == "MIXED_TEXT_LAYER_PDF"
    assert doc.parser_id == "pypdf" or doc.parser_id == "pymupdf"
    # The warning states the observation, and offers OCR as a possibility
    # rather than asserting the pages are scans.
    assert "无可提取文字层" in doc.parse_warning
    assert "扫描件" not in doc.parse_warning


# ------------------------------- B6/B7 external recovery is baseline-agnostic


async def test_external_recovery_is_reachable_without_pymupdf(monkeypatch, tmp_path):
    """D20: MinerU must be attempted even when PyMuPDF does not exist.

    The old control flow returned from the pypdf branch before ever reaching
    the recovery step, so installing MinerU could never help on Windows.
    """
    import mathtutor.infrastructure.document_parser as parser_module
    from mathtutor.domain.documents import ParsedBlock, ParsedTextDocument

    calls: list[str] = []

    def _fake_mineru(file_path, *, asset_dir, asset_ref_prefix):
        calls.append(str(file_path))
        return ParsedTextDocument(
            blocks=(ParsedBlock(type="paragraph", page=1, text="recovered text"),),
            total_pages=1,
            text_pages=1,
            extractable_chars=len("recovered text"),
        )

    monkeypatch.setattr(parser_module, "try_mineru_parse", _fake_mineru)

    doc = await _parse(_pdf_with_pages(["", ""]), tmp_path)

    assert calls, "the optional recovery adapter was never offered the file"
    assert doc.extractable_chars > 0


async def test_recovered_text_is_labelled_as_external(monkeypatch, tmp_path):
    """D7: text that did not come from the text layer must not claim it did."""
    import mathtutor.infrastructure.document_parser as parser_module
    from mathtutor.domain.documents import ParsedBlock, ParsedTextDocument

    monkeypatch.setattr(
        parser_module,
        "try_mineru_parse",
        lambda *a, **k: ParsedTextDocument(
            blocks=(ParsedBlock(type="paragraph", page=1, text="recovered"),),
            total_pages=1,
            text_pages=1,
            extractable_chars=9,
        ),
    )

    doc = await _parse(_pdf_with_pages([""]), tmp_path)

    assert doc.parse_mode == "recovered_external"
    assert doc.parser_id == "mineru"
    assert doc.parse_mode != "text_layer"


async def test_recovery_failure_stays_an_honest_needs_ocr(monkeypatch, tmp_path):
    """An unavailable adapter must not be reported as success."""
    import mathtutor.infrastructure.document_parser as parser_module

    monkeypatch.setattr(parser_module, "try_mineru_parse", lambda *a, **k: None)

    doc = await _parse(_pdf_with_pages([""]), tmp_path)

    assert doc.extractable_chars == 0
    assert doc.parse_mode == "empty"
    assert doc.classification == "NO_TEXT_LAYER_PDF"


# -------------------------------- B8/B9 pypdf text still reaches the chunker


async def test_baseline_text_flows_into_the_existing_chunker(tmp_path):
    """B8: no parallel chunking path is introduced for the baseline parser."""
    body = "例1 求解方程 x + 1 = 5。\n\n解：移项得 x = 4。"
    doc = await _parse(_cjk_pdf(body), tmp_path)

    drafts = TextChunker().chunk(doc.blocks)

    assert drafts
    assert all(draft["chunk_type"] != "" for draft in drafts)
    assert any(draft["chunk_type"] == "example" for draft in drafts)


async def test_chinese_math_role_detection_survives_baseline_parsing(tmp_path):
    """B9: text-semantic structure is independent of PDF layout structure.

    The baseline parser cannot emit heading/table/figure blocks, but the
    Chinese role markers live in the text itself, so they still chunk. This is
    the one structural capability PDFs keep under the pypdf baseline.
    """
    body = "定义1 一元二次方程的一般形式。\n\n解：移项得 x = 2。"
    doc = await _parse(_cjk_pdf(body), tmp_path)

    # The parser must not have mangled the text on the way through.
    assert "定义" in doc.full_text()
    assert not any(block.type in {"heading", "table", "figure"} for block in doc.blocks)

    types = {draft["chunk_type"] for draft in TextChunker().chunk(doc.blocks)}
    assert types & {"definition", "solution"}, types


# ------------------------------------------- B10 contract matches manifest


def test_declared_dependencies_match_the_shipped_runtime():
    """D19: the dependency declaration must not claim what the release omits."""
    import tomllib
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    core = " ".join(project["dependencies"])

    assert "pypdf" in core, "pypdf is the guaranteed baseline and must be core"
    assert "pymupdf" not in core, "PyMuPDF is optional; core must not claim it"
    assert "sentence-transformers" not in core
    assert "modelscope" not in core
    assert "pymupdf" in " ".join(project["optional-dependencies"]["pdf-rich"])
    assert "sentence-transformers" in " ".join(project["optional-dependencies"]["embedding"])

    import json

    allowlist = json.loads(
        (root / "desktop" / "package_allowlist.json").read_text(encoding="utf-8")
    )
    runtime = allowlist["python_runtime"]
    assert "pypdf" in runtime["required_import_roots"]
    assert "pymupdf" not in runtime["required_import_roots"]
    for package in ("sentence_transformers", "torch", "modelscope"):
        assert any(entry.startswith(package) for entry in runtime["forbidden_feature_packages"])


# --------------------------------------------------------------------------
# OPTIONAL: rich-parser expectations. Environment-gated — a skip here is NOT
# evidence that the shipped product supports these capabilities.
# --------------------------------------------------------------------------

requires_pymupdf = pytest.mark.skipif(
    not pytest.importorskip("importlib").util.find_spec("fitz"),
    reason="PyMuPDF is an OPTIONAL rich parser and is absent from the shipped runtime",
)


@requires_pymupdf
async def test_optional_rich_parser_emits_heading_blocks(tmp_path):
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "一元二次方程", fontsize=24, fontname="china-s")
    body = "正文用于解释一元二次方程的基本解法。" * 4
    assert page.insert_textbox(
        fitz.Rect(72, 140, 520, 300), body, fontsize=10, fontname="china-s"
    ) >= 0
    payload = document.tobytes()
    document.close()

    doc = await _parse(payload, tmp_path)

    assert doc.parser_id == "pymupdf"
    assert any(block.type == "heading" for block in doc.blocks)
    heading = next(block for block in doc.blocks if block.type == "heading")
    assert heading.text == "一元二次方程"
    assert body in doc.full_text().replace("\n", "")
    assert all(block.heading_path == (heading.text,) for block in doc.blocks)


@requires_pymupdf
@pytest.mark.parametrize(
    "heading,heading_size,body,body_size,expected_heading",
    [
        ("函数", 24, "正文解释函数性质。" * 6, 10, True),
        ("一元二次方程的根与系数之间的关系", 18, "理解根与系数的关系需要结合具体例题。" * 4, 12, True),
        ("配方法", 16, "通过配方求解方程。" * 3, 11, True),
        ("同字号短句", 12, "正文和短句采用相同字号。" * 4, 12, False),
        ("略大字号短句", 13, "不足以形成明确字号层级。" * 4, 12, False),
        ("图注", 8, "这段正文使用普通字号。" * 5, 12, False),
        # A title-dominated sparse page has no reliable body-font baseline.
        ("一段占据页面大部分文字的较长短句", 24, "短文", 10, False),
    ],
)
async def test_rich_heading_uses_text_weighted_font_evidence(
    tmp_path, heading, heading_size, body, body_size, expected_heading
):
    import fitz

    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), heading, fontsize=heading_size, fontname="china-s")
        assert page.insert_textbox(
            fitz.Rect(72, 140, 520, 450), body, fontsize=body_size, fontname="china-s"
        ) >= 0
        payload = document.tobytes()

    doc = await _parse(payload, tmp_path)
    assert heading in doc.full_text()
    assert body in doc.full_text().replace("\n", "")
    assert [block.text for block in doc.blocks if block.type == "heading"] == (
        [heading] if expected_heading else []
    )
    assert all(block.type == "paragraph" for block in doc.blocks if block.text != heading)


@requires_pymupdf
async def test_rich_many_short_headings_do_not_outvote_long_body(tmp_path):
    import fitz

    headings = ["函数定义", "基本性质", "应用方法"]
    body = "正文需要结合实际例题说明函数的基本性质。" * 5
    with fitz.open() as document:
        page = document.new_page()
        for index, heading in enumerate(headings):
            page.insert_text((72, 72 + index * 70), heading, fontsize=24, fontname="china-s")
        assert page.insert_textbox(
            fitz.Rect(72, 300, 520, 500), body, fontsize=10, fontname="china-s"
        ) >= 0
        payload = document.tobytes()

    doc = await _parse(payload, tmp_path)
    assert [block.text for block in doc.blocks if block.type == "heading"] == headings
    assert body in doc.full_text().replace("\n", "")
    assert doc.blocks[-1].type == "paragraph"
    assert doc.blocks[-1].heading_path == (headings[-1],)
    drafts = TextChunker().chunk(doc.blocks)
    assert any(draft["heading_path"] == [headings[-1]] for draft in drafts)


@requires_pymupdf
async def test_rich_large_initial_does_not_turn_body_into_heading(tmp_path):
    import fitz

    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "A", fontsize=24)
        page.insert_text((90, 72), " short paragraph with a large initial.", fontsize=10)
        page.insert_text((72, 140), "Ordinary body text provides the normal page font.", fontsize=10)
        payload = document.tobytes()

    doc = await _parse(payload, tmp_path)
    assert "A short paragraph with a large initial." in doc.full_text()
    assert all(block.type == "paragraph" for block in doc.blocks)
    assert all(block.heading_path == () for block in doc.blocks)


@requires_pymupdf
async def test_optional_rich_parser_measures_images(tmp_path):
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), _MATH, fontsize=12)
    document.close()

    doc = await _parse(_pdf_with_pages([_MATH]), tmp_path)

    assert doc.pages[0].image_count is not None
