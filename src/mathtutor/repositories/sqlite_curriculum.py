"""SQLite curriculum catalog (Phase 6 §9.1): versions, nodes, edges.

Contract + in-memory implementation + SQLite implementation, one file:

- ``CurriculumRepository`` — the async contract the catalog service uses.
- ``InMemoryCurriculumRepository`` — process-local (dev/tests), mirrors the
  SQLite structural constraints (version existence, code uniqueness, node
  existence) so the two implementations stay behaviorally aligned.
- ``SQLiteCurriculumRepository`` — durable store over ``MathTutorUow`` on
  the Phase 6 tables (``curriculum_versions`` / ``curriculum_nodes`` /
  ``curriculum_edges``), short UoW transactions, FK + unique constraints
  enforced by the database itself.

Business rules are enforced by the catalog SERVICE
(``application/curriculum_catalog.py``) — version immutability after
publish, edge kind constraints, cross-version edges, self-loops. The
repositories only mirror the *storage-level* constraints (uniqueness,
existence, FK parity), exactly like ``sqlite_practice.py`` keeps the
release gate in the service and the DB constraints in the tables.

``validate_graph`` is a pure defensive checker: it never raises, it
returns an issue list (orphan nodes, duplicate codes, dangling edges,
self-loops, duplicate edges, invalid edge kinds, unreachable concepts).
It is runnable on any node/edge data — including data that did not come
through the service (bulk import, restored backups, corrupted stores).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from mathtutor.domain.curriculum import (
    CurriculumEdge,
    CurriculumNode,
    CurriculumVersion,
)
from mathtutor.infrastructure.schema import (
    curriculum_edges,
    curriculum_nodes,
    curriculum_versions,
)


# ------------------------------------------------------------------ errors


class CurriculumCatalogError(Exception):
    """Base class for curriculum catalog failures."""


class DuplicateCodeError(CurriculumCatalogError):
    """A version code (or a node code inside one version) already exists."""


class VersionImmutableError(CurriculumCatalogError):
    """A published/archived version is immutable: node/edge writes refused."""


class VersionNotFoundError(CurriculumCatalogError):
    """No curriculum version with this id."""


class NodeNotFoundError(CurriculumCatalogError):
    """No curriculum node with this id."""


class InvalidEdgeError(CurriculumCatalogError):
    """An edge violates catalog invariants (dangling / cross-version /
    self-loop / kind constraint)."""


# ------------------------------------------------------------------ shapes


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding of the defensive graph checker."""

    severity: str  # "error" | "warning"
    code: str  # machine-readable: orphan_node | duplicate_node_code | ...
    message: str
    node_id: UUID | None = None
    edge_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CurriculumGraph:
    """One version with its nodes and edges (loaded atomically)."""

    version: CurriculumVersion
    nodes: tuple[CurriculumNode, ...]
    edges: tuple[CurriculumEdge, ...]

    def nodes_of_kind(self, kind: str) -> list[CurriculumNode]:
        return [node for node in self.nodes if node.kind == kind]

    def node(self, node_id: UUID) -> CurriculumNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None


# ------------------------------------------------------------ edge rules


def _check_edge_kind(from_node: CurriculumNode, to_node: CurriculumNode, kind: str) -> None:
    """Kind matrix for directed edges (spec §9.1)."""
    if kind == "PREREQUISITE_OF":
        if from_node.kind != "skill" or to_node.kind != "skill":
            raise InvalidEdgeError(
                f"PREREQUISITE_OF 只能 skill→skill（实际 {from_node.kind}→{to_node.kind}）"
            )
    elif kind == "PART_OF":
        ok = (from_node.kind == "chapter" and to_node.kind == "concept") or (
            from_node.kind == "concept" and to_node.kind == "skill"
        )
        if not ok:
            raise InvalidEdgeError(
                f"PART_OF 必须是 chapter→concept 或 concept→skill（实际 "
                f"{from_node.kind}→{to_node.kind}）"
            )
    elif kind == "RELATED_TO":
        if from_node.kind != to_node.kind:
            raise InvalidEdgeError(
                f"RELATED_TO 只能同 kind 节点之间（实际 {from_node.kind}→{to_node.kind}）"
            )
    else:
        raise InvalidEdgeError(f"未知边类型: {kind!r}")


