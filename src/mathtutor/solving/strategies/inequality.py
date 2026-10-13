"""One-variable linear inequality. Reuses the linear equation steps, then states the range."""
from __future__ import annotations

from fractions import Fraction
from typing import Any

from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import _common as c
from mathtutor.solving.strategies import linear

STRATEGY_NAME = "mt-linear-inequality-v1"
_FLIP = {"gt": "lt", "lt": "gt", "ge": "le", "le": "ge"}
_LATEX = {"gt": ">", "ge": r"\ge", "lt": "<", "le": r"\le"}


def solved_form(equation: n.Equation, variable: str, relation: str) -> tuple[str, Fraction]:
    """Return the solved relation and boundary. A negative coefficient flips the relation."""
    if relation not in _FLIP:
        raise n.MathDomainError("unknown inequality relation")
    diff = n.equation_difference(equation, variable)
    if diff is None or any(degree > 1 and coeff != 0 for degree, coeff in diff.items()):
        raise n.MathDomainError("not a linear inequality")
    slope = diff.get(1, Fraction(0))
    intercept = diff.get(0, Fraction(0))
    if slope == 0:
        raise n.MathDomainError("not a linear inequality")
    kept = relation if slope > 0 else _FLIP[relation]
    return kept, Fraction(-intercept, slope)


def solve(parsed: ParsedProblem) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    if not parsed.relation or not isinstance(parsed.ast, n.Equation):
        raise n.MathDomainError("linear inequality is missing its relation")
    steps, _equation_answer = linear.solve(parsed)
    relation, boundary = solved_form(parsed.ast, parsed.variable or "", parsed.relation)
    rendered = str(boundary.numerator) if boundary.denominator == 1 else f"\\frac{{{boundary.numerator}}}{{{boundary.denominator}}}"
    final_answer = {
        "kind": "inequality",
        "relation": relation,
        "variable": parsed.variable,
        "boundary": c.frac_to_dict(boundary),
        "latex": f"{parsed.variable} {_LATEX[relation]} {rendered}",
    }
    return steps, final_answer
