"""User Document Knowledge domain — the student's own imported materials.

The pipeline is strictly local and staged (design requirement §14):

    native file picker → DesktopFileAdapter → DocumentIngestionService
        → validate → store (MathTutor-controlled storage) → parse
        → chunk → optional vector index → retrieval

NEVER: user file → LLM directly. Generative providers only receive the
student request plus deliberately selected, projected chunks — never whole
files, and never as a provider-native File API (which is not a core
architecture dependency; MathTutor owns storage/parsing/chunking/retrieval).

Import invariants:

- only EXPLICITLY picked files are imported — the business layer never
  scans host directories (no Desktop/Documents/Downloads traversal);
- the original host path is NOT the source of truth: after import the
  document is addressed by ``document_id`` and lives in controlled storage
  (``data/uploads/<student_id>/<document_id>/<safe-filename>``);
- extension allowlist + MIME validation + size limit + content hash +
  safe filename + owner scope + soft delete;
- parsing documents NEVER executes them (no Python/JS/shell/Office macros/
  Manim/embedded executables); no OCR/VLM is added opportunistically.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Sequence
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

DocumentStatus = Literal[
    "importing",
    "parsing",
    "ready",
    "ready_with_warnings",
    "needs_ocr",
    "failed",
    "deleted",
]

# Statuses whose chunks may enter retrieval (owner + retrieval_enabled +
# not-deleted still apply at the data layer). Zero-text / OCR-needed
# documents are never in this set.
RETRIEVABLE_DOCUMENT_STATUSES: frozenset[str] = frozenset(
    {"ready", "ready_with_warnings"}
)

# ``recovered_external`` marks text that did NOT come from the PDF's own text
# layer — it was produced by the optional external recovery adapter (MinerU).
# Labelling such text ``text_layer`` would tell the user and telemetry that the
# page always had selectable text.
ParseMode = Literal["text_layer", "empty", "mixed", "recovered_external"]

# Which parser actually produced this document's text. Recorded per document
# because the shipped runtime does NOT provide PyMuPDF (see
# docs/CURRENT_STATE_RAG_AUDIT.md §6.1): a document ingested on a machine with
# PyMuPDF gets headings/tables/figures, one ingested without it cannot. Without
# this column the degradation is invisible after the fact.
ParserId = Literal["", "pymupdf", "pypdf", "mineru", "text"]

# Per-page extractability. This is a statement about the TEXT LAYER only.
#
# NO_EXTRACTABLE_TEXT is deliberately NOT named "SCAN": a parser that extracts
# no text cannot distinguish a scanned page from a blank page, a figure-only
# page, a page drawn entirely with vector art, a page whose font the parser
# cannot decode, or a genuinely scanned page. Only image-coverage analysis or a
# real page classifier could make that claim, and this build has neither.
PageTextLayer = Literal["TEXT_LAYER", "NO_EXTRACTABLE_TEXT"]

# Document-level classification, derived from per-page facts or from the parse
# failure that ended the attempt. Names state what was OBSERVED, not a guess
# about why. A UI may render NO_TEXT_LAYER_PDF as "可能需要 OCR"; the data
# model does not assert it.
DocumentClassification = Literal[
    "TEXT_PDF",                # every page yielded extractable text
    "MIXED_TEXT_LAYER_PDF",    # some pages yielded text, some did not
    "NO_TEXT_LAYER_PDF",       # no page yielded extractable text
    "ENCRYPTED_PDF",           # password-protected; needs a key before parsing
    "CORRUPTED_PDF",           # structurally broken; the parser could not read it
    "TEXT_FILE",               # .txt / .md / .markdown / .tex — no page model
    "PARSE_TIMEOUT",           # cooperative processing deadline was exceeded
    "PARSE_CANCELLED",         # user cancellation or owned-service shutdown
    "PARSE_BUSY",              # bounded worker admission queue was full
    "PARSE_CLOSED",            # worker service no longer accepts parsing
    "PARSE_PAGE_LIMIT",        # PDF page count exceeded the configured budget
    "PARSE_TEXT_LIMIT",        # extracted characters exceeded the budget
    "PARSE_BLOCK_LIMIT",       # extracted blocks exceeded the budget
    "PARSE_ASSET_LIMIT",       # extracted image count/bytes exceeded the budget
]


class DocumentParseError(Exception):
    """Parsing failed for a *classified* reason.

    ``ingest`` maps this onto ``status="failed"`` plus the recorded
    classification, so an encrypted or corrupted upload is distinguishable
    from a generic failure instead of collapsing into one message.
    """

    def __init__(self, classification: str, message: str) -> None:
        super().__init__(message)
        self.classification = classification

# Lean parse IR (not a full math-role taxonomy). Chunking still reads
# page/section/text; extra fields travel with the block for later stages.
ParsedElementType = Literal["heading", "paragraph", "formula", "table", "figure"]

# Extension allowlist (fail closed): plain-text and PDF text extraction only.
# No executable formats, no Office macro carriers, no archives in the MVP.
ALLOWED_DOCUMENT_EXTENSIONS: frozenset[str] = frozenset(
    {".txt", ".md", ".markdown", ".tex", ".pdf"}
)

ALLOWED_DOCUMENT_MIME_TYPES: frozenset[str] = frozenset(
    {
        "text/plain",
        "text/markdown",
        "text/x-tex",
        "application/pdf",
    }
)

# 20 MB — aligned with DeepTutor's attachment document limit; the whole
# file is read into memory by the picker before ingestion.
MAX_DOCUMENT_BYTES: int = 20 * 1024 * 1024

# Retention policy (MVP): deleting a document removes the controlled file
# immediately after the soft-delete + retrieval removal commit. A future
# DataLifecycleService may hold files for a retention window instead.
DOCUMENT_RETENTION_DELETE_IMMEDIATELY = "delete_immediately"


class ParsedBlock(BaseModel):
    """One lean parse-IR element (page-aware for PDFs).

    ``section`` is the leaf of ``heading_path`` so the existing chunker can
    keep using page/section/text without a rewrite.
    """

    model_config = ConfigDict(frozen=True)

    type: ParsedElementType = "paragraph"
    page: int | None = None
    section: str = ""
    text: str = ""
    heading_path: tuple[str, ...] = ()
    latex: str | None = None
    image_path: str | None = None
    caption: str | None = None
    ocr_text: str | None = None


class PdfPageProfile(BaseModel):
    """Per-page extractability of one PDF page's text layer.

    Carries ONLY the facts a baseline parser can prove. Fields such as
    ``text_blocks``, ``image_count``, ``image_coverage`` or ``font_size`` are
    deliberately absent: the shipped runtime parses PDFs with pypdf, which
    cannot produce them (docs/CURRENT_STATE_RAG_AUDIT.md §6.1). An optional
    rich parser may fill ``image_count`` when present; nothing may fabricate it.
    """

    model_config = ConfigDict(frozen=True)

    page_number: int = Field(ge=1)
    extractable_text_chars: int = Field(ge=0, default=0)
    text_layer: PageTextLayer = "NO_EXTRACTABLE_TEXT"
    # Only populated by a rich parser (PyMuPDF). ``None`` means "not measured",
    # never "zero images".
    image_count: int | None = None

    @property
    def has_extractable_text(self) -> bool:
        return self.text_layer == "TEXT_LAYER"


class ParsedTextDocument(BaseModel):
    """Parser output: extracted text blocks plus extractability stats.

    Parsing never executes files and never runs OCR. A page with no
    extractable text contributes to ``empty_pages`` / ``parse_mode`` rather
    than to ``blocks`` (chunking is unchanged).
    """

    model_config = ConfigDict(frozen=True)

    blocks: tuple[ParsedBlock, ...]
    total_pages: int = Field(ge=0, default=0)
    text_pages: int = Field(ge=0, default=0)
    empty_pages: int = Field(ge=0, default=0)
    extractable_chars: int = Field(ge=0, default=0)
    parse_mode: ParseMode = "empty"
    parse_warning: str = ""
    image_count: int = Field(ge=0, default=0)
    pages: tuple[PdfPageProfile, ...] = ()
    classification: DocumentClassification = "TEXT_FILE"
    parser_id: ParserId = ""

    def full_text(self) -> str:
        return "\n".join(block.text for block in self.blocks)


def classify_pdf(pages: Sequence[PdfPageProfile]) -> DocumentClassification:
    """Classify a PDF from per-page text-layer facts only.

    States only what was observed: how many pages yielded extractable text.
    It does NOT claim any page is a scan — see :data:`PageTextLayer`.
    """
    if not pages:
        return "NO_TEXT_LAYER_PDF"
    with_text = sum(1 for page in pages if page.has_extractable_text)
    if with_text == 0:
        return "NO_TEXT_LAYER_PDF"
    if with_text == len(pages):
        return "TEXT_PDF"
    return "MIXED_TEXT_LAYER_PDF"


class UserDocument(BaseModel):
    """One imported document (metadata only — bytes live in storage)."""

    model_config = ConfigDict(frozen=True)

    document_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    filename: str  # sanitized display name (no path separators)
    mime_type: str
    content_hash: str  # sha256 of the imported bytes
    storage_ref: str  # relative path under controlled storage
    status: DocumentStatus = "importing"
    size_bytes: int = Field(ge=0)
    parser_version: str = ""
    # Which parser produced the text, and what was observed about the text
    # layer. Both are per-document history: a document ingested on a runtime
    # with PyMuPDF carries headings/tables, one ingested without it cannot, and
    # neither fact is recoverable later from the bytes alone.
    parser_id: ParserId = ""
    classification: DocumentClassification = "TEXT_FILE"
    is_global: bool = False  # Explicit owner-local sharing across conversations.
    retrieval_enabled: bool = True
    parse_error: str = ""
    page_count: int = Field(ge=0, default=0)
    chunk_count: int = Field(ge=0, default=0)
    image_count: int = Field(ge=0, default=0)
    empty_page_count: int = Field(ge=0, default=0)
    parse_warning: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    deleted_at: datetime | None = None

    def can_enable_retrieval(self) -> bool:
        """True when the document has extractable chunks and a ready status."""
        return (
            self.deleted_at is None
            and self.status in RETRIEVABLE_DOCUMENT_STATUSES
            and self.chunk_count > 0
        )

    def is_retrievable(self) -> bool:
        # Status is the retrieval gate (needs_ocr / failed never match).
        # chunk_count is enforced at ingest and on the enable-toggle; search
        # still uses status so seeded test documents without a persisted
        # count remain visible when they actually have chunks.
        return (
            self.retrieval_enabled
            and self.deleted_at is None
            and self.status in RETRIEVABLE_DOCUMENT_STATUSES
        )


class DocumentChunk(BaseModel):
    """One chunk of extracted text — the retrieval fact unit.

    The chunk TEXT is a fact (derived from the document bytes once);
    chunk boundaries and vectors are derived projections that rebuilds may
    replace without re-importing the original file.
    """

    model_config = ConfigDict(frozen=True)

    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    student_id: UUID
    sequence: int = Field(ge=0)
    page: int | None = None
    section: str = ""
    text: str
    content_hash: str
    chunk_type: str = "paragraph"
    heading_path: tuple[str, ...] = ()
    page_start: int | None = None
    page_end: int | None = None
    parent_chunk_id: UUID | None = None
    metadata_json: dict = {}
    chunker_version: str = ""
    fts_text: str = ""


class RetrievedChunk(BaseModel):
    """One ranked retrieval hit with provenance (query-time projection)."""

    model_config = ConfigDict(frozen=True)

    chunk: DocumentChunk
    document_id: UUID
    filename: str
    score: float = Field(ge=0.0)
    lexical_score: float = Field(ge=0.0, default=0.0)
    vector_score: float | None = None  # None → vector backend unavailable


class DocumentQueryResult(BaseModel):
    """Deterministic query outcome: retriever chain + provenance."""

    model_config = ConfigDict(frozen=True)

    query: str
    hits: tuple[RetrievedChunk, ...] = ()
    vector_used: bool = False
    embedding_backend_id: str = ""
    index_version: int | None = None
    degraded: bool = False  # True → lexical only (no vector backend)


class IndexBuildRecord(BaseModel):
    """Index-lifecycle row for one (student, document) — the CURRENT build.

    The full build signature is persisted so a rebuild decision is always
    deterministic: any change to the embedding descriptor (backend/model/
    version/dimension), the chunker version, or the parser version marks
    the build stale → rebuild vectors from chunks. The original file is
    NEVER re-imported (chunks derive from the parsed document, which
    derives from the stored bytes).
    """

    model_config = ConfigDict(frozen=True)

    student_id: UUID
    document_id: UUID
    index_version: int = Field(ge=1)
    embedding_backend_id: str
    embedding_model_id: str
    embedding_model_version: str
    embedding_dimension: int = Field(ge=1)
    chunker_version: str
    parser_version: str
    # D4: part of the descriptor's own signature. Empty means "recorded before
    # this field existed" and is treated as a mismatch, so an old row rebuilds
    # once rather than silently claiming currency.
    embedding_normalization: str = ""
    embedding_runtime_version: str = ""
    built_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def matches_signature(
        self,
        descriptor: "EmbeddingDescriptor",
        chunker_version: str,
        parser_version: str,
    ) -> bool:
        """True when this build was produced by the same code + model chain."""
        return (
            self.embedding_backend_id == descriptor.backend_id
            and self.embedding_model_id == descriptor.model_id
            and self.embedding_model_version == descriptor.model_version
            and self.embedding_dimension == descriptor.dimension
            # D4: a normalization or runtime change alters the vectors for the
            # same text, so it must invalidate the index like any other term.
            and self.embedding_normalization == descriptor.normalization
            and self.embedding_runtime_version == (descriptor.runtime_version or "")
            and self.chunker_version == chunker_version
            and self.parser_version == parser_version
        )


__all__ = [
    "ALLOWED_DOCUMENT_EXTENSIONS",
    "ALLOWED_DOCUMENT_MIME_TYPES",
    "DOCUMENT_RETENTION_DELETE_IMMEDIATELY",
    "DocumentChunk",
    "DocumentClassification",
    "DocumentParseError",
    "DocumentQueryResult",
    "DocumentStatus",
    "IndexBuildRecord",
    "MAX_DOCUMENT_BYTES",
    "PageTextLayer",
    "ParseMode",
    "ParsedBlock",
    "ParsedElementType",
    "ParsedTextDocument",
    "ParserId",
    "PdfPageProfile",
    "RETRIEVABLE_DOCUMENT_STATUSES",
    "RetrievedChunk",
    "UserDocument",
    "classify_pdf",
]
