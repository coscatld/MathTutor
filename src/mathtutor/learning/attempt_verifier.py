"""Attempt verification (Phase 4 learning loop, step 2).

Compares one parsed :class:`StudentAttempt` against the *verified*
reference solution of the cycle's canonical problem and emits a structured
:class:`AttemptAssessment` — never a bare boolean and never an LLM opinion.

Correctness policy (``Correctness``, values stored lowercase to match the
existing ``attempt_assessments.correctness`` column):

- ``CORRECT``      — the complete, mathematically exact answer. Equivalence
  is accepted: ``x=2`` / ``2=x`` / ``x=4/2`` / ``2.0`` are all correct for
  ``2x+3=7`` (exact rational comparison, canonical root-set comparison).
- ``PARTIAL``      — a valid intermediate step. Example: answering ``2x=4``
  to ``2x+3=7`` (an equivalent equation that is not solved for the
  variable). Policy for quadratics: **giving only one of several roots is
  PARTIAL** (missing-root signal); an equivalent equation restatement is
  PARTIAL.
- ``INCORRECT``    — a definite error: substitution fails / root set
  mismatches / value differs. Policy: **a wrong root is INCORRECT** (even
  when other roots are right — extraneous-root signal), and any claimed
  root that does not substitute back to zero is INCORRECT.
- ``UNDETERMINED`` — the answer cannot be reliably parsed or judged. The
  assessment still records the reason; the EvidenceFactory hard-refuses to
  turn it into evidence.

Signal table (``assessment.signals``) — structural facts the diagnosis
rules consume:

=====================  ====================================================
signal                 meaning
=====================  ====================================================
``equivalent_equation`` PARTIAL: equivalent equation, not solved for x
``missing_root``        PARTIAL: some (not all) expected roots given
``extraneous_root``     INCORRECT: >=1 claimed root fails substitution
``sign_flip``           INCORRECT: answer is the negation of the truth
``wrong_operation``     INCORRECT: same x-coefficient, wrong constant
                       (classic transposition slip, e.g. ``2x=10`` for
                       ``2x+3=7``)
``wrong_family``        INCORRECT: wrong family/variable/answer shape
``wrong_value``         INCORRECT: substitution fails, no clearer signal
=====================  ====================================================
"""

from __future__ import annotations

from enum import Enum
from fractions import Fraction
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.domain.attempt import StudentAttempt
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.learning.attempt_parser import ParsedAttempt, interpret_attempt
from mathtutor.solving import nodes as n
from mathtutor.solving.strategies import _common as c
from mathtutor.solving.strategies import quadratic as q

ATTEMPT_VERIFIER_POLICY_VERSION = "mt-attempt-verifier-v1"

# PARTIAL score for an equivalent-equation restatement (no final value/root
# set given yet, but the step itself is mathematically valid).
EQUIVALENT_EQUATION_SCORE = 0.5


class Correctness(str, Enum):
    """Assessment verdict; str values match the persisted correctness column."""

    CORRECT = "correct"
    PARTIAL = "partial"
    INCORRECT = "incorrect"
    UNDETERMINED = "undetermined"


class AttemptAssessment(BaseModel):
    """Structured, append-only assessment of one attempt (frozen record).

    ``verified_claims`` / ``invalid_claims`` / ``remaining_requirements`` are
    JSON-safe claim dicts; ``signals`` is the structural signal tuple the
    rule-first diagnosis consumes.
    """

    model_config = ConfigDict(frozen=True)

    attempt_id: UUID
    student_id: UUID
    problem_id: UUID
    reference_solution_payload_hash: str
    correctness: Correctness
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    verified_claims: tuple[dict[str, Any], ...] = ()
    invalid_claims: tuple[dict[str, Any], ...] = ()
    remaining_requirements: tuple[dict[str, Any], ...] = ()
    signals: tuple[str, ...] = ()
    policy_version: str = ATTEMPT_VERIFIER_POLICY_VERSION
    reason: str = ""


# ---------------------------------------------------------------------------
# Reference helpers (exact, canonical — reused across families)
# ---------------------------------------------------------------------------


def _problem_variable(problem_ast: n.Node) -> str | None:
    variables = n.variables(problem_ast)
    return sorted(variables)[0] if len(variables) == 1 else None


def _root_as_fraction(root: dict[str, Any]) -> Fraction | None:
    if root.get("kind") != "rational":
        return None
    return c.frac_from_dict(root["value"])


