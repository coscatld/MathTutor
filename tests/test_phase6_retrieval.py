"""Phase 6 — metadata-first retrieval router tests (spec §9.2).

Covers: metadata filtering happens FIRST (mismatched stage/grade/skill/
owner excluded before any vector work), graceful degradation with
``vector: "unavailable"`` when no embedding backend exists, INVARIANT F
(``retrieval_enabled=false`` sources are NEVER retrieved, whatever the
request), and the NoOp reranker contract (order-preserving identity +
limit truncation) with provenance attached to every result.
"""

from __future__ import annotations

import pytest

from mathtutor.application.practice_release import (
    mapping_id_for_concept,
    mapping_id_for_skill,
)
from mathtutor.application.retrieval_router import (
    MetadataFirstRetriever,
    NoOpReranker,
    RetrievalItem,
)
from mathtutor.infrastructure.embedding_runtime import (
    FAKE_BACKEND_ID,
    build_fake_embedding_runtime,
)
from mathtutor.learning.skills import (
    CONCEPT_LINEAR_EQUATIONS,
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
)

pytestmark = pytest.mark.asyncio


def _item(
    item_id: str,
    *,
    owner: str = "student-a",
    enabled: bool = True,
    stage: str = "middle",
    grade: int = 7,
    skills: tuple[str, ...] = (),
    concepts: tuple[str, ...] = (),
    mappings: tuple[str, ...] = (),
    source: str = "curriculum",
) -> RetrievalItem:
    return RetrievalItem(
        item_id=item_id,
        text=f"content of {item_id}",
        source_type=source,
        owner_scope=owner,
        retrieval_enabled=enabled,
        stage=stage,
        grade=grade,
        skill_codes=skills,
        concept_codes=concepts,
        mapping_ids=mappings,
    )


async def test_metadata_filters_exclude_mismatched_first():
    """不匹配的 stage/grade/skill/owner 在向量/词法之前就被排除。"""
    router = MetadataFirstRetriever(None)
    mapping = str(mapping_id_for_skill(SKILL_ARITHMETIC))
    items = [
        _item("match", skills=(SKILL_ARITHMETIC,), mappings=(mapping,)),
        _item("wrong-stage", stage="primary", skills=(SKILL_ARITHMETIC,)),
        _item("wrong-grade", grade=6, skills=(SKILL_ARITHMETIC,)),
        _item("wrong-skill", skills=(SKILL_LINEAR_EQUATION,)),
        _item("wrong-owner", owner="student-b", skills=(SKILL_ARITHMETIC,)),
    ]
    results = await router.retrieve(
        "hint",
        items,
        owner_scope="student-a",
        stage="middle",
        grade=7,
        skill_codes=[SKILL_ARITHMETIC],
    )
    assert [r.item.item_id for r in results] == ["match"]
    matched = results[0].provenance["matched_metadata"]
    assert "owner_scope" in matched
    assert "stage" in matched
    assert "grade" in matched
    assert "skill" in matched


async def test_no_embedding_backend_degrades_with_vector_unavailable():
    """无 embedding backend → 降级为 metadata/词法，标注 vector unavailable；
    有 backend → 向量路径启用并标注 vector used。"""
    items = [
        _item("a", skills=(SKILL_ARITHMETIC,)),
        _item("b", skills=(SKILL_ARITHMETIC,)),
    ]
    router = MetadataFirstRetriever(None)  # 无 backend
    results = await router.retrieve("hint", items, owner_scope="student-a")
    assert len(results) == 2
    for result in results:
        assert result.provenance["vector"] == "unavailable"
        assert result.score is None
        assert result.provenance["reason"] == "metadata_lexical"

    router2 = MetadataFirstRetriever(build_fake_embedding_runtime(), NoOpReranker())
    results2 = await router2.retrieve("hint", items, owner_scope="student-a")
    assert len(results2) == 2
    for result in results2:
        assert result.provenance["vector"] == "used"
        assert result.score is not None
        assert result.provenance["embedding_backend"] == FAKE_BACKEND_ID


async def test_retrieval_disabled_sources_never_retrieved():
    """INVARIANT F：retrieval_enabled=false 的源即使请求完全匹配也不返回。"""
    router = MetadataFirstRetriever(None)
    mapping = str(mapping_id_for_concept(CONCEPT_LINEAR_EQUATIONS))
    items = [
        _item(
            "disabled",
            enabled=False,
            concepts=(CONCEPT_LINEAR_EQUATIONS,),
            mappings=(mapping,),
        ),
        _item(
            "enabled",
            concepts=(CONCEPT_LINEAR_EQUATIONS,),
            mappings=(mapping,),
        ),
    ]
    results = await router.retrieve(
        "hint",
        items,
        owner_scope="student-a",
        concept_codes=[CONCEPT_LINEAR_EQUATIONS],
        mapping_ids=[mapping],
    )
    assert [r.item.item_id for r in results] == ["enabled"]


async def test_noop_reranker_keeps_order_and_provenance():
    """NoOp reranker 保序截断；每个结果带来源 + 过滤原因 provenance。"""
    router = MetadataFirstRetriever(None, NoOpReranker())
    items = [
        _item("c", skills=(SKILL_ARITHMETIC,)),
        _item("a", skills=(SKILL_ARITHMETIC,)),
        _item("b", skills=(SKILL_ARITHMETIC,)),
    ]
    results = await router.retrieve(
        "hint",
        items,
        owner_scope="student-a",
        skill_codes=[SKILL_ARITHMETIC],
        limit=2,
    )
    assert [r.item.item_id for r in results] == ["c", "a"]
    for result in results:
        assert result.provenance["source_type"] == "curriculum"
        assert result.provenance["source_id"] == result.item.item_id
        assert "skill" in result.provenance["matched_metadata"]
        assert result.provenance["reranker"] == "NoOpReranker"
