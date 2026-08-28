"""Phase 6 — curriculum catalog tests (spec §9.1).

Covers: version lifecycle immutability (publish → writes refused), code
uniqueness, the full edge validation matrix (dangling / cross-version /
self-loop / kind rules), the defensive graph checker (orphan nodes,
duplicate codes, dangling edges, cycles, unreachable concepts), mapping-id
consistency with the practice side, and the SQLite persistence roundtrip
(upgrade_db'd tmp db + MathTutorUow).
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from mathtutor.application.curriculum_catalog import (
    CurriculumCatalogService,
    concept_mapping_ids,
    skill_mapping_ids,
)
from mathtutor.application.practice_release import (
    labels_for_mapping_ids,
    mapping_id_for_concept,
    mapping_id_for_skill,
)
from mathtutor.domain.curriculum import (
    CurriculumEdge,
    CurriculumNode,
    CurriculumVersion,
)
from mathtutor.learning.skills import (
    CONCEPT_LINEAR_EQUATIONS,
    CONCEPT_QUADRATIC_EQUATIONS,
    SKILL_LINEAR_EQUATION,
    SKILL_QUADRATIC_EQUATION,
    all_skill_ids,
)
from mathtutor.repositories.sqlite_curriculum import (
    DuplicateCodeError,
    InvalidEdgeError,
    SQLiteCurriculumRepository,
    VersionImmutableError,
    validate_graph,
)
from mathtutor.repositories.uow import MathTutorUow

pytestmark = pytest.mark.asyncio


async def test_publish_makes_version_immutable():
    """draft 可写 → publish 后任何 node/edge 写入被拒；archive 后同样不可写。"""
    svc = CurriculumCatalogService()
    version = await svc.create_version("mt-v1", "课程 v1")
    node = await svc.add_node(
        version.version_id, code="CH1", kind="chapter", title="第1章"
    )
    published = await svc.publish_version(version.version_id)
    assert published.status == "published"
    assert published.released_at is not None
    with pytest.raises(VersionImmutableError):
        await svc.add_node(
            published.version_id, code="CH2", kind="chapter", title="第2章"
        )
    with pytest.raises(VersionImmutableError):
        await svc.add_edge(
            published.version_id,
            from_node_id=node.node_id,
            to_node_id=node.node_id,
            kind="RELATED_TO",
        )
    # Re-publish is an idempotent no-op; archiving works; archived stays immutable.
    again = await svc.publish_version(version.version_id)
    assert again.status == "published"
    archived = await svc.archive_version(version.version_id)
    assert archived.status == "archived"
    with pytest.raises(VersionImmutableError):
        await svc.add_node(
            archived.version_id, code="CH3", kind="chapter", title="第3章"
        )


async def test_version_and_node_code_unique():
    """version code 全局唯一；node code 在版本内唯一（跨版本可复用）。"""
    svc = CurriculumCatalogService()
    await svc.create_version("uniq", "唯一版本")
    with pytest.raises(DuplicateCodeError):
        await svc.create_version("uniq", "重复版本")
    version = await svc.create_version("uniq-2", "唯一版本2")
    await svc.add_node(version.version_id, code="N1", kind="concept", title="概念1")
    with pytest.raises(DuplicateCodeError):
        await svc.add_node(version.version_id, code="N1", kind="skill", title="技能1")
    other = await svc.create_version("uniq-3", "唯一版本3")
    await svc.add_node(other.version_id, code="N1", kind="skill", title="技能1")


async def test_edge_validation_matrix():
    """完整边校验矩阵：kind 约束 + 悬空 / 跨版本 / 自环全部拒绝。"""
    svc = CurriculumCatalogService()
    version = await svc.create_version("edge-matrix", "边校验")
    ids: dict[str, UUID] = {}
    for label, kind in (
        ("chapter", "chapter"),
        ("concept", "concept"),
        ("skill", "skill"),
        ("skill2", "skill"),
    ):
        node = await svc.add_node(
            version.version_id, code=f"N_{label}", kind=kind, title=label
        )
        ids[label] = node.node_id

    cases = [
        ("PREREQUISITE_OF", "skill", "skill2", False),
        ("PREREQUISITE_OF", "concept", "skill", True),
        ("PREREQUISITE_OF", "chapter", "concept", True),
        ("PART_OF", "chapter", "concept", False),
        ("PART_OF", "concept", "skill", False),
        ("PART_OF", "chapter", "skill", True),
        ("PART_OF", "skill", "concept", True),
        ("RELATED_TO", "skill", "skill2", False),
        ("RELATED_TO", "chapter", "concept", True),
    ]
    for kind, from_label, to_label, expect_error in cases:
        from_id, to_id = ids[from_label], ids[to_label]
        if expect_error:
            with pytest.raises(InvalidEdgeError):
                await svc.add_edge(
                    version.version_id, from_node_id=from_id, to_node_id=to_id, kind=kind
                )
        else:
            edge = await svc.add_edge(
                version.version_id, from_node_id=from_id, to_node_id=to_id, kind=kind
            )
            assert edge.kind == kind

    # 结构拒绝：跨版本（端点属于另一个版本）、悬空（端点不存在）、自环。
    other = await svc.create_version("edge-other", "其他版本")
    foreign = await svc.add_node(
        other.version_id, code="F1", kind="concept", title="外部概念"
    )
    with pytest.raises(InvalidEdgeError):
        await svc.add_edge(
            version.version_id,
            from_node_id=ids["chapter"],
            to_node_id=foreign.node_id,
            kind="PART_OF",
        )
    with pytest.raises(InvalidEdgeError):
        await svc.add_edge(
            version.version_id,
            from_node_id=uuid4(),
            to_node_id=ids["concept"],
            kind="PART_OF",
        )
    with pytest.raises(InvalidEdgeError):
        await svc.add_edge(
            version.version_id,
            from_node_id=ids["skill"],
            to_node_id=ids["skill"],
            kind="PREREQUISITE_OF",
        )


async def test_validate_graph_reports_issue_classes():
    """防御性图校验：孤儿 / 重复 code / 悬空 / 自环 / 重复边 / 跨版本 /
    非法 kind / 不可达概念 / 前置环全部上报（纯函数，不抛错）。"""
    version = CurriculumVersion(code="issues", name="issues")
    other = CurriculumVersion(code="v-other", name="other")
    chapter = CurriculumNode(version_id=version.version_id, code="CH1", kind="chapter", title="章")
    concept = CurriculumNode(version_id=version.version_id, code="CP1", kind="concept", title="概念")
    lonely = CurriculumNode(version_id=version.version_id, code="CP2", kind="concept", title="孤立概念")
    skill_a = CurriculumNode(version_id=version.version_id, code="SK1", kind="skill", title="技能A")
    skill_dup = CurriculumNode(version_id=version.version_id, code="SK1", kind="skill", title="重复code技能")
    orphan = CurriculumNode(version_id=version.version_id, code="CH2", kind="chapter", title="孤立章")
    missing = uuid4()

    edges = [
        CurriculumEdge(version_id=version.version_id, from_node_id=chapter.node_id, to_node_id=concept.node_id, kind="PART_OF"),
        CurriculumEdge(version_id=version.version_id, from_node_id=chapter.node_id, to_node_id=concept.node_id, kind="PART_OF"),  # duplicate
        CurriculumEdge(version_id=version.version_id, from_node_id=skill_a.node_id, to_node_id=missing, kind="PART_OF"),  # dangling
        CurriculumEdge(version_id=version.version_id, from_node_id=skill_a.node_id, to_node_id=skill_a.node_id, kind="PREREQUISITE_OF"),  # self-loop
        CurriculumEdge(version_id=other.version_id, from_node_id=chapter.node_id, to_node_id=concept.node_id, kind="PART_OF"),  # cross-version
        CurriculumEdge(version_id=version.version_id, from_node_id=chapter.node_id, to_node_id=skill_a.node_id, kind="PART_OF"),  # invalid kind
        CurriculumEdge(version_id=version.version_id, from_node_id=skill_a.node_id, to_node_id=skill_dup.node_id, kind="PREREQUISITE_OF"),
        CurriculumEdge(version_id=version.version_id, from_node_id=skill_dup.node_id, to_node_id=skill_a.node_id, kind="PREREQUISITE_OF"),  # cycle
    ]
    issues = validate_graph(
        [chapter, concept, lonely, skill_a, skill_dup, orphan], edges
    )
    codes = {issue.code for issue in issues}
    for expected in (
        "duplicate_node_code",
        "dangling_edge",
        "duplicate_edge",
        "self_loop",
        "cross_version_edge",
        "invalid_edge_kind",
        "unreachable_concept",
        "orphan_node",
        "prerequisite_cycle",
    ):
        assert expected in codes, f"missing issue code {expected}: {codes}"


async def test_mapping_ids_consistent_with_practice_release():
    """skill/concept code ↔ mapping UUID 与 practice_release 完全一致。"""
    svc = CurriculumCatalogService()
    version = await svc.create_version("mt-map", "映射一致性")
    for code in all_skill_ids():
        await svc.add_node(version.version_id, code=code, kind="skill", title=code)
    for code in (CONCEPT_LINEAR_EQUATIONS, CONCEPT_QUADRATIC_EQUATIONS):
        await svc.add_node(version.version_id, code=code, kind="concept", title=code)
    graph = await svc.load_graph(version.version_id)

    skill_ids = skill_mapping_ids(graph)
    concept_ids = concept_mapping_ids(graph)
    assert skill_ids == {code: mapping_id_for_skill(code) for code in all_skill_ids()}
    assert concept_ids[CONCEPT_LINEAR_EQUATIONS] == mapping_id_for_concept(
        CONCEPT_LINEAR_EQUATIONS
    )
    # Same code → same mapping id, across reloads.
    assert skill_mapping_ids(await svc.load_graph(version.version_id)) == skill_ids
    # The practice-side reverse projection resolves the catalog codes back.
    labels = labels_for_mapping_ids(
        list(skill_ids.values()) + list(concept_ids.values())
    )
    assert SKILL_LINEAR_EQUATION in labels["skill_labels"]
    assert SKILL_QUADRATIC_EQUATION in labels["skill_labels"]
    assert CONCEPT_LINEAR_EQUATIONS in labels["concept_labels"]
    assert CONCEPT_QUADRATIC_EQUATIONS in labels["concept_labels"]


async def test_sqlite_roundtrip_persists_and_enforces(tmp_path):
    """upgrade_db 的临时 db + MathTutorUow：发布后重开实例图仍完整、写入被拒。"""
    from mathtutor.infrastructure.db import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db

    db_path = tmp_path / "curriculum.db"
    upgrade_db(str(db_path))
    engine = create_db_engine(db_path)
    try:
        uow = MathTutorUow(engine)
        svc = CurriculumCatalogService(SQLiteCurriculumRepository(uow))
        version = await svc.create_version("sql-v1", "SQLite 课程")
        chapter = await svc.add_node(
            version.version_id, code="CH1", kind="chapter", title="第1章", stage="middle", grade=7
        )
        concept = await svc.add_node(
            version.version_id, code="CONCEPT_LINEAR_EQUATIONS", kind="concept",
            title="线性方程", stage="middle", grade=7,
        )
        skill = await svc.add_node(
            version.version_id, code="LINEAR_EQUATION", kind="skill",
            title="解线性方程", stage="middle", grade=7,
        )
        skill2 = await svc.add_node(
            version.version_id, code="QUADRATIC_EQUATION", kind="skill",
            title="解二次方程", stage="middle", grade=7,
        )
        await svc.add_edge(version.version_id, from_node_id=chapter.node_id, to_node_id=concept.node_id, kind="PART_OF")
        await svc.add_edge(version.version_id, from_node_id=concept.node_id, to_node_id=skill.node_id, kind="PART_OF")
        await svc.add_edge(version.version_id, from_node_id=concept.node_id, to_node_id=skill2.node_id, kind="PART_OF")
        await svc.add_edge(version.version_id, from_node_id=skill.node_id, to_node_id=skill2.node_id, kind="PREREQUISITE_OF")
        published = await svc.publish_version(version.version_id)
        assert published.node_count == 4
        assert published.edge_count == 4

        # 全新实例（同一 db）恢复已发布图：内容与约束都持久化。
        svc2 = CurriculumCatalogService(
            SQLiteCurriculumRepository(MathTutorUow(engine))
        )
        loaded = await svc2.load_version(version.version_id)
        assert loaded is not None and loaded.status == "published"
        assert loaded.released_at is not None
        graph = await svc2.load_graph(version.version_id)
        assert len(graph.nodes) == 4
        assert len(graph.edges) == 4
        assert await svc2.validate_graph(version.version_id) == []
        with pytest.raises(VersionImmutableError):
            await svc2.add_node(version.version_id, code="CH9", kind="chapter", title="新章")
        with pytest.raises(DuplicateCodeError):
            await svc2.create_version("sql-v1", "重复")
    finally:
        await engine.dispose()
