"""Resource rejection precedes costly exact arithmetic and preserves the next turn."""
import asyncio
from fractions import Fraction

import pytest

from mathtutor.solving import nodes as n
from mathtutor.solving.budget import (
    ParseBudget, MAX_TOKENS, MAX_PARSE_DEPTH, MAX_LITERAL_DIGITS, MAX_VALUE_BITS,
    MAX_TEXT_CHARS, check_product,
)
from mathtutor.solving.parser import _Tokenizer, parse_problem, parse_linear_equation_fragment


@pytest.mark.parametrize("token", ["1", "x", "+", "-", "−", "*", "×", "·", "⋅", "/", "÷", "^", "=", "(", ")", r"\times", r"\cdot", r"\div"])
def test_every_token_branch_consumes_the_shared_budget(token):
    for size in (MAX_TOKENS - 1, MAX_TOKENS):
        budget = ParseBudget()
        assert len(_Tokenizer(" ".join([token] * size), budget).tokenize()) == size
        assert budget.tokens == size
    with pytest.raises(n.MathComplexityError, match="记号预算"):
        _Tokenizer(" ".join([token] * (MAX_TOKENS + 1))).tokenize()


def test_fraction_children_and_outer_token_share_one_counter():
    text = r"\frac{\frac{1}{2}}{3}"
    for limit in (5, 6):
        budget = ParseBudget(max_tokens=limit)
        assert parse_problem(text, budget=budget).kind == "parsed"
        assert budget.tokens == 5
    outcome = parse_problem(text, budget=ParseBudget(max_tokens=4))
    assert (outcome.kind, outcome.code) == ("unsupported", "resource_limit")
    # Counting only root-level tokens would see 171, but children also count.
    outcome = parse_problem("+".join([r"\frac{1}{2}"] * 65))
    assert outcome.code == "resource_limit"


def test_unsupported_sqrt_still_counts_command_and_child_tokens():
    budget = ParseBudget(max_tokens=2)
    assert len(_Tokenizer(r"\sqrt{1}", budget).tokenize()) == 1
    assert budget.tokens == 2
    with pytest.raises(n.MathComplexityError):
        _Tokenizer(r"\sqrt{1}", ParseBudget(max_tokens=1)).tokenize()


def test_system_equations_share_the_same_token_budget():
    text = "x+y=3;x-y=1"
    for limit in (10, 11):
        budget = ParseBudget(max_tokens=limit)
        assert parse_problem(text, budget=budget).kind == "parsed"
        assert budget.tokens == 10
    assert parse_problem(text, budget=ParseBudget(max_tokens=9)).code == "resource_limit"


@pytest.mark.parametrize("wrapper", [lambda n: "+" * n + "1", lambda n: "(" * n + "1" + ")" * n,
    lambda n: r"\frac{" * n + "1" + "}{1}" * n])
def test_depth_is_checked_before_recursive_descent(wrapper):
    for depth in (MAX_PARSE_DEPTH - 2, MAX_PARSE_DEPTH - 1):
        assert parse_problem(wrapper(depth)).kind == "parsed"
    assert parse_problem(wrapper(MAX_PARSE_DEPTH)).code == "resource_limit"


def test_depth_budget_is_released_even_when_parse_fails():
    budget = ParseBudget(max_depth=2)
    assert parse_problem("(((1)))", budget=budget).code == "resource_limit"
    assert budget.depth == 0


@pytest.mark.parametrize("literal", [lambda n: "9" * n, lambda n: "0." + "9" * (n - 1), lambda n: "." + "9" * n])
def test_literal_digits_checked_before_integer_conversion(literal):
    for digits in (MAX_LITERAL_DIGITS - 1, MAX_LITERAL_DIGITS):
        assert parse_problem(literal(digits)).kind == "parsed"
    assert parse_problem(literal(MAX_LITERAL_DIGITS + 1)).code == "resource_limit"


@pytest.mark.parametrize("text", ["2^20000", "2^-20000", "(1/2)^4096", "(2/3)^4096", "2^(2^20000)", "(2^20000)^2", "x^(2^20000)"])
def test_over_budget_power_is_rejected_before_rational_power(monkeypatch, text):
    def forbidden(*args):
        raise AssertionError("rejected power must not execute")
    monkeypatch.setattr(n.Rational, "__pow__", forbidden)
    outcome = parse_problem(text)
    assert (outcome.kind, outcome.code) == ("unsupported", "resource_limit")


def test_folded_value_bit_boundary_remains_json_serializable():
    from mathtutor.domain.hashing import content_hash
    for exponent in (MAX_VALUE_BITS - 2, MAX_VALUE_BITS - 1):
        outcome = parse_problem(f"2^{exponent}")
        assert outcome.kind == "parsed"
        assert outcome.problem.ast.value.n.bit_length() == exponent + 1
        assert content_hash(outcome.problem.normalized_ast)
    assert parse_problem(f"2^{MAX_VALUE_BITS}").code == "resource_limit"


