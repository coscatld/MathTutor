"""Curriculum catalog service (Phase 6 §9.1) — versioned curriculum graph.

Publishes the design contract: published curriculum versions are IMMUTABLE
— any later node/edge write is refused; a curriculum change always yields a
NEW version. ``validate_graph`` reports pre-publish issues (orphan nodes,
duplicate codes, dangling edges, unreachable concepts, ...).

Mapping-id consistency (permanent design invariant): the catalog's
skill/concept ``code`` ↔ practice-mapping UUID relationship is derived
EXCLUSIVELY from ``practice_release.mapping_id_for_skill`` /
``mapping_id_for_concept`` (server-owned, deterministic) — the same code
always produces the same mapping id, and
``practice_release.labels_for_mapping_ids`` reverse-maps them for the
/offers projection. No second mapping namespace exists.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from mathtutor.application.practice_release import (
    mapping_id_for_concept,
    mapping_id_for_skill,
)
from mathtutor.domain.curriculum import (
    CurriculumEdge,
    CurriculumNode,
    CurriculumVersion,
)
from mathtutor.repositories.sqlite_curriculum import (
    CurriculumCatalogError,
    CurriculumGraph,
    DuplicateCodeError,
    InMemoryCurriculumRepository,
    InvalidEdgeError,
    ValidationIssue,
    VersionImmutableError,
    VersionNotFoundError,
    check_edge,
    validate_graph,
)

__all__ = [
    "CurriculumCatalogError",
    "CurriculumCatalogService",
    "DuplicateCodeError",
    "InvalidEdgeError",
    "ValidationIssue",
    "VersionImmutableError",
    "VersionNotFoundError",
    "concept_mapping_ids",
    "skill_mapping_ids",
]


def skill_mapping_ids(graph: CurriculumGraph) -> dict[str, UUID]:
    """Stable mapping ids for every skill code in a version.

    Deterministic and identical to the practice side: the SAME code yields
    the SAME mapping id everywhere (spec §9.2 metadata filter uses these
    ids to bind exercises and curriculum retrieval to one namespace).
    """
    return {
        node.code: mapping_id_for_skill(node.code)
        for node in graph.nodes
        if node.kind == "skill"
    }


def concept_mapping_ids(graph: CurriculumGraph) -> dict[str, UUID]:
    """Stable mapping ids for every concept code in a version."""
    return {
        node.code: mapping_id_for_concept(node.code)
        for node in graph.nodes
        if node.kind == "concept"
    }


class CurriculumCatalogService:
    """Version lifecycle + graph authoring over a :class:`CurriculumRepository`.

    Business rules enforced here (repositories stay storage-only):

    - ``create_version``: ``code`` unique across all versions;
    - ``add_node`` / ``add_edge``: only on DRAFT versions — a published or
      archived version is immutable (any write raises
      :class:`VersionImmutableError`);
    - ``add_edge``: endpoints must exist in the same version, no self-loop,
      kind matrix (PREREQUISITE_OF skill→skill, PART_OF
      chapter→concept|concept→skill, RELATED_TO same kind);
    - ``publish_version``: draft→published, freezes content; re-publish is
      an idempotent no-op; archiving a published/draft version is allowed,
      un-publishing never is.
    """

    def __init__(self, repository: Any | None = None) -> None:
        self.repository = repository or InMemoryCurriculumRepository()

    # ------------------------------------------------------- lifecycle

    async def create_version(self, code: str, name: str) -> CurriculumVersion:
        code = code.strip()
        if not code:
            raise CurriculumCatalogError("version code 不能为空")
        if await self.repository.find_version_by_code(code) is not None:
            raise DuplicateCodeError(f"version code {code!r} 已存在")
        return await self.repository.create_version(
            CurriculumVersion(code=code, name=name)
        )

    async def publish_version(self, version_id: UUID) -> CurriculumVersion:
        return await self.repository.publish(version_id)

    async def archive_version(self, version_id: UUID) -> CurriculumVersion:
        return await self.repository.archive(version_id)

    # ------------------------------------------------------ graph writes

    async def add_node(
        self,
        version_id: UUID,
        *,
        code: str,
        kind: str,
        title: str,
        stage: str | None = None,
        grade: int | None = None,
    ) -> CurriculumNode:
        """Add one node to a DRAFT version (published → immutable)."""
        await self._require_editable(version_id)
        graph = await self.repository.load_graph(version_id)
        if any(node.code == code for node in graph.nodes):
            raise DuplicateCodeError(f"节点 code {code!r} 在该版本中已存在")
        node = CurriculumNode(
            version_id=version_id,
            code=code,
            kind=kind,
            title=title,
            stage=stage,
            grade=grade,
        )
        return await self.repository.add_node(node)

    async def add_edge(
        self,
        version_id: UUID,
        *,
        from_node_id: UUID,
        to_node_id: UUID,
        kind: str,
    ) -> CurriculumEdge:
        """Add one validated edge to a DRAFT version (published → immutable)."""
        await self._require_editable(version_id)
        # Endpoint existence + cross-version (the endpoint may live in a
        # DIFFERENT version — invisible inside this version's own graph).
        for node_id in (from_node_id, to_node_id):
            node = await self.repository.find_node(node_id)
            if node is None:
                raise InvalidEdgeError(f"悬空边被拒绝：端点节点不存在: {node_id}")
            if node.version_id != version_id:
                raise InvalidEdgeError(
                    f"边不得跨版本：节点 {node_id} 属于版本 {node.version_id}"
                )
        graph = await self.repository.load_graph(version_id)
        edge = CurriculumEdge(
            version_id=version_id,
            from_node_id=from_node_id,
            to_node_id=to_node_id,
            kind=kind,
        )
        # Self-loop + kind matrix (nodes are all in-version here).
        check_edge(version_id, graph.nodes, edge)
        return await self.repository.add_edge(edge)

    # ------------------------------------------------------------ reads

    async def load_version(self, version_id: UUID) -> CurriculumVersion | None:
        return await self.repository.load_version(version_id)

    async def load_graph(self, version_id: UUID) -> CurriculumGraph:
        return await self.repository.load_graph(version_id)

    async def list_versions(self) -> list[CurriculumVersion]:
        return await self.repository.list_versions()

    async def validate_graph(self, version_id: UUID) -> list[ValidationIssue]:
        """Defensive pre-publish check; returns an issue list (never raises)."""
        return await self.repository.validate_graph(version_id)

    # ---------------------------------------------------------- helpers

    async def _require_editable(self, version_id: UUID) -> CurriculumVersion:
        version = await self.repository.load_version(version_id)
        if version is None:
            raise VersionNotFoundError(f"版本不存在: {version_id}")
        if version.status != "draft":
            raise VersionImmutableError(
                f"版本 {version.code!r} 已 {version.status}，内容不可变"
            )
        return version