def check_edge(version_id: UUID, nodes: Sequence[CurriculumNode], edge: CurriculumEdge) -> None:
    """Service-level edge validation; raises :class:`InvalidEdgeError`.

    Checks: endpoints exist (no dangling), both endpoints belong to the
    SAME version (no cross-version edges), no self-loop, kind matrix.
    """
    if edge.version_id != version_id:
        raise InvalidEdgeError("edge 不属于该版本")
    if edge.from_node_id == edge.to_node_id:
        raise InvalidEdgeError(f"自环边被拒绝: {edge.from_node_id}")
    by_id = {str(node.node_id): node for node in nodes}
    from_node = by_id.get(str(edge.from_node_id))
    to_node = by_id.get(str(edge.to_node_id))
    if from_node is None or to_node is None:
        raise InvalidEdgeError("悬空边被拒绝：端点节点不存在")
    if from_node.version_id != version_id or to_node.version_id != version_id:
        raise InvalidEdgeError("边不得跨版本（端点属于另一个版本）")
    _check_edge_kind(from_node, to_node, edge.kind)


# --------------------------------------------------------- graph checker


def validate_graph(
    nodes: Sequence[CurriculumNode],
    edges: Sequence[CurriculumEdge],
) -> list[ValidationIssue]:
    """Defensive graph check — returns an issue list, never raises.

    Reported findings (spec §9.1 pre-publish checks):

    - ``duplicate_node_code``   — two nodes carry the same stable code;
    - ``dangling_edge``         — edge references a missing node;
    - ``self_loop``             — from == to;
    - ``duplicate_edge``        — same (kind, from, to) twice;
    - ``invalid_edge_kind``     — kind matrix violation;
    - ``unreachable_concept``   — concept has no PART_OF path from a chapter;
    - ``orphan_node``           — node with no incident edge (warning).
    """
    issues: list[ValidationIssue] = []
    nodes_by_id = {str(node.node_id): node for node in nodes}
    incident: dict[str, int] = {str(node.node_id): 0 for node in nodes}

    # Duplicate stable codes.
    seen_codes: dict[str, str] = {}
    for node in nodes:
        if node.code in seen_codes:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="duplicate_node_code",
                    message=f"code {node.code!r} 重复（{seen_codes[node.code]} 与 {node.node_id}）",
                    node_id=node.node_id,
                )
            )
        seen_codes[node.code] = str(node.node_id)

    seen_pairs: set[tuple[str, str, str]] = set()
    for edge in edges:
        edge_id = edge.edge_id
        if edge.from_node_id == edge.to_node_id:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="self_loop",
                    message=f"自环边: {edge.from_node_id}",
                    edge_id=edge_id,
                )
            )
        from_node = nodes_by_id.get(str(edge.from_node_id))
        to_node = nodes_by_id.get(str(edge.to_node_id))
        if from_node is None or to_node is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="dangling_edge",
                    message=(
                        f"悬空边 {edge.edge_id}: from={edge.from_node_id} "
                        f"to={edge.to_node_id}"
                    ),
                    edge_id=edge_id,
                )
            )
            continue
        if (
            from_node.version_id != edge.version_id
            or to_node.version_id != edge.version_id
        ):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="cross_version_edge",
                    message=(
                        f"跨版本边 {edge.edge_id}: 边属于 {edge.version_id} 但端点属于 "
                        f"{from_node.version_id}/{to_node.version_id}"
                    ),
                    edge_id=edge_id,
                )
            )
            continue
        incident[str(edge.from_node_id)] += 1
        incident[str(edge.to_node_id)] += 1
        pair = (edge.kind, str(edge.from_node_id), str(edge.to_node_id))
        if pair in seen_pairs:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="duplicate_edge",
                    message=f"重复边: {edge.kind} {edge.from_node_id}→{edge.to_node_id}",
                    edge_id=edge_id,
                )
            )
        seen_pairs.add(pair)
        try:
            _check_edge_kind(from_node, to_node, edge.kind)
        except InvalidEdgeError as exc:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="invalid_edge_kind",
                    message=str(exc),
                    edge_id=edge_id,
                )
            )

    # Prerequisite subgraph must be acyclic (§9.1): DFS cycle detection over
    # PREREQUISITE_OF edges (self-loops are reported separately above).
    prereq_adj: dict[str, list[tuple[UUID, UUID]]] = {}
    for edge in edges:
        if edge.kind == "PREREQUISITE_OF" and edge.from_node_id != edge.to_node_id:
            prereq_adj.setdefault(str(edge.from_node_id), []).append(
                (edge.edge_id, edge.to_node_id)
            )
    _visiting: set[str] = set()
    _done: set[str] = set()

    def _visit(node_key: str) -> None:
        if node_key in _done:
            return
        if node_key in _visiting:
            return  # the closing edge already reported the cycle
        _visiting.add(node_key)
        for edge_id, to_id in prereq_adj.get(node_key, []):
            target = str(to_id)
            if target in _visiting:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="prerequisite_cycle",
                        message=f"前置依赖环: {node_key}→{target}",
                        edge_id=edge_id,
                    )
                )
            else:
                _visit(target)
        _visiting.discard(node_key)
        _done.add(node_key)

    for node_key in list(prereq_adj):
        _visit(node_key)

    # Reachability over PART_OF edges (direction from→to), roots = chapters.
    reachable: set[str] = {
        str(node.node_id) for node in nodes if node.kind == "chapter"
    }
    frontier = list(reachable)
    while frontier:
        current = frontier.pop()
        for edge in edges:
            if edge.kind != "PART_OF":
                continue
            if str(edge.from_node_id) == current:
                target = str(edge.to_node_id)
                if target not in reachable:
                    reachable.add(target)
                    frontier.append(target)

    for node in nodes:
        key = str(node.node_id)
        if node.kind == "concept" and key not in reachable:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="unreachable_concept",
                    message=f"概念 {node.code!r} 无法从任何 chapter 经 PART_OF 到达",
                    node_id=node.node_id,
                )
            )
        if node.kind == "skill" and key not in reachable:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="unreachable_skill",
                    message=f"技能 {node.code!r} 无法从任何 chapter 经 PART_OF 到达",
                    node_id=node.node_id,
                )
            )
        if incident.get(key, 0) == 0:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="orphan_node",
                    message=f"节点 {node.code!r} ({node.kind}) 没有任何边",
                    node_id=node.node_id,
                )
            )
    return issues


