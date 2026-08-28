"""Math extraction helpers for the OutputGuard (Phase 3D).

The guard reuses the SAME parser/normalizer as the math core: leakage is
decided by canonical equality (root sets, exact values), never by string
matching for literal answers like "x=2".
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Any

from mathtutor.solving import nodes as n
from mathtutor.solving import parse_problem
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import _common as common
from mathtutor.solving.strategies import quadratic as q

_FRAGMENT_RE = re.compile(r"[0-9a-zA-Z()+\-*/^=√\\.一-鿿]{2,}")


def equation_roots(parsed: ParsedProblem) -> tuple[dict[str, Any], ...] | None:
    """Root set of a parsed linear/quadratic equation, exact and canonical."""
    if parsed.problem_type not in ("linear", "quadratic") or parsed.variable is None:
        return None
    assert isinstance(parsed.ast, n.Equation)
    diff = n.equation_difference(parsed.ast, parsed.variable)
    if diff is None:
        return None
    if parsed.problem_type == "linear":
        a, b = diff[1], diff.get(0, Fraction(0))
        return (common.rational_root(Fraction(-b, a)),)
    return q.quad_roots(diff.get(2, Fraction(0)), diff.get(1, Fraction(0)), diff.get(0, Fraction(0)))


def extract_math_fragments(text: str) -> list[str]:
    """Candidate expression fragments from natural-language text."""
    return [fragment.strip() for fragment in _FRAGMENT_RE.findall(text) if fragment.strip()]


def parse_fragment(fragment: str) -> ParsedProblem | None:
    """Parse one fragment; only clean parses count (ambiguous → not usable
    as a leakage signal — the guard must never false-positive)."""
    outcome = parse_problem(fragment)
    if outcome.kind not in ("ok",) and outcome.problem is None:
        return None
    return outcome.problem


def numeric_values(text: str) -> set[Fraction]:
    """Every exact numeric value appearing in the text (decimals, fractions,
    integers) — including disguised forms like 4/2 or 2.0."""
    values: set[Fraction] = set()
    for token in re.findall(r"\d+(?:\.\d+)?(?:/\d+(?:\.\d+)?)?", text):
        if "/" in token:
            num, den = token.split("/")
            try:
                values.add(Fraction(int(num), int(den)))
            except (ValueError, ZeroDivisionError):
                try:
                    values.add(Fraction(num).limit_denominator() / Fraction(den).limit_denominator())
                except (ValueError, ZeroDivisionError):
                    continue
        else:
            try:
                values.add(Fraction(token).limit_denominator())
            except (ValueError, ZeroDivisionError):
                continue
    return values


__all__ = [
    "equation_roots",
    "extract_math_fragments",
    "numeric_values",
    "parse_fragment",
]
