"""Phase 6 第二轮 — INVARIANT C/D 顺序验证 + sqlite-vec 可选适配器测试。

第一部分（metadata-first 顺序，INVARIANT C）：证明元数据过滤严格先于
向量计算 —— 即使某条候选的向量相似度是全场最高（与命中条目同文本 →
余弦 1.0），只要 owner / retrieval_enabled / stage / grade / skill /
concept / mapping 任一不匹配就绝不出现；且 metadata 过滤结果为空时
embed_texts/embed_query 根本不被调用（计数 fake backend 断言 0 次）。

第二部分（sqlite-vec 可选适配器）：仅当 /tmp 探测产物存在时运行
（skip-if），且只从 /tmp 探测路径加载扩展；不可用路径的干净 DEGRADED
测试在任何机器上都运行。
"""

from __future__ import annotations

from pathlib import Path

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
from mathtutor.domain.embedding import EmbeddingDescriptor, EmbeddingVector
from mathtutor.infrastructure.embedding_runtime import (
    FakeEmbeddingBackend,
    build_fake_embedding_runtime,
)
from mathtutor.infrastructure.sqlite_vec_index import (
    SqliteVecUnavailableError,
    SqliteVecVectorIndex,
)
from mathtutor.learning.skills import (
    CONCEPT_LINEAR_EQUATIONS,
    CONCEPT_NUMBER_OPERATIONS,
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
)
from mathtutor.repositories.document_repository import cosine_similarity

pytestmark = pytest.mark.asyncio

# sqlite-vec 探测产物（第二轮实测 artifact，/tmp 下载解压，未安装）。
_PROBE_DYLIB = Path("/tmp/sqlite_vec_probe/extracted/sqlite_vec/vec0.dylib")
requires_sqlite_vec = pytest.mark.skipif(
    not _PROBE_DYLIB.exists(),
    reason="sqlite-vec 探测 dylib 不在 /tmp/sqlite_vec_probe（本轮实测环境专用）",
)

# 与命中条目逐字相同的文本：向量完全一致 → 余弦 1.0（理论上限）。
_CANON_TEXT = "加法交换律：两个数相加，交换加数的位置，和不变。"


class CountingEmbeddingBackend:
    """包装 FakeEmbeddingBackend 的计数后端：记录 embed 调用次数与入参。"""

    def __init__(self) -> None:
        self._inner = FakeEmbeddingBackend()
        self.texts_calls = 0
        self.query_calls = 0
        self.last_texts: list[str] = []

    def describe(self) -> EmbeddingDescriptor:
        return self._inner.describe()

    async def embed_texts(self, texts) -> list[EmbeddingVector]:
        self.texts_calls += 1
        self.last_texts = list(texts)
        return list(await self._inner.embed_texts(texts))

    async def embed_query(self, text: str) -> EmbeddingVector:
        self.query_calls += 1
        return await self._inner.embed_query(text)


def _item(
    item_id: str,
    *,
    text: str = "内容",
    owner: str = "student-a",
    enabled: bool = True,
    stage: str | None = "middle",
    grade: int | None = 7,
    skills: tuple[str, ...] = (),
    concepts: tuple[str, ...] = (),
    mappings: tuple[str, ...] = (),
) -> RetrievalItem:
    return RetrievalItem(
        item_id=item_id,
        text=text,
        source_type="curriculum",
        owner_scope=owner,
        retrieval_enabled=enabled,
        stage=stage,
        grade=grade,
        skill_codes=skills,
        concept_codes=concepts,
        mapping_ids=mappings,
    )


def _arithmetic_scope() -> tuple[
    tuple[str, ...], tuple[str, ...], tuple[str, ...]
]:
    """(skills, concepts, mappings) —— 小学算术条目的三组编码。"""
    return (
        (SKILL_ARITHMETIC,),
        (CONCEPT_NUMBER_OPERATIONS,),
        (
            str(mapping_id_for_skill(SKILL_ARITHMETIC)),
            str(mapping_id_for_concept(CONCEPT_NUMBER_OPERATIONS)),
        ),
    )


# ==================================================================
# 第一部分：metadata filter 严格先于 vector stage（INVARIANT C/D）
# ==================================================================


