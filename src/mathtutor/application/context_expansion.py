"""ContextExpander — restore the neighbouring context a chunk boundary cut off.

A retrieval hit is a *slice*, and slices cut mid-thought. This stage widens a
hit whose text is visibly incomplete, then stops hard:

    chunk N  →  [N-1 | N | N+1]        (only when N looks truncated)

Two properties matter more than the widening itself:

- **Adjacency is derived, not stored.** ``(document_id, sequence)`` is read at
  request time. No ``prev_chunk_id`` / ``next_chunk_id`` columns exist, so no
  migration and no backfill can drift out of sync with the chunks.
- **Bounded by construction.** At most ``MAX_EXPANDED_ITEMS`` hits are
  expanded and at most ``MAX_EXPANSION_CHARS`` characters may be added in
  total. Expansion must never turn a bounded top-K into a whole-document read.

The trigger is deterministic and conservative — a chunk is expanded only when
it *looks* cut off, never merely because neighbours exist.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol, Sequence
from uuid import UUID

from mathtutor.domain.documents import DocumentChunk, RetrievedChunk

logger = logging.getLogger(__name__)

#: A chunk opening with one of these is continuing an earlier thought.
_CONTINUATION_PREFIX = re.compile(
    r"^\s*(?:"
    r"如上所述|如上|根据上述|由上述|上述|因此|所以|由此可见|由此可得|综上"
    r"|同理|类似地|接着|继续|上式中|其中|另一方面|反之|此外"
    r")"
)

#: ...and a chunk ending WITHOUT terminal punctuation was cut off.
_TERMINAL = re.compile(r"[。！？；：.!?;:）)」』】\]]\s*$")

MAX_EXPANDED_ITEMS = 4
MAX_EXPANSION_CHARS = 2400
#: One neighbour on each side. A wider window is a different feature (parent
#: / section retrieval), not a bigger number here.
NEIGHBOUR_RADIUS = 1


class ChunkNeighbourhood(Protocol):
    """The only repository capability this stage needs."""

    async def list_chunk_neighbourhood(
        self,
        student_id: str,
        document_id: UUID,
        *,
        sequence_start: int,
        sequence_end: int,
        chunk_ids: Sequence[UUID] = (),
    ) -> list[DocumentChunk]: ...


@dataclass(frozen=True, slots=True)
class ExpandedHit:
    """A hit plus the widened projection actually handed downstream.

    ``hit`` is left untouched: what matched and what is shown stay
    distinguishable, and ``expanded_from`` names every extra chunk merged in.
    """

    hit: RetrievedChunk
    text: str
    expanded_from: tuple[UUID, ...] = ()
    window: tuple[int, int] | None = None

    @property
    def expanded(self) -> bool:
        return bool(self.expanded_from)


def needs_expansion(text: str) -> bool:
    """Deterministic, conservative trigger.

    Expanding everything would waste the budget on chunks that are already
    self-contained; the two signals below are the cheap, observable ones.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    if _CONTINUATION_PREFIX.match(stripped):
        return True
    return _TERMINAL.search(stripped) is None