# ----------------------------------------------------------------- mappers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _version_from_row(row: Any) -> CurriculumVersion:
    return CurriculumVersion(
        version_id=UUID(row.version_id),
        code=row.code,
        name=row.name,
        status=row.status,
        node_count=row.node_count,
        edge_count=row.edge_count,
        released_at=(
            datetime.fromisoformat(row.released_at) if row.released_at else None
        ),
        created_at=datetime.fromisoformat(row.created_at),
    )


def _node_from_row(row: Any) -> CurriculumNode:
    return CurriculumNode(
        node_id=UUID(row.node_id),
        version_id=UUID(row.version_id),
        code=row.code,
        kind=row.kind,
        title=row.title,
        stage=row.stage,
        grade=row.grade,
    )


def _edge_from_row(row: Any) -> CurriculumEdge:
    return CurriculumEdge(
        edge_id=UUID(row.edge_id),
        version_id=UUID(row.version_id),
        from_node_id=UUID(row.from_node_id),
        to_node_id=UUID(row.to_node_id),
        kind=row.kind,
    )


# ----------------------------------------------------------------- protocol


class CurriculumRepository(Protocol):
    """Async curriculum catalog contract (Phase 6 §9.1)."""

    async def create_version(self, version: CurriculumVersion) -> CurriculumVersion: ...

    async def add_node(self, node: CurriculumNode) -> CurriculumNode: ...

    async def add_edge(self, edge: CurriculumEdge) -> CurriculumEdge: ...

    async def publish(self, version_id: UUID) -> CurriculumVersion: ...

    async def archive(self, version_id: UUID) -> CurriculumVersion: ...

    async def load_version(self, version_id: UUID) -> CurriculumVersion | None: ...

    async def find_version_by_code(self, code: str) -> CurriculumVersion | None: ...

    async def find_node(self, node_id: UUID) -> CurriculumNode | None: ...

    async def list_versions(self) -> list[CurriculumVersion]: ...

    async def load_graph(self, version_id: UUID) -> CurriculumGraph: ...

    async def validate_graph(self, version_id: UUID) -> list[ValidationIssue]: ...


