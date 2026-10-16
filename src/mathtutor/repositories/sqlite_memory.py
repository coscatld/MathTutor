"""SQLite personal-memory persistence (Phase 5/6 — infrastructure).

Same contract and invariants as repositories/memory_repository.py
(owner scope, retrieval_enabled + deleted_at IS NULL on retrievable
reads, soft delete only). These functions move validated domain models
into one short transaction — READ → COMPUTE → COMMIT, no LLM or long
work inside a transaction.

The FK column stores the RAW owner string (Phase 0 identity, matching
sqlite_education); inserts ensure the identity rows first
(``ensure_student``) and reads convert raw → ``student_uuid`` when
building domain models.

Personal memory NEVER stores authoritative educational facts — the
domain layer rejects FORBIDDEN_MEMORY_TYPES before anything reaches
this module.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.domain.memory import PersonalMemoryEdge, PersonalMemoryNode
from mathtutor.infrastructure.schema import (
    personal_memory_edges,
    personal_memory_nodes,
)
from mathtutor.repositories.sqlite_runtime import ensure_student
from mathtutor.security.scopes import student_uuid


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


async def _next_updated_at(
    conn: AsyncConnection, student_id: str, *, not_before: str | None = None
) -> str:
    """Reserve the SQLite writer before reading an owner's logical clock.

    The no-op UPDATE takes a write reservation even for an empty owner, so
    separate connections cannot read the same maximum then publish a tie.
    The reservation lives until the caller's existing transaction commits.
    """
    owner_node = (
        select(personal_memory_nodes.c.memory_id)
        .where(personal_memory_nodes.c.student_id == student_id)
        .limit(1)
        .correlate(None)
        .scalar_subquery()
    )
    await conn.execute(
        personal_memory_nodes.update()
        .where(personal_memory_nodes.c.student_id == student_id,
               personal_memory_nodes.c.memory_id == owner_node)
        .values(updated_at=personal_memory_nodes.c.updated_at)
    )
    rows = await conn.execute(
        select(personal_memory_nodes.c.updated_at, personal_memory_nodes.c.created_at)
        .where(personal_memory_nodes.c.student_id == student_id)
    )
    previous = [_parse_dt(value) for row in rows for value in row if value]
    timestamp = datetime.fromisoformat(_now())
    if not_before is not None:
        timestamp = max(timestamp, datetime.fromisoformat(not_before))
    if previous:
        timestamp = max(timestamp, max(previous) + timedelta(microseconds=1))
    return timestamp.isoformat()


# ------------------------------------------------------------- row models

def _node_from_row(row: Any) -> PersonalMemoryNode:
    return PersonalMemoryNode(
        memory_id=UUID(row.memory_id),
        student_id=student_uuid(row.student_id),  # stored raw, modeled as UUID
        memory_type=row.memory_type,
        subject=row.subject,
        predicate=row.predicate,
        object_json=row.object_json or {},
        source_type=row.source_type,
        confidence=float(row.confidence),
        retrieval_enabled=bool(row.retrieval_enabled),
        created_at=_parse_dt(row.created_at) or datetime.now(timezone.utc),
        updated_at=_parse_dt(row.updated_at) or datetime.now(timezone.utc),
        deleted_at=_parse_dt(row.deleted_at),
    )


def _edge_from_row(row: Any) -> PersonalMemoryEdge:
    return PersonalMemoryEdge(
        edge_id=UUID(row.edge_id),
        student_id=student_uuid(row.student_id),
        source_node_id=UUID(row.source_node_id),
        relation=row.relation,
        target_node_id=UUID(row.target_node_id),
        confidence=float(row.confidence),
        created_at=_parse_dt(row.created_at) or datetime.now(timezone.utc),
        deleted_at=_parse_dt(row.deleted_at),
    )


# ---------------------------------------------------------------- writes

async def insert_personal_memory_node(
    conn: AsyncConnection, *, student_id: str, node: PersonalMemoryNode
) -> UUID:
    created_at = _now()
    updated_at = await _next_updated_at(conn, student_id, not_before=created_at)
    await ensure_student(conn, student_id=student_id)
    await conn.execute(
        personal_memory_nodes.insert().values(
            memory_id=str(node.memory_id),
            student_id=student_id,  # raw owner — FK into student_profiles
            memory_type=node.memory_type,
            subject=node.subject,
            predicate=node.predicate,
            object_json=node.object_json,
            source_type=node.source_type,
            confidence=node.confidence,
            retrieval_enabled=1 if node.retrieval_enabled else 0,
            created_at=created_at,
            updated_at=updated_at,
            deleted_at=None,
        )
    )
    return node.memory_id


async def update_personal_memory_node(
    conn: AsyncConnection, *, student_id: str, node: PersonalMemoryNode
) -> PersonalMemoryNode | None:
    """Owner-scoped full update (bumps updated_at). Returns the new state."""
    updated_at = await _next_updated_at(conn, student_id)
    result = await conn.execute(
        personal_memory_nodes.update()
        .where(
            personal_memory_nodes.c.memory_id == str(node.memory_id),
            personal_memory_nodes.c.student_id == student_id,
            personal_memory_nodes.c.deleted_at.is_(None),
        )
        .values(
            memory_type=node.memory_type,
            subject=node.subject,
            predicate=node.predicate,
            object_json=node.object_json,
            source_type=node.source_type,
            confidence=node.confidence,
            retrieval_enabled=1 if node.retrieval_enabled else 0,
            updated_at=updated_at,
        )
    )
    if result.rowcount == 0:
        return None
    return await select_personal_memory_node(
        conn, student_id=student_id, memory_id=node.memory_id
    )


async def soft_delete_personal_memory_node(
    conn: AsyncConnection, *, student_id: str, memory_id: UUID
) -> bool:
    result = await conn.execute(
        personal_memory_nodes.update()
        .where(
            personal_memory_nodes.c.memory_id == str(memory_id),
            personal_memory_nodes.c.student_id == student_id,
            personal_memory_nodes.c.deleted_at.is_(None),
        )
        .values(deleted_at=_now())
    )
    return result.rowcount > 0


async def set_memory_retrieval_enabled(
    conn: AsyncConnection, *, student_id: str, memory_id: UUID, enabled: bool
) -> PersonalMemoryNode | None:
    updated_at = await _next_updated_at(conn, student_id)
    result = await conn.execute(
        personal_memory_nodes.update()
        .where(
            personal_memory_nodes.c.memory_id == str(memory_id),
            personal_memory_nodes.c.student_id == student_id,
            personal_memory_nodes.c.deleted_at.is_(None),
        )
        .values(retrieval_enabled=1 if enabled else 0, updated_at=updated_at)
    )
    if result.rowcount == 0:
        return None
    return await select_personal_memory_node(
        conn, student_id=student_id, memory_id=memory_id
    )


async def insert_personal_memory_edge(
    conn: AsyncConnection, *, student_id: str, edge: PersonalMemoryEdge
) -> UUID:
    await ensure_student(conn, student_id=student_id)
    await conn.execute(
        personal_memory_edges.insert().values(
            edge_id=str(edge.edge_id),
            student_id=student_id,  # raw owner — FK into student_profiles
            source_node_id=str(edge.source_node_id),
            relation=edge.relation,
            target_node_id=str(edge.target_node_id),
            confidence=edge.confidence,
            created_at=_now(),
            deleted_at=None,
        )
    )
    return edge.edge_id


# ----------------------------------------------------------------- reads

async def select_personal_memory_node(
    conn: AsyncConnection,
    *,
    student_id: str,
    memory_id: UUID,
    include_deleted: bool = False,
) -> PersonalMemoryNode | None:
    stmt = select(personal_memory_nodes).where(
        personal_memory_nodes.c.memory_id == str(memory_id),
        personal_memory_nodes.c.student_id == student_id,
    )
    if not include_deleted:
        stmt = stmt.where(personal_memory_nodes.c.deleted_at.is_(None))
    row = (await conn.execute(stmt)).first()
    return _node_from_row(row) if row is not None else None


async def list_personal_memory_nodes(
    conn: AsyncConnection,
    *,
    student_id: str,
    memory_type: str | None = None,
    include_deleted: bool = False,
    limit: int | None = None,
) -> list[PersonalMemoryNode]:
    stmt = select(personal_memory_nodes).where(
        personal_memory_nodes.c.student_id == student_id
    )
    if not include_deleted:
        stmt = stmt.where(personal_memory_nodes.c.deleted_at.is_(None))
    if memory_type is not None:
        stmt = stmt.where(personal_memory_nodes.c.memory_type == memory_type)
    stmt = stmt.order_by(personal_memory_nodes.c.created_at)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await conn.execute(stmt)).all()
    return [_node_from_row(row) for row in rows]


async def list_retrievable_personal_memory_nodes(
    conn: AsyncConnection,
    *,
    student_id: str,
    memory_type: str | None = None,
    source_types: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[PersonalMemoryNode]:
    """Data-layer enforcement of user permission: only retrieval_enabled,
    non-deleted nodes come back — regardless of any policy demand."""
    stmt = select(personal_memory_nodes).where(
        personal_memory_nodes.c.student_id == student_id,
        personal_memory_nodes.c.retrieval_enabled == 1,
        personal_memory_nodes.c.deleted_at.is_(None),
    )
    if memory_type is not None:
        stmt = stmt.where(personal_memory_nodes.c.memory_type == memory_type)
    if source_types is not None:
        stmt = stmt.where(personal_memory_nodes.c.source_type.in_(list(source_types)))
    stmt = stmt.order_by(personal_memory_nodes.c.created_at)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = (await conn.execute(stmt)).all()
    return [_node_from_row(row) for row in rows]


async def list_personal_memory_edges(
    conn: AsyncConnection, *, student_id: str, include_deleted: bool = False
) -> list[PersonalMemoryEdge]:
    stmt = select(personal_memory_edges).where(
        personal_memory_edges.c.student_id == student_id
    )
    if not include_deleted:
        stmt = stmt.where(personal_memory_edges.c.deleted_at.is_(None))
    stmt = stmt.order_by(personal_memory_edges.c.created_at)
    rows = (await conn.execute(stmt)).all()
    return [_edge_from_row(row) for row in rows]


__all__ = [
    "insert_personal_memory_edge",
    "insert_personal_memory_node",
    "list_personal_memory_edges",
    "list_personal_memory_nodes",
    "list_retrievable_personal_memory_nodes",
    "select_personal_memory_node",
    "set_memory_retrieval_enabled",
    "soft_delete_personal_memory_node",
    "update_personal_memory_node",
]