async def test_disabled_source_with_max_vector_similarity_never_retrieved():
    """retrieval_enabled=false 且文本与 query 命中条目逐字相同（向量分
    理论上限）→ 绝不出现。INVARIANT D：数据层/过滤层阻断优先。"""
    skills, concepts, mappings = _arithmetic_scope()
    router = MetadataFirstRetriever(build_fake_embedding_runtime(), NoOpReranker())
    items = [
        _item("disabled", text=_CANON_TEXT, enabled=False, skills=skills, concepts=concepts, mappings=mappings),
        _item("enabled", text=_CANON_TEXT, skills=skills, concepts=concepts, mappings=mappings),
    ]
    results = await router.retrieve(
        _CANON_TEXT,
        items,
        owner_scope="student-a",
        skill_codes=list(skills),
        concept_codes=list(concepts),
        mapping_ids=list(mappings),
        limit=5,
    )
    assert [r.item.item_id for r in results] == ["enabled"]
    assert results[0].provenance["vector"] == "used"  # 向量路径确实启用


async def test_foreign_owner_with_max_vector_similarity_never_retrieved():
    """owner 不匹配且文本与命中条目逐字相同 → 绝不出现（owner 隔离）。"""
    skills, concepts, _ = _arithmetic_scope()
    router = MetadataFirstRetriever(build_fake_embedding_runtime(), NoOpReranker())
    items = [
        _item("foreign", text=_CANON_TEXT, owner="student-b", skills=skills, concepts=concepts),
        _item("mine", text=_CANON_TEXT, skills=skills, concepts=concepts),
    ]
    results = await router.retrieve(
        _CANON_TEXT,
        items,
        owner_scope="student-a",
        skill_codes=list(skills),
        concept_codes=list(concepts),
        limit=5,
    )
    assert [r.item.item_id for r in results] == ["mine"]


async def test_mismatched_metadata_excluded_even_with_highest_vector_score():
    """stage/grade/skill/concept/mapping 不匹配的条目即使向量分最高
    （与 query 文本逐字相同）也绝不出现。"""
    skills, concepts, mappings = _arithmetic_scope()
    router = MetadataFirstRetriever(build_fake_embedding_runtime(), NoOpReranker())
    items = [
        _item("match", text=_CANON_TEXT, skills=skills, concepts=concepts, mappings=mappings),
        _item("wrong-stage", text=_CANON_TEXT, stage="primary", skills=skills, concepts=concepts, mappings=mappings),
        _item("wrong-grade", text=_CANON_TEXT, grade=6, skills=skills, concepts=concepts, mappings=mappings),
        _item("wrong-skill", text=_CANON_TEXT, skills=(SKILL_LINEAR_EQUATION,), concepts=concepts, mappings=mappings),
        _item("wrong-concept", text=_CANON_TEXT, skills=skills, concepts=(CONCEPT_LINEAR_EQUATIONS,), mappings=mappings),
        _item("wrong-mapping", text=_CANON_TEXT, skills=skills, concepts=concepts, mappings=()),
    ]
    results = await router.retrieve(
        _CANON_TEXT,
        items,
        owner_scope="student-a",
        stage="middle",
        grade=7,
        skill_codes=list(skills),
        concept_codes=list(concepts),
        mapping_ids=list(mappings),
        limit=10,
    )
    assert [r.item.item_id for r in results] == ["match"]
    matched = results[0].provenance["matched_metadata"]
    for expected in ("owner_scope", "retrieval_enabled", "stage", "grade", "skill", "concept", "mapping_id"):
        assert expected in matched


async def test_empty_metadata_filter_never_calls_embedding():
    """metadata 过滤结果为空 → embed_texts/embed_query 调用次数为 0
    （向量计算严格发生在过滤之后）。"""
    counting = CountingEmbeddingBackend()
    from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime

    router = MetadataFirstRetriever(EmbeddingRuntime(counting), NoOpReranker())
    items = [
        _item("foreign", text=_CANON_TEXT, owner="student-b"),
        _item("disabled", text=_CANON_TEXT, enabled=False),
    ]
    results = await router.retrieve(_CANON_TEXT, items, owner_scope="student-a")
    assert results == []
    assert counting.texts_calls == 0
    assert counting.query_calls == 0


async def test_partial_filter_embeds_only_filtered_items():
    """部分条目被过滤时，embed_texts 只收到过滤后条目的文本 ——
    被排除的文本永远不会进入向量计算。"""
    counting = CountingEmbeddingBackend()
    from mathtutor.infrastructure.embedding_runtime import EmbeddingRuntime

    router = MetadataFirstRetriever(EmbeddingRuntime(counting), NoOpReranker())
    items = [
        _item("disabled", text="被禁用的文本", enabled=False),
        _item("foreign", text="别的学生的文本", owner="student-b"),
        _item("kept", text="保留的文本"),
    ]
    await router.retrieve("保留", items, owner_scope="student-a", limit=5)
    assert counting.texts_calls == 1
    assert counting.last_texts == ["保留的文本"]