def _roots_as_fractions(roots: tuple[dict[str, Any], ...]) -> tuple[Fraction, ...]:
    values = [_root_as_fraction(root) for root in roots]
    return tuple(v for v in values if v is not None)


def _negate_root(root: dict[str, Any]) -> dict[str, Any]:
    if root["kind"] == "rational":
        value = c.frac_from_dict(root["value"])
        return c.rational_root(-value)
    num = c.frac_from_dict(root["num"])
    coeff = c.frac_from_dict(root["coeff"])
    return c.surd_root(-num, -coeff, root["radicand"])


def _expected_roots(
    problem_ast: n.Node, problem_type: str, variable: str
) -> tuple[dict[str, Any], ...]:
    """Independent recomputation of the expected root set (exact)."""
    diff = n.equation_difference(problem_ast, variable)
    assert diff is not None and diff, "problem is not a solvable equation"
    if problem_type == "linear":
        a, b = diff.get(1, Fraction(0)), diff.get(0, Fraction(0))
        return (c.rational_root(Fraction(-b, a)),)
    a = diff.get(2, Fraction(0))
    b = diff.get(1, Fraction(0))
    cc = diff.get(0, Fraction(0))
    return q.quad_roots(a, b, cc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def verify_attempt(
    student_attempt: StudentAttempt,
    problem: MathProblem,
    verified_candidate: MathSolutionCandidate,
) -> AttemptAssessment:
    """Assess one attempt against the cycle's VERIFIED reference solution.

    Pure and deterministic: same inputs -> identical assessment. The caller
    is responsible for only ever passing a *verified* candidate (the
    attestation lives in the repository layer); a candidate bound to a
    different problem is treated as an internal inconsistency and fails
    closed into UNDETERMINED.
    """
    base: dict[str, Any] = dict(
        attempt_id=student_attempt.attempt_id,
        student_id=student_attempt.student_id,
        problem_id=problem.problem_id,
        reference_solution_payload_hash=verified_candidate.payload_hash,
    )
    if verified_candidate.problem_id != problem.problem_id:
        return AttemptAssessment(
            correctness=Correctness.UNDETERMINED,
            reason="参考解与题目不匹配（problem_id 不一致）",
            **base,
        )

    parsed_answer = interpret_attempt(student_attempt)
    if parsed_answer.kind == "undeterminable":
        return AttemptAssessment(
            correctness=Correctness.UNDETERMINED,
            reason=parsed_answer.reason or "作答无法可靠解析",
            **base,
        )
    if parsed_answer.kind == "linear_system" and problem.problem_type != "linear_system":
        return AttemptAssessment(correctness=Correctness.INCORRECT, signals=("wrong_family",),
                                 reason="当前题目不需要一组未知数的答案", **base)

    try:
        problem_ast = n.from_dict(problem.normalized_ast)
    except (KeyError, ValueError, TypeError) as exc:
        return AttemptAssessment(
            correctness=Correctness.UNDETERMINED,
            reason=f"题目规范化 AST 不可回放: {exc}",
            **base,
        )

    if problem.problem_type == "arithmetic":
        return _verify_arithmetic(problem_ast, parsed_answer, base)
    if problem.problem_type == "polynomial":
        return _verify_polynomial(problem_ast, parsed_answer, base)
    if problem.problem_type == "linear":
        return _verify_linear(problem_ast, parsed_answer, base)
    if problem.problem_type == "quadratic":
        return _verify_quadratic(problem_ast, parsed_answer, base)
    if problem.problem_type == "linear_system":
        from mathtutor.learning.linear_system_attempt import verify_system_attempt
        return verify_system_attempt(problem_ast, parsed_answer, base)
    return AttemptAssessment(
        correctness=Correctness.UNDETERMINED,
        reason=f"未知题族: {problem.problem_type}",
        **base,
    )


# ---------------------------------------------------------------------------
# Family checks
# ---------------------------------------------------------------------------


def _verify_arithmetic(problem_ast: n.Node, answer: ParsedAttempt, base: dict[str, Any]) -> AttemptAssessment:
    if answer.kind == "empty_root_set":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            invalid_claims=({"claim": "empty_root_set", "reason": "算术题的回答是数值，不是根集"},),
            signals=("wrong_family",),
            **base,
        )
    if answer.kind == "equation":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            invalid_claims=({"claim": "equation_answer", "reason": "算术题的回答应为数值"},),
            signals=("wrong_family",),
            **base,
        )
    parsed = answer.parsed
    assert parsed is not None
    if parsed.problem_type != "arithmetic":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            invalid_claims=({"claim": "value_answer", "reason": "作答不是算术表达式"},),
            signals=("wrong_family",),
            **base,
        )
    try:
        expected = n.evaluate(problem_ast)
        actual = n.evaluate(parsed.ast)
    except n.MathDomainError as exc:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason=f"无法求值: {exc}", **base)
    if actual == expected:
        return AttemptAssessment(
            correctness=Correctness.CORRECT,
            score=1.0,
            verified_claims=({"claim": "final_value", "value": actual.to_dict()},),
            **base,
        )
    signals = ("sign_flip",) if actual == -expected else ("wrong_value",)
    return AttemptAssessment(
        correctness=Correctness.INCORRECT,
        score=0.0,
        invalid_claims=(
            {"claim": "final_value", "actual": actual.to_dict(), "expected": expected.to_dict()},
        ),
        signals=signals,
        **base,
    )


