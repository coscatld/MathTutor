"""Rule-first misconception diagnosis (Phase 4 learning loop, step 3).

The verifier's structural signals are mapped through a fixed, ordered rule
table into a :class:`MisconceptionObservation` candidate — one piece of
evidence about this attempt, NEVER a permanent label on the student. The
projection layer decides (by reduction over many attempts) whether a
misconception becomes active; a single observation never does.

No LLM participates: every rule is a deterministic signal→rule lookup with
a fixed confidence constant.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.attempt import StudentAttempt
from mathtutor.domain.problem import MathProblem
from mathtutor.learning.attempt_verifier import AttemptAssessment, Correctness
from mathtutor.learning.skills import skill_for_problem

# Namespace for deterministic observation ids (uuid5, stable across replays).
_OBSERVATION_NAMESPACE = UUID("6f2c1e4d-9a3b-4c5e-8d7f-0b1a2c3d4e5f")


@dataclass(frozen=True, slots=True)
class RuleSpec:
    """One diagnosis rule: signal(s) → rule id + fixed confidence."""

    rule_id: str
    signals: tuple[str, ...]
    confidence: float
    title: str


# Ordered rule table: first match wins (deterministic priority).
RULES: tuple[RuleSpec, ...] = (
    RuleSpec("miscon-sign-error", ("sign_flip",), 0.8, "符号错误"),
    RuleSpec("miscon-missing-root", ("missing_root",), 0.75, "漏根：忽略了方程的其他解"),
    RuleSpec("miscon-extraneous-root", ("extraneous_root",), 0.75, "增根：混入了不满足方程的解"),
    RuleSpec("miscon-transposition-error", ("wrong_operation",), 0.7, "移项/常数处理错误"),
    RuleSpec("miscon-computation-error", ("wrong_value",), 0.6, "计算错误"),
    RuleSpec("miscon-wrong-family", ("wrong_family",), 0.5, "题族/变量混淆"),
)

_RULES_BY_SIGNAL: dict[str, RuleSpec] = {
    signal: rule for rule in RULES for signal in rule.signals
}


class MisconceptionObservation(BaseModel):
    """One append-only observation fact about one attempt (never a label)."""

    model_config = ConfigDict(frozen=True)

    observation_id: UUID
    student_id: UUID
    attempt_id: UUID
    rule_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    detail: dict[str, Any] = {}
    created_at: str = ""


def diagnose(
    *,
    assessment: AttemptAssessment,
    problem: MathProblem,
    attempt: StudentAttempt,
) -> MisconceptionObservation | None:
    """Map an assessment's signals onto at most one rule observation.

    CORRECT / UNDETERMINED assessments never produce observations, and a
    PARTIAL equivalent step (``equivalent_equation``) is a valid move — not
    a misconception — so it also maps to None.
    """
    if assessment.correctness not in (Correctness.PARTIAL, Correctness.INCORRECT):
        return None
    for signal in assessment.signals:
        rule = _RULES_BY_SIGNAL.get(signal)
        if rule is None:
            continue
        observation_id = uuid5(
            _OBSERVATION_NAMESPACE,
            f"observation:{attempt.attempt_id}:{rule.rule_id}",
        )
        detail: dict[str, Any] = {
            "signal": signal,
            "rule_title": rule.title,
            "skill_id": skill_for_problem(problem),
            "problem_id": str(problem.problem_id),
            "problem_type": problem.problem_type,
            "correctness": assessment.correctness.value,
            "score": assessment.score,
            "attempt_index": attempt.attempt_index,
            "assessment_policy_version": assessment.policy_version,
        }
        return MisconceptionObservation(
            observation_id=observation_id,
            student_id=attempt.student_id,
            attempt_id=attempt.attempt_id,
            rule_id=rule.rule_id,
            confidence=rule.confidence,
            detail=detail,
        )
    return None


__all__ = ["RULES", "MisconceptionObservation", "RuleSpec", "diagnose"]
