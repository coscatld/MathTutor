"""MVP skill taxonomy for the Phase 4 learning loop.

The full curriculum (versioned nodes, mappings, stages) is out of scope for
the MVP: each of the four problem families maps to exactly one stable skill
id and one parent concept id. These ids are *stable strings* — they are what
``mastery_evidence`` replay and the estimator project against, so they must
never be renamed silently (a rename would orphan persisted evidence).
"""

from __future__ import annotations

from mathtutor.domain.problem import MathProblem

# Stable skill ids (one per MVP problem family).
SKILL_ARITHMETIC = "ARITHMETIC"
SKILL_POLYNOMIAL_BASIC = "POLYNOMIAL_BASIC"
SKILL_LINEAR_EQUATION = "LINEAR_EQUATION"
SKILL_QUADRATIC_EQUATION = "QUADRATIC_EQUATION"
SKILL_LINEAR_SYSTEM = "LINEAR_SYSTEM"

_SKILL_BY_PROBLEM_TYPE: dict[str, str] = {
    "arithmetic": SKILL_ARITHMETIC,
    "polynomial": SKILL_POLYNOMIAL_BASIC,
    "linear": SKILL_LINEAR_EQUATION,
    "linear_inequality": SKILL_LINEAR_EQUATION,
    "quadratic": SKILL_QUADRATIC_EQUATION,
    "linear_system": SKILL_LINEAR_SYSTEM,
}

# Stable concept ids (parent concepts; MVP maps 1:1 onto skills).
CONCEPT_NUMBER_OPERATIONS = "CONCEPT_NUMBER_OPERATIONS"
CONCEPT_POLYNOMIALS = "CONCEPT_POLYNOMIALS"
CONCEPT_LINEAR_EQUATIONS = "CONCEPT_LINEAR_EQUATIONS"
CONCEPT_QUADRATIC_EQUATIONS = "CONCEPT_QUADRATIC_EQUATIONS"
CONCEPT_LINEAR_SYSTEMS = "CONCEPT_LINEAR_SYSTEMS"

_SKILL_TO_CONCEPT: dict[str, str] = {
    SKILL_ARITHMETIC: CONCEPT_NUMBER_OPERATIONS,
    SKILL_POLYNOMIAL_BASIC: CONCEPT_POLYNOMIALS,
    SKILL_LINEAR_EQUATION: CONCEPT_LINEAR_EQUATIONS,
    SKILL_QUADRATIC_EQUATION: CONCEPT_QUADRATIC_EQUATIONS,
    SKILL_LINEAR_SYSTEM: CONCEPT_LINEAR_SYSTEMS,
}

# Routing vocabulary belongs to the skill catalog, not to individual exercise
# strings. It only establishes topical relevance; it never proves correctness.
_TOPIC_TERMS: dict[str, tuple[str, ...]] = {
    SKILL_LINEAR_SYSTEM: ("二元一次", "方程组", "消元", "代入", "加减消元", "两个未知数", "代回检验"),
    SKILL_ARITHMETIC: ("四则运算", "分数", "小数", "整数", "通分", "约分", "分母", "分子", "运算顺序", "分配律", "括号"),
    SKILL_POLYNOMIAL_BASIC: ("多项式", "单项式", "同类项", "系数", "次数", "展开", "因式分解", "乘法公式", "分配律"),
    SKILL_LINEAR_EQUATION: ("一元一次", "一次方程", "方程", "等式", "移项", "去分母", "未知数", "系数", "代回", "代入检验"),
    SKILL_QUADRATIC_EQUATION: ("一元二次", "二次方程", "方程", "等式", "配方", "配方法", "判别式", "求根公式", "因式分解", "实根", "重根", "韦达", "根与系数"),
}


def relates_to_skill(text: str, skill_id: str) -> bool:
    """Conservative positive signal for a follow-up within the bound skill.

    A miss is not a topic-change decision: the caller keeps the problem and
    clarifies ambiguous mathematical input instead of silently replacing it.
    """
    return any(term in text for term in _TOPIC_TERMS.get(skill_id, ()))


def skill_for_problem(problem: MathProblem) -> str:
    """Stable skill id for a canonical problem (deterministic mapping)."""
    return skill_for_problem_type(problem.problem_type)


def skill_for_problem_type(problem_type: str) -> str:
    """Skill id for a problem family string; unknown families raise.

    Problems are server-canonicalized, so an unknown family here is a
    programming error, not a student-input case (fail loudly, not silently).
    """
    skill = _SKILL_BY_PROBLEM_TYPE.get(problem_type)
    if skill is None:
        raise ValueError(f"未知题族，无法映射技能: {problem_type!r}")
    return skill


def concept_for_skill(skill_id: str) -> str:
    """Parent concept id for a skill id."""
    concept = _SKILL_TO_CONCEPT.get(skill_id)
    if concept is None:
        raise ValueError(f"未知技能，无法映射概念: {skill_id!r}")
    return concept


def all_skill_ids() -> tuple[str, ...]:
    """Every skill the MVP estimator tracks (deterministic order)."""
    return tuple(_SKILL_TO_CONCEPT)


__all__ = [
    "CONCEPT_LINEAR_EQUATIONS",
    "CONCEPT_NUMBER_OPERATIONS",
    "CONCEPT_POLYNOMIALS",
    "CONCEPT_QUADRATIC_EQUATIONS",
    "CONCEPT_LINEAR_SYSTEMS",
    "SKILL_ARITHMETIC",
    "SKILL_LINEAR_EQUATION",
    "SKILL_POLYNOMIAL_BASIC",
    "SKILL_QUADRATIC_EQUATION",
    "SKILL_LINEAR_SYSTEM",
    "all_skill_ids",
    "concept_for_skill",
    "skill_for_problem",
    "skill_for_problem_type",
]