def _verify_polynomial(problem_ast: n.Node, answer: ParsedAttempt, base: dict[str, Any]) -> AttemptAssessment:
    if answer.kind == "empty_root_set":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            invalid_claims=({"claim": "empty_root_set", "reason": "多项式化简题的回答是表达式，不是根集"},),
            signals=("wrong_family",),
            **base,
        )
    if answer.kind == "equation":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            invalid_claims=({"claim": "equation_answer", "reason": "多项式化简题的回答应为表达式"},),
            signals=("wrong_family",),
            **base,
        )
    parsed = answer.parsed
    assert parsed is not None
    variable = _problem_variable(problem_ast)
    if parsed.problem_type != "polynomial":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            invalid_claims=({"claim": "value_answer", "reason": "作答不是多项式"},),
            signals=("wrong_family",),
            **base,
        )
    if variable is None or parsed.variable != variable:
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            invalid_claims=({"claim": "polynomial_answer", "reason": "变量不一致"},),
            signals=("wrong_family",),
            **base,
        )
    expected = n.poly_coeffs(problem_ast, variable)
    actual = n.poly_coeffs(parsed.ast, variable)
    if expected is None or actual is None:
        return AttemptAssessment(
            correctness=Correctness.UNDETERMINED,
            reason="系数展开失败，无法判定",
            **base,
        )
    if actual == expected:
        return AttemptAssessment(
            correctness=Correctness.CORRECT,
            score=1.0,
            verified_claims=({"claim": "canonical_form", "coeffs": c.coeffs_to_dict(actual)},),
            **base,
        )
    return AttemptAssessment(
        correctness=Correctness.INCORRECT,
        score=0.0,
        invalid_claims=(
            {
                "claim": "canonical_form",
                "actual": c.coeffs_to_dict(actual),
                "expected": c.coeffs_to_dict(expected),
            },
        ),
        signals=("wrong_value",),
        **base,
    )


