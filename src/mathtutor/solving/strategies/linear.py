"""Linear equation strategy: ax + b = 0 via three side transforms.

Steps record ``before``/``after`` equation sides plus the transform, so the
verifier can replay them exactly (step-relation check). The root is the
exact rational ``-b/a``.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import _common as c

STRATEGY_NAME = "mt-linear-v1"


def solve(parsed: ParsedProblem) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    assert parsed.variable is not None
    assert isinstance(parsed.ast, n.Equation)
    lhs, rhs = c.equation_sides(parsed.ast, parsed.variable)

    steps: list[dict[str, Any]] = []
    current_lhs, current_rhs = lhs, rhs

    def record(label: str, transform: dict[str, Any]) -> None:
        nonlocal current_lhs, current_rhs
        before = {"lhs": c.coeffs_to_dict(current_lhs), "rhs": c.coeffs_to_dict(current_rhs)}
        after = c.apply_transform(before, transform)
        steps.append(
            {
                "label": label,
                "transform": transform,
                "before": before,
                "after": after,
            }
        )
        current_lhs = c.coeffs_from_dict(after["lhs"])
        current_rhs = c.coeffs_from_dict(after["rhs"])

    # 1) Move the whole right side to the left: a*x + b = 0.
    record(
        "移项：把右边的项移到左边",
        {"kind": "subtract_term", "coeffs": c.coeffs_to_dict(rhs)},
    )
    # 2) Move the constant term to the right side.
    constant = current_lhs.get(0, Fraction(0))
    if constant != 0:
        record(
            "移项：把常数项移到等号右边",
            {"kind": "subtract_term", "coeffs": c.coeffs_to_dict({0: constant})},
        )
    # 3) Normalize the x coefficient to 1.
    coefficient = current_lhs.get(1, Fraction(0))
    if coefficient != 1:
        record(
            "两边除以一次项系数",
            {"kind": "divide_all", "value": c.frac_to_dict(coefficient)},
        )

    root = Fraction(-constant, coefficient)
    final_answer = {
        "kind": "roots",
        "roots": (c.rational_root(root),),
        "latex": c.root_latex(c.rational_root(root), parsed.variable),
    }
    return (tuple(steps), final_answer)
