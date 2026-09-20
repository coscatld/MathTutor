"""DEPRECATED — SUPERSEDED.

Replaced by ``tests/test_rag_production_benchmark.py``, which scores the
REAL production contract (real SQLite corpus -> DocumentIndexManager ->
ConversationRetrievalOrchestrator -> ProductionReranker -> EvidencePack)
instead of hand-built ``RetrievalItem`` projections. Its frozen numbers
responded to nothing in the product.

Kept only until the last consumer of ``MetadataFirstRetriever`` is removed;
it is NOT an official benchmark any more. The official one is the migrated
file named above.
Phase 6 第二轮 — 检索评测 benchmark（小规模、确定性、进常规套件）。

三链路对比（同一固定语料 + 同一 ground truth）：

- ``lexical``：词法基线 —— 无 embedding backend（vector unavailable）
  的 metadata/词法路径，候选按词法分预排序；
- ``lexical+vector``：FakeEmbeddingBackend 向量重排 + NoOpReranker；
- ``lexical+vector+reranker``：向量重排后接 LexicalScoreReranker。

指标：Recall@K / MRR / nDCG（K=3/5，简单确定性实现，二元相关）；
以固定语料的**具体数值**断言（不是阈值判断）—— 任何上游行为漂移
都会让数值变化，使 benchmark 成为回归钉。另断言：禁用文档/错 owner
文档在所有链路所有 query 中贡献为零；同一 pipeline 重复运行逐位相同。

实测（2026-08-21）的链路对比结论：词法基线满分；确定性伪随机向量
（FakeEmbeddingBackend）会打乱排序；LexicalScoreReranker 完全纠偏。
真实 embedding 模型上线后本 benchmark 数值会变 —— 届时更新冻结值并
把该变化记录进检索评测文档，而不是悄悄放宽断言。

全部纯内存、无网络、无模型，随常规 pytest 运行（亚秒级）。
"""

from __future__ import annotations

import math
from typing import Sequence

import pytest

from mathtutor.application.lexical_reranker import LexicalScoreReranker
from mathtutor.application.retrieval_router import (
    MetadataFirstRetriever,
    NoOpReranker,
    RetrievalItem,
)
from mathtutor.infrastructure.embedding_runtime import (
    EmbeddingRuntime,
    build_fake_embedding_runtime,
)
from mathtutor.infrastructure.lexical import lexical_score, tokenize_lexical

from benchmark_fixtures import (
    BENCHMARK_QUERIES,
    OWNER_A,
    ZERO_CONTRIBUTION_IDS,
    BenchmarkQuery,
    build_corpus,
)

pytestmark = pytest.mark.asyncio

# ------------------------------------------------------------- metrics
# 二元相关；位置 i 从 0 起，折扣 1/log2(i+2)（nDCG 的 MSLR 惯例）。


def recall_at_k(ranked_ids: Sequence[str], relevant: frozenset[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked_ids[:k]) & relevant) / len(relevant)


def mrr_at_k(ranked_ids: Sequence[str], relevant: frozenset[str], k: int) -> float:
    for position, item_id in enumerate(ranked_ids[:k], start=1):
        if item_id in relevant:
            return 1.0 / position
    return 0.0


def ndcg_at_k(ranked_ids: Sequence[str], relevant: frozenset[str], k: int) -> float:
    gains = [1.0 if item_id in relevant else 0.0 for item_id in ranked_ids[:k]]
    dcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(gains))
    ideal = sorted(gains, reverse=True)
    idcg = sum(gain / math.log2(index + 2) for index, gain in enumerate(ideal))
    return dcg / idcg if idcg > 0.0 else 0.0


# ------------------------------------------------------------ pipelines
# 词法基线预排序：真实检索链里仓库按词法分排序，router 无向量时保序。


def _lexical_preorder(query: str, items: Sequence[RetrievalItem]) -> list[RetrievalItem]:
    tokens = tokenize_lexical(query)
    scored = [(lexical_score(item.text, tokens), index, item) for index, item in enumerate(items)]
    scored.sort(key=lambda row: row[0], reverse=True)
    return [item for _, _, item in scored]


def _build_router(pipeline: str):
    if pipeline == "lexical":
        return MetadataFirstRetriever(EmbeddingRuntime(), NoOpReranker())
    runtime = build_fake_embedding_runtime()
    if pipeline == "lexical+vector":
        return MetadataFirstRetriever(runtime, NoOpReranker())
    if pipeline == "lexical+vector+reranker":
        return MetadataFirstRetriever(runtime, LexicalScoreReranker())
    raise ValueError(f"unknown pipeline: {pipeline!r}")


PIPELINES: tuple[str, ...] = ("lexical", "lexical+vector", "lexical+vector+reranker")


async def _ranked_ids(router, query_spec: BenchmarkQuery, items) -> list[str]:
    results = await router.retrieve(
        query_spec.query,
        _lexical_preorder(query_spec.query, items),
        owner_scope=OWNER_A,
        stage=query_spec.stage,
        grade=query_spec.grade,
        skill_codes=query_spec.skill_codes,
        concept_codes=query_spec.concept_codes,
        mapping_ids=query_spec.mapping_ids,
        limit=5,
    )
    return [result.item.item_id for result in results]


