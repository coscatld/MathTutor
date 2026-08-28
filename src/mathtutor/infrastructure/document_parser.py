"""Local document parsing — text extraction, NEVER execution.

Parsing turns stored bytes into :class:`ParsedTextDocument` blocks. The
design contract (§14):

- parsing a document NEVER executes it — no Python/JS/shell, no Office
  macros, no Manim, no embedded executables. Only static text extraction:
  UTF-8 decode for text formats, pypdf page extraction for PDFs;
- no OCR / VLM is added opportunistically — scanned PDFs yield empty
  text and simply contribute no blocks;
- extension dispatch is fail-closed: anything outside the allowlist
  raises (the allowlist is enforced again here even though ingestion
  validates first — defense in depth).

The parser version is part of the index-lifecycle signature: a parser
change marks documents stale for re-parse and indexes for rebuild —
original files are never re-imported.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from mathtutor.domain.documents import (
    ALLOWED_DOCUMENT_EXTENSIONS,
    ParsedBlock,
    ParsedTextDocument,
)

PARSER_VERSION = "mt-local-parser-v1"

# One extracted text block stays under this many chars so a single
# pathological paragraph cannot dominate chunking (chunking hard-splits
# long sentences anyway; this keeps block/page grain sane).
_MAX_BLOCK_CHARS = 8000

_MARKDOWN_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


class DocumentParser(Protocol):
    """Parse stored bytes into extracted text blocks (async, no side effects)."""

    def parser_version(self) -> str: ...

    async def parse(self, *, path: str) -> ParsedTextDocument: ...


class LocalDocumentParser:
    """Dependency-light parser: pypdf for PDFs, plain decode otherwise.

    pypdf is imported lazily so the math_tutor core (and every test that
    doesn't touch PDFs) works even where pypdf is absent; PDF parsing is
    the only path that needs it.
    """

    def parser_version(self) -> str:
        return PARSER_VERSION

    def supported_extensions(self) -> frozenset[str]:
        return ALLOWED_DOCUMENT_EXTENSIONS

    async def parse(self, *, path: str) -> ParsedTextDocument:
        file_path = Path(path)
        extension = file_path.suffix.lower()
        if extension not in ALLOWED_DOCUMENT_EXTENSIONS:
            raise ValueError(
                f"unsupported document extension: {extension!r} "
                f"(allowlist: {sorted(ALLOWED_DOCUMENT_EXTENSIONS)})"
            )
        if extension == ".pdf":
            blocks = self._parse_pdf(file_path)
        else:
            blocks = self._parse_text(file_path, markdown=extension in {".md", ".markdown"})
        return ParsedTextDocument(blocks=tuple(blocks))

    # ------------------------------------------------------------- helpers

    def _parse_pdf(self, file_path: Path) -> list[ParsedBlock]:
        """pypdf page-by-page text extraction (no OCR, no execution)."""
        from pypdf import PdfReader

        reader = PdfReader(str(file_path))
        blocks: list[ParsedBlock] = []
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                continue
            blocks.extend(
                ParsedBlock(page=page_number, section="", text=part)
                for part in _split_oversize(text)
            )
        return blocks

    def _parse_text(self, file_path: Path, *, markdown: bool) -> list[ParsedBlock]:
        """UTF-8 decode + paragraph blocks (markdown tracks `#` sections)."""
        raw = file_path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        blocks: list[ParsedBlock] = []
        section = ""
        for paragraph in _paragraphs(text):
            heading = _MARKDOWN_HEADING.match(paragraph) if markdown else None
            if heading:
                section = heading.group(2).strip()
                # Headings also become their own (short) block so the chunk
                # sequence preserves structure.
                blocks.append(ParsedBlock(page=None, section=section, text=paragraph))
                continue
            blocks.extend(
                ParsedBlock(page=None, section=section, text=part)
                for part in _split_oversize(paragraph)
            )
        return blocks


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs (never returns empty parts)."""
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _split_oversize(text: str) -> list[str]:
    """Hard-split over-long extracts so one block stays bounded."""
    if len(text) <= _MAX_BLOCK_CHARS:
        return [text]
    return [text[i : i + _MAX_BLOCK_CHARS] for i in range(0, len(text), _MAX_BLOCK_CHARS)]


__all__ = ["DocumentParser", "LocalDocumentParser", "PARSER_VERSION"]
