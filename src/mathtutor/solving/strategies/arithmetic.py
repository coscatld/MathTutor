"""Arithmetic strategy: exact evaluation of a rational expression.

Each AST node contributes one step (``expr`` + its exact ``value``), so the
verifier can replay every step by independently re-evaluating the recorded
sub-expression — the step-relation check.
"""

from __future__ import annotations

from typing import Any

from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import _common as c

STRATEGY_NAME = "mt-arithmetic-v1"


def solve(parsed: ParsedProblem) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    """Evaluate the arithmetic expression bottom-up; one step per node."""

    steps: list[dict[str, Any]] = []

    def walk(node: n.Node) -> n.Rational:
        if isinstance(node, n.Num):
            value = node.value
        elif isinstance(node, n.Add):
            value = sum((walk(term) for term in node.terms), n.ZERO)
        elif isinstance(node, n.Mul):
            value = n.ONE
            for factor in node.factors:
                value = value * walk(factor)
        elif isinstance(node, n.Pow):
            value = walk(node.base) ** node.exp
        elif isinstance(node, n.Div):
            value = walk(node.num) / walk(node.den)
        else:
            raise n.MathDomainError(f"arithmetic strategy cannot evaluate {node!r}")
        steps.append(
            {
                "label": f"计算 {n.to_latex(node)}",
                "expr": n.to_dict(node),
                "value": value.to_dict(),
            }
        )
        return value

    total = walk(parsed.ast)
    final_answer = {
        "kind": "rational",
        "value": total.to_dict(),
        "latex": n.to_latex(n.Num(total)),
    }
    return (tuple(steps), final_answer)
