"""Gold set: solve + verify. Positive examples must VERIFY; tampered
candidates (wrong answers, missing roots, extra roots, fabricated steps,
mismatched strategies) must be FAILED — the false-VERIFIED protection."""

from __future__ import annotations

from fractions import Fraction
from uuid import uuid4

import pytest

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.solving import parse_problem, solve_problem, verify
from mathtutor.solving.strategies import _common as c


def verified_candidate(text: str) -> tuple[MathProblem, MathSolutionCandidate]:
    outcome = parse_problem(text)
    assert outcome.kind == "parsed", outcome.reason
    parsed = outcome.problem
    assert parsed is not None
    problem = MathProblem.canonicalize(parsed.problem_type, parsed.normalized_ast, parsed.display_latex)
    solved = solve_problem(problem, parsed)
    assert solved.kind == "solved", solved.reason
    return problem, solved.candidate  # type: ignore[return-value]


def assert_verified(text: str) -> None:
    problem, candidate = verified_candidate(text)
    decision = verify(problem, candidate)
    assert decision.verdict == "VERIFIED", f"{text!r}: {_failed_details(decision)}"
    assert problem.content_hash == decision.problem_content_hash
    assert candidate.payload_hash == decision.candidate_payload_hash


def _failed_details(decision) -> str:
    return "; ".join(f"{c.name}={c.status}" for c in decision.checks if c.status == "failed")


class TestGoldPositive:
    @pytest.mark.parametrize(
        "text",
        [
            "3/4 + 1/2",      # 5/4
            "0.5 + 1/4",      # 3/4
            "2*(3+4)",        # 14
            "6/2",            # 3
            "-2^2",           # -4  (minus binds looser than ^)
            "(-2)^2",         # 4
        ],
    )
    def test_arithmetic(self, text: str) -> None:
        assert_verified(text)

    @pytest.mark.parametrize(
        "text",
        [
            "2x^2 + 4x",
            "2x(x+2)",
            "x",
            "3x/2",
        ],
    )
    def test_polynomial(self, text: str) -> None:
        assert_verified(text)

    @pytest.mark.parametrize(
        "text",
        [
            "2x + 3 = 7",          # x=2
            "3x - 1 = 2x + 4",     # x=5
            "x/2 = 3",             # x=6
            "x = 2",               # x=2
            "2x + 3 = 3x",         # x=3
            "-x + 1 = 0",          # x=1
        ],
    )
    def test_linear(self, text: str) -> None:
        assert_verified(text)

    @pytest.mark.parametrize(
        "text",
        [
            "x^2 - 5x + 6 = 0",      # 2, 3
            "x^2 = 5",               # ±√5
            "x^2 + 1 = 0",           # no real roots
            "(x+1)^2 = 4",           # -3, 1
            "2x^2 + 4x - 6 = 0",     # -3, 1
            "x^2 - 2x - 4 = 0",      # 1±√5
            "x^2 - 4x + 4 = 0",      # double root 2
            "x^2 + 5x = -6",         # -3, -2
            "x^2 = -4",              # no real roots
        ],
    )
    def test_quadratic(self, text: str) -> None:
        assert_verified(text)

    def test_final_answer_values(self) -> None:
        problem, candidate = verified_candidate("x^2 - 5x + 6 = 0")
        roots = candidate.final_answer["roots"]
        values = [c.frac_from_dict(root["value"]) for root in roots]
        assert values == [Fraction(2), Fraction(3)]

    def test_surd_roots(self) -> None:
        problem, candidate = verified_candidate("x^2 - 2x - 4 = 0")
        roots = candidate.final_answer["roots"]
        assert [root["kind"] for root in roots] == ["surd", "surd"]
        assert roots[0]["radicand"] == 5
        assert roots[0]["num"] == {"n": 1, "d": 1}
        assert roots[0]["coeff"] == {"n": -1, "d": 1}

    def test_no_real_roots(self) -> None:
        problem, candidate = verified_candidate("x^2 + 1 = 0")
        assert candidate.final_answer["roots"] == ()

    def test_equivalent_forms_same_answer(self) -> None:
        """2x(x+2) ≡ 2x^2+4x: same canonical answer even though the trees differ."""
        _, a = verified_candidate("2x(x+2)")
        _, b = verified_candidate("2x^2 + 4x")
        assert a.final_answer["coeffs"] == b.final_answer["coeffs"]

    def test_distinct_forms_distinct_answers(self) -> None:
        _, a = verified_candidate("3x/2")
        _, b = verified_candidate("x")
        assert a.final_answer["coeffs"] != b.final_answer["coeffs"]