# ==================================================================
# 第二部分：sqlite-vec 可选适配器（skip-if 扩展不可用；只从 /tmp 探测产物加载）
# ==================================================================


def test_sqlite_vec_unavailable_path_degrades_cleanly():
    """sqlite-vec 不可用（扩展路径不存在/不可加载）→ 构造 fail-closed、
    try_open 干净返回 None、probe 返回 False —— 绝不崩溃。"""
    bogus = "/tmp/does/not/exist/sqlite_vec_missing.dylib"
    with pytest.raises(SqliteVecUnavailableError):
        SqliteVecVectorIndex(bogus, dimension=4)
    assert SqliteVecVectorIndex.try_open(bogus, dimension=4) is None
    assert SqliteVecVectorIndex.probe(bogus) is False


async def test_sqlite_vec_rejects_invalid_entries():
    """维度不匹配/非有限值/重复标识 → ValueError（fail-closed，与
    validate_vector 同一纪律）。"""
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    with pytest.raises(ValueError):
        await index.build([("a", (0.1, 0.2, 0.3))])  # 维度 3 ≠ 4
    with pytest.raises(ValueError):
        await index.build([("a", (0.1, float("nan"), 0.3, 0.4))])
    with pytest.raises(ValueError):
        await index.build([("a", (1.0, 0.0, 0.0, 0.0)), ("a", (0.0, 1.0, 0.0, 0.0))])
    index.close()


@requires_sqlite_vec
async def test_sqlite_vec_probe_and_version():
    """探测产物在本 Python 上真实可加载（第二轮实测的回归钉）。"""
    assert SqliteVecVectorIndex.probe(str(_PROBE_DYLIB)) is True
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    assert index.extension_version().startswith("v")
    assert index.indexed_count() == 0
    index.close()


@requires_sqlite_vec
async def test_sqlite_vec_search_matches_full_scan_cosine():
    """vec0 KNN 排序与 full-scan cosine 排序一致（相似度数值容差内相等）
    —— 证明可选 ANN 路径与既有 full-scan fusion 契约可互换。"""
    # 契约：向量为 L2-normalized（descriptor.normalization="l2"）；
    # 全量扫描参照用点积（normalized 时点积 == 余弦）。
    entries = [
        ("zero", (1.0, 0.0, 0.0, 0.0)),
        ("one", (0.0, 1.0, 0.0, 0.0)),
        ("diag", (0.7071067811865476, 0.7071067811865476, 0.0, 0.0)),
        ("neg", (-1.0, 0.0, 0.0, 0.0)),
    ]
    query = (0.6, 0.8, 0.0, 0.0)  # |query| = 1.0
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    assert await index.build(entries) == 4
    hits = await index.search(query, k=4)

    expected = sorted(
        (
            entry_id,
            max(-1.0, min(1.0, cosine_similarity(query, vector))),
        )
        for entry_id, vector in entries
    )
    expected.sort(key=lambda row: row[1], reverse=True)
    assert [hit.id for hit in hits] == [entry_id for entry_id, _ in expected]
    for hit, (_, wanted) in zip(hits, expected):
        assert abs(hit.similarity - wanted) < 1e-5
    index.close()


@requires_sqlite_vec
async def test_sqlite_vec_rebuild_replaces_entries_and_empty_search():
    """build 是整体替换（derived projection，绝不追加）；空索引/非正 k
    搜索返回空列表。"""
    index = SqliteVecVectorIndex(str(_PROBE_DYLIB), dimension=4)
    await index.build([("old-1", (1.0, 0.0, 0.0, 0.0)), ("old-2", (0.0, 1.0, 0.0, 0.0))])
    assert await index.search((1.0, 0.0, 0.0, 0.0), k=0) == []
    assert await index.search((1.0, 0.0, 0.0, 0.0), k=-1) == []

    await index.build([("new-1", (0.0, 0.0, 1.0, 0.0))])
    assert index.indexed_count() == 1
    hits = await index.search((0.0, 0.0, 1.0, 0.0), k=10)
    assert [hit.id for hit in hits] == ["new-1"]  # 旧条目已被整体替换
    assert abs(hits[0].similarity - 1.0) < 1e-5
    index.close()
