"""Quadratic equation strategy: ax^2 + bx + c = 0 via the discriminant.

Roots are computed *exactly*:

- ``D < 0`` -> no real solutions (a complete, correct answer);
- ``D = 0`` -> one rational double root;
- ``D > 0`` with a rational square discriminant -> two rational roots;
- otherwise two surd roots ``num ± coeff*sqrt(radicand)`` with a squarefree
  radicand.

The verifier re-derives ``D`` and the roots independently (its own code
path) and additionally substitutes every root back into the original
polynomial — the extraneous-root check — which is exact even for surds
because ``(p + q*sqrt(r))^2 = p^2 + q^2*r + 2pq*sqrt(r)`` in ``Q(sqrt(r))``.
"""

from __future__ import annotations

from fractions import Fraction
import math
from typing import Any

from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import _common as common

STRATEGY_NAME = "mt-quadratic-v1"

_TRIAL_DIVISION_BOUND = 100_000  # squarefree normalization budget


def sqrt_factor(m: int) -> tuple[int, int]:
    """Return ``(k, r)`` with ``m == k^2 * r`` and ``r`` squarefree, ``r >= 1``.

    Trial division over primes up to :data:`_TRIAL_DIVISION_BOUND`; if the
    remaining factor exceeds the budget the radicand is left unnormalized —
    the substitution check stays exact either way (fail closed on huge
    inputs).
    """
    if m < 0:
        raise ValueError("sqrt_factor requires m >= 0")
    if m == 0:
        return (0, 0)
    r = m
    k = 1
    squarefree = 1  # odd-exponent primes already divided out of r
    divisor = 2
    while divisor * divisor <= r and divisor <= _TRIAL_DIVISION_BOUND:
        if r % divisor:
            divisor = 3 if divisor == 2 else divisor + 2
            continue
        exponent = 0
        while r % divisor == 0:
            r //= divisor
            exponent += 1
        k *= divisor ** (exponent // 2)
        if exponent % 2:
            squarefree *= divisor
    return (k, squarefree * r)


def _is_perfect_square(value: int) -> bool:
    return value >= 0 and math.isqrt(value) ** 2 == value


def quad_roots(a: Fraction, b: Fraction, c: Fraction) -> tuple[dict[str, Any], ...]:
    """Exact real root set of ``a x^2 + b x + c = 0`` (a != 0), sorted."""
    discriminant = b * b - 4 * a * c
    if discriminant < 0:
        return ()
    if discriminant == 0:
        root = Fraction(-b, 2 * a)
        return (common.rational_root(root),)
    p, q = discriminant.numerator, discriminant.denominator
    if _is_perfect_square(p) and _is_perfect_square(q):
        sqrt_d = Fraction(math.isqrt(p), math.isqrt(q))
        roots = [(-b + sqrt_d) / (2 * a), (-b - sqrt_d) / (2 * a)]
        roots.sort()
        return tuple(common.rational_root(root) for root in roots)
    # Surd case: sqrt(D) = k*sqrt(r)/q  with  D = p/q,  m = p*q = k^2*r.
    k, r = sqrt_factor(p * q)
    num_part = Fraction(-b, 2 * a)          # (-b)/(2a)
    coeff = Fraction(k, 2 * a * q)          # k/(2a*q)
    roots = [
        common.surd_root(num_part, coeff, r),
        common.surd_root(num_part, -coeff, r),
    ]
    roots.sort(
        key=lambda root: (root["num"]["n"] / root["num"]["d"], root["coeff"]["n"] / root["coeff"]["d"])
    )
    return tuple(roots)


def quad_discriminant(a: Fraction, b: Fraction, c: Fraction) -> Fraction:
    return b * b - 4 * a * c


def quad_eval_surd(a: Fraction, b: Fraction, c: Fraction, num: Fraction, coeff: Fraction, radicand: int) -> tuple[Fraction, Fraction]:
    """Value of ``a x^2 + b x + c`` at ``x = num + coeff*sqrt(radicand)``.

    Returns ``(rational_part, surd_part)``; the substitution check passes
    iff both are exactly zero.
    """
    x2_rational = num * num + coeff * coeff * radicand
    x2_surd = 2 * num * coeff
    rational_part = a * x2_rational + b * num + c
    surd_part = a * x2_surd + b * coeff
    return (rational_part, surd_part)


def solve(parsed: ParsedProblem) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    assert parsed.variable is not None
    assert isinstance(parsed.ast, n.Equation)
    lhs, rhs = common.equation_sides(parsed.ast, parsed.variable)
    diff = {d: lhs.get(d, Fraction(0)) - rhs.get(d, Fraction(0)) for d in set(lhs) | set(rhs)}
    diff = {d: coeff for d, coeff in diff.items() if coeff != 0}
    a = diff.get(2, Fraction(0))
    b = diff.get(1, Fraction(0))
    cc = diff.get(0, Fraction(0))
    if a == 0:
        raise n.MathDomainError("not a quadratic equation")

    discriminant = quad_discriminant(a, b, cc)
    roots = quad_roots(a, b, cc)

    steps = (
        {
            "label": "计算判别式 \\Delta = b^2 - 4ac",
            "a": common.frac_to_dict(a),
            "b": common.frac_to_dict(b),
            "c": common.frac_to_dict(cc),
            "discriminant": common.frac_to_dict(discriminant),
        },
        {
            "label": "由求根公式得到解",
            "roots": roots,
        },
    )
    if not roots:
        latex = "无实数解"
    elif len(roots) == 1:
        latex = common.root_latex(roots[0], parsed.variable)
    else:
        latex = " 或 ".join(common.root_latex(root, parsed.variable) for root in roots)
    final_answer = {"kind": "roots", "roots": roots, "latex": latex}
    return (steps, final_answer)