def _verify_linear(problem_ast: n.Node, answer: ParsedAttempt, base: dict[str, Any]) -> AttemptAssessment:
    variable = _problem_variable(problem_ast)
    if variable is None:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="题目变量缺失", **base)
    diff = n.equation_difference(problem_ast, variable)
    assert diff is not None
    expected = Fraction(-diff.get(0, Fraction(0)), diff.get(1, Fraction(1)))

    if answer.kind == "empty_root_set":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=({"claim": "empty_root_set", "reason": "一元一次方程必有实数根"},),
            signals=("wrong_value",),
            **base,
        )
    if answer.kind == "value":
        parsed = answer.parsed
        assert parsed is not None
        if parsed.problem_type != "arithmetic":
            return AttemptAssessment(
                correctness=Correctness.INCORRECT,
                score=0.0,
                invalid_claims=({"claim": "value_answer", "reason": "作答不是数值"},),
                signals=("wrong_family",),
                **base,
            )
        try:
            actual = n.evaluate(parsed.ast)
        except n.MathDomainError as exc:
            return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason=f"无法求值: {exc}", **base)
        actual_fraction = actual.to_fraction()
        if actual_fraction == expected:
            return AttemptAssessment(
                correctness=Correctness.CORRECT,
                score=1.0,
                verified_claims=({"claim": "root_value", "value": actual.to_dict()},),
                **base,
            )
        signals = ("sign_flip",) if actual_fraction == -expected else ("wrong_value",)
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=(
                {
                    "claim": "root_value",
                    "actual": actual.to_dict(),
                    "expected": c.frac_to_dict(expected),
                },
            ),
            signals=signals,
            **base,
        )

    # Equation answer.
    parsed = answer.parsed
    assert parsed is not None
    if parsed.problem_type != "linear":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=({"claim": "equation_answer", "reason": "作答不是一元一次方程"},),
            signals=("wrong_family",),
            **base,
        )
    if parsed.variable != variable:
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=({"claim": "equation_answer", "reason": "变量不一致"},),
            signals=("wrong_family",),
            **base,
        )
    answer_diff = n.equation_difference(parsed.ast, variable)
    if answer_diff is None or answer_diff.get(1, Fraction(0)) == 0:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="作答方程无法提取一次项系数", **base)
    actual = Fraction(-answer_diff.get(0, Fraction(0)), answer_diff.get(1, Fraction(1)))
    if actual == expected:
        # Equivalent equation; solved-for-x only when |leading coefficient| == 1
        # (x=2, 2=x, x=4/2 all normalize to that; 2x=4 does not).
        if abs(answer_diff[1]) == 1:
            return AttemptAssessment(
                correctness=Correctness.CORRECT,
                score=1.0,
                verified_claims=(
                    {
                        "claim": "root_value",
                        "value": c.frac_to_dict(expected),
                        "variable": variable,
                    },
                ),
                **base,
            )
        return AttemptAssessment(
            correctness=Correctness.PARTIAL,
            score=EQUIVALENT_EQUATION_SCORE,
            verified_claims=(
                {"claim": "equivalent_equation", "root": c.frac_to_dict(expected)},
            ),
            remaining_requirements=(
                {"requirement": "solve_for_variable", "variable": variable, "expected": c.frac_to_dict(expected)},
            ),
            signals=("equivalent_equation",),
            **base,
        )
    # Different root set: a definite error.
    signals: tuple[str, ...]
    if answer_diff[1] == diff[1]:
        signals = ("wrong_operation",)  # same x-coefficient: transposition slip
    elif actual == -expected:
        signals = ("sign_flip",)
    else:
        signals = ("wrong_value",)
    return AttemptAssessment(
        correctness=Correctness.INCORRECT,
        score=0.0,
        invalid_claims=(
            {"claim": "root_value", "actual": c.frac_to_dict(actual), "expected": c.frac_to_dict(expected)},
        ),
        signals=signals,
        **base,
    )


