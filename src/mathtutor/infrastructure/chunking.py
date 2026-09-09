"""Deterministic math-structure chunking for user documents.

Chunker output is versioned (``CHUNKER_VERSION``): a chunker change
re-chunks documents and marks their vector index stale — but never
re-imports the original file.

Rules (hand-written, no bbox, no model):

- split on headings; an example (例n) swallows until the next example or
  section; 「解：」/「证明：」 become a child of the open example when long
  enough, otherwise stay in the parent chunk;
- formulas merge into the preceding group;
- tables/figures stay whole and attach to the open example, else the
  current section;
- sentence-split ONLY when a group exceeds ``max_chunk_chars`` (1000),
  with ~100-char overlap; pieces shorter than ``min_chunk_chars`` merge
  back so we do not emit dozens-of-character fragments.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from mathtutor.domain.documents import ParsedBlock

CHUNKER_VERSION = "mt-chunker-v2"

_DEFAULT_MAX_CHUNK_CHARS = 1000
_DEFAULT_OVERLAP_CHARS = 100
_DEFAULT_MIN_CHUNK_CHARS = 80

_SENTENCE_END = re.compile(r"[。！？；!?;\n]+")

# Line-start structure markers. 「例如」 is excluded so it is not an example.
_LINE_ROLE = re.compile(
    r"(?m)^(?P<marker>"
    r"例\s*题?\s*(?:[0-9０-９]+|[一二三四五六七八九十]{1,3})(?!如)"
    r"|例\s*[:：]"
    r"|解\s*[:：]"
    r"|证明\s*[:：]"
    r"|定义\s*[0-9]*"
    r"|定理\s*[0-9]*"
    r"|引理\s*[0-9]*"
    r"|推论\s*[0-9]*"
    r"|命题\s*[0-9]*"
    r"|习题\s*[0-9]*"
    r"|练习题?\s*[0-9]*"
    r")"
)

_ROLE_EXAMPLE = "example"
_ROLE_SOLUTION = "solution"
_ROLE_DEFINITION = "definition"
_ROLE_THEOREM = "theorem"
_ROLE_EXERCISE = "exercise"
_ROLE_HEADING = "heading"
_ROLE_PARAGRAPH = "paragraph"
_ROLE_FORMULA = "formula"
_ROLE_TABLE = "table"
_ROLE_FIGURE = "figure"


@dataclass
class _Unit:
    role: str
    text: str
    page: int | None
    heading_path: tuple[str, ...]
    latex: str | None = None
    image_path: str | None = None
    caption: str | None = None
    ocr_text: str | None = None


@dataclass
class _Group:
    chunk_type: str
    heading_path: tuple[str, ...]
    parent_token: int | None
    token: int
    units: list[_Unit] = field(default_factory=list)


class TextChunker:
    """Heading / example / formula-aware chunker over parsed blocks."""

    def __init__(
        self,
        *,
        max_chunk_chars: int = _DEFAULT_MAX_CHUNK_CHARS,
        overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
        min_chunk_chars: int = _DEFAULT_MIN_CHUNK_CHARS,
    ) -> None:
        if max_chunk_chars < 1:
            raise ValueError("max_chunk_chars must be >= 1")
        if overlap_chars < 0 or overlap_chars >= max_chunk_chars:
            raise ValueError("overlap_chars must be in [0, max_chunk_chars)")
        if min_chunk_chars < 1 or min_chunk_chars > max_chunk_chars:
            raise ValueError("min_chunk_chars must be in [1, max_chunk_chars]")
        self.max_chunk_chars = max_chunk_chars
        self.overlap_chars = overlap_chars
        self.min_chunk_chars = min_chunk_chars

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

    def chunk(self, blocks: Sequence[ParsedBlock] | Sequence[object]) -> list[dict]:
        """Chunk parsed blocks into sequence-ordered drafts.

        Draft keys: page, section, text, chunk_type, heading_path,
        page_start, page_end, parent_index, metadata.
        ``parent_index`` is the stem draft index (ingestion stamps UUID).
        """
        units = _units_from_blocks(blocks)
        groups = _group_units(units)
        groups = self._merge_tiny_solutions(groups)
        return self._emit_drafts(groups)

    def _merge_tiny_solutions(self, groups: list[_Group]) -> list[_Group]:
        """Keep a short 「解：」 inside the example parent instead of a shard."""
        merged: list[_Group] = []
        for group in groups:
            if (
                group.chunk_type == _ROLE_SOLUTION
                and group.parent_token is not None
                and _group_text(group)
                and len(_group_text(group)) < self.min_chunk_chars
                and merged
                and merged[-1].token == group.parent_token
            ):
                merged[-1].units.extend(group.units)
                continue
            merged.append(group)
        return merged

    def _emit_drafts(self, groups: list[_Group]) -> list[dict]:
        drafts: list[dict] = []
        token_to_index: dict[int, int] = {}
        for group in groups:
            pieces = self._split_group_text(_group_text(group))
            if not pieces and not _group_has_figure(group):
                continue
            if not pieces:
                pieces = [_group_text(group) or (group.units[0].caption if group.units else "") or "[图]"]
            parent_index = (
                token_to_index.get(group.parent_token)
                if group.parent_token is not None
                else None
            )
            metadata = _group_metadata(group)
            pages = [unit.page for unit in group.units if unit.page is not None]
            page_start = min(pages) if pages else None
            page_end = max(pages) if pages else None
            section = group.heading_path[-1] if group.heading_path else ""
            first_index = len(drafts)
            for piece in pieces:
                drafts.append(
                    {
                        "page": page_start,
                        "section": section,
                        "text": piece,
                        "chunk_type": group.chunk_type,
                        "heading_path": list(group.heading_path),
                        "page_start": page_start,
                        "page_end": page_end,
                        "parent_index": parent_index,
                        "metadata": dict(metadata),
                    }
                )
            token_to_index[group.token] = first_index
        return drafts

    def _split_group_text(self, text: str) -> list[str]:
        text = (text or "").strip()
        if not text:
            return []
        if len(text) <= self.max_chunk_chars:
            return [text]
        sentences = self._sentences(text)
        pieces: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = sentence if not current else f"{current}\n{sentence}"
            if len(candidate) <= self.max_chunk_chars:
                current = candidate
                continue
            if current:
                pieces.append(current)
                overlap = current[-self.overlap_chars :] if self.overlap_chars else ""
                if overlap and sentence.startswith(overlap):
                    current = sentence
                elif overlap:
                    current = f"{overlap}\n{sentence}"
                    if len(current) > self.max_chunk_chars:
                        current = sentence
                else:
                    current = sentence
            else:
                current = sentence
            while len(current) > self.max_chunk_chars:
                pieces.append(current[: self.max_chunk_chars])
                current = current[self.max_chunk_chars - self.overlap_chars :]
        if current:
            pieces.append(current)
        return self._merge_short_pieces(pieces)

    def _merge_short_pieces(self, pieces: list[str]) -> list[str]:
        if len(pieces) <= 1:
            return pieces
        merged: list[str] = []
        for piece in pieces:
            if (
                merged
                and len(piece) < self.min_chunk_chars
                and len(merged[-1]) + 1 + len(piece) <= self.max_chunk_chars
            ):
                merged[-1] = f"{merged[-1]}\n{piece}"
            else:
                merged.append(piece)
        return merged


def _units_from_blocks(blocks: Sequence[object]) -> list[_Unit]:
    units: list[_Unit] = []
    for block in blocks:
        units.extend(_units_from_block(block))
    return units


def _units_from_block(block: object) -> list[_Unit]:
    block_type = str(getattr(block, "type", None) or "paragraph")
    text = str(getattr(block, "text", "") or "")
    page = getattr(block, "page", None)
    heading_path = tuple(getattr(block, "heading_path", ()) or ())
    if not heading_path:
        section = str(getattr(block, "section", "") or "")
        heading_path = (section,) if section else ()
    latex = getattr(block, "latex", None)
    image_path = getattr(block, "image_path", None)
    caption = getattr(block, "caption", None)
    ocr_text = getattr(block, "ocr_text", None)
    if block_type in {_ROLE_HEADING, _ROLE_FORMULA, _ROLE_TABLE, _ROLE_FIGURE}:
        if block_type != _ROLE_FIGURE and not text.strip() and not image_path:
            return []
        role = block_type
        if block_type == _ROLE_HEADING and not heading_path:
            title = text.splitlines()[0].lstrip("#").strip() if text else ""
            heading_path = (title,) if title else ()
        return [
            _Unit(
                role=role,
                text=text,
                page=page,
                heading_path=heading_path,
                latex=latex,
                image_path=image_path,
                caption=caption,
                ocr_text=ocr_text,
            )
        ]
    pieces = _split_plain_roles(text)
    if not pieces:
        if image_path:
            return [
                _Unit(
                    role=_ROLE_FIGURE,
                    text=text,
                    page=page,
                    heading_path=heading_path,
                    image_path=image_path,
                    caption=caption,
                    ocr_text=ocr_text,
                )
            ]
        return []
    return [
        _Unit(
            role=role,
            text=part,
            page=page,
            heading_path=heading_path,
            latex=latex if role == _ROLE_FORMULA else None,
            image_path=image_path if role == _ROLE_FIGURE else None,
            caption=caption if role == _ROLE_FIGURE else None,
            ocr_text=ocr_text,
        )
        for role, part in pieces
        if part.strip()
    ]


def _split_plain_roles(text: str) -> list[tuple[str, str]]:
    if not (text or "").strip():
        return []
    matches = list(_LINE_ROLE.finditer(text))
    if not matches:
        return [(_ROLE_PARAGRAPH, text.strip())]
    units: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        prefix = text[: matches[0].start()].strip()
        if prefix:
            units.append((_ROLE_PARAGRAPH, prefix))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.start() : end].strip()
        if body:
            units.append((_role_from_marker(match.group("marker")), body))
    return units


def _role_from_marker(marker: str) -> str:
    stripped = marker.strip()
    if stripped.startswith("例"):
        return _ROLE_EXAMPLE
    if stripped.startswith("解") or stripped.startswith("证明"):
        return _ROLE_SOLUTION
    if stripped.startswith("定义"):
        return _ROLE_DEFINITION
    if stripped.startswith("习题") or stripped.startswith("练习"):
        return _ROLE_EXERCISE
    if stripped.startswith(("定理", "引理", "推论", "命题")):
        return _ROLE_THEOREM
    return _ROLE_PARAGRAPH


def _group_units(units: list[_Unit]) -> list[_Group]:
    groups: list[_Group] = []
    current: _Group | None = None
    path: tuple[str, ...] = ()
    example_token: int | None = None
    example_path: tuple[str, ...] = ()
    next_token = 0

    def flush() -> None:
        nonlocal current
        if current is not None and (current.units or _group_text(current)):
            groups.append(current)
        current = None

    def start(chunk_type: str, *, parent: int | None) -> _Group:
        nonlocal next_token, current
        flush()
        group = _Group(
            chunk_type=chunk_type,
            heading_path=path,
            parent_token=parent,
            token=next_token,
        )
        next_token += 1
        current = group
        return group

    for unit in units:
        if unit.heading_path:
            path = unit.heading_path
        if unit.role == _ROLE_HEADING:
            title = unit.text.splitlines()[0].lstrip("#").strip() if unit.text else ""
            if title:
                path = unit.heading_path or (title,)
            example_token = None
            example_path = ()
            flush()
            continue
        if unit.role == _ROLE_EXAMPLE:
            group = start(_ROLE_EXAMPLE, parent=None)
            if unit.text:
                label = unit.text.splitlines()[0].strip()[:40]
                group.heading_path = path + (label,) if path else (label,)
            group.units.append(unit)
            example_token = group.token
            example_path = group.heading_path
            continue
        if unit.role == _ROLE_SOLUTION:
            if example_token is not None:
                child = start(_ROLE_SOLUTION, parent=example_token)
                child.heading_path = example_path or path
                child.units.append(unit)
            elif current is not None:
                current.units.append(unit)
            else:
                start(_ROLE_SOLUTION, parent=None).units.append(unit)
            continue
        if unit.role in {_ROLE_DEFINITION, _ROLE_THEOREM, _ROLE_EXERCISE}:
            example_token = None
            start(unit.role, parent=None).units.append(unit)
            continue
        if unit.role in {_ROLE_FORMULA, _ROLE_TABLE, _ROLE_FIGURE}:
            if current is None:
                start(unit.role, parent=example_token).units.append(unit)
            else:
                current.units.append(unit)
            continue
        # paragraph
        if current is None:
            start(_ROLE_PARAGRAPH, parent=example_token).units.append(unit)
        elif current.chunk_type in {
            _ROLE_EXAMPLE,
            _ROLE_SOLUTION,
            _ROLE_PARAGRAPH,
            _ROLE_DEFINITION,
            _ROLE_THEOREM,
            _ROLE_EXERCISE,
        }:
            current.units.append(unit)
        else:
            start(_ROLE_PARAGRAPH, parent=example_token).units.append(unit)
    flush()
    return groups


def _group_text(group: _Group) -> str:
    parts = [unit.text.strip() for unit in group.units if (unit.text or "").strip()]
    if not parts:
        for unit in group.units:
            if unit.caption:
                return unit.caption.strip()
    return "\n".join(parts)


def _group_has_figure(group: _Group) -> bool:
    return any(unit.image_path or unit.role == _ROLE_FIGURE for unit in group.units)


def _group_metadata(group: _Group) -> dict:
    image_paths = [unit.image_path for unit in group.units if unit.image_path]
    captions = [unit.caption for unit in group.units if unit.caption]
    ocr = [unit.ocr_text for unit in group.units if unit.ocr_text]
    latex = [unit.latex for unit in group.units if unit.latex]
    meta: dict = {
        "chunk_type": group.chunk_type,
        "heading_path": list(group.heading_path),
    }
    if image_paths:
        meta["image_paths"] = image_paths
    if captions:
        meta["caption"] = "\n".join(captions)
    if ocr:
        meta["ocr_text"] = "\n".join(ocr)
    if latex:
        meta["latex"] = "\n".join(latex)
    if group.chunk_type == _ROLE_SOLUTION:
        meta["role"] = "solution"
    elif group.chunk_type == _ROLE_EXAMPLE:
        meta["role"] = "stem"
    return meta


__all__ = ["CHUNKER_VERSION", "TextChunker"]
