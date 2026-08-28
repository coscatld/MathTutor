"""Canonical AST invariants: Rational, builders, expansion, round trip."""

from __future__ import annotations

from fractions import Fraction

import pytest

from mathtutor.solving import nodes as n


class TestRational:
    def test_reduces(self) -> None:
        assert n.Rational(6, 4) == n.Rational(3, 2)
        assert n.Rational(6, 4).n == 3
        assert n.Rational(6, 4).d == 2

    def test_positive_denominator(self) -> None:
        assert n.Rational(1, -2) == n.Rational(-1, 2)

    def test_zero_is_zero_over_one(self) -> None:
        assert n.Rational(0, 5) == n.ZERO
        assert n.Rational(0, 5).d == 1

    def test_zero_denominator_raises(self) -> None:
        with pytest.raises(n.MathDomainError):
            n.Rational(1, 0)

    def test_arithmetic_exact(self) -> None:
        assert n.Rational(1, 3) + n.Rational(1, 6) == n.Rational(1, 2)
        assert n.Rational(2, 3) / n.Rational(4, 9) == n.Rational(3, 2)
        assert n.Rational(3, 2) ** 3 == n.Rational(27, 8)

    def test_division_by_zero_raises(self) -> None:
        with pytest.raises(n.MathDomainError):
            n.Rational(1, 2) / n.Rational(0)


class TestBuilders:
    def test_add_combines_and_sorts(self) -> None:
        node = n.add(n.mul(n.num(2), n.var("x")), n.num(3), n.mul(n.num(4), n.var("x")))
        assert node == n.add(n.mul(n.num(6), n.var("x")), n.num(3))
        assert isinstance(node, n.Add)
        assert node.terms[0] == n.mul(n.num(6), n.var("x"))  # variables before constants

    def test_add_drops_zeros_and_collapses(self) -> None:
        assert n.add(n.num(0), n.num(0)) == n.num(0)
        assert n.add(n.num(0), n.num(5)) == n.num(5)

    def test_mul_folds_literals_and_drops_ones(self) -> None:
        assert n.mul(n.num(2), n.num(3)) == n.num(6)
        assert n.mul(n.num(2), n.num(1), n.var("x")) == n.mul(n.num(2), n.var("x"))
        assert n.mul(n.num(0), n.var("x")) == n.num(0)

    def test_pow_canonical_restrictions(self) -> None:
        with pytest.raises(ValueError):
            n.pow(n.var("x"), 1)  # exp must be >= 2
        with pytest.raises(ValueError):
            n.pow(n.num(2), 2)  # literal base folds at the parser, not here

    def test_div_folds_and_rejects_zero(self) -> None:
        assert n.div(n.num(6), n.num(2)) == n.num(3)
        assert n.div(n.num(1), n.num(1)) == n.num(1)
        with pytest.raises(n.MathDomainError):
            n.div(n.num(1), n.num(0))

    def test_serialization_round_trip(self) -> None:
        node = n.eq(n.add(n.mul(n.num(2), n.var("x")), n.num(3)), n.num(7))
        assert n.from_dict(n.to_dict(node)) == node


class TestPolyCoeffs:
    def test_linear(self) -> None:
        node = n.add(n.mul(n.num(2), n.var("x")), n.num(3))
        assert n.poly_coeffs(node, "x") == {1: Fraction(2), 0: Fraction(3)}

    def test_expansion_of_power(self) -> None:
        node = n.pow(n.add(n.var("x"), n.num(1)), 2)
        assert n.poly_coeffs(node, "x") == {2: Fraction(1), 1: Fraction(2), 0: Fraction(1)}

    def test_division_by_constant(self) -> None:
        node = n.div(n.var("x"), n.num(2))
        assert n.poly_coeffs(node, "x") == {1: Fraction(1, 2)}

    def test_variable_in_denominator_is_none(self) -> None:
        node = n.div(n.num(1), n.var("x"))
        assert n.poly_coeffs(node, "x") is None

    def test_multi_variable_is_none(self) -> None:
        node = n.mul(n.var("x"), n.var("y"))
        assert n.poly_coeffs(node, "x") is None

    def test_scalar_not_normalized(self) -> None:
        """3x/2 and x must NOT collapse — equality is exact, not projective."""
        assert n.poly_coeffs(n.div(n.mul(n.num(3), n.var("x")), n.num(2)), "x") != n.poly_coeffs(n.var("x"), "x")


class TestEvaluate:
    def test_arithmetic_exact(self) -> None:
        node = n.add(n.num(n.Rational(1, 3)), n.num(n.Rational(1, 6)))
        assert n.evaluate(node) == n.Rational(1, 2)

    def test_variable_raises(self) -> None:
        with pytest.raises(n.MathDomainError):
            n.evaluate(n.var("x"))


class TestLatex:
    def test_fraction(self) -> None:
        assert n.to_latex(n.div(n.num(1), n.num(2))) == "\\frac{1}{2}"

    def test_polynomial(self) -> None:
        assert n.poly_to_latex({2: Fraction(2), 1: Fraction(-1), 0: Fraction(1, 2)}, "x") == "2x^{2} - x + \\frac{1}{2}"

    def test_negative_leading(self) -> None:
        assert n.poly_to_latex({1: Fraction(-1)}, "x") == "-x"

    def test_equation(self) -> None:
        node = n.eq(n.add(n.mul(n.num(2), n.var("x")), n.num(3)), n.num(7))
        assert n.to_latex(node) == "2x + 3 = 7"
