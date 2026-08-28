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

_SKILL_BY_PROBLEM_TYPE: dict[str, str] = {
    "arithmetic": SKILL_ARITHMETIC,
    "polynomial": SKILL_POLYNOMIAL_BASIC,
    "linear": SKILL_LINEAR_EQUATION,
    "quadratic": SKILL_QUADRATIC_EQUATION,
}

# Stable concept ids (parent concepts; MVP maps 1:1 onto skills).
CONCEPT_NUMBER_OPERATIONS = "CONCEPT_NUMBER_OPERATIONS"
CONCEPT_POLYNOMIALS = "CONCEPT_POLYNOMIALS"
CONCEPT_LINEAR_EQUATIONS = "CONCEPT_LINEAR_EQUATIONS"
CONCEPT_QUADRATIC_EQUATIONS = "CONCEPT_QUADRATIC_EQUATIONS"

_SKILL_TO_CONCEPT: dict[str, str] = {
    SKILL_ARITHMETIC: CONCEPT_NUMBER_OPERATIONS,
    SKILL_POLYNOMIAL_BASIC: CONCEPT_POLYNOMIALS,
    SKILL_LINEAR_EQUATION: CONCEPT_LINEAR_EQUATIONS,
    SKILL_QUADRATIC_EQUATION: CONCEPT_QUADRATIC_EQUATIONS,
}


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
    "SKILL_ARITHMETIC",
    "SKILL_LINEAR_EQUATION",
    "SKILL_POLYNOMIAL_BASIC",
    "SKILL_QUADRATIC_EQUATION",
    "all_skill_ids",
    "concept_for_skill",
    "skill_for_problem",
    "skill_for_problem_type",
]
