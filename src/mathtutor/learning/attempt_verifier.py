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
from mathtutor.learning.attempt_parser import MAX_WORKING_LINES, ParsedAttempt, interpret_attempt, interpret_step
from mathtutor.solving import nodes as n
from mathtutor.solving.strategies import _common as c
from mathtutor.solving.strategies import quadratic as q

ATTEMPT_VERIFIER_POLICY_VERSION = "mt-attempt-verifier-v2"
WORKING_POLICY_VERSION = "mt-equation-working-v1"

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

    try:
        if len(student_attempt.parsed_steps) > 1:
            return _verify_working(student_attempt.parsed_steps, problem, base)
        return _assess_answer(problem, interpret_attempt(student_attempt), base)
    except n.MathComplexityError:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="这次作答超出精确计算预算，请拆成较小的步骤。", **base)


def _assess_answer(problem: MathProblem, parsed_answer: ParsedAttempt, base: dict[str, Any]) -> AttemptAssessment:
    if parsed_answer.kind == "undeterminable":
        return AttemptAssessment(
            correctness=Correctness.UNDETERMINED,
            reason=parsed_answer.reason or "作答无法可靠解析",
            **base,
        )
    if parsed_answer.kind == "linear_system" and problem.problem_type != "linear_system":
        return AttemptAssessment(correctness=Correctness.INCORRECT, signals=("wrong_family",),
                                 reason="当前题目不需要一组未知数的答案", **base)
    if problem.problem_type == "linear_inequality":
        return _verify_linear_inequality(problem, parsed_answer, base)
    if problem.problem_type == "quadratic_inequality":
        return _verify_quadratic_inequality(problem, parsed_answer, base)
    if parsed_answer.kind in {"inequality", "inequality_relation", "inequality_set"}:
        return AttemptAssessment(correctness=Correctness.INCORRECT, signals=("wrong_family",),
                                 reason="这道题要的不是取值范围。", **base)

    try:
        problem_ast = n.from_dict(problem.normalized_ast)
    except (KeyError, ValueError, TypeError) as exc:
        return AttemptAssessment(
            correctness=Correctness.UNDETERMINED,
            reason=f"题目规范化 AST 不可回放: {exc}",
            **base,
        )

    if parsed_answer.kind == "root_values":
        base = {**base, "policy_version": "mt-attempt-root-set-v2"}
        if problem.problem_type not in {"linear", "quadratic"}:
            return AttemptAssessment(correctness=Correctness.INCORRECT, signals=("wrong_family",), **base)
        variable = _problem_variable(problem_ast)
        if parsed_answer.answer_variable and parsed_answer.answer_variable != variable:
            return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_family",),
                                     reason="这一行使用的未知数与原题不同。", **base)
        expected = _roots_as_fractions(_expected_roots(problem_ast, problem.problem_type, variable))
        claimed = tuple(sorted(set(parsed_answer.root_values)))
        if set(claimed) == set(expected):
            return AttemptAssessment(correctness=Correctness.CORRECT, score=1.0,
                verified_claims=({"claim": "complete_root_set", "roots": [c.frac_to_dict(r) for r in claimed]},), **base)
        return _judge_claimed_root_values(claimed, expected, base)
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


