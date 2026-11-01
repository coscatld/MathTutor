"""Personal Memory KG application service — the ONLY write/read surface.

Boundary enforcement (design doc, the Student Model authority boundary):

- this service CANNOT touch the Student Model: it has no reference to
  mastery/assessment/misconception/verification state, and the domain
  layer (``assert_memory_writable``) rejects FORBIDDEN_MEMORY_TYPES at
  write time — authoritative facts can never enter the personal KG;
- deleting or disabling a memory NEVER changes mastery;
- MODEL_INFERRED memories are always distinguishable (source_type) and
  confirmable/deletable by the user — ``confirm`` is the only legal
  source-type transition (MODEL_INFERRED → USER_CONFIRMED);
- reads for retrieval go through ``retrievable`` which enforces
  ``retrieval_enabled`` at the DATA layer — user permission wins over
  the Router; the assembler can never pull a disabled memory.

The service works against the :class:`MemoryRepository` Protocol —
in-memory for tests, SQLite-backed for the product.
"""

from __future__ import annotations

from datetime import datetime
from typing import Sequence
from uuid import UUID

from mathtutor.domain.memory import (
    MemoryNotFoundError,
    PersonalMemoryEdge,
    PersonalMemoryNode,
    assert_memory_writable,
)
from mathtutor.repositories.memory_repository import MemoryRepository
from mathtutor.security.scopes import student_uuid


class PersonalMemoryService:
    """User-controlled preference/goal/note KG (non-authoritative)."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------- writes

    async def add_explicit(
        self,
        student_id: str,
        *,
        memory_type: str,
        subject: str,
        predicate: str,
        object_json: dict,
        confidence: float = 0.9,
    ) -> PersonalMemoryNode:
        """A memory the student wrote themselves (USER_EXPLICIT)."""
        assert_memory_writable(memory_type, "USER_EXPLICIT")
        node = PersonalMemoryNode(
            student_id=student_uuid(student_id),
            memory_type=memory_type,  # type: ignore[arg-type]
            subject=subject,
            predicate=predicate,
            object_json=object_json,
            source_type="USER_EXPLICIT",
            confidence=confidence,
        )
        return await self._repo.add_node(student_id, node)

    async def add_inference(
        self,
        student_id: str,
        *,
        subject: str,
        predicate: str,
        object_json: dict,
        confidence: float = 0.5,
    ) -> PersonalMemoryNode:
        """An AI inference (MODEL_INFERRED) — distinguishable, confirmable.

        The caller (a future inference pipeline) may only propose
        preferences/notes — never authoritative facts; the domain guard
        rejects anything else.
        """
        assert_memory_writable("ai_inference", "MODEL_INFERRED")
        node = PersonalMemoryNode(
            student_id=student_uuid(student_id),
            memory_type="ai_inference",
            subject=subject,
            predicate=predicate,
            object_json=object_json,
            source_type="MODEL_INFERRED",
            confidence=confidence,
        )
        return await self._repo.add_node(student_id, node)

    async def confirm(self, student_id: str, memory_id: UUID, *,
                      expected_updated_at: datetime | None = None) -> PersonalMemoryNode:
        """Confirm only the source, with no implicit retrieval authorization."""
        node = await self._repo.get_node(student_id, memory_id)
        if node is None:
            raise MemoryNotFoundError(f"memory not found: {memory_id}")
        result = await self._repo.confirm_node(student_id, memory_id,
            expected_updated_at=expected_updated_at if expected_updated_at is not None else node.updated_at)
        if result is None:
            raise MemoryNotFoundError(f"memory not found: {memory_id}")
        return result

    async def update(self, student_id: str, memory_id: UUID, *,
                     object_json: dict | None = None, predicate: str | None = None,
                     confidence: float | None = None,
                     expected_updated_at: datetime | None = None) -> PersonalMemoryNode:
        """Patch content fields only; stale snapshots never restore permission."""
        node = await self._repo.get_node(student_id, memory_id)
        if node is None:
            raise MemoryNotFoundError(f"memory not found: {memory_id}")
        result = await self._repo.patch_node(student_id, memory_id,
            expected_updated_at=expected_updated_at if expected_updated_at is not None else node.updated_at,
            object_json=object_json, predicate=predicate, confidence=confidence)
        if result is None:
            raise MemoryNotFoundError(f"memory not found: {memory_id}")
        return result

    async def delete(self, student_id: str, memory_id: UUID) -> bool:
        """Soft delete. Does NOT touch mastery (by construction)."""
        return await self._repo.soft_delete_node(student_id, memory_id)

    async def set_retrieval_enabled(
        self, student_id: str, memory_id: UUID, enabled: bool, *, expected_updated_at: datetime | None = None
    ) -> PersonalMemoryNode:
        node = await self._repo.set_retrieval_enabled(student_id, memory_id, enabled,
                                                       expected_updated_at=expected_updated_at)
        if node is None:
            raise MemoryNotFoundError(f"memory not found: {memory_id}")
        return node

    async def relate(
        self,
        student_id: str,
        *,
        source_node_id: UUID,
        relation: str,
        target_node_id: UUID,
        confidence: float = 0.5,
    ) -> PersonalMemoryEdge:
        """Add a KG edge between two of the student's own memories."""
        edge = PersonalMemoryEdge(
            student_id=student_uuid(student_id),
            source_node_id=source_node_id,
            relation=relation,
            target_node_id=target_node_id,
            confidence=confidence,
        )
        return await self._repo.add_edge(student_id, edge)

    # -------------------------------------------------------------- reads

    async def list(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]:
        """All live memories (including retrieval-disabled — user view)."""
        return await self._repo.list_nodes(
            student_id, memory_type=memory_type, limit=limit
        )

    async def list_retrievable(
        self,
        student_id: str,
        *,
        memory_type: str | None = None,
        source_types: Sequence[str] | None = None,
        limit: int | None = None,
    ) -> list[PersonalMemoryNode]:
        """Memories the assembler may see (data-layer permission enforced)."""
        return await self._repo.list_retrievable(
            student_id,
            memory_type=memory_type,
            source_types=source_types,
            limit=limit,
        )

    async def list_edges(self, student_id: str) -> list[PersonalMemoryEdge]:
        return await self._repo.list_edges(student_id)


__all__ = ["PersonalMemoryService"]