def _verify_quadratic(problem_ast: n.Node, answer: ParsedAttempt, base: dict[str, Any]) -> AttemptAssessment:
    variable = _problem_variable(problem_ast)
    if variable is None:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="题目变量缺失", **base)
    expected = _expected_roots(problem_ast, "quadratic", variable)
    expected_values = _roots_as_fractions(expected)

    if answer.kind == "empty_root_set":
        if not expected:
            return AttemptAssessment(
                correctness=Correctness.CORRECT,
                score=1.0,
                verified_claims=({"claim": "no_real_roots"},),
                **base,
            )
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=({"claim": "empty_root_set", "reason": "方程存在实数根"},),
            signals=("wrong_value",),
            **base,
        )

    if answer.kind == "value":
        parsed = answer.parsed
        assert parsed is not None
        if parsed.problem_type != "arithmetic":
            return AttemptAssessment(
                correctness=Correctness.INCORRECT,
                score=0.0,
                invalid_claims=({"claim": "value_answer", "reason": "作答不是数值"},),
                signals=("wrong_family",),
                **base,
            )
        try:
            claimed = (n.evaluate(parsed.ast).to_fraction(),)
        except n.MathDomainError as exc:
            return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason=f"无法求值: {exc}", **base)
        return _judge_claimed_root_values(claimed, expected_values, base)

    # Equation answer.
    parsed = answer.parsed
    assert parsed is not None
    if parsed.problem_type == "linear":
        if parsed.variable != variable:
            return AttemptAssessment(
                correctness=Correctness.INCORRECT,
                score=0.0,
                invalid_claims=({"claim": "equation_answer", "reason": "变量不一致"},),
                signals=("wrong_family",),
                **base,
            )
        answer_diff = n.equation_difference(parsed.ast, variable)
        if answer_diff is None or answer_diff.get(1, Fraction(0)) == 0:
            return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="作答方程无法提取根", **base)
        claimed_root = Fraction(-answer_diff.get(0, Fraction(0)), answer_diff.get(1, Fraction(1)))
        return _judge_claimed_root_values((claimed_root,), expected_values, base)
    if parsed.problem_type != "quadratic":
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=({"claim": "equation_answer", "reason": "作答不是一元二次方程"},),
            signals=("wrong_family",),
            **base,
        )
    if parsed.variable != variable:
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=({"claim": "equation_answer", "reason": "变量不一致"},),
            signals=("wrong_family",),
            **base,
        )
    answer_diff = n.equation_difference(parsed.ast, variable)
    if answer_diff is None or answer_diff.get(2, Fraction(0)) == 0:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="作答方程无法提取二次项系数", **base)
    claimed_roots = q.quad_roots(
        answer_diff.get(2, Fraction(0)),
        answer_diff.get(1, Fraction(0)),
        answer_diff.get(0, Fraction(0)),
    )
    valid = [root for root in claimed_roots if root in expected]
    invalid = [root for root in claimed_roots if root not in expected]
    if invalid:
        # Policy: any wrong root (one that does not substitute back) is
        # INCORRECT — even alongside correct ones (extraneous root).
        if valid:
            signals = ("extraneous_root",)
        elif tuple(_negate_root(root) for root in claimed_roots) == expected:
            signals = ("sign_flip",)
        else:
            signals = ("wrong_value",)
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=(
                {"claim": "root_set", "invalid_roots": list(invalid)},
            ),
            signals=signals,
            **base,
        )
    if len(claimed_roots) == len(expected):
        # Identical root set via an equivalent equation (never the root-list
        # final form) -> valid step, still missing the explicit answer.
        return AttemptAssessment(
            correctness=Correctness.PARTIAL,
            score=EQUIVALENT_EQUATION_SCORE,
            verified_claims=({"claim": "equivalent_equation", "roots": list(claimed_roots)},),
            remaining_requirements=({"requirement": "state_roots", "expected_roots": list(expected)},),
            signals=("equivalent_equation",),
            **base,
        )
    # Proper subset: missing-root policy -> PARTIAL with proportional score.
    return AttemptAssessment(
        correctness=Correctness.PARTIAL,
        score=Fraction(len(claimed_roots), len(expected)) if expected else 0.0,
        verified_claims=({"claim": "root_subset", "roots": list(claimed_roots)},),
        remaining_requirements=(
            {"requirement": "give_all_roots", "missing_roots": list(r for r in expected if r not in claimed_roots)},
        ),
        signals=("missing_root",),
        **base,
    )


def _judge_claimed_root_values(
    claimed: tuple[Fraction, ...],
    expected_values: tuple[Fraction, ...],
    base: dict[str, Any],
) -> AttemptAssessment:
    """Shared value-based judgment for claimed roots (plain value or x=v)."""
    valid = [value for value in claimed if value in expected_values]
    invalid = [value for value in claimed if value not in expected_values]
    if invalid:
        if tuple(-value for value in claimed) == expected_values:
            signals = ("sign_flip",)
        elif valid:
            signals = ("extraneous_root",)
        else:
            signals = ("wrong_value",)
        return AttemptAssessment(
            correctness=Correctness.INCORRECT,
            score=0.0,
            invalid_claims=(
                {"claim": "root_value", "invalid": [c.frac_to_dict(v) for v in invalid]},
            ),
            signals=signals,
            **base,
        )
    if len(expected_values) == 1:
        # Double root: the single value is the complete answer.
        return AttemptAssessment(
            correctness=Correctness.CORRECT,
            score=1.0,
            verified_claims=({"claim": "root_value", "value": c.frac_to_dict(claimed[0])},),
            **base,
        )
    # One correct root out of several: PARTIAL (missing-root policy).
    return AttemptAssessment(
        correctness=Correctness.PARTIAL,
        score=Fraction(len(claimed), len(expected_values)),
        verified_claims=({"claim": "root_subset", "roots": [c.frac_to_dict(v) for v in claimed]},),
        remaining_requirements=(
            {
                "requirement": "give_all_roots",
                "missing_roots": [c.frac_to_dict(v) for v in expected_values if v not in claimed],
            },
        ),
        signals=("missing_root",),
        **base,
    )


__all__ = [
    "ATTEMPT_VERIFIER_POLICY_VERSION",
    "EQUIVALENT_EQUATION_SCORE",
    "AttemptAssessment",
    "Correctness",
    "verify_attempt",
]
