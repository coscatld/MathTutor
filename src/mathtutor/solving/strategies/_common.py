"""Shared payload helpers for solver strategies and the verifier.

Candidate steps and final answers are JSON-safe dicts so they can be bound
into hashed attestations. Coefficients of a polynomial ``c0 + c1*x + ...``
serialize as ``{"0": [n, d], "1": [n, d], ...}`` with reduced Fractions.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from mathtutor.solving import nodes as n


def frac_to_dict(value: Fraction) -> dict[str, int]:
    return {"n": value.numerator, "d": value.denominator}


def frac_from_dict(payload: dict[str, int]) -> Fraction:
    return Fraction(payload["n"], payload["d"])


def coeffs_to_dict(poly: dict[int, Fraction]) -> dict[str, dict[str, int]]:
    return {str(degree): frac_to_dict(coeff) for degree, coeff in poly.items()}


def coeffs_from_dict(payload: dict[str, dict[str, int]]) -> dict[int, Fraction]:
    return {int(degree): frac_from_dict(value) for degree, value in payload.items()}


def rational_root(value: Fraction) -> dict[str, Any]:
    return {"kind": "rational", "value": frac_to_dict(value)}


def surd_root(num: Fraction, coeff: Fraction, radicand: int) -> dict[str, Any]:
    """x = num ± coeff * sqrt(radicand) with ``radicand`` squarefree."""
    return {
        "kind": "surd",
        "num": frac_to_dict(num),
        "coeff": frac_to_dict(coeff),
        "radicand": radicand,
    }


def root_latex(root: dict[str, Any], variable: str = "x") -> str:
    if root["kind"] == "rational":
        value = frac_from_dict(root["value"])
        rendered = (
            str(value.numerator)
            if value.denominator == 1
            else f"\\frac{{{value.numerator}}}{{{value.denominator}}}"
        )
        return f"{variable} = {rendered}"
    num = frac_from_dict(root["num"])
    coeff = frac_from_dict(root["coeff"])
    radicand = root["radicand"]
    sign = " + " if coeff >= 0 else " - "
    coeff_abs = abs(coeff)
    surd_piece = (
        f"\\sqrt{{{radicand}}}" if coeff_abs == 1 else f"{coeff_abs}\\sqrt{{{radicand}}}"
    )
    return f"{variable} = {num}{sign}{surd_piece}"


def equation_sides(equation: n.Equation, variable: str) -> tuple[dict[int, Fraction], dict[int, Fraction]]:
    """Coefficient vectors of (lhs, rhs) — raises on out-of-family input."""
    lhs = n.poly_coeffs(equation.lhs, variable)
    rhs = n.poly_coeffs(equation.rhs, variable)
    if lhs is None or rhs is None:
        raise n.MathDomainError("equation is not a single-variable rational polynomial")
    return lhs, rhs


def apply_transform(before: dict[str, dict[str, int]], transform: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Replay one recorded step transform over an equation's sides.

    ``before`` is ``{"lhs": coeffs, "rhs": coeffs}``; ``transform`` is
    ``{"kind": "subtract_term", "coeffs": ...}`` or
    ``{"kind": "divide_all", "value": [n, d]}``. The verifier applies this
    to the recorded *before* state and compares with the recorded *after*
    state (the step-relation check).
    """
    lhs = coeffs_from_dict(before["lhs"])
    rhs = coeffs_from_dict(before["rhs"])
    kind = transform["kind"]
    if kind == "subtract_term":
        delta = coeffs_from_dict(transform["coeffs"])
        for side in (lhs, rhs):
            for degree, value in delta.items():
                side[degree] = side.get(degree, Fraction(0)) - value
        return {"lhs": coeffs_to_dict(lhs), "rhs": coeffs_to_dict(rhs)}
    if kind == "divide_all":
        divisor = frac_from_dict(transform["value"])
        if divisor == 0:
            raise n.MathDomainError("cannot divide an equation by zero")
        lhs = {d: c / divisor for d, c in lhs.items()}
        rhs = {d: c / divisor for d, c in rhs.items()}
        return {"lhs": coeffs_to_dict(lhs), "rhs": coeffs_to_dict(rhs)}
    raise ValueError(f"unknown transform kind: {kind!r}")
