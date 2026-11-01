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

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.domain.memory import MemoryConflictError, PersonalMemoryEdge, PersonalMemoryNode, confirm_inference
from mathtutor.repositories.memory_repository import MemoryCounts, MemoryCursor
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
        select(func.max(personal_memory_nodes.c.updated_at), func.max(personal_memory_nodes.c.created_at))
        .where(personal_memory_nodes.c.student_id == student_id)
    )
    previous = [_parse_dt(value) for value in rows.one() if value]
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


def _version(value: datetime) -> str:
    return (value.astimezone(timezone.utc) if value.tzinfo is not None else value).isoformat()


def _live_node(student_id: str, memory_id: UUID):
    return (personal_memory_nodes.c.student_id == student_id,
            personal_memory_nodes.c.memory_id == str(memory_id),
            personal_memory_nodes.c.deleted_at.is_(None))


async def _cas_result(conn, student_id, memory_id, result):
    latest = await select_personal_memory_node(conn, student_id=student_id, memory_id=memory_id)
    if result.rowcount == 0 and latest is not None:
        raise MemoryConflictError(latest)
    return latest


async def update_personal_memory_node(conn: AsyncConnection, *, student_id: str,
                                      node: PersonalMemoryNode) -> PersonalMemoryNode | None:
    """Compatibility surface: never write permission/source/identity fields."""
    return await patch_personal_memory_node(conn, student_id=student_id, memory_id=node.memory_id,
        expected_updated_at=node.updated_at, object_json=node.object_json,
        predicate=node.predicate, confidence=node.confidence)


async def patch_personal_memory_node(conn: AsyncConnection, *, student_id: str, memory_id: UUID,
                                    expected_updated_at: datetime, object_json: dict | None = None,
                                    predicate: str | None = None, confidence: float | None = None
                                    ) -> PersonalMemoryNode | None:
    updated_at = await _next_updated_at(conn, student_id)
    fields = {key: value for key, value in {"object_json": object_json, "predicate": predicate,
                                           "confidence": confidence}.items() if value is not None}
    if confidence is not None and not 0 <= confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")
    result = await conn.execute(personal_memory_nodes.update().where(
        *_live_node(student_id, memory_id),
        personal_memory_nodes.c.updated_at == _version(expected_updated_at),
    ).values(**fields, updated_at=updated_at))
    return await _cas_result(conn, student_id, memory_id, result)


async def confirm_personal_memory_node(conn: AsyncConnection, *, student_id: str, memory_id: UUID,
                                      expected_updated_at: datetime) -> PersonalMemoryNode | None:
    updated_at = await _next_updated_at(conn, student_id)
    current = await select_personal_memory_node(conn, student_id=student_id, memory_id=memory_id)
    if current is None:
        return None
    if confirm_inference(current) is current:
        return current  # already confirmed; no timestamp/permission/content writes
    result = await conn.execute(personal_memory_nodes.update().where(
        *_live_node(student_id, memory_id),
        personal_memory_nodes.c.updated_at == _version(expected_updated_at),
        personal_memory_nodes.c.source_type == "MODEL_INFERRED",
    ).values(source_type="USER_CONFIRMED", updated_at=updated_at))
    return await _cas_result(conn, student_id, memory_id, result)


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


async def set_memory_retrieval_enabled(conn: AsyncConnection, *, student_id: str,
                                      memory_id: UUID, enabled: bool,
                                      expected_updated_at: datetime | None = None) -> PersonalMemoryNode | None:
    updated_at = await _next_updated_at(conn, student_id)
    stmt = personal_memory_nodes.update().where(*_live_node(student_id, memory_id))
    if expected_updated_at is not None:
        stmt = stmt.where(personal_memory_nodes.c.updated_at == _version(expected_updated_at))
    result = await conn.execute(stmt.values(retrieval_enabled=int(enabled), updated_at=updated_at))
    return await _cas_result(conn, student_id, memory_id, result)


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


async def personal_memory_retrieval_counts(conn: AsyncConnection, *, student_id: str,
                                          source_types: Sequence[str]) -> MemoryCounts:
    enabled = personal_memory_nodes.c.retrieval_enabled == 1
    eligible = and_(enabled, personal_memory_nodes.c.source_type.in_(list(source_types)))
    row = (await conn.execute(select(
        func.count(), func.coalesce(func.sum(case((enabled, 1), else_=0)), 0),
        func.coalesce(func.sum(case((eligible, 1), else_=0)), 0),
    ).select_from(personal_memory_nodes).where(personal_memory_nodes.c.student_id == student_id,
                                             personal_memory_nodes.c.deleted_at.is_(None)))).one()
    return MemoryCounts(*map(int, row))


async def list_recent_retrievable_memories(conn: AsyncConnection, *, student_id: str,
                                         source_types: Sequence[str], limit: int,
                                         before: MemoryCursor | None = None) -> list[PersonalMemoryNode]:
    if limit < 1:
        raise ValueError("memory page limit must be positive")
    table = personal_memory_nodes.c
    stmt = select(personal_memory_nodes).where(table.student_id == student_id,
        table.retrieval_enabled == 1, table.deleted_at.is_(None), table.source_type.in_(list(source_types)))
    if before is not None:
        updated, created, memory_id = before
        stmt = stmt.where(or_(table.updated_at < _version(updated),
            and_(table.updated_at == _version(updated), table.created_at < _version(created)),
            and_(table.updated_at == _version(updated), table.created_at == _version(created),
                 table.memory_id < str(memory_id))))
    rows = (await conn.execute(stmt.order_by(table.updated_at.desc(), table.created_at.desc(),
                                           table.memory_id.desc()).limit(limit))).all()
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
    "patch_personal_memory_node",
    "confirm_personal_memory_node",
    "personal_memory_retrieval_counts",
    "list_recent_retrievable_memories",
]
