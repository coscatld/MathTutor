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

from typing import Sequence
from uuid import UUID

from mathtutor.domain.memory import (
    PersonalMemoryEdge,
    PersonalMemoryNode,
    assert_memory_writable,
    confirm_inference,
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

    async def confirm(self, student_id: str, memory_id: UUID) -> PersonalMemoryNode:
        """User confirms a MODEL_INFERRED memory → USER_CONFIRMED.

        Raises ValueError when the memory is not MODEL_INFERRED (a
        USER_EXPLICIT memory is already user truth and needs no
        confirmation).
        """
        node = await self._repo.get_node(student_id, memory_id)
        if node is None:
            raise ValueError(f"memory not found: {memory_id}")
        confirmed = confirm_inference(node)
        if confirmed is node:
            return node  # already USER_CONFIRMED — idempotent
        updated = await self._repo.update_node(student_id, confirmed)
        if updated is None:
            raise ValueError(f"memory not updatable: {memory_id}")
        return updated

    async def update(
        self,
        student_id: str,
        memory_id: UUID,
        *,
        object_json: dict | None = None,
        predicate: str | None = None,
        confidence: float | None = None,
    ) -> PersonalMemoryNode:
        """Edit a user memory's content (never its source_type)."""
        node = await self._repo.get_node(student_id, memory_id)
        if node is None:
            raise ValueError(f"memory not found: {memory_id}")
        updated = node.model_copy(
            update={
                key: value
                for key, value in {
                    "object_json": object_json,
                    "predicate": predicate,
                    "confidence": confidence,
                }.items()
                if value is not None
            }
        )
        result = await self._repo.update_node(student_id, updated)
        if result is None:
            raise ValueError(f"memory not updatable: {memory_id}")
        return result

    async def delete(self, student_id: str, memory_id: UUID) -> bool:
        """Soft delete. Does NOT touch mastery (by construction)."""
        return await self._repo.soft_delete_node(student_id, memory_id)

    async def set_retrieval_enabled(
        self, student_id: str, memory_id: UUID, enabled: bool
    ) -> PersonalMemoryNode:
        node = await self._repo.set_retrieval_enabled(student_id, memory_id, enabled)
        if node is None:
            raise ValueError(f"memory not found: {memory_id}")
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
