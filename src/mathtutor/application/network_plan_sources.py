"""Choose a reading excerpt from this answer's retained source evidence."""
from __future__ import annotations

import re
from datetime import UTC, datetime

from pydantic import ValidationError

from mathtutor.application.exploration_evidence import SourceSnapshot, build_evidence_spans, text_hash
from mathtutor.application.learning_actions import GOALS, goal_label
from mathtutor.learning.skill_graph import SKILLS

_AMBIGUOUS = {"符号", "两边", "平衡", "系数", "隔离", "代入", "检验", "验算", "成立", "合并", "展开",
              "未知数", "等价", "根号", "分解", "十字", "配方", "二元", "消去", "加减法", "都满足"}
_DOMAIN_TERMS = {
    "calculus": ("微积分", "导数", "极限", "可导", "calculus", "derivative", "limits", "differentiability"),
    "probability": ("概率", "贝叶斯", "probability", "bayes"),
    "linear_algebra": ("线性代数", "向量空间", "linear algebra", "vector space"),
    "machine_learning": ("机器学习", "深度学习", "machine learning", "deep learning"),
    "algorithms": ("算法", "数据结构", "algorithm", "algorithms", "data structures"),
    "research_methods": ("科研方法", "论文阅读", "reading papers", "research methods"),
}


def _matches(target, text):
    if target in SKILLS:
        skill = SKILLS[target]
        terms = (skill.label, goal_label(target, "en"), *(a for a in skill.aliases if a not in _AMBIGUOUS))
    elif target in GOALS:
        terms = _DOMAIN_TERMS.get(target, GOALS[target][:2])
    else:
        return False
    return any(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text, re.I)
               if term.isascii() else term in text for term in terms)


def _bind(evidence, registry):
    metadata = registry.get(evidence.get("source_id"))
    if not metadata:
        return None
    try:
        source = SourceSnapshot.model_validate({k: v for k, v in metadata.items() if k in SourceSnapshot.model_fields})
        if source.duplicate_of or source.content_warnings:
            return None
        span = next((s for s in build_evidence_spans((source,)) if s.span_id == evidence["span_id"]), None)
        start, end = evidence.get("quote_start"), evidence.get("quote_end")
        if (span is None or evidence.get("span_sha256") != text_hash(span.text) or
                evidence.get("span_start") != span.start or evidence.get("span_end") != span.end or
                type(start) is not int or type(end) is not int or not span.start <= start < end <= span.end or
                source.text[start:end] != evidence["quote"]):
            return None
    except (ValidationError, KeyError, TypeError, ValueError):
        return None
    return source, metadata, evidence


def choose_current_reading(sources, claims, retained_ids, *, target, language):
    """Require a retained claim, live premises and a bound, target-specific quote."""
    registry = {row["source_id"]: row for row in sources}
    retained, valid = set(retained_ids), set()
    candidates = []
    for claim in claims:
        if (claim["claim_id"] not in retained or not claim["accepted"] or
                claim.get("source_support") != "supported" or claim["kind"] not in {"source_statement", "author_view"} or
                claim.get("math") == "incorrect" or not set(claim["dependencies"]) <= valid):
            continue
        bindings = [_bind(evidence, registry) for evidence in claim["evidence"]]
        if not bindings or any(bound is None for bound in bindings):
            continue
        valid.add(claim["claim_id"])
        if _matches(target, claim["text"]):
            candidates.extend((claim, *bound) for bound in bindings if _matches(target, bound[2]["quote"]))
    if not candidates:
        return None
    claim, source, metadata, evidence = candidates[0]
    quote = evidence["quote"]
    preview = quote if len(quote) <= 180 else quote[:180] + "…"
    label = goal_label(target, language)
    reason = (f"本次摘要包含“{preview}”，对应当前“{label}”目标；先选读这一段，再按本次安排练习和核对。"
              if language == "zh" else
              f'The retrieved excerpt includes “{preview}”, matching your current goal, {label}. Read this passage, then follow the practice and check steps in this plan.')
    stamp = metadata.get("published_or_updated_at")
    source_time = datetime.fromtimestamp(stamp, UTC).isoformat() if type(stamp) is int and 0 < stamp < 253402300800 else None
    return {"resource_id": source.source_id, "title": source.title, "author": source.author,
            "url": source.original_url, "summary": quote, "summary_sha256": text_hash(quote),
            "excerpt_sha256": source.text_sha256, "selection_reason": reason,
            "source_time": source_time, "source_time_kind": "published_or_updated" if source_time else "unknown",
            "origin": "current_search_summary", "source_id": source.source_id,
            "supporting_claim_ids": [claim["claim_id"], *claim["dependencies"]],
            "span_id": evidence["span_id"], "quote_start": evidence["quote_start"], "quote_end": evidence["quote_end"]}