async def _pipeline_metrics(pipeline: str) -> tuple[float, ...]:
    """一次完整运行：7 query × 6 指标取均值 → 6 元组（round 6）。"""
    items = build_corpus()
    router = _build_router(pipeline)
    per_query: list[tuple[float, ...]] = []
    for query_spec in BENCHMARK_QUERIES:
        ranked = await _ranked_ids(router, query_spec, items)
        per_query.append(
            (
                recall_at_k(ranked, query_spec.relevant_ids, 3),
                recall_at_k(ranked, query_spec.relevant_ids, 5),
                mrr_at_k(ranked, query_spec.relevant_ids, 3),
                mrr_at_k(ranked, query_spec.relevant_ids, 5),
                ndcg_at_k(ranked, query_spec.relevant_ids, 3),
                ndcg_at_k(ranked, query_spec.relevant_ids, 5),
            )
        )
    count = len(per_query)
    return tuple(
        round(sum(row[column] for row in per_query) / count, 6)
        for column in range(6)
    )


#: 2026-08-21 实测冻结的精确指标（Recall@3, Recall@5, MRR@3, MRR@5,
#: nDCG@3, nDCG@5）—— 任何检索链漂移都会改变这些数值。
#: 实测结论：词法基线在本语料上满分；FakeEmbeddingBackend 的确定性伪
#: 随机向量会把好排序打乱（Recall@3 掉到 0.5）；LexicalScoreReranker
#: 把向量噪声完全纠偏回满分 —— 这正是「向量可选、词法保底」的设计意图。
EXPECTED_METRICS: dict[str, tuple[float, ...]] = {
    "lexical": (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
    "lexical+vector": (0.5, 0.785714, 0.380952, 0.452381, 0.428571, 0.561714),
    "lexical+vector+reranker": (1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
}


# ------------------------------------------------------------- 指标单元


def test_metric_functions_hand_computed():
    ranked = ["a", "b", "c", "d", "e"]
    relevant = frozenset({"c", "e"})
    assert recall_at_k(ranked, relevant, 3) == pytest.approx(1 / 2)
    assert recall_at_k(ranked, relevant, 5) == pytest.approx(1.0)
    assert mrr_at_k(ranked, relevant, 3) == pytest.approx(1 / 3)
    assert mrr_at_k(ranked, relevant, 5) == pytest.approx(1 / 3)
    assert mrr_at_k(["x", "y"], relevant, 2) == 0.0
    # nDCG@3：gains [0,0,1]，dcg = 1/log2(4)（位置 2，0 起）；idcg = 1/log2(2)。
    assert ndcg_at_k(ranked, relevant, 3) == pytest.approx(0.5)
    assert ndcg_at_k(["x"], frozenset(), 3) == 0.0
    assert recall_at_k([], frozenset(), 3) == 0.0


# ------------------------------------------------------------- benchmark


async def test_benchmark_metrics_exactly_reproducible():
    """三链路指标与 2026-08-21 冻结数值逐位相等（固定语料回归钉）。"""
    for pipeline, expected in EXPECTED_METRICS.items():
        measured = await _pipeline_metrics(pipeline)
        # Demo 可观测性：`pytest -s` 时打印实测链路指标（断言仍是权威）。
        print(f"[benchmark] {pipeline}: {measured}")
        assert measured == expected, f"{pipeline}: {measured} != {expected}"


async def test_disabled_and_foreign_documents_contribute_zero():
    """禁用文档/错 owner 文档在所有链路所有 query 中贡献为零
    （INVARIANT D + owner 隔离的评测面证据）。"""
    items = build_corpus()
    for pipeline in PIPELINES:
        router = _build_router(pipeline)
        for query_spec in BENCHMARK_QUERIES:
            ranked = await _ranked_ids(router, query_spec, items)
            assert not (set(ranked) & ZERO_CONTRIBUTION_IDS), (
                f"{pipeline} / {query_spec.query!r} 泄漏了阻断条目: {set(ranked) & ZERO_CONTRIBUTION_IDS}"
            )


async def test_stage_filter_blocks_shared_keyword_docs():
    """stage 过滤下共享「方程」关键词的初中条目绝不出现（即使向量/
    词法都能召回它）。"""
    items = build_corpus()
    for pipeline in PIPELINES:
        router = _build_router(pipeline)
        for query_spec in (q for q in BENCHMARK_QUERIES if q.query == "方程"):
            ranked = await _ranked_ids(router, query_spec, items)
            for item_id in ranked:
                item = next(i for i in items if i.item_id == item_id)
                assert item.stage == "primary"


async def test_benchmark_is_deterministic_across_runs():
    """同一 pipeline 连续两次运行逐 query 逐位相同（确定性）。"""
    items = build_corpus()
    for pipeline in PIPELINES:
        router = _build_router(pipeline)
        first = [
            await _ranked_ids(router, query_spec, items) for query_spec in BENCHMARK_QUERIES
        ]
        second = [
            await _ranked_ids(router, query_spec, items) for query_spec in BENCHMARK_QUERIES
        ]
        assert first == second


async def test_reranker_pipeline_provenance_marker():
    """benchmark 链路里 reranker provenance 标记正确（导出审计用）。"""
    router = _build_router("lexical+vector+reranker")
    results = await router.retrieve(
        "加法交换律",
        build_corpus(),
        owner_scope=OWNER_A,
        stage="primary",
        limit=5,
    )
    assert results
    assert all(r.provenance["reranker"] == "LexicalScoreReranker" for r in results)
