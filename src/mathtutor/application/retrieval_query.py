"""Chinese retrieval query pack for user-document search.

Skill/concept *codes* (``LINEAR_EQUATION`` …) are filters and curriculum
node ids. They are NOT the lexical query: uploaded notes are Chinese, so
the query is the knowledge-point title + aliases + the student's own
problem text / misconception titles.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from mathtutor.learning.diagnosis import RULES
from mathtutor.learning.skills import (
    CONCEPT_LINEAR_EQUATIONS,
    CONCEPT_NUMBER_OPERATIONS,
    CONCEPT_POLYNOMIALS,
    CONCEPT_QUADRATIC_EQUATIONS,
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
    SKILL_POLYNOMIAL_BASIC,
    SKILL_QUADRATIC_EQUATION,
)

# Title is the canonical Chinese name; aliases expand lexical coverage.
_SKILL_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    SKILL_ARITHMETIC: ("四则运算", "分数运算", "加减乘除", "数的运算"),
    SKILL_POLYNOMIAL_BASIC: ("多项式基础", "整式运算", "多项式", "合并同类项"),
    SKILL_LINEAR_EQUATION: ("一元一次方程", "一次方程", "解方程", "移项"),
    SKILL_QUADRATIC_EQUATION: ("一元二次方程", "二次方程", "求根公式", "判别式"),
}

_CONCEPT_QUERY_TERMS: dict[str, tuple[str, ...]] = {
    CONCEPT_NUMBER_OPERATIONS: ("数与运算", "四则运算"),
    CONCEPT_POLYNOMIALS: ("多项式", "整式"),
    CONCEPT_LINEAR_EQUATIONS: ("一次方程", "一元一次方程"),
    CONCEPT_QUADRATIC_EQUATIONS: ("二次方程", "一元二次方程"),
}

_MISCONCEPTION_TITLES: dict[str, str] = {rule.rule_id: rule.title for rule in RULES}

_MAX_PROBLEM_CHARS = 200


def skill_query_terms(skill_id: str) -> tuple[str, ...]:
    return _SKILL_QUERY_TERMS.get(skill_id, ())


def aliases_for_blob(*parts: str) -> tuple[str, ...]:
    """Skill/concept aliases whose title or code appears in the blob.

    Hung onto ``fts_text`` at ingest so a query like「解方程」can hit a
    chunk that only wrote「一元一次方程」in the source text.
    """
    haystack = " ".join(part for part in parts if part)
    if not haystack:
        return ()
    extra: list[str] = []
    for skill_id, terms in _SKILL_QUERY_TERMS.items():
        if skill_id in haystack or any(term in haystack for term in terms):
            extra.append(skill_id)
            extra.extend(terms)
    for concept_id, terms in _CONCEPT_QUERY_TERMS.items():
        if concept_id in haystack or any(term in haystack for term in terms):
            extra.append(concept_id)
            extra.extend(terms)
    return tuple(_unique(extra))


def build_retrieval_query(
    *,
    skill_ids: Sequence[str] = (),
    concept_ids: Sequence[str] = (),
    problem_text: str = "",
    misconception_ids: Sequence[str] = (),
) -> str:
    """Join Chinese titles, aliases, problem text, and misconception names.

    Skill/concept codes are never emitted: they do not match Chinese notes
    and must not be the sole query. Callers still pass codes as ``node_ids``
    for curriculum filtering.
    """
    terms: list[str] = []
    for skill_id in skill_ids:
        terms.extend(_SKILL_QUERY_TERMS.get(skill_id, ()))
    for concept_id in concept_ids:
        terms.extend(_CONCEPT_QUERY_TERMS.get(concept_id, ()))
    for rule_id in misconception_ids:
        title = _MISCONCEPTION_TITLES.get(rule_id)
        if title:
            terms.append(title)
        elif _looks_like_natural_language(rule_id):
            terms.append(rule_id)
    clipped = (problem_text or "").strip()
    if clipped:
        terms.append(clipped[:_MAX_PROBLEM_CHARS])
    return " ".join(_unique(terms))


def _looks_like_natural_language(value: str) -> bool:
    if not value or value.isascii() and value.replace("_", "").isupper():
        return False
    return any("\u4e00" <= ch <= "\u9fff" for ch in value)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = value.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


__all__ = [
    "aliases_for_blob",
    "build_retrieval_query",
    "skill_query_terms",
]