def _verify_linear_inequality(problem: MathProblem, answer: ParsedAttempt, base: dict[str, Any]) -> AttemptAssessment:
    """A boundary equation is not a solution. The range is recomputed from the stored equation."""
    from mathtutor.solving.strategies.inequality import solved_form
    if answer.kind not in {"inequality", "inequality_relation", "inequality_set"}:
        return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_family",),
                                 reason="不等式的答案要保留不等号，不能只写边界方程。", **base)
    try:
        payload = problem.normalized_ast
        equation = n.from_dict(payload["equation"])
        kept, boundary = solved_form(equation, payload["variable"], payload["relation"])
        variable, actual_relation, actual_boundary = answer.answer_variable, answer.relation, answer.boundary
        isolated = True
        if answer.kind == "inequality_set":
            from mathtutor.solving.quadratic_inequality import parse_answer
            symbol = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}[kept]
            expected = parse_answer(f"{payload['variable']}{symbol}{boundary}", payload["variable"])
            claimed = parse_answer(answer.set_text, payload["variable"])
            if claimed is None:
                return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="请核对区间两端、括号与并集写法。", **base)
            if claimed != expected:
                return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_value",),
                                         reason="这个区间与原题的解集不同，请核对方向及端点是否包含。", **base)
            return AttemptAssessment(correctness=Correctness.CORRECT, score=1,
                                     verified_claims=({"claim": "inequality_solution", "relation": kept},), **base)
        if answer.kind == "inequality_relation":
            parsed = answer.parsed
            if parsed.problem_type != "linear_inequality":
                return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="这一行超出一次不等式的核验范围。", **base)
            variable = parsed.variable
            actual_relation, actual_boundary = solved_form(parsed.ast, variable, parsed.relation)
            isolated = answer.isolated_variable
    except (KeyError, TypeError, ValueError, n.MathDomainError, n.MathComplexityError) as exc:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason=f"不等式不能回放: {exc}", **base)
    if variable.lower() != str(payload["variable"]).lower():
        return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_family",), reason="未知数和原题不一致。", **base)
    if actual_boundary == boundary and actual_relation == kept:
        if isolated:
            return AttemptAssessment(correctness=Correctness.CORRECT, score=1,
                verified_claims=({"claim": "inequality_solution", "relation": kept},), **base)
        return AttemptAssessment(correctness=Correctness.PARTIAL, score=EQUIVALENT_EQUATION_SCORE,
            verified_claims=({"claim": "equivalent_inequality", "relation": actual_relation},),
            remaining_requirements=({"requirement": "state_interval"},), signals=("equivalent_inequality",), **base)
    if actual_boundary == boundary:
        return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_value",),
            reason="边界数值相同，请核对不等号方向以及边界点是否包含。", **base)
    return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_value",),
                             reason="这个范围的边界没有通过原题检验。", **base)


def _verify_quadratic_inequality(problem: MathProblem, answer: ParsedAttempt, base: dict[str, Any]) -> AttemptAssessment:
    """Compare the student's solution set with the exact one."""
    from mathtutor.solving import quadratic_inequality as qi
    variable = str(problem.normalized_ast.get("variable", "x"))
    symbols = {"gt": ">", "ge": ">=", "lt": "<", "le": "<="}
    if answer.kind == "inequality_relation":
        parsed = answer.parsed
        if parsed.problem_type != "quadratic_inequality" or parsed.variable != variable:
            return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="请写出完整区间，以便核对这个不等式。", **base)
        original = n.from_dict(problem.normalized_ast["equation"])
        expected = qi.solution_set(*qi.coefficients(original, variable), problem.normalized_ast["relation"])
        actual = qi.solution_set(*qi.coefficients(parsed.ast, variable), parsed.relation)
        if actual != expected:
            return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_value",),
                                     reason="这一步改变了解集，请核对因式的符号、不等号和边界点。", **base)
        return AttemptAssessment(correctness=Correctness.PARTIAL, score=EQUIVALENT_EQUATION_SCORE,
            verified_claims=({"claim": "equivalent_inequality", "relation": parsed.relation},),
            remaining_requirements=({"requirement": "state_interval"},), signals=("equivalent_inequality",), **base)
    if answer.kind == "inequality_set":
        text = answer.set_text
    elif answer.kind == "inequality" and answer.boundary is not None:
        text = f"{answer.answer_variable}{symbols[answer.relation]}{answer.boundary}"
    elif answer.kind == "empty_root_set":
        text = "无解"
    elif answer.kind == "root_values" and len(answer.root_values) == 1:
        text = f"{variable}={answer.root_values[0]}"
    elif answer.kind == "equation" and answer.parsed is not None and isinstance(answer.parsed.ast, n.Equation):
        text = answer.parsed.display_latex.replace(" ", "")
    else:
        text = ""
    try:
        verdict = qi.assess(problem, text) if text else None
    except (KeyError, TypeError, ValueError, ZeroDivisionError, n.MathDomainError) as exc:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason=f"不等式不能回放: {exc}", **base)
    if verdict is None and answer.kind == "inequality_set":
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="请核对区间两端、括号与并集写法。", **base)
    if verdict is None:
        return AttemptAssessment(correctness=Correctness.INCORRECT, signals=("wrong_family",),
                                 reason="请写出解集，例如 x<2 或 x>3、2<x<3。", **base)
    correctness, signals, reason = verdict
    if correctness == "correct":
        return AttemptAssessment(correctness=Correctness.CORRECT, score=1.0,
                                 verified_claims=({"claim": "inequality_solution_set"},), **base)
    return AttemptAssessment(correctness=Correctness.INCORRECT, signals=signals, reason=reason, **base)


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

    return _assess_equation(problem_ast, "linear", answer, base)


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

    return _assess_equation(problem_ast, "quadratic", answer, base)


