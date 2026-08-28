"""Phase 6 第二轮 — LexicalScoreReranker 单元 + 集成 + provenance 测试。

覆盖：[x] reranker 可选；[x] NoOp 路径不变；[x] provenance 每个
RetrievedResult 带 source_type/source_id/matched_metadata/vector
marker/reranker 名；[x] 导出给评测的 provenance 不含任何内部 DB row
字段（只有 item 投影 + provenance dict）。

LexicalScoreReranker 契约（与 router 的 Reranker Protocol 一致）：
确定性、稳定排序（同分保持输入顺序）、截断到 limit、纯函数式。
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from mathtutor.application.lexical_reranker import LexicalScoreReranker
from mathtutor.application.retrieval_router import (
    MetadataFirstRetriever,
    NoOpReranker,
    RetrievalItem,
    RetrievedResult,
    VECTOR_UNAVAILABLE,
    VECTOR_USED,
)
from mathtutor.infrastructure.embedding_runtime import build_fake_embedding_runtime
from mathtutor.infrastructure.lexical import lexical_score, tokenize_lexical

pytestmark = pytest.mark.asyncio


def _item(item_id: str, text: str, *, owner: str = "student-a") -> RetrievalItem:
    return RetrievalItem(
        item_id=item_id,
        text=text,
        source_type="curriculum",
        owner_scope=owner,
        retrieval_enabled=True,
        stage="middle",
        grade=7,
    )


# ==================================================================
# 单元：确定性 / 稳定排序 / 截断 / 纯函数式
# ==================================================================


async def test_reranker_scores_lexical_overlap_descending():
    """按 query 词元覆盖率降序重排；同分保持输入顺序（stable）。"""
    reranker = LexicalScoreReranker()
    candidates = [
        _item("none", "完全无关的内容"),
        _item("half", "交换加数"),
        _item("full", "加法交换律：交换加数位置，和不变"),
        _item("tie-a", "交换加数的位置"),
        _item("tie-b", "加数位置交换"),
    ]
    ranked = await reranker.rerank("加法交换律 交换加数", candidates, limit=10)
    # half / tie-a / tie-b 同分（2/5），保持输入顺序（stable）。
    assert [item.item_id for item in ranked] == ["full", "half", "tie-a", "tie-b", "none"]
    # 与 lexical_score 逐字一致的分数语义
    tokens = tokenize_lexical("加法交换律 交换加数")
    assert lexical_score("加法交换律：交换加数位置，和不变", tokens) == 1.0
    assert lexical_score("完全无关的内容", tokens) == 0.0


async def test_reranker_truncates_to_limit():
    reranker = LexicalScoreReranker()
    candidates = [_item(f"c{i}", f"文本 {i}") for i in range(5)]
    ranked = await reranker.rerank("文本", candidates, limit=3)
    assert len(ranked) == 3
    # 截断之外的内容确实来自输入（不新增、不篡改）
    assert all(any(item is candidate for candidate in candidates) for item in ranked)


async def test_reranker_is_deterministic_and_pure():
    """同一输入两次调用逐对象相同；无 text 属性的候选按 0 分沉底。"""
    reranker = LexicalScoreReranker()
    plain = _item("plain", "加法交换律")
    class NoText:  # 模拟无 text 的候选（Protocol 是 Any）
        pass

    candidates: list[Any] = [plain, NoText()]
    first = await reranker.rerank("加法交换律", candidates, limit=5)
    second = await reranker.rerank("加法交换律", candidates, limit=5)
    assert first == second
    assert first[0] is plain  # 无 text 者 0 分沉底且保序


async def test_empty_query_tokens_sink_everything_but_keep_order():
    """空 query 词元 → 全员 0 分 → 输出 = 输入（稳定、截断）。"""
    reranker = LexicalScoreReranker()
    candidates = [_item("a", "甲"), _item("b", "乙"), _item("c", "丙")]
    ranked = await reranker.rerank("!!!", candidates, limit=2)
    assert [item.item_id for item in ranked] == ["a", "b"]


# ==================================================================
# 集成：MetadataFirstRetriever(reranker=LexicalScoreReranker())
# ==================================================================


async def test_reranker_integration_reorders_and_records_provenance():
    """注入 LexicalScoreReranker 后：重排生效、provenance.reranker 正确；
    NoOp 路径保持输入顺序不变（NoOp 路径不变的回归钉）。"""
    items = [
        _item("vector-top", "无关的向量高分文本无关"),
        _item("lexical-top", "加法交换律：交换加数的位置和不变"),
        _item("lexical-mid", "交换加数"),
    ]

    noop = MetadataFirstRetriever(build_fake_embedding_runtime(), NoOpReranker())
    noop_results = await noop.retrieve("加法交换律", items, owner_scope="student-a", limit=3)
    assert [r.provenance["reranker"] for r in noop_results] == ["NoOpReranker"] * 3
    assert noop_results[0].provenance["vector"] == VECTOR_USED

    reranked = MetadataFirstRetriever(build_fake_embedding_runtime(), LexicalScoreReranker())
    results = await reranked.retrieve("加法交换律", items, owner_scope="student-a", limit=3)
    assert [r.item.item_id for r in results] == ["lexical-top", "lexical-mid", "vector-top"]
    for result in results:
        assert result.provenance["reranker"] == "LexicalScoreReranker"


async def test_reranker_works_on_degraded_lexical_path_too():
    """无 embedding backend（vector unavailable）时 reranker 依然生效
    —— 词法重排与向量存在与否解耦。"""
    items = [
        _item("b", "乙内容"),
        _item("a", "加法交换律内容"),
    ]
    router = MetadataFirstRetriever(None, LexicalScoreReranker())
    results = await router.retrieve("加法交换律", items, owner_scope="student-a", limit=2)
    assert [r.item.item_id for r in results] == ["a", "b"]
    assert results[0].provenance["vector"] == VECTOR_UNAVAILABLE
    assert results[0].provenance["reranker"] == "LexicalScoreReranker"


# ==================================================================
# Provenance（§4.6）：导出给评测的投影不含内部 DB row 字段
# ==================================================================

#: 评测导出允许的 provenance 键白名单（router 的投影契约；向量路径
#: 会额外带 embedding_backend id —— 后端标识，非 DB row 字段）。
_EXPORT_PROVENANCE_KEYS = frozenset(
    {"source_type", "source_id", "matched_metadata", "reason", "vector",
     "reranker", "embedding_backend"}
)
#: item 投影白名单：交给 LLM/评测的只有这些字段，绝无内部 DB row 字段。
_EXPORT_ITEM_KEYS = frozenset(
    {"item_id", "text", "source_type", "owner_scope", "retrieval_enabled",
     "stage", "grade", "skill_codes", "concept_codes", "mapping_ids", "extra"}
)


def project_for_evaluation(results: list[RetrievedResult]) -> list[dict[str, Any]]:
    """评测/LLM 导出投影：item 白名单字段 + provenance dict，仅此而已。

    该函数是「provenance 不含内部 DB row 字段」的可执行定义：任何
    数据库内部字段（created_at、storage_ref、content_hash、rowid、
    deleted_at、status……）都不在白名单内，出现即测试失败。
    """
    exported: list[dict[str, Any]] = []
    for result in results:
        exported.append(
            {
                **{key: getattr(result.item, key) for key in _EXPORT_ITEM_KEYS},
                "provenance": dict(result.provenance),
            }
        )
    return exported


async def test_provenance_fields_complete_on_both_paths():
    """每个 RetrievedResult 带全量 provenance（两条路径分别验证）。"""
    items = [_item("a", "加法交换律内容")]
    for runtime in (None, build_fake_embedding_runtime()):
        router = MetadataFirstRetriever(runtime, LexicalScoreReranker())
        results = await router.retrieve("加法交换律", items, owner_scope="student-a")
        assert len(results) == 1
        provenance = results[0].provenance
        for key in ("source_type", "source_id", "matched_metadata", "reason", "vector", "reranker"):
            assert key in provenance
        assert provenance["source_id"] == "a"
        assert provenance["source_type"] == "curriculum"
        assert "owner_scope" in provenance["matched_metadata"]


async def test_evaluation_export_contains_no_internal_db_row_fields():
    """导出给评测的内容只有 item 投影 + provenance dict；任何内部 DB
    row 字段（created_at/storage_ref/content_hash/status/rowid/…）都不
    得出现 —— 不把内部完整 DB row 交给 LLM。"""
    router = MetadataFirstRetriever(build_fake_embedding_runtime(), LexicalScoreReranker())
    items = [_item("a", "加法交换律内容"), _item("b", "交换加数")]
    results = await router.retrieve("加法交换律", items, owner_scope="student-a", limit=2)

    exported = project_for_evaluation(results)
    internal_row_fields = {
        "created_at", "storage_ref", "content_hash", "status", "rowid",
        "deleted_at", "document_id", "chunk_id", "sequence", "page",
        "parser_version", "chunker_version", "student_id", "filename",
    }
    for entry in exported:
        assert set(entry["provenance"]) <= _EXPORT_PROVENANCE_KEYS
        assert set(entry) - {"provenance"} == _EXPORT_ITEM_KEYS
        for field in internal_row_fields:
            assert field not in entry
            assert field not in entry["provenance"]
    # 导出为纯数据（无对象引用/连接/游标），可 JSON 序列化。
    json.dumps(exported, ensure_ascii=False)  # 不抛异常即通过


async def test_provenance_matched_metadata_records_filter_reasons():
    """matched_metadata 记录实际命中的过滤维度（含 owner/retrieval）。"""
    router = MetadataFirstRetriever(None, NoOpReranker())
    items = [_item("a", "内容", owner="student-a")]
    results = await router.retrieve(
        "hint", items, owner_scope="student-a", stage="middle", grade=7
    )
    matched = results[0].provenance["matched_metadata"]
    assert matched == ["owner_scope", "retrieval_enabled", "stage", "grade"]
