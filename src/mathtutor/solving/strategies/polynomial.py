"""Polynomial strategy: expand and combine like terms (equivalence form).

The canonical answer is the exact coefficient vector of the expanded
polynomial — no scalar or sign normalization, so ``3x/2`` stays different
from ``x`` while ``2x^2 + 4x`` equals ``2x(x + 2)``. The verifier replays
the expansion independently.
"""

from __future__ import annotations

from typing import Any

from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import _common as c

STRATEGY_NAME = "mt-polynomial-v1"


def solve(parsed: ParsedProblem) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    assert parsed.variable is not None
    coeffs = n.poly_coeffs(parsed.ast, parsed.variable)
    if coeffs is None:
        raise n.MathDomainError("expression is not a single-variable rational polynomial")
    steps = (
        {
            "label": f"展开并合并同类项（变量 {parsed.variable}）",
            "expr": n.to_dict(parsed.ast),
            "coeffs": c.coeffs_to_dict(coeffs),
        },
    )
    final_answer = {
        "kind": "polynomial",
        "var": parsed.variable,
        "coeffs": c.coeffs_to_dict(coeffs),
        "latex": n.poly_to_latex(coeffs, parsed.variable),
    }
    return (steps, final_answer)
