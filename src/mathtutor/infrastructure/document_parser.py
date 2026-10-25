"""Local document parsing — text + lean IR, NEVER execution.

Parsing turns stored bytes into :class:`ParsedTextDocument` blocks.

PDF decision tree:

    1. BASELINE parse with the best available local parser:

           PyMuPDF   optional rich parser (headings, tables, images)
           pypdf     guaranteed baseline — the shipped runtime has only this
                     (docs/CURRENT_STATE_RAG_AUDIT.md §6.1)

       Both raise :class:`DocumentParseError` for encrypted / corrupted
       files, so the outcome is classified rather than generic.
    2. If the baseline extracted no usable text, attempt the OPTIONAL
       external recovery adapter (MinerU). This step does NOT depend on
       step 1's parser choice — a pypdf baseline can still recover.
    3. Nothing available → parse_mode=empty; ingest marks needs_ocr.
       Never pretend a page with no text layer is ready.

Per page we record only what a parser can prove: how many characters its
text layer yielded. A page with none is ``NO_EXTRACTABLE_TEXT``, which is
NOT the same claim as "this page is a scan" — see
:data:`mathtutor.domain.documents.PageTextLayer`.

OCR/VLM is never added opportunistically and never requires a cloud key.
Docling / LlamaParse adapters exist but are not invoked here.

The parser version is part of the index-lifecycle signature.
"""

from __future__ import annotations

import contextvars
import math
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from mathtutor.domain.documents import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    DocumentParseError,
    ParseMode,
    ParsedBlock,
    ParsedElementType,
    ParsedTextDocument,
    PdfPageProfile,
    classify_pdf,
)
from mathtutor.infrastructure.parse_adapters import try_mineru_parse
from mathtutor.infrastructure.document_workers import DocumentWorkControl, DocumentWorkerPool

PARSER_VERSION = "mt-local-parser-v5"