class ContextExpander:
    """Widens visibly-truncated hits within a hard character budget."""

    def __init__(
        self,
        reader: ChunkNeighbourhood,
        *,
        max_items: int = MAX_EXPANDED_ITEMS,
        max_chars: int = MAX_EXPANSION_CHARS,
        radius: int = NEIGHBOUR_RADIUS,
    ) -> None:
        self._reader = reader
        self.max_items = max_items
        self.max_chars = max_chars
        self.radius = radius
        #: Observability for the degraded path above — an expansion stage that
        #: silently never fires is indistinguishable from one that is broken.
        self.read_failures = 0

    async def expand(
        self, owner: str, hits: Sequence[RetrievedChunk]
    ) -> list[ExpandedHit]:
        """Return one :class:`ExpandedHit` per input hit, in input order.

        Hits are never reordered or dropped here — this stage only widens.
        """
        budget = self.max_chars
        expanded_count = 0
        results: list[ExpandedHit] = []

        for hit in hits:
            chunk = hit.chunk
            text = chunk.text or ""
            # Two independent triggers. The truncation heuristic answers "does
            # this text look cut off?"; a child answers a different question —
            # "is the thing this refers to missing?" A solution chunk is often
            # perfectly punctuated and still unanswerable without its stem, so
            # gating parent recovery on the punctuation heuristic would make
            # parent-expansion unreachable for exactly the chunks that need it.
            should = needs_expansion(text) or chunk.parent_chunk_id is not None

            if not should or expanded_count >= self.max_items or budget <= 0:
                results.append(ExpandedHit(hit=hit, text=text))
                continue

            start = max(0, chunk.sequence - self.radius)
            end = chunk.sequence + self.radius
            # The parent is requested BY ID: its sequence is not derivable from
            # the child, and scanning the document to find it would turn a
            # bounded expansion into a full-document read. It is re-checked by
            # the same visibility gate as everything else — a parent is not
            # implicitly readable because its child matched.
            parent_ids = (chunk.parent_chunk_id,) if chunk.parent_chunk_id else ()
            try:
                window = await self._reader.list_chunk_neighbourhood(
                    owner, chunk.document_id, sequence_start=start,
                    sequence_end=end, chunk_ids=parent_ids,
                )
            except Exception as error:
                # Expansion is an enhancement: a read failure must not lose the
                # hit. It is logged rather than swallowed, because a silently
                # caught error here also hides read-contract bugs.
                logger.warning(
                    "context expansion read failed document=%s sequence=%s: %r",
                    chunk.document_id,
                    chunk.sequence,
                    error,
                )
                self.read_failures += 1
                results.append(ExpandedHit(hit=hit, text=text))
                continue

            merged, extra = self._merge(chunk, window, budget)
            if not extra:
                results.append(ExpandedHit(hit=hit, text=text))
                continue

            added = len(merged) - len(text)
            budget -= max(0, added)
            expanded_count += 1
            results.append(
                ExpandedHit(
                    hit=hit,
                    text=merged,
                    expanded_from=tuple(extra),
                    window=(start, end),
                )
            )

        return results

    def _merge(
        self, chunk: DocumentChunk, window: Sequence[DocumentChunk], budget: int
    ) -> tuple[str, list[UUID]]:
        """Assemble parent first, then in-section neighbours, within budget.

        Priority is frozen and each item is charged as it is added:

            1. the matched chunk (never dropped)
            2. its parent, when it is a child
            3. neighbours from the SAME section

        Neighbours from another section are refused outright. ``sequence``
        adjacency is a storage fact, not a semantic one: the last chunk of
        "判别式" sits next to the first chunk of "韦达定理", and pulling the
        latter in on that basis would hand the model a confident-looking
        irrelevant passage.
        """
        parent = next(
            (
                item
                for item in window
                if chunk.parent_chunk_id is not None and item.chunk_id == chunk.parent_chunk_id
            ),
            None,
        )
        neighbours = sorted(
            (
                item
                for item in window
                if item.chunk_id != chunk.chunk_id
                and (parent is None or item.chunk_id != parent.chunk_id)
                and self._same_section(chunk, item)
            ),
            key=lambda item: item.sequence,
        )

        parts: list[str] = [chunk.text or ""]
        extra: list[UUID] = []
        spent = 0
        for item in ([parent] if parent is not None else []) + neighbours:
            piece = item.text or ""
            if not piece.strip():
                continue
            if spent + len(piece) > budget:
                continue  # a large parent must not block a small neighbour
            spent += len(piece)
            extra.append(item.chunk_id)
            parts.append(piece)
        if not extra:
            return chunk.text or "", []
        return "\n".join(part for part in parts if part), extra

    @staticmethod
    def _same_section(chunk: DocumentChunk, other: DocumentChunk) -> bool:
        """Whether ``other`` belongs to the same structural unit as ``chunk``.

        A document with no heading information anywhere is treated as one
        continuous section — otherwise expansion would never fire on the plain
        text files a student can also import.
        """
        if chunk.heading_path or other.heading_path:
            return chunk.heading_path == other.heading_path
        if chunk.section or other.section:
            return chunk.section == other.section
        return True


__all__ = [
    "ContextExpander",
    "ExpandedHit",
    "MAX_EXPANDED_ITEMS",
    "MAX_EXPANSION_CHARS",
    "NEIGHBOUR_RADIUS",
    "needs_expansion",
]
