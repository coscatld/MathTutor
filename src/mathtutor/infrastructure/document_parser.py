"""Local document parsing — text + lean IR, NEVER execution.

Parsing turns stored bytes into :class:`ParsedTextDocument` blocks.

PDF decision tree:

    1. Digital PDF → PyMuPDF (text layer, embedded images, empty-page
       detection). pypdf is a fallback when PyMuPDF is absent.
    2. No extractable text layer → optional local MinerU.
    3. MinerU missing or failing → parse_mode=empty (ingest marks
       needs_ocr). Never pretend a scan is ready.

OCR/VLM is never added opportunistically and never requires a cloud key.
Docling / LlamaParse adapters exist but are not invoked here.

The parser version is part of the index-lifecycle signature.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from mathtutor.domain.documents import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ParseMode,
    ParsedBlock,
    ParsedElementType,
    ParsedTextDocument,
)
from mathtutor.infrastructure.parse_adapters import mineru_available, try_mineru_parse

PARSER_VERSION = "mt-local-parser-v2"

# Empty-page fraction at or above this value sets parse_warning (mixed PDFs).
EMPTY_PAGE_WARNING_RATIO = 0.3

NO_TEXT_LAYER_WARNING = (
    "未提取到文字层，可能是扫描件。未安装 MinerU 时无法 OCR，无法用于检索。"
)
NO_TEXT_FILE_WARNING = "文件没有可提取的文字，无法用于检索。"

# One extracted text block stays under this many chars so a single
# pathological paragraph cannot dominate chunking (chunking hard-splits
# long sentences anyway; this keeps block/page grain sane).
_MAX_BLOCK_CHARS = 8000
_MIN_IMAGE_EDGE = 40

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_TEX_HEADING = re.compile(
    r"^\\(part|chapter|section|subsection|subsubsection)\*?\{(.+?)\}"
)
_DISPLAY_FORMULA = re.compile(
    r"^(\$\$.*\$\$|\\\[.*\\\]|\\begin\{equation\*?\}.*\\end\{equation\*?\})$",
    re.S,
)


class DocumentParser(Protocol):
    """Parse stored bytes into lean IR blocks.

    ``asset_dir`` is the only allowed side effect: extracted original
    images are written under the MathTutor-controlled assets folder.
    """

    def parser_version(self) -> str: ...

    async def parse(
        self,
        *,
        path: str,
        asset_dir: str | None = None,
        asset_ref_prefix: str = "",
    ) -> ParsedTextDocument: ...


class LocalDocumentParser:
    """PyMuPDF for digital PDFs; UTF-8 decode for text; optional MinerU."""

    def parser_version(self) -> str:
        return PARSER_VERSION

    def supported_extensions(self) -> frozenset[str]:
        return ALLOWED_DOCUMENT_EXTENSIONS

    async def parse(
        self,
        *,
        path: str,
        asset_dir: str | None = None,
        asset_ref_prefix: str = "",
    ) -> ParsedTextDocument:
        file_path = Path(path)
        extension = file_path.suffix.lower()
        if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise ValueError(
                f"unsupported document extension: {extension!r} "
                f"(allowlist: {sorted(ALLOWED_DOCUMENT_EXTENSIONS)})"
            )
        if extension == ".pdf":
            blocks, stats = self._parse_pdf(
                file_path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix
            )
        else:
            blocks, stats = self._parse_text(
                file_path,
                markdown=extension in {".md", ".markdown"},
                tex=extension == ".tex",
            )
        return ParsedTextDocument(blocks=tuple(blocks), **stats)

    # ------------------------------------------------------------- PDF

    def _parse_pdf(
        self,
        file_path: Path,
        *,
        asset_dir: str | None,
        asset_ref_prefix: str,
    ) -> tuple[list[ParsedBlock], dict]:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            return self._parse_pdf_pypdf(file_path)

        blocks, stats = self._parse_pdf_pymupdf(
            fitz, file_path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix
        )
        if stats["extractable_chars"] > 0:
            return blocks, stats

        # Empty text layer: optional local MinerU. Failure stays empty.
        mineru_doc = try_mineru_parse(
            file_path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix
        )
        if mineru_doc is not None and mineru_doc.extractable_chars > 0:
            return list(mineru_doc.blocks), {
                "total_pages": mineru_doc.total_pages,
                "text_pages": mineru_doc.text_pages,
                "empty_pages": mineru_doc.empty_pages,
                "extractable_chars": mineru_doc.extractable_chars,
                "parse_mode": mineru_doc.parse_mode,
                "parse_warning": mineru_doc.parse_warning,
                "image_count": mineru_doc.image_count,
            }
        if stats["parse_warning"] and not mineru_available():
            stats["parse_warning"] = NO_TEXT_LAYER_WARNING
        return blocks, stats

    def _parse_pdf_pymupdf(
        self,
        fitz,
        file_path: Path,
        *,
        asset_dir: str | None,
        asset_ref_prefix: str,
    ) -> tuple[list[ParsedBlock], dict]:
        document = fitz.open(str(file_path))
        try:
            return self._extract_pymupdf_document(
                document,
                asset_dir=asset_dir,
                asset_ref_prefix=asset_ref_prefix,
            )
        finally:
            document.close()

    def _extract_pymupdf_document(
        self,
        document,
        *,
        asset_dir: str | None,
        asset_ref_prefix: str,
    ) -> tuple[list[ParsedBlock], dict]:
        blocks: list[ParsedBlock] = []
        total_pages = document.page_count
        text_pages = 0
        empty_pages = 0
        extractable_chars = 0
        image_count = 0
        heading_path: list[str] = []
        dest = Path(asset_dir) if asset_dir else None
        if dest is not None:
            dest.mkdir(parents=True, exist_ok=True)

        for page_number, page in enumerate(document, start=1):
            page_chars = 0
            table_rects = _table_rects(page)
            for table in _page_tables(page):
                table_text = (table.extract() if hasattr(table, "extract") else None)
                rendered = _render_table(table_text)
                if not rendered:
                    continue
                page_chars += len(rendered)
                blocks.extend(
                    _sized_blocks(
                        type="table",
                        page=page_number,
                        text=part,
                        heading_path=tuple(heading_path),
                    )
                    for part in _split_oversize(rendered)
                )

            page_dict = page.get_text("dict") or {}
            page_median = _page_median_size(page_dict)
            for raw_block in page_dict.get("blocks") or []:
                if raw_block.get("type") != 0:
                    continue
                bbox = raw_block.get("bbox")
                if bbox and _bbox_in_tables(bbox, table_rects):
                    continue
                text, max_size, _block_median = _block_text_and_size(raw_block)
                if not text:
                    continue
                page_chars += len(text)
                kind, latex = _classify_text_block(
                    text, max_size=max_size, median=page_median
                )
                if kind == "heading":
                    heading_path = [text.splitlines()[0][:80]]
                blocks.extend(
                    _sized_blocks(
                        type=kind,
                        page=page_number,
                        text=part,
                        heading_path=tuple(heading_path),
                        latex=latex,
                    )
                    for part in _split_oversize(text)
                )

            saved = _save_page_images(
                document,
                page,
                page_number=page_number,
                dest=dest,
                asset_ref_prefix=asset_ref_prefix,
            )
            image_count += len(saved)
            for figure in saved:
                blocks.append(figure)

            if page_chars:
                text_pages += 1
                extractable_chars += page_chars
            else:
                empty_pages += 1

        stats = _parse_stats(
            total_pages=total_pages,
            text_pages=text_pages,
            empty_pages=empty_pages,
            extractable_chars=extractable_chars,
            empty_warning=NO_TEXT_LAYER_WARNING,
            image_count=image_count,
        )
        return blocks, stats

    def _parse_pdf_pypdf(self, file_path: Path) -> tuple[list[ParsedBlock], dict]:
        """Fallback when PyMuPDF is not installed (text only, no images)."""
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        blocks: list[ParsedBlock] = []
        total_pages = len(reader.pages)
        text_pages = 0
        empty_pages = 0
        extractable_chars = 0
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                empty_pages += 1
                continue
            text_pages += 1
            extractable_chars += len(text)
            blocks.extend(
                _sized_blocks(type="paragraph", page=page_number, text=part)
                for part in _split_oversize(text)
            )
        return blocks, _parse_stats(
            total_pages=total_pages,
            text_pages=text_pages,
            empty_pages=empty_pages,
            extractable_chars=extractable_chars,
            empty_warning=NO_TEXT_LAYER_WARNING,
            image_count=0,
        )

    # ------------------------------------------------------------- text

    def _parse_text(
        self, file_path: Path, *, markdown: bool, tex: bool
    ) -> tuple[list[ParsedBlock], dict]:
        raw = file_path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        blocks: list[ParsedBlock] = []
        heading_path: list[str] = []
        for paragraph in _paragraphs(text):
            heading = None
            level = 1
            if markdown:
                matched = _MARKDOWN_HEADING.match(paragraph)
                if matched:
                    level = len(matched.group(1))
                    heading = matched.group(2).strip()
            elif tex:
                matched = _TEX_HEADING.match(paragraph.strip())
                if matched:
                    level = {
                        "part": 1,
                        "chapter": 1,
                        "section": 1,
                        "subsection": 2,
                        "subsubsection": 3,
                    }.get(matched.group(1), 1)
                    heading = matched.group(2).strip()
            if heading:
                heading_path = heading_path[: level - 1] + [heading]
                blocks.append(
                    ParsedBlock(
                        type="heading",
                        page=None,
                        section=heading,
                        text=paragraph,
                        heading_path=tuple(heading_path),
                    )
                )
                continue
            kind: ParsedElementType = "paragraph"
            latex = None
            if _is_markdown_table(paragraph):
                kind = "table"
            elif _DISPLAY_FORMULA.match(paragraph.strip()) or _inline_formula_only(paragraph):
                kind = "formula"
                latex = paragraph.strip()
            blocks.extend(
                _sized_blocks(
                    type=kind,
                    page=None,
                    text=part,
                    heading_path=tuple(heading_path),
                    latex=latex,
                )
                for part in _split_oversize(paragraph)
            )
        extractable_chars = len(text.strip())
        return blocks, _parse_stats(
            total_pages=0,
            text_pages=0,
            empty_pages=0,
            extractable_chars=extractable_chars,
            empty_warning=NO_TEXT_FILE_WARNING,
            image_count=0,
        )


def _sized_blocks(
    *,
    type: ParsedElementType,
    page: int | None,
    text: str,
    heading_path: tuple[str, ...] = (),
    latex: str | None = None,
) -> ParsedBlock:
    section = heading_path[-1] if heading_path else ""
    return ParsedBlock(
        type=type,
        page=page,
        section=section,
        text=text,
        heading_path=heading_path,
        latex=latex,
    )


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs (never returns empty parts)."""
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _split_oversize(text: str) -> list[str]:
    """Hard-split over-long extracts so one block stays bounded."""
    if len(text) <= _MAX_BLOCK_CHARS:
        return [text]
    return [text[i : i + _MAX_BLOCK_CHARS] for i in range(0, len(text), _MAX_BLOCK_CHARS)]


