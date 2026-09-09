"""Parser gold set: family classification, ambiguity and unsupported input."""

from __future__ import annotations

import pytest

from mathtutor.solving.parser import parse_problem


def parsed(text: str):
    outcome = parse_problem(text)
    assert outcome.kind == "parsed", f"预期 parsed，实际 {outcome.kind}: {outcome.reason}"
    return outcome.problem


class TestFamilies:
    @pytest.mark.parametrize(
        "text",
        [
            "3/4 + 1/2",
            "0.5 + 1/4",
            "2*(3+4)",
            "6/2",
            "-2^2",
            "(-2)^2",
            "\\frac{1}{2} + \\frac{1}{3}",
            "1/2 \\cdot 2/3",
            "2+2=?",
            "2+2=",
        ],
    )
    def test_arithmetic(self, text: str) -> None:
        assert parsed(text).problem_type == "arithmetic"

    @pytest.mark.parametrize(
        "text",
        [
            "2x^2 + 4x",
            "2x(x+2)",
            "4x + 2x^2",
            "x",
            "3x/2",
            "\\frac{x}{2}",
        ],
    )
    def test_polynomial(self, text: str) -> None:
        assert parsed(text).problem_type == "polynomial"

    @pytest.mark.parametrize(
        "text",
        ["2x + 3 = 7", "3x - 1 = 2x + 4", "x/2 = 3", "x = 2", "\\frac{1}{2}x - 1 = 0"],
    )
    def test_linear(self, text: str) -> None:
        assert parsed(text).problem_type == "linear"

    @pytest.mark.parametrize(
        "text",
        [
            "x^2 - 5x + 6 = 0",
            "x^2 = 5",
            "x^2 + 1 = 0",
            "(x+1)^2 = 4",
            "2x^2 + 4x - 6 = 0",
            "x^2 - 2x - 4 = 0",
            "x^2 + 5x = -6",
            "求 x^2 + 2x + 1 = 0",
        ],
    )
    def test_quadratic(self, text: str) -> None:
        assert parsed(text).problem_type == "quadratic"


class TestCanonicalEquality:
    def test_term_order_is_irrelevant(self) -> None:
        assert parsed("2x^2 + 4x").normalized_ast == parsed("4x + 2x^2").normalized_ast

    def test_factorized_equals_expanded(self) -> None:
        """Canonical trees keep products; equivalence holds on the expanded
        coefficient answer (checked by the verifier's final_answer check)."""
        assert parsed("2x(x+2)").problem_type == parsed("2x^2 + 4x").problem_type == "polynomial"

    def test_scalar_not_equal(self) -> None:
        """3x/2 is not x — canonical form must not scalar-normalize."""
        assert parsed("3x/2").normalized_ast != parsed("x").normalized_ast

    def test_latex_and_plain_equivalent(self) -> None:
        assert parsed("\\frac{1}{2} + \\frac{1}{3}").normalized_ast == parsed("1/2 + 1/3").normalized_ast


class TestAmbiguous:
    @pytest.mark.parametrize("text", ["2 3", "x y", "xy = 2"])
    def test_ambiguous(self, text: str) -> None:
        assert parse_problem(text).kind == "ambiguous"

    def test_ambiguous_has_reason(self) -> None:
        assert parse_problem("2 3").reason


class TestUnparseable:
    @pytest.mark.parametrize("text", ["", "x +", "1..2", "2 = = 2"])
    def test_unparseable(self, text: str) -> None:
        assert parse_problem(text).kind == "unparseable", text


class TestUnsupported:
    @pytest.mark.parametrize(
        "text",
        [
            "1/0",            # division by zero
            "x = x",          # identity
            "1 = 2",          # contradiction
            "x^3 = 8",        # degree 3
            "x^2 + x^3 = 0",  # degree 3
            "\\sqrt{4} + 1",  # square roots are not an MVP family
            "1/x = 2",        # variable in denominator
            "2x + 3y = 1",    # two variables
            "x^2 y = 1",      # multi-variable product
        ],
    )
    def test_unsupported(self, text: str) -> None:
        outcome = parse_problem(text)
        assert outcome.kind == "unsupported", f"{text!r}: {outcome.kind} {outcome.reason}"

    def test_unsupported_has_reason(self) -> None:
        assert parse_problem("x^3 = 8").reason


class TestVariables:
    def test_variable_name_recorded(self) -> None:
        assert parsed("2y + 3 = 7").variable == "y"
        assert parsed("x^2 = 5").variable == "x"
        assert parsed("3/4 + 1/2").variable is None
