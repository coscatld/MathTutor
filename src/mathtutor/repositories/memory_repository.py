"""Personal Memory KG repository contract.

Data-layer invariants (the same in BOTH implementations — they are the
security boundary, not a UI concern):

- owner scope: every query carries the owner; memory of another student
  is structurally unreachable (the id alone never crosses owners);
- ``retrievable`` reads enforce ``retrieval_enabled AND deleted_at IS
  NULL`` — user permission wins over the Router: a disabled memory is
  never returned to the assembler, no matter what the policy says;
- soft delete only: deleting a memory NEVER touches the Student Model
  (mastery/assessment/misconception are append-only elsewhere);
- authoritative facts (FORBIDDEN_MEMORY_TYPES) are rejected at the
  domain layer (``assert_memory_writable``); repositories store what the
  domain validated — nothing more.

The SQLite implementation lives in repositories/sqlite_memory.py with
the same contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol, Sequence
from uuid import UUID

from mathtutor.domain.memory import PersonalMemoryEdge, PersonalMemoryNode

MemoryCursor = tuple[datetime, datetime, UUID]


@dataclass(frozen=True)
class MemoryCounts:
    live: int
    enabled: int
    eligible: int


class MemoryRepository(Protocol):
    """Async personal-memory persistence contract (owner-scoped)."""

    async def add_node(
        self, student_id: str, node: PersonalMemoryNode
    ) -> PersonalMemoryNode: ...

    async def get_node(
        self, student_id: str, memory_id: UUID, *, include_deleted: bool = False
    ) -> PersonalMemoryNode | None: ...

    async def update_node(
        self, student_id: str, node: PersonalMemoryNode
    ) -> PersonalMemoryNode | None: ...

    async def patch_node(
        self,
        student_id: str,
        memory_id: UUID,
        *,
        expected_updated_at: datetime,
        object_json: dict | None = None,
        predicate: str | None = None,
        confidence: float | None = None,
    ) -> PersonalMemoryNode | None: ...

    async def confirm_node(
        self, student_id: str, memory_id: UUID, *, expected_updated_at: datetime
    ) -> PersonalMemoryNode | None: ...

    async def retrieval_counts(
        self, student_id: str, *, source_types: Sequence[str]
    ) -> MemoryCounts: ...

    async def list_recent_retrievable(
        self,
        student_id: str,
        *,
        source_types: Sequence[str],
        limit: int,
        before: MemoryCursor | None = None,
    ) -> list[PersonalMemoryNode]: ...

    async def soft_delete_node(self, student_id: str, memory_id: UUID) -> bool: ...

    async def set_retrieval_enabled(
        self,
        student_id: str,
        memory_id: UUID,
        enabled: bool,
        *,
        expected_updated_at: datetime | None = None,
    ) -> PersonalMemoryNode | None: ...

    async def list_nodes(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]: ...

    async def list_retrievable(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        source_types: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]: ...

    async def add_edge(
        self, student_id: str, edge: PersonalMemoryEdge
    ) -> PersonalMemoryEdge: ...

    async def list_edges(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[PersonalMemoryEdge]: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["MemoryRepository"]