def _parse_stats(
    *,
    total_pages: int,
    text_pages: int,
    empty_pages: int,
    extractable_chars: int,
    empty_warning: str,
    image_count: int = 0,
) -> dict:
    """Derive parse_mode / parse_warning. Does not change block extraction."""
    parse_mode: ParseMode
    parse_warning = ""
    if extractable_chars <= 0:
        parse_mode = "empty"
        parse_warning = empty_warning
    elif empty_pages > 0 and total_pages > 0:
        parse_mode = "mixed"
        if empty_pages / total_pages >= EMPTY_PAGE_WARNING_RATIO:
            parse_warning = (
                f"共 {total_pages} 页，其中 {empty_pages} 页无文字，可能含扫描页。"
            )
    else:
        parse_mode = "text_layer"
    return {
        "total_pages": total_pages,
        "text_pages": text_pages,
        "empty_pages": empty_pages,
        "extractable_chars": extractable_chars,
        "parse_mode": parse_mode,
        "parse_warning": parse_warning,
        "image_count": image_count,
    }


def _page_median_size(page_dict: dict) -> float:
    sizes: list[float] = []
    for raw_block in page_dict.get("blocks") or []:
        if raw_block.get("type") != 0:
            continue
        for line in raw_block.get("lines") or []:
            for span in line.get("spans") or []:
                try:
                    sizes.append(float(span.get("size") or 0.0))
                except (TypeError, ValueError):
                    continue
    if not sizes:
        return 0.0
    return sorted(sizes)[len(sizes) // 2]


def _block_text_and_size(raw_block: dict) -> tuple[str, float, float]:
    lines: list[str] = []
    sizes: list[float] = []
    for line in raw_block.get("lines") or []:
        pieces: list[str] = []
        for span in line.get("spans") or []:
            piece = (span.get("text") or "").strip()
            if piece:
                pieces.append(piece)
            try:
                sizes.append(float(span.get("size") or 0.0))
            except (TypeError, ValueError):
                pass
        if pieces:
            lines.append(" ".join(pieces))
    text = "\n".join(lines).strip()
    max_size = max(sizes) if sizes else 0.0
    median = sorted(sizes)[len(sizes) // 2] if sizes else 0.0
    return text, max_size, median


def _classify_text_block(
    text: str, *, max_size: float, median: float
) -> tuple[ParsedElementType, str | None]:
    stripped = text.strip()
    if _DISPLAY_FORMULA.match(stripped) or _inline_formula_only(stripped):
        return "formula", stripped
    short = len(stripped) <= 80 and "\n" not in stripped
    larger = median > 0 and max_size >= median * 1.35
    if short and (larger or stripped.endswith(("：", ":"))):
        return "heading", None
    return "paragraph", None


def _inline_formula_only(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped.startswith("$") and stripped.endswith("$") and stripped.count("$") >= 2)


def _is_markdown_table(paragraph: str) -> bool:
    lines = [line for line in paragraph.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return all("|" in line for line in lines)


def _page_tables(page) -> list:
    try:
        finder = page.find_tables()
    except Exception:
        return []
    tables = getattr(finder, "tables", None)
    if tables is None:
        return list(finder) if finder else []
    return list(tables)


def _table_rects(page) -> list[tuple[float, float, float, float]]:
    rects: list[tuple[float, float, float, float]] = []
    for table in _page_tables(page):
        bbox = getattr(table, "bbox", None)
        if bbox and len(bbox) == 4:
            rects.append(tuple(float(v) for v in bbox))
    return rects


def _bbox_in_tables(bbox, table_rects: list[tuple[float, float, float, float]]) -> bool:
    if not table_rects or not bbox or len(bbox) != 4:
        return False
    x0, y0, x1, y1 = (float(v) for v in bbox)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    for tx0, ty0, tx1, ty1 in table_rects:
        if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
            return True
    return False


def _render_table(extracted) -> str:
    if not extracted:
        return ""
    rows: list[str] = []
    for row in extracted:
        cells = [str(cell or "").strip() for cell in row]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _save_page_images(
    document,
    page,
    *,
    page_number: int,
    dest: Path | None,
    asset_ref_prefix: str,
) -> list[ParsedBlock]:
    if dest is None:
        return []
    figures: list[ParsedBlock] = []
    try:
        images = page.get_images(full=True)
    except Exception:
        return []
    for index, image in enumerate(images):
        xref = image[0]
        try:
            extracted = document.extract_image(xref)
        except Exception:
            continue
        width = int(extracted.get("width") or 0)
        height = int(extracted.get("height") or 0)
        payload = extracted.get("image") or b""
        if width < _MIN_IMAGE_EDGE or height < _MIN_IMAGE_EDGE or not payload:
            continue
        ext = (extracted.get("ext") or "png").lstrip(".")
        name = f"page-{page_number}-img-{index}.{ext}"
        (dest / name).write_bytes(payload)
        ref = f"{asset_ref_prefix}/{name}" if asset_ref_prefix else name
        figures.append(
            ParsedBlock(
                type="figure",
                page=page_number,
                text="",
                image_path=ref,
            )
        )
    return figures


__all__ = [
    "DocumentParser",
    "EMPTY_PAGE_WARNING_RATIO",
    "LocalDocumentParser",
    "NO_TEXT_FILE_WARNING",
    "NO_TEXT_LAYER_WARNING",
    "PARSER_VERSION",
]