# ------------------------------------------------------- in-memory store


class InMemoryCurriculumRepository:
    """Process-local curriculum catalog (dev/tests).

    Mirrors the SQLite structural constraints: version code unique, node
    code unique within a version, version/node existence on write. Business
    rules (immutability after publish, edge kinds, cross-version, self-loop)
    live in the catalog service — same as with the SQLite store.
    """

    def __init__(self) -> None:
        self._versions: dict[str, CurriculumVersion] = {}
        self._nodes: dict[str, CurriculumNode] = {}
        self._edges: dict[str, CurriculumEdge] = {}

    async def create_version(self, version: CurriculumVersion) -> CurriculumVersion:
        key = str(version.version_id)
        if key in self._versions:
            raise DuplicateCodeError(f"version_id 已存在: {key}")
        self._versions[key] = version
        return version

    async def add_node(self, node: CurriculumNode) -> CurriculumNode:
        if str(node.version_id) not in self._versions:
            raise VersionNotFoundError(f"版本不存在: {node.version_id}")
        for existing in self._nodes.values():
            if (
                existing.version_id == node.version_id
                and existing.code == node.code
            ):
                raise DuplicateCodeError(
                    f"节点 code {node.code!r} 在该版本中已存在"
                )
        self._nodes[str(node.node_id)] = node
        return node

    async def add_edge(self, edge: CurriculumEdge) -> CurriculumEdge:
        if str(edge.version_id) not in self._versions:
            raise VersionNotFoundError(f"版本不存在: {edge.version_id}")
        for node_id in (str(edge.from_node_id), str(edge.to_node_id)):
            if node_id not in self._nodes:
                raise NodeNotFoundError(f"端点节点不存在: {node_id}")
        self._edges[str(edge.edge_id)] = edge
        return edge

    async def publish(self, version_id: UUID) -> CurriculumVersion:
        version = self._versions.get(str(version_id))
        if version is None:
            raise VersionNotFoundError(f"版本不存在: {version_id}")
        if version.status == "published":
            return version  # idempotent re-publish
        if version.status == "archived":
            raise VersionImmutableError("archived 版本不能重新发布")
        node_count = sum(1 for n in self._nodes.values() if n.version_id == version_id)
        edge_count = sum(1 for e in self._edges.values() if e.version_id == version_id)
        published = version.model_copy(
            update={
                "status": "published",
                "node_count": node_count,
                "edge_count": edge_count,
                "released_at": datetime.now(timezone.utc),
            }
        )
        self._versions[str(version_id)] = published
        return published

    async def archive(self, version_id: UUID) -> CurriculumVersion:
        version = self._versions.get(str(version_id))
        if version is None:
            raise VersionNotFoundError(f"版本不存在: {version_id}")
        if version.status == "archived":
            return version
        archived = version.model_copy(update={"status": "archived"})
        self._versions[str(version_id)] = archived
        return archived

    async def load_version(self, version_id: UUID) -> CurriculumVersion | None:
        return self._versions.get(str(version_id))

    async def find_version_by_code(self, code: str) -> CurriculumVersion | None:
        for version in self._versions.values():
            if version.code == code:
                return version
        return None

    async def find_node(self, node_id: UUID) -> CurriculumNode | None:
        return self._nodes.get(str(node_id))

    async def list_versions(self) -> list[CurriculumVersion]:
        return list(self._versions.values())

    async def load_graph(self, version_id: UUID) -> CurriculumGraph:
        version = self._versions.get(str(version_id))
        if version is None:
            raise VersionNotFoundError(f"版本不存在: {version_id}")
        nodes = tuple(
            n for n in self._nodes.values() if n.version_id == version_id
        )
        edges = tuple(
            e for e in self._edges.values() if e.version_id == version_id
        )
        return CurriculumGraph(version=version, nodes=nodes, edges=edges)

    async def validate_graph(self, version_id: UUID) -> list[ValidationIssue]:
        graph = await self.load_graph(version_id)
        return validate_graph(graph.nodes, graph.edges)

    async def clear(self) -> None:
        self._versions.clear()
        self._nodes.clear()
        self._edges.clear()