def _assess_equation(previous: n.Equation, family: str, answer: ParsedAttempt, base: dict[str, Any],
                     *, allow_root_subset: bool = True) -> AttemptAssessment:
    """Check the two equations' real solution sets before deciding final form."""
    parsed = answer.parsed
    variable = _problem_variable(previous)
    if (parsed is None or not isinstance(parsed.ast, n.Equation)
            or parsed.problem_type not in {"linear", "quadratic"} or parsed.variable != variable):
        return AttemptAssessment(correctness=Correctness.INCORRECT, score=0, signals=("wrong_family",),
                                 invalid_claims=({"claim": "equation_answer"},), reason="请保持原题的未知数和等式。", **base)
    expected = _expected_roots(previous, family, variable)
    actual = _expected_roots(parsed.ast, parsed.problem_type, variable)
    # Older serialized attempts may predate the source-form flag.
    isolated = answer.isolated_variable
    if isolated is None:
        isolated = any(isinstance(side, n.Var) and not n.variables(other)
                       for side, other in ((parsed.ast.lhs, parsed.ast.rhs), (parsed.ast.rhs, parsed.ast.lhs)))
    if actual == expected:
        if isolated and len(actual) == 1:
            return AttemptAssessment(correctness=Correctness.CORRECT, score=1,
                verified_claims=({"claim": "root_value", "value": actual[0]["value"], "variable": variable},), **base)
        if family == "linear":
            roots = {"root": expected[0]["value"]}
            requirement = {"requirement": "solve_for_variable", "variable": variable, "expected": expected[0]["value"]}
        else:
            roots = {"roots": list(expected)}
            requirement = {"requirement": "state_roots", "expected_roots": list(expected)}
        return AttemptAssessment(correctness=Correctness.PARTIAL, score=EQUIVALENT_EQUATION_SCORE,
            verified_claims=({"claim": "equivalent_equation", "equation": n.to_dict(parsed.ast), **roots},),
            remaining_requirements=(requirement,), signals=("equivalent_equation",), **base)
    extra = [root for root in actual if root not in expected]
    missing = [root for root in expected if root not in actual]
    if not extra:
        if allow_root_subset and isolated:
            return _judge_claimed_root_values(_roots_as_fractions(actual), _roots_as_fractions(expected), base)
        signal, reason = "missing_root", "这一行丢失了上一式的解。请检查除去的因式是否可能为零，或是否遗漏了另一支解。"
    elif not missing or any(root in expected for root in actual):
        signal, reason = "extraneous_root", "这一行引入了额外的解。请把候选解代回上一式，检查平方或乘因式的条件。"
    else:
        before = n.equation_difference(previous, variable)
        after = n.equation_difference(parsed.ast, variable)
        if family == parsed.problem_type == "linear" and before[1] == after[1]:
            signal, reason = "wrong_operation", "把两式各自整理到一侧，一次项系数相同，常数项却发生了变化。请复核移项的符号。"
        elif len(actual) == len(expected) == 1 and _negate_root(actual[0]) == expected[0]:
            signal, reason = "sign_flip", "这一步所得数值的符号相反。请复核两边乘除时的正负号。"
        elif family == parsed.problem_type == "linear" and before.get(0, 0) == after.get(0, 0) != 0:
            signal, reason = "like_terms", "把两式各自整理到一侧，常数项相同，一次项系数却发生了变化。请复核含未知数各项的系数。"
        else:
            signal, reason = "wrong_value", "两式的解集不同。请逐项复核括号、符号及等式两边所做的运算。"
    return AttemptAssessment(correctness=Correctness.INCORRECT, score=0,
        invalid_claims=({"claim": "equation_relation", "invalid_roots": extra},),
        signals=(signal,), reason=reason, **base)


