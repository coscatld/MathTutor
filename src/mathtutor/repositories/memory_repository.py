"""Personal Memory KG repository contract + in-memory implementation.

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
from datetime import datetime, timedelta, timezone
from typing import Protocol, Sequence
from uuid import UUID

from mathtutor.domain.memory import MemoryConflictError, PersonalMemoryEdge, PersonalMemoryNode, confirm_inference
from mathtutor.security.scopes import student_uuid


MemoryCursor = tuple[datetime, datetime, UUID]


@dataclass(frozen=True)
class MemoryCounts:
    live: int
    enabled: int
    eligible: int


class MemoryRepository(Protocol):
    """Async personal-memory persistence contract (owner-scoped)."""

    async def add_node(self, student_id: str, node: PersonalMemoryNode) -> PersonalMemoryNode: ...

    async def get_node(
        self, student_id: str, memory_id: UUID, *, include_deleted: bool = False
    ) -> PersonalMemoryNode | None: ...

    async def update_node(
        self, student_id: str, node: PersonalMemoryNode
    ) -> PersonalMemoryNode | None: ...

    async def patch_node(self, student_id: str, memory_id: UUID, *, expected_updated_at: datetime,
                         object_json: dict | None = None, predicate: str | None = None,
                         confidence: float | None = None) -> PersonalMemoryNode | None: ...

    async def confirm_node(self, student_id: str, memory_id: UUID, *,
                           expected_updated_at: datetime) -> PersonalMemoryNode | None: ...

    async def retrieval_counts(self, student_id: str, *, source_types: Sequence[str]) -> MemoryCounts: ...

    async def list_recent_retrievable(self, student_id: str, *, source_types: Sequence[str],
                                    limit: int, before: MemoryCursor | None = None) -> list[PersonalMemoryNode]: ...

    async def soft_delete_node(self, student_id: str, memory_id: UUID) -> bool: ...

    async def set_retrieval_enabled(
        self, student_id: str, memory_id: UUID, enabled: bool, *, expected_updated_at: datetime | None = None
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

    async def add_edge(self, student_id: str, edge: PersonalMemoryEdge) -> PersonalMemoryEdge: ...

    async def list_edges(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[PersonalMemoryEdge]: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


class InMemoryMemoryRepository:
    """Process-local memory KG (dev/tests). Enforces the same invariants."""

    def __init__(self) -> None:
        self._nodes: dict[UUID, PersonalMemoryNode] = {}
        self._edges: dict[UUID, PersonalMemoryEdge] = {}

    def _next_updated_at(self, owner: UUID, *, not_before: datetime | None = None) -> datetime:
        """Order owner writes even when the wall clock repeats or moves back."""
        timestamp = _now()
        if not_before is not None:
            timestamp = max(timestamp, not_before)
        previous = [time for node in self._nodes.values() if node.student_id == owner
                    for time in (node.updated_at, node.created_at)]
        if previous:
            timestamp = max(timestamp, max(previous) + timedelta(microseconds=1))
        return timestamp

    # ------------------------------------------------------------- nodes

    async def add_node(self, student_id: str, node: PersonalMemoryNode) -> PersonalMemoryNode:
        owner = student_uuid(student_id)
        stored = node.model_copy(update={
            "student_id": owner,
            "updated_at": self._next_updated_at(owner, not_before=max(node.created_at, node.updated_at)),
        })
        self._nodes[stored.memory_id] = stored
        return stored

    async def get_node(
        self, student_id: str, memory_id: UUID, *, include_deleted: bool = False
    ) -> PersonalMemoryNode | None:
        node = self._nodes.get(memory_id)
        if node is None or node.student_id != student_uuid(student_id):
            return None
        if node.deleted_at is not None and not include_deleted:
            return None
        return node

    async def update_node(self, student_id: str, node: PersonalMemoryNode) -> PersonalMemoryNode | None:
        """Compatibility surface: content only, with the supplied snapshot CAS."""
        return await self.patch_node(student_id, node.memory_id, expected_updated_at=node.updated_at,
                                     object_json=node.object_json, predicate=node.predicate, confidence=node.confidence)

    async def patch_node(self, student_id: str, memory_id: UUID, *, expected_updated_at: datetime,
                         object_json: dict | None = None, predicate: str | None = None,
                         confidence: float | None = None) -> PersonalMemoryNode | None:
        current = await self.get_node(student_id, memory_id)
        if current is None:
            return None
        if current.updated_at != expected_updated_at:
            raise MemoryConflictError(current)
        fields = {key: value for key, value in {"object_json": object_json, "predicate": predicate,
                                               "confidence": confidence}.items() if value is not None}
        stored = PersonalMemoryNode.model_validate({**current.model_dump(), **fields,
                     "updated_at": self._next_updated_at(current.student_id)})
        self._nodes[memory_id] = stored
        return stored

    async def confirm_node(self, student_id: str, memory_id: UUID, *,
                           expected_updated_at: datetime) -> PersonalMemoryNode | None:
        current = await self.get_node(student_id, memory_id)
        if current is None:
            return None
        confirmed = confirm_inference(current)
        if confirmed is current:
            return current
        if current.updated_at != expected_updated_at:
            raise MemoryConflictError(current)
        stored = current.model_copy(update={"source_type": "USER_CONFIRMED",
                                            "updated_at": self._next_updated_at(current.student_id)})
        self._nodes[memory_id] = stored
        return stored

    async def soft_delete_node(self, student_id: str, memory_id: UUID) -> bool:
        owner = student_uuid(student_id)
        current = self._nodes.get(memory_id)
        if current is None or current.student_id != owner or current.deleted_at is not None:
            return False
        self._nodes[memory_id] = current.model_copy(update={"deleted_at": _now()})
        return True

    async def set_retrieval_enabled(
        self, student_id: str, memory_id: UUID, enabled: bool, *, expected_updated_at: datetime | None = None
    ) -> PersonalMemoryNode | None:
        owner = student_uuid(student_id)
        current = self._nodes.get(memory_id)
        if current is None or current.student_id != owner or current.deleted_at is not None:
            return None
        if expected_updated_at is not None and current.updated_at != expected_updated_at:
            raise MemoryConflictError(current)
        stored = current.model_copy(
            update={"retrieval_enabled": enabled, "updated_at": self._next_updated_at(owner)}
        )
        self._nodes[memory_id] = stored
        return stored

    async def list_nodes(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]:
        owner = student_uuid(student_id)
        rows = [
            node
            for node in self._nodes.values()
            if node.student_id == owner
            and (include_deleted or node.deleted_at is None)
            and (memory_type is None or node.memory_type == memory_type)
        ]
        rows.sort(key=lambda node: node.created_at)
        return rows[:limit] if limit is not None else rows

    async def list_retrievable(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        source_types: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]:
        owner = student_uuid(student_id)
        wanted_sources = set(source_types) if source_types is not None else None
        rows = [
            node
            for node in self._nodes.values()
            if node.student_id == owner
            and node.retrieval_enabled
            and node.deleted_at is None
            and (memory_type is None or node.memory_type == memory_type)
            and (wanted_sources is None or node.source_type in wanted_sources)
        ]
        rows.sort(key=lambda node: node.created_at)
        return rows[:limit] if limit is not None else rows

    async def retrieval_counts(self, student_id: str, *, source_types: Sequence[str]) -> MemoryCounts:
        owner, sources = student_uuid(student_id), set(source_types)
        live = enabled = eligible = 0
        for node in self._nodes.values():
            if node.student_id != owner or node.deleted_at is not None:
                continue
            live += 1
            if node.retrieval_enabled:
                enabled += 1
                eligible += int(node.source_type in sources)
        return MemoryCounts(live, enabled, eligible)

    async def list_recent_retrievable(self, student_id: str, *, source_types: Sequence[str],
                                    limit: int, before: MemoryCursor | None = None) -> list[PersonalMemoryNode]:
        if limit < 1:
            raise ValueError("memory page limit must be positive")
        owner, sources = student_uuid(student_id), set(source_types)
        key = lambda node: (node.updated_at, node.created_at, node.memory_id)
        rows = [node for node in self._nodes.values() if node.student_id == owner
                and node.is_retrievable() and node.source_type in sources
                and (before is None or key(node) < before)]
        rows.sort(key=key, reverse=True)
        return rows[:limit]

    # ------------------------------------------------------------- edges

    async def add_edge(self, student_id: str, edge: PersonalMemoryEdge) -> PersonalMemoryEdge:
        owner = student_uuid(student_id)
        stored = edge.model_copy(update={"student_id": owner})
        self._edges[stored.edge_id] = stored
        return stored

    async def list_edges(
        self, student_id: str, *, include_deleted: bool = False
    ) -> list[PersonalMemoryEdge]:
        owner = student_uuid(student_id)
        rows = [
            edge
            for edge in self._edges.values()
            if edge.student_id == owner
            and (include_deleted or edge.deleted_at is None)
        ]
        rows.sort(key=lambda edge: edge.created_at)
        return rows


__all__ = ["InMemoryMemoryRepository", "MemoryRepository"]