# -------------------------------------------------------------- sqlite


class SQLiteCurriculumRepository:
    """Curriculum catalog over the product database (short UoW transactions)."""

    def __init__(self, uow: Any) -> None:
        self.uow = uow

    async def create_version(self, version: CurriculumVersion) -> CurriculumVersion:
        async with self.uow.transaction() as conn:
            await conn.execute(
                curriculum_versions.insert().values(
                    version_id=str(version.version_id),
                    code=version.code,
                    name=version.name,
                    status=version.status,
                    node_count=version.node_count,
                    edge_count=version.edge_count,
                    released_at=(
                        version.released_at.isoformat()
                        if version.released_at
                        else None
                    ),
                    created_at=version.created_at.isoformat(),
                )
            )
        return version

    async def add_node(self, node: CurriculumNode) -> CurriculumNode:
        async with self.uow.transaction() as conn:
            await self._require_version(conn, node.version_id)
            await conn.execute(
                curriculum_nodes.insert().values(
                    node_id=str(node.node_id),
                    version_id=str(node.version_id),
                    code=node.code,
                    kind=node.kind,
                    title=node.title,
                    stage=node.stage,
                    grade=node.grade,
                )
            )
        return node

    async def add_edge(self, edge: CurriculumEdge) -> CurriculumEdge:
        async with self.uow.transaction() as conn:
            await self._require_version(conn, edge.version_id)
            for node_id in (edge.from_node_id, edge.to_node_id):
                found = (
                    await conn.execute(
                        select(curriculum_nodes.c.node_id).where(
                            curriculum_nodes.c.node_id == str(node_id)
                        )
                    )
                ).first()
                if found is None:
                    raise NodeNotFoundError(f"端点节点不存在: {node_id}")
            await conn.execute(
                curriculum_edges.insert().values(
                    edge_id=str(edge.edge_id),
                    version_id=str(edge.version_id),
                    from_node_id=str(edge.from_node_id),
                    to_node_id=str(edge.to_node_id),
                    kind=edge.kind,
                )
            )
        return edge

    async def publish(self, version_id: UUID) -> CurriculumVersion:
        async with self.uow.transaction() as conn:
            version = await self._load_version(conn, version_id)
            if version is None:
                raise VersionNotFoundError(f"版本不存在: {version_id}")
            if version.status == "published":
                return version
            if version.status == "archived":
                raise VersionImmutableError("archived 版本不能重新发布")
            node_count = len(
                (
                    await conn.execute(
                        select(curriculum_nodes.c.node_id).where(
                            curriculum_nodes.c.version_id == str(version_id)
                        )
                    )
                ).all()
            )
            edge_count = len(
                (
                    await conn.execute(
                        select(curriculum_edges.c.edge_id).where(
                            curriculum_edges.c.version_id == str(version_id)
                        )
                    )
                ).all()
            )
            released_at = _now()
            await conn.execute(
                curriculum_versions.update()
                .where(curriculum_versions.c.version_id == str(version_id))
                .values(
                    status="published",
                    node_count=node_count,
                    edge_count=edge_count,
                    released_at=released_at,
                )
            )
            return version.model_copy(
                update={
                    "status": "published",
                    "node_count": node_count,
                    "edge_count": edge_count,
                    "released_at": datetime.fromisoformat(released_at),
                }
            )

    async def archive(self, version_id: UUID) -> CurriculumVersion:
        async with self.uow.transaction() as conn:
            version = await self._load_version(conn, version_id)
            if version is None:
                raise VersionNotFoundError(f"版本不存在: {version_id}")
            if version.status == "archived":
                return version
            await conn.execute(
                curriculum_versions.update()
                .where(curriculum_versions.c.version_id == str(version_id))
                .values(status="archived")
            )
            return version.model_copy(update={"status": "archived"})

    async def load_version(self, version_id: UUID) -> CurriculumVersion | None:
        async with self.uow.transaction() as conn:
            return await self._load_version(conn, version_id)

    async def find_version_by_code(self, code: str) -> CurriculumVersion | None:
        async with self.uow.transaction() as conn:
            row = (
                await conn.execute(
                    select(curriculum_versions).where(
                        curriculum_versions.c.code == code
                    )
                )
            ).first()
            return _version_from_row(row) if row is not None else None

    async def find_node(self, node_id: UUID) -> CurriculumNode | None:
        async with self.uow.transaction() as conn:
            row = (
                await conn.execute(
                    select(curriculum_nodes).where(
                        curriculum_nodes.c.node_id == str(node_id)
                    )
                )
            ).first()
            return _node_from_row(row) if row is not None else None

    async def list_versions(self) -> list[CurriculumVersion]:
        async with self.uow.transaction() as conn:
            rows = (
                await conn.execute(
                    select(curriculum_versions).order_by(
                        curriculum_versions.c.created_at
                    )
                )
            ).all()
            return [_version_from_row(row) for row in rows]

    async def load_graph(self, version_id: UUID) -> CurriculumGraph:
        async with self.uow.transaction() as conn:
            version = await self._load_version(conn, version_id)
            if version is None:
                raise VersionNotFoundError(f"版本不存在: {version_id}")
            node_rows = (
                await conn.execute(
                    select(curriculum_nodes)
                    .where(curriculum_nodes.c.version_id == str(version_id))
                    .order_by(curriculum_nodes.c.code)
                )
            ).all()
            edge_rows = (
                await conn.execute(
                    select(curriculum_edges)
                    .where(curriculum_edges.c.version_id == str(version_id))
                    .order_by(curriculum_edges.c.edge_id)
                )
            ).all()
            return CurriculumGraph(
                version=version,
                nodes=tuple(_node_from_row(row) for row in node_rows),
                edges=tuple(_edge_from_row(row) for row in edge_rows),
            )

    async def validate_graph(self, version_id: UUID) -> list[ValidationIssue]:
        graph = await self.load_graph(version_id)
        return validate_graph(graph.nodes, graph.edges)

    # ---------------------------------------------------------- helpers

    @staticmethod
    async def _load_version(
        conn: AsyncConnection, version_id: UUID
    ) -> CurriculumVersion | None:
        row = (
            await conn.execute(
                select(curriculum_versions).where(
                    curriculum_versions.c.version_id == str(version_id)
                )
            )
        ).first()
        return _version_from_row(row) if row is not None else None

    @staticmethod
    async def _require_version(conn: AsyncConnection, version_id: UUID) -> None:
        found = (
            await conn.execute(
                select(curriculum_versions.c.version_id).where(
                    curriculum_versions.c.version_id == str(version_id)
                )
            )
        ).first()
        if found is None:
            raise VersionNotFoundError(f"版本不存在: {version_id}")


__all__ = [
    "CurriculumCatalogError",
    "CurriculumGraph",
    "CurriculumRepository",
    "DuplicateCodeError",
    "InMemoryCurriculumRepository",
    "InvalidEdgeError",
    "NodeNotFoundError",
    "SQLiteCurriculumRepository",
    "ValidationIssue",
    "VersionImmutableError",
    "VersionNotFoundError",
    "check_edge",
    "validate_graph",
]