class TestGoldNegative:
    """Tampered candidates must never VERIFY."""

    def _tamper(self, text: str, *, final_answer, steps=None) -> tuple[MathProblem, MathSolutionCandidate]:
        problem, original = verified_candidate(text)
        candidate = MathSolutionCandidate.canonicalize(
            problem_id=problem.problem_id,
            strategy=original.strategy,
            steps=steps if steps is not None else original.steps,
            final_answer=final_answer,
        )
        return problem, candidate

    def _assert_failed(self, problem, candidate) -> None:
        decision = verify(problem, candidate)
        assert decision.verdict == "FAILED", f"期望 FAILED，实际 {decision.verdict}"

    def test_linear_wrong_root(self) -> None:
        problem, candidate = self._tamper(
            "2x + 3 = 7",
            final_answer={"kind": "roots", "roots": (c.rational_root(Fraction(3)),), "latex": "x = 3"},
        )
        self._assert_failed(problem, candidate)

    def test_quadratic_missing_root(self) -> None:
        problem, candidate = self._tamper(
            "x^2 - 5x + 6 = 0",
            final_answer={
                "kind": "roots",
                "roots": (c.rational_root(Fraction(2)),),
                "latex": "x = 2",
            },
        )
        decision = verify(problem, candidate)
        assert decision.verdict == "FAILED"
        assert any(check.name == "completeness" and check.status == "failed" for check in decision.checks)

    def test_quadratic_extraneous_root(self) -> None:
        problem, candidate = self._tamper(
            "x^2 - 5x + 6 = 0",
            final_answer={
                "kind": "roots",
                "roots": (c.rational_root(Fraction(2)), c.rational_root(Fraction(3)), c.rational_root(Fraction(4))),
                "latex": "x = 2, 3, 4",
            },
        )
        decision = verify(problem, candidate)
        assert decision.verdict == "FAILED"
        assert any(check.name == "extraneous_roots" and check.status == "failed" for check in decision.checks)

    def test_quadratic_false_surd_root(self) -> None:
        """Claiming 2+√5 for x^2-2x-4=0 (true roots 1±√5): substitution fails."""
        problem, candidate = self._tamper(
            "x^2 - 2x - 4 = 0",
            final_answer={
                "kind": "roots",
                "roots": (
                    c.surd_root(Fraction(2), Fraction(1), 5),
                    c.surd_root(Fraction(2), Fraction(-1), 5),
                ),
                "latex": "x = 2±√5",
            },
        )
        decision = verify(problem, candidate)
        assert decision.verdict == "FAILED"
        assert any(check.name == "extraneous_roots" and check.status == "failed" for check in decision.checks)

    def test_arithmetic_wrong_value(self) -> None:
        problem, candidate = self._tamper(
            "3/4 + 1/2",
            final_answer={"kind": "rational", "value": {"n": 5, "d": 2}, "latex": "5/2"},
        )
        self._assert_failed(problem, candidate)

    def test_fabricated_step_fails_replay(self) -> None:
        """A step claiming a wrong intermediate value must fail step_relation."""
        problem, original = verified_candidate("3/4 + 1/2")
        bad_step = {"label": "伪造步骤", "expr": {"kind": "num", "value": {"n": 1, "d": 4}}, "value": {"n": 9, "d": 4}}
        candidate = MathSolutionCandidate.canonicalize(
            problem_id=problem.problem_id,
            strategy=original.strategy,
            steps=(bad_step,),
            final_answer=original.final_answer,
        )
        decision = verify(problem, candidate)
        assert decision.verdict == "FAILED"
        assert any(check.name == "step_relation" and check.status == "failed" for check in decision.checks)

    def test_wrong_strategy_name_fails_policy(self) -> None:
        problem, original = verified_candidate("2x + 3 = 7")
        candidate = MathSolutionCandidate.canonicalize(
            problem_id=problem.problem_id,
            strategy="quadratic",
            steps=original.steps,
            final_answer=original.final_answer,
        )
        decision = verify(problem, candidate)
        assert decision.verdict == "FAILED"
        assert any(check.name == "policy_coverage" and check.status == "failed" for check in decision.checks)

    def test_candidate_bound_to_other_problem_fails(self) -> None:
        problem, _ = verified_candidate("2x + 3 = 7")
        other, other_candidate = verified_candidate("x^2 - 5x + 6 = 0")
        decision = verify(problem, other_candidate)
        assert decision.verdict == "FAILED"
        assert any(check.name == "policy_coverage" and check.status == "failed" for check in decision.checks)

    def test_unknown_final_kind_fails(self) -> None:
        problem, original = verified_candidate("3/4 + 1/2")
        candidate = MathSolutionCandidate.canonicalize(
            problem_id=problem.problem_id,
            strategy=original.strategy,
            steps=original.steps,
            final_answer={"kind": "roots", "roots": (), "latex": "?"},
        )
        self._assert_failed(problem, candidate)


class TestVerifierBindings:
    def test_decision_hashes_bound(self) -> None:
        problem, candidate = verified_candidate("x^2 - 5x + 6 = 0")
        decision = verify(problem, candidate)
        assert decision.problem_id == problem.problem_id
        assert decision.problem_content_hash == problem.content_hash
        assert decision.candidate_id == candidate.candidate_id
        assert decision.candidate_payload_hash == candidate.payload_hash

    def test_verify_is_deterministic_and_pure(self) -> None:
        problem, candidate = verified_candidate("2x + 3 = 7")
        first = verify(problem, candidate)
        second = verify(problem, candidate)
        # Each call issues a fresh verification-log identity, but the
        # verdict, checks and bound hashes are identical — and nothing
        # mutated.
        assert first.verdict == second.verdict == "VERIFIED"
        assert first.checks == second.checks
        assert first.problem_content_hash == second.problem_content_hash == problem.content_hash
        assert first.decision_id != second.decision_id

    def test_payload_hash_changes_with_answer(self) -> None:
        problem, candidate = verified_candidate("2x + 3 = 7")
        tampered = MathSolutionCandidate.canonicalize(
            problem_id=problem.problem_id,
            strategy=candidate.strategy,
            steps=candidate.steps,
            final_answer={"kind": "roots", "roots": (c.rational_root(Fraction(99)),), "latex": "x=99"},
        )
        assert tampered.payload_hash != candidate.payload_hash