@dataclass(frozen=True)
class DocumentParseLimits:
    """Budgets for extracted output; not an operating-system memory sandbox."""

    max_pages: int = 500
    max_text_chars: int = 2_000_000
    max_blocks: int = 20_000
    max_assets: int = 256
    max_asset_bytes: int = 32 * 1024 * 1024
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        for name in ("max_pages", "max_text_chars", "max_blocks", "max_assets", "max_asset_bytes"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")


@dataclass
class _ParseBudget:
    limits: DocumentParseLimits
    control: DocumentWorkControl
    text_chars: int = 0
    asset_count: int = 0
    asset_bytes: int = 0

    def check(self) -> None:
        self.control.check()

    def pages(self, count: int) -> None:
        self.check()
        if count > self.limits.max_pages:
            raise DocumentParseError("PARSE_PAGE_LIMIT", "PDF 页数超过解析限制。")

    def text(self, count: int) -> None:
        self.check()
        self.text_chars += count
        if self.text_chars > self.limits.max_text_chars:
            raise DocumentParseError("PARSE_TEXT_LIMIT", "文档提取文字超过解析限制。")

    def blocks(self, count: int) -> None:
        self.check()
        if count > self.limits.max_blocks:
            raise DocumentParseError("PARSE_BLOCK_LIMIT", "文档内容块数量超过解析限制。")

    def asset(self, size: int) -> None:
        self.check()
        self.asset_count += 1
        self.asset_bytes += size
        if self.asset_count > self.limits.max_assets or self.asset_bytes > self.limits.max_asset_bytes:
            raise DocumentParseError("PARSE_ASSET_LIMIT", "文档图片数量或总大小超过解析限制。")


_ACTIVE_BUDGET: contextvars.ContextVar[_ParseBudget] = contextvars.ContextVar("document_parse_budget")
# PyMuPDF's native runtime does not support concurrent multithreaded access.
# Keep optional rich parsing serial even across separate parser instances.
_PYMUPDF_LOCK = threading.Lock()

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


def _pymupdf():
    """The optional rich parser, or ``None`` when it is not installed.

    A named seam rather than an inline ``import fitz``: the baseline choice is
    the single most consequential branch in PDF handling, and tests need to
    exercise the degraded configuration deterministically on a machine that
    happens to have PyMuPDF.
    """
    try:
        import fitz  # PyMuPDF — optional rich parser
    except ImportError:
        return None
    return fitz


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
    """Bounded, owned thread parsing with cooperative cancellation/deadlines.

    Library calls can temporarily allocate more than the output budgets and
    cannot be forcibly interrupted. Shutdown joins them before releasing files.
    """

    def __init__(
        self,
        *,
        limits: DocumentParseLimits | None = None,
        workers: DocumentWorkerPool | None = None,
    ) -> None:
        self.limits = limits or DocumentParseLimits()
        self._workers = workers or DocumentWorkerPool()
        self._owns_workers = workers is None

    async def aclose(self) -> None:
        if self._owns_workers:
            await self._workers.aclose()

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
        # Never expose files from an incomplete/cancelled parse. Ingestion
        # adds a second staging boundary around parse + chunk publication.
        destination = Path(asset_dir) if asset_dir else None
        stage = None
        if destination is not None:
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".parse-", dir=destination.parent))
        try:
            parsed = await self._workers.run(
                lambda control: self._parse_sync(
                    path=path,
                    asset_dir=str(stage) if stage is not None else None,
                    asset_ref_prefix=asset_ref_prefix,
                    control=control,
                ),
                timeout_seconds=self.limits.timeout_seconds,
            )
            if stage is not None and destination is not None:
                # Existing assets belong to the previous successful result.
                # Move them aside only once the entire new result is valid.
                old = destination.with_name(destination.name + ".old-" + stage.name)
                if destination.exists():
                    destination.replace(old)
                try:
                    stage.replace(destination)
                except BaseException:
                    if old.exists():
                        old.replace(destination)
                    raise
                finally:
                    shutil.rmtree(old, ignore_errors=True)
            return parsed
        finally:
            if stage is not None:
                shutil.rmtree(stage, ignore_errors=True)

    def _parse_sync(
        self,
        *,
        path: str,
        asset_dir: str | None,
        asset_ref_prefix: str,
        control: DocumentWorkControl,
    ) -> ParsedTextDocument:
        token = _ACTIVE_BUDGET.set(_ParseBudget(self.limits, control))
        try:
            return self._parse_file(path=path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix)
        finally:
            _ACTIVE_BUDGET.reset(token)

    def _parse_file(
        self, *, path: str, asset_dir: str | None, asset_ref_prefix: str
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
        _ACTIVE_BUDGET.get().blocks(len(blocks))
        if asset_dir is not None:
            # Validate optional adapter output as well as the baseline's writes.
            limits = self.limits
            count = size = 0
            for asset in Path(asset_dir).rglob("*"):
                _ACTIVE_BUDGET.get().check()
                if not asset.is_file():
                    continue
                count += 1
                size += asset.stat().st_size
                if count > limits.max_assets or size > limits.max_asset_bytes:
                    raise DocumentParseError("PARSE_ASSET_LIMIT", "文档图片数量或总大小超过解析限制。")
        return ParsedTextDocument(blocks=tuple(blocks), **stats)

    # ------------------------------------------------------------- PDF

    def _parse_pdf(
        self,
        file_path: Path,
        *,
        asset_dir: str | None,
        asset_ref_prefix: str,
    ) -> tuple[list[ParsedBlock], dict]:
        """Baseline parse, then optional external recovery.

        The baseline is pypdf whenever PyMuPDF is absent — which is the shipped
        configuration (docs/CURRENT_STATE_RAG_AUDIT.md §6.1). Recovery is
        attempted for ANY baseline that extracted no usable text, so MinerU
        reachability does not depend on PyMuPDF being installed.
        """
        blocks, stats = self._parse_pdf_baseline(
            file_path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix
        )
        if stats["extractable_chars"] > 0:
            return blocks, stats

        # No usable text from the document's own text layer. The optional
        # external adapter is the only remaining source — and it is allowed to
        # be absent, in which case this stays an honest "no text layer".
        recovered = try_mineru_parse(
            file_path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix
        )
        if recovered is not None and recovered.extractable_chars > 0:
            budget = _ACTIVE_BUDGET.get()
            budget.pages(recovered.total_pages)
            budget.text(max(recovered.extractable_chars, sum(len(block.text) for block in recovered.blocks)))
            budget.blocks(len(recovered.blocks))
            return list(recovered.blocks), {
                "total_pages": recovered.total_pages,
                "text_pages": recovered.text_pages,
                "empty_pages": recovered.empty_pages,
                "extractable_chars": recovered.extractable_chars,
                # Never "text_layer": this text did not come from the PDF's own
                # layer, and saying otherwise would misreport the source.
                "parse_mode": "recovered_external",
                "parse_warning": recovered.parse_warning,
                "image_count": recovered.image_count,
                "pages": (),
                "classification": "NO_TEXT_LAYER_PDF",
                "parser_id": "mineru",
            }
        stats["parse_warning"] = NO_TEXT_LAYER_WARNING
        return blocks, stats

    def _parse_pdf_baseline(
        self,
        file_path: Path,
        *,
        asset_dir: str | None,
        asset_ref_prefix: str,
    ) -> tuple[list[ParsedBlock], dict]:
        """Best available local parser: PyMuPDF when present, else pypdf."""
        fitz = _pymupdf()
        if fitz is None:
            return self._parse_pdf_pypdf(file_path)
        budget = _ACTIVE_BUDGET.get()
        while not _PYMUPDF_LOCK.acquire(timeout=0.05):
            budget.check()
        try:
            budget.check()
            return self._parse_pdf_pymupdf(
                fitz, file_path, asset_dir=asset_dir, asset_ref_prefix=asset_ref_prefix
            )
        finally:
            _PYMUPDF_LOCK.release()

    def _parse_pdf_pymupdf(
        self,
        fitz,
        file_path: Path,
        *,
        asset_dir: str | None,
        asset_ref_prefix: str,
    ) -> tuple[list[ParsedBlock], dict]:
        """Optional rich parser. Only reachable when PyMuPDF is installed."""
        try:
            document = fitz.open(str(file_path))
        except Exception as error:
            raise DocumentParseError("CORRUPTED_PDF", f"PDF 结构无法读取：{error}") from error
        try:
            if getattr(document, "needs_pass", False):
                raise DocumentParseError(
                    "ENCRYPTED_PDF",
                    "PDF 已加密，需要密码才能解析；当前版本不支持加密文档。",
                )
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
        pages: list[PdfPageProfile] = []
        total_pages = document.page_count
        budget = _ACTIVE_BUDGET.get()
        budget.pages(total_pages)
        text_pages = 0
        empty_pages = 0
        extractable_chars = 0
        image_count = 0
        heading_path: list[str] = []
        dest = Path(asset_dir) if asset_dir else None
        if dest is not None:
            dest.mkdir(parents=True, exist_ok=True)

        for page_number, page in enumerate(document, start=1):
            budget.check()
            page_chars = 0
            table_rects = _table_rects(page)
            for table in _page_tables(page):
                table_text = (table.extract() if hasattr(table, "extract") else None)
                rendered = _render_table(table_text)
                if not rendered:
                    continue
                budget.text(len(rendered))
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
                budget.blocks(len(blocks))

            page_dict = page.get_text("dict") or {}
            page_median = _page_median_size(page_dict)
            for raw_block in page_dict.get("blocks") or []:
                if raw_block.get("type") != 0:
                    continue
                bbox = raw_block.get("bbox")
                if bbox and _bbox_in_tables(bbox, table_rects):
                    continue
                text, _max_size, block_median = _block_text_and_size(raw_block)
                if not text:
                    continue
                budget.text(len(text))
                page_chars += len(text)
                kind, latex = _classify_text_block(
                    text, font_size=block_median, median=page_median
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
                budget.blocks(len(blocks))

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
            budget.blocks(len(blocks))

            if page_chars:
                text_pages += 1
                extractable_chars += page_chars
            else:
                empty_pages += 1
            pages.append(
                PdfPageProfile(
                    page_number=page_number,
                    extractable_text_chars=page_chars,
                    text_layer="TEXT_LAYER" if page_chars else "NO_EXTRACTABLE_TEXT",
                    # PyMuPDF can actually measure this; pypdf cannot. Kept as a
                    # measured value rather than inferred from the text layer.
                    image_count=len(saved),
                )
            )

        stats = _parse_stats(
            total_pages=total_pages,
            text_pages=text_pages,
            empty_pages=empty_pages,
            extractable_chars=extractable_chars,
            empty_warning=NO_TEXT_LAYER_WARNING,
            image_count=image_count,
            pages=pages,
            parser_id="pymupdf",
        )
        return blocks, stats

    def _parse_pdf_pypdf(self, file_path: Path) -> tuple[list[ParsedBlock], dict]:
        """The guaranteed PDF baseline: text-layer extraction only.

        pypdf cannot report tables, images, fonts or layout, so nothing here
        invents them. Raises :class:`DocumentParseError` when the file is
        encrypted or structurally unreadable, so ingestion can record a real
        classification instead of a generic failure.
        """
        from pypdf import PdfReader
        from pypdf.errors import FileNotDecryptedError, PdfReadError, PyPdfError

        try:
            reader = PdfReader(str(file_path))
        except PyPdfError as error:
            raise DocumentParseError("CORRUPTED_PDF", f"PDF 结构无法读取：{error}") from error
        except Exception as error:
            raise DocumentParseError("CORRUPTED_PDF", f"PDF 结构无法读取：{error}") from error

        if reader.is_encrypted:
            raise DocumentParseError(
                "ENCRYPTED_PDF",
                "PDF 已加密，需要密码才能解析；当前版本不支持加密文档。",
            )

        blocks: list[ParsedBlock] = []
        pages: list[PdfPageProfile] = []
        text_pages = 0
        empty_pages = 0
        extractable_chars = 0
        budget = _ACTIVE_BUDGET.get()
        try:
            total_pages = len(reader.pages)
            budget.pages(total_pages)
            for page_number, page in enumerate(reader.pages, start=1):
                budget.check()
                text = (page.extract_text() or "").strip()
                budget.text(len(text))
                if not text:
                    empty_pages += 1
                    pages.append(PdfPageProfile(page_number=page_number))
                    continue
                text_pages += 1
                extractable_chars += len(text)
                pages.append(
                    PdfPageProfile(
                        page_number=page_number,
                        extractable_text_chars=len(text),
                        text_layer="TEXT_LAYER",
                    )
                )
                blocks.extend(
                    _sized_blocks(type="paragraph", page=page_number, text=part)
                    for part in _split_oversize(text)
                )
                budget.blocks(len(blocks))
        except FileNotDecryptedError as error:
            raise DocumentParseError(
                "ENCRYPTED_PDF",
                "PDF 已加密，需要密码才能解析；当前版本不支持加密文档。",
            ) from error
        except PyPdfError as error:
            raise DocumentParseError("CORRUPTED_PDF", f"PDF 页面无法读取：{error}") from error

        stats = _parse_stats(
            total_pages=total_pages,
            text_pages=text_pages,
            empty_pages=empty_pages,
            extractable_chars=extractable_chars,
            empty_warning=NO_TEXT_LAYER_WARNING,
            image_count=0,
            pages=pages,
            parser_id="pypdf",
        )
        return blocks, stats

    # ------------------------------------------------------------- text

    def _parse_text(
        self, file_path: Path, *, markdown: bool, tex: bool
    ) -> tuple[list[ParsedBlock], dict]:
        budget = _ACTIVE_BUDGET.get()
        # UTF-8 has at most four bytes per character. Bound even standalone
        # parser use before decoding; ingestion separately bounds input bytes.
        with file_path.open("rb") as stream:
            raw = stream.read(budget.limits.max_text_chars * 4 + 1)
        if len(raw) > budget.limits.max_text_chars * 4:
            raise DocumentParseError("PARSE_TEXT_LIMIT", "文档提取文字超过解析限制。")
        text = raw.decode("utf-8", errors="replace")
        budget.text(len(text))
        blocks: list[ParsedBlock] = []
        heading_path: list[str] = []
        for paragraph in _paragraphs(text):
            budget.check()
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
                budget.blocks(len(blocks))
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
            budget.blocks(len(blocks))
        extractable_chars = len(text.strip())
        return blocks, _parse_stats(
            total_pages=0,
            text_pages=0,
            empty_pages=0,
            extractable_chars=extractable_chars,
            empty_warning=NO_TEXT_FILE_WARNING,
            image_count=0,
            parser_id="text",
            classification="TEXT_FILE",
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
    pages: Sequence[PdfPageProfile] = (),
    parser_id: str = "",
    classification: str = "",
) -> dict:
    """Derive parse_mode / parse_warning / classification from page facts.

    Does not change block extraction.
    """
    parse_mode: ParseMode
    parse_warning = ""
    if extractable_chars <= 0:
        parse_mode = "empty"
        parse_warning = empty_warning
    elif empty_pages > 0 and total_pages > 0:
        parse_mode = "mixed"
        if empty_pages / total_pages >= EMPTY_PAGE_WARNING_RATIO:
            parse_warning = (
                f"共 {total_pages} 页，其中 {empty_pages} 页无可提取文字层，可能需要 OCR。"
            )
    else:
        parse_mode = "text_layer"
    if classification:
        resolved = classification
    elif pages:
        resolved = classify_pdf(tuple(pages))
    else:
        # No page model at all (plain text input, or a PDF that never opened).
        resolved = "NO_TEXT_LAYER_PDF"
    return {
        "total_pages": total_pages,
        "text_pages": text_pages,
        "empty_pages": empty_pages,
        "extractable_chars": extractable_chars,
        "parse_mode": parse_mode,
        "parse_warning": parse_warning,
        "image_count": image_count,
        "pages": tuple(pages),
        "classification": resolved,
        "parser_id": parser_id,
    }


def _page_median_size(page_dict: dict) -> float:
    sizes: list[tuple[float, int]] = []
    for raw_block in page_dict.get("blocks") or []:
        if raw_block.get("type") != 0:
            continue
        for line in raw_block.get("lines") or []:
            for span in line.get("spans") or []:
                if sample := _span_font_sample(span):
                    sizes.append(sample)
    return _text_weighted_median_size(sizes)


def _span_font_sample(span: dict) -> tuple[float, int] | None:
    """Ignore whitespace and unusable font metadata when estimating text size."""
    weight = sum(not char.isspace() for char in (span.get("text") or ""))
    try:
        size = float(span.get("size") or 0.0)
    except (TypeError, ValueError):
        return None
    if not weight or not math.isfinite(size) or size <= 0:
        return None
    return size, weight


def _text_weighted_median_size(samples: Sequence[tuple[float, int]]) -> float:
    """Median over visible characters, without allocating an entry per character.

    A font/style change can split a paragraph into many spans; a whole body
    paragraph can also be one span. Weight by text rather than these arbitrary
    boundaries so short headings cannot outvote most of a page's body text.
    As with an ordinary median, average the two central values for even totals.
    """
    total = sum(weight for _, weight in samples)
    if not total:
        return 0.0
    lower_rank, upper_rank = (total - 1) // 2, total // 2
    seen = 0
    lower = None
    for size, weight in sorted(samples):
        seen += weight
        if lower is None and seen > lower_rank:
            lower = size
        if seen > upper_rank:
            return (lower + size) / 2
    return 0.0


def _block_text_and_size(raw_block: dict) -> tuple[str, float, float]:
    lines: list[str] = []
    sizes: list[tuple[float, int]] = []
    for line in raw_block.get("lines") or []:
        pieces: list[str] = []
        for span in line.get("spans") or []:
            piece = (span.get("text") or "").strip()
            if piece:
                pieces.append(piece)
            if sample := _span_font_sample(span):
                sizes.append(sample)
        if pieces:
            lines.append(" ".join(pieces))
    text = "\n".join(lines).strip()
    max_size = max((size for size, _ in sizes), default=0.0)
    median = _text_weighted_median_size(sizes)
    return text, max_size, median


def _classify_text_block(
    text: str, *, font_size: float, median: float
) -> tuple[ParsedElementType, str | None]:
    stripped = text.strip()
    if _DISPLAY_FORMULA.match(stripped) or _inline_formula_only(stripped):
        return "formula", stripped
    short = len(stripped) <= 80 and "\n" not in stripped
    larger = median > 0 and font_size >= median * 1.35
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
        budget = _ACTIVE_BUDGET.get()
        budget.check()
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
        budget.asset(len(payload))
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
    "DocumentParseLimits",
    "EMPTY_PAGE_WARNING_RATIO",
    "LocalDocumentParser",
    "NO_TEXT_FILE_WARNING",
    "NO_TEXT_LAYER_WARNING",
    "PARSER_VERSION",
]