def _verify_working(steps: tuple[dict[str, Any], ...], problem: MathProblem,
                    base: dict[str, Any]) -> AttemptAssessment:
    """Check successive equations, keeping the verified prefix and first broken link."""
    base = {**base, "policy_version": WORKING_POLICY_VERSION}
    if len(steps) > MAX_WORKING_LINES:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="推导行数超过核验预算，请分段提交。", **base)
    if problem.problem_type == "linear_system" and len(steps) == 2:
        # A system answer can be a pair of simultaneous equations on separate lines.
        rows = [interpret_step(step) for step in steps]
        if all(row.kind == "equation" and row.parsed and isinstance(row.parsed.ast, n.Equation) for row in rows):
            from mathtutor.learning.linear_system_attempt import verify_system_attempt
            from mathtutor.solving.parser import ParsedProblem
            system = n.LinearSystem(tuple(row.parsed.ast for row in rows))
            parsed = ParsedProblem("linear_system", system, n.to_dict(system), n.to_latex(system), None)
            return verify_system_attempt(n.from_dict(problem.normalized_ast), ParsedAttempt("linear_system", parsed), base)
    inequality_task = problem.problem_type in {"linear_inequality", "quadratic_inequality"}
    if not inequality_task and problem.problem_type not in {"linear", "quadratic"}:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED,
            reason="这类题的多行变形尚不能逐步核验，请单独提交完整答案。", **base)

    previous = None if inequality_task else n.from_dict(problem.normalized_ast)
    family = problem.problem_type
    prefix = []
    previous_line = 0
    for index, step in enumerate(steps):
        line = step.get("line", index + 1)
        answer = interpret_step(step)
        final = index == len(steps) - 1
        if previous is not None and answer.kind == "equation":
            verdict = _assess_equation(previous, family, answer, base, allow_root_subset=final)
        elif final or inequality_task or answer.kind == "undeterminable":
            verdict = _assess_answer(problem, answer, base)
        else:
            verdict = AttemptAssessment(correctness=Correctness.UNDETERMINED,
                reason="请将这一行写成含原题未知数的完整等式，以便核对相邻两式。", **base)

        claims = tuple({**claim, "line": line} for claim in verdict.verified_claims)
        if verdict.correctness in {Correctness.INCORRECT, Correctness.UNDETERMINED}:
            anchor = f"第 {previous_line} 行" if previous_line else "原题"
            reason = verdict.reason or "这一步与上一式的解集不同，请复核等式两边的运算。"
            unknown = verdict.correctness is Correctness.UNDETERMINED
            location = f"第 {line} 行与{anchor}之间暂时无法核验。" if unknown else f"第 {line} 行未通过与{anchor}的核对。"
            reason = location + reason
            if not final:
                last_answer = interpret_step(steps[-1])
                try:
                    last_is_correct = _assess_answer(problem, last_answer, base).correctness is Correctness.CORRECT
                except n.MathComplexityError:
                    last_is_correct = False
                if last_is_correct:
                    reason += "末行的答案单独通过了原题检验，请补正这里的推导。"
            failure = {"line": line, "previous_line": previous_line, "reason": reason}
            return verdict.model_copy(update={
                "verified_claims": tuple(prefix), "reason": reason,
                "invalid_claims": ({"claim": "equation_step", **failure},) if not unknown else (),
                "remaining_requirements": ({"requirement": "clarify_step" if unknown else "revise_step", **failure},),
                "policy_version": WORKING_POLICY_VERSION,
            })
        prefix.extend(claims)
        if final:
            return verdict.model_copy(update={"verified_claims": tuple(prefix), "policy_version": WORKING_POLICY_VERSION})
        if previous is not None:
            previous = answer.parsed.ast
            family = answer.parsed.problem_type
        previous_line = line


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
