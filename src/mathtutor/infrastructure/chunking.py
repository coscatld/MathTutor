"""Deterministic text chunking for user documents.

Chunker output is versioned (``CHUNKER_VERSION``): a chunker change
re-chunks documents and marks their vector index stale — but never
re-imports the original file (chunk text is derived from the parsed
document, which is itself derived from the stored bytes).

Chunking is deterministic: paragraph → sentence boundaries, capped at
``max_chunk_chars`` with a tail overlap into the next chunk. CJK
punctuation (。！？；) and newlines are sentence boundaries; latin text
uses standard sentence ends. No model, no network.
"""

from __future__ import annotations

import re
from typing import Sequence

from mathtutor.domain.documents import ParsedBlock

CHUNKER_VERSION = "mt-chunker-v1"

_DEFAULT_MAX_CHUNK_CHARS = 1000
_DEFAULT_OVERLAP_CHARS = 100

_SENTENCE_END = re.compile(r"[。！？；!?;\n]+")


class TextChunker:
    """Pure, deterministic chunker over parsed blocks."""

    def __init__(
        self,
        *,
        max_chunk_chars: int = _DEFAULT_MAX_CHUNK_CHARS,
        overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
    ) -> None:
        if max_chunk_chars < 1:
            raise ValueError("max_chunk_chars must be >= 1")
        if overlap_chars < 0 or overlap_chars >= max_chunk_chars:
            raise ValueError("overlap_chars must be in [0, max_chunk_chars)")
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars

    def _sentences(self, text: str) -> list[str]:
        """Split into sentence-ish units; long sentences are hard-split."""
        raw_parts = [part.strip() for part in _SENTENCE_END.split(text) if part.strip()]
        units: list[str] = []
        for part in raw_parts:
            while len(part) > self.max_chunk_chars:
                units.append(part[: self.max_chunk_chars])
                part = part[self.max_chunk_chars :]
            if part:
                units.append(part)
        return units

    def chunk(self, blocks: Sequence[ParsedBlock]) -> list[dict]:
        """Chunk parsed blocks into sequence-ordered drafts.

        Returns dict drafts: {page, section, text} — the ingestion service
        stamps chunk_id/sequence/content_hash/chunker_version.
        """
        drafts: list[dict] = []
        for block in blocks:
            sentences = self._sentences(block.text)
            if not sentences:
                continue
            current = ""
            for sentence in sentences:
                if not current:
                    current = sentence
                    continue
                candidate = f"{current}\n{sentence}"
                if len(candidate) <= self.max_chunk_chars:
                    current = candidate
                else:
                    drafts.append(
                        {"page": block.page, "section": block.section, "text": current}
                    )
                    current = sentence[-self.overlap_chars :] if self.overlap_chars else ""
                    if current and not sentence.startswith(current):
                        current = sentence
            if current:
                drafts.append({"page": block.page, "section": block.section, "text": current})
        return drafts


__all__ = ["CHUNKER_VERSION", "TextChunker"]
