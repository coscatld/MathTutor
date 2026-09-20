"""DEPRECATED (Route 2, docs/CURRENT_STATE_RAG_AUDIT.md §4.3).

Superseded by ``application/rerank.py::ProductionReranker``, which ranks
real ``RetrievedChunk`` objects. This implementation reads
``getattr(candidate, "text", "")`` — empty for a ``RetrievedChunk``, whose
text lives at ``.chunk.text`` — so it scored every real hit zero. That is
exactly why the production path needed a reranker written against the real
contract rather than an adapter to this one.

No production callers. Do NOT wire into a production path.
LexicalScoreReranker — deterministic, model-free local reranker.

Phase 6 第二轮检索基础设施。实现 :mod:`mathtutor.application
.retrieval_router` 中声明的 ``Reranker`` Protocol（直接 import 该
Protocol，不复制定义）：基于 query 与候选文本的词法重合度对「已按
向量/元数据排序」的候选做确定性重排。

设计约束（与本文件永久绑定）：

- 纯函数式：无网络、无模型、无权重、无随机数；同一输入永远同一输出；
- 确定性稳定排序：分数相同的候选保持输入顺序（Python sort 稳定）；
  只截断到 ``limit``，不新增、不丢弃未超限的候选之外的任何内容；
- 打分复用 :mod:`mathtutor.infrastructure.lexical` 的
  ``tokenize_lexical`` + ``lexical_score``（CJK bigram + latin 词法），
  与词法检索共用同一套分词语义 —— 重排结果与 lexical baseline 可比；
- CPU-safe / 离线可用：数学语料关键词密集，词法重合是最便宜的
  「向量误召」纠偏信号，且不引入任何 Embedding Distribution 依赖
  （INVARIANT F：Embedding Model / Distribution Strategy 仍 DEFERRED）。

复杂度：O(N × T × L)，N 为候选数、T 为 query 词元数、L 为候选文本
平均长度（子串匹配）；对本地桌面规模的候选集（几十条）为亚毫秒级。
"""

from __future__ import annotations

from typing import Any, Sequence

from mathtutor.application.retrieval_router import Reranker
from mathtutor.infrastructure.lexical import (
    lexical_score,
    tokenize_lexical,
)


class LexicalScoreReranker:
    """按 query 词元在候选文本中的覆盖率（[0, 1]）降序重排。

    候选来自 router 的向量/元数据排序结果（``Sequence[Any]``，实际为
    ``RetrievalItem``）。无 ``text`` 属性的候选按 0 分沉底并保持原
    相对顺序 —— 不崩溃、不臆造分数。打分公式与词法检索一致：

        score(item) = |{query 词元 t : t 出现在 item.text 中}| / |query 词元|

    CJK 用 bigram（单字词元按单字）、latin/digit 用词边界词元，全部
    小写化后子串匹配 —— 与 :func:`lexical_score` 逐字相同。
    """

    async def rerank(
        self,
        query_hint: str,
        candidates: Sequence[Any],
        limit: int,
    ) -> list[Any]:
        query_tokens = tokenize_lexical(query_hint)
        # (score, index, candidate)：index 兜底保证完全确定性（分数
        # 相同时保持输入顺序 —— Python sort 本身稳定，index 仅是
        # 显式声明，防未来换成不稳定排序算法）。
        scored = [
            (lexical_score(getattr(candidate, "text", ""), query_tokens), index, candidate)
            for index, candidate in enumerate(candidates)
        ]
        scored.sort(key=lambda row: row[0], reverse=True)
        return [candidate for _, _, candidate in scored[:limit]]


__all__ = ["LexicalScoreReranker"]