def test_multiplication_and_fraction_folding_cannot_grow_past_value_budget():
    assert parse_problem("2^2047*2^2048").kind == "parsed"
    assert parse_problem("2^2048*2^2048").code == "resource_limit"
    assert parse_problem(r"\frac{1}{2^2048}/2^2048").code == "resource_limit"
    with pytest.raises(n.MathComplexityError):
        check_product(1 << 2048, 1 << 2048)
    assert n.Rational(1 << 2048, 3) * n.Rational(3, 1 << 2048) == n.ONE
    assert n.Rational(1, 3) + n.Rational(1, 6) == n.Rational(1, 2)


def test_raw_input_length_is_bounded_before_normalization():
    for size in (MAX_TEXT_CHARS - 1, MAX_TEXT_CHARS):
        assert parse_problem(" " * (size - 1) + "1").kind == "parsed"
    assert parse_problem(" " * MAX_TEXT_CHARS + "1").code == "resource_limit"


@pytest.mark.parametrize("text", ["x+2^20000>1", "2x+y=2^20000;x-y=1", "x+" + "9" * 513 + "=1"])
def test_resource_code_survives_inequality_and_system_wrappers(text):
    assert parse_problem(text).code == "resource_limit"
    assert parse_linear_equation_fragment("x+y=2^20000").code == "resource_limit"


def test_normal_school_arithmetic_stays_exact_and_negative_power_stays_unsupported():
    assert parse_problem(r"\frac{2}{3}^4").problem.ast.value.to_fraction() == Fraction(16, 81)
    assert parse_problem("-2^2").problem.ast.value == n.Rational(-4)
    assert parse_problem("2^-3").kind == "unsupported"  # existing family restriction


def test_large_quadratic_values_use_exact_ordering_without_float_overflow():
    from mathtutor.domain.problem import MathProblem
    from mathtutor.solving.solver import solve_problem
    parsed = parse_problem("x^2+2^2000*x+1=0").problem
    problem = MathProblem.canonicalize(parsed.problem_type, parsed.normalized_ast, parsed.display_latex)
    result = solve_problem(problem, parsed)
    assert result.kind == "solved" and result.candidate.payload_hash
    assert result.candidate.final_answer["roots"][0]["coeff"]["n"] < 0


@pytest.mark.parametrize("text", ["x^2+2^3000*x+1=0", "x^2+2^3000*x+1>0", "2^3000*x+y=1;x+2^3000*y=1"])
def test_symbolic_intermediates_share_numeric_budget(text):
    from mathtutor.application.math_tutor_service import MathTutorApplicationService
    result = asyncio.run(MathTutorApplicationService().submit_problem(text))
    assert result.kind == "unsupported" and result.code == "resource_limit"
    assert result.candidate is None and result.verified_ref is None


def test_constraint_and_service_return_resource_limit_without_attestation():
    from mathtutor.application.constraint_layer import evaluate_constraints, ConstraintStatus
    from mathtutor.application.math_tutor_service import MathTutorApplicationService
    constraint = evaluate_constraints("2^20000")
    assert constraint.status == ConstraintStatus.HARD_FAIL and constraint.reason == "resource_limit"
    result = asyncio.run(MathTutorApplicationService().submit_problem("2^20000"))
    assert result.kind == "unsupported" and result.code == "resource_limit"
    assert result.problem is None and result.verified_ref is None and result.candidate is None


@pytest.mark.parametrize("command,text", [("submit_problem", "2^20000"), ("send_message", "2^20000"),
                                         ("submit_problem", "x^2+2^3000*x+1=0")])
def test_ws_rejects_resource_limit_and_next_request_recovers(tmp_path, command, text):
    from test_tutor_p0 import client_at, send, summary, count
    db = tmp_path / "math-budget.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        prior_verifications = count(db, "verification_logs")
        rejected = send(ws, command, "oversized", {"text": text})
        assert any(frame.get("payload", {}).get("error_code") == "RESOURCE_LIMIT" for frame in rejected)
        assert not any(frame["event_type"] == "assistant_complete" for frame in rejected)
        assert count(db, "verification_logs") == prior_verifications
        # Ordinary chat starts a fresh cycle after a solver-level unsupported
        # outcome; direct submit_problem belongs to the initial-cycle protocol.
        send(ws, "send_message", "ordinary", {"text": "2x+3=7"})
        assert summary(client)["state"] == "awaiting_attempt"
        send(ws, "submit_attempt", "answer", {"answer": "x=2"})
        assert summary(client)["state"] == "solved"
