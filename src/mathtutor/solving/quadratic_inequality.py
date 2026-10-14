"""One-variable quadratic inequality ``a x^2 + b x + c (>, >=, <, <=) 0``.

Only rational roots are supported: an irrational boundary is rejected at
parse time rather than approximated. The solution set is a union of
intervals with exact Fraction endpoints:

    Interval(lo, lo_closed, hi, hi_closed), ``None`` meaning infinity.

The strategy reuses the quadratic-equation steps for the boundary roots and
adds one step for the sign. The verifier is independent of that reasoning:
it checks the boundary roots against the polynomial and then evaluates the
polynomial's sign at test points around every root, comparing each point's
membership with the claimed set.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from mathtutor.solving import nodes as n

STRATEGY_NAME = "mt-quadratic-inequality-v1"
_SATISFIES = {"gt": lambda v: v > 0, "ge": lambda v: v >= 0, "lt": lambda v: v < 0, "le": lambda v: v <= 0}


@dataclass(frozen=True, order=True)
class Interval:
    lo: Fraction | None
    lo_closed: bool
    hi: Fraction | None
    hi_closed: bool

    def contains(self, x: Fraction) -> bool:
        above = self.lo is None or x > self.lo or (self.lo_closed and x == self.lo)
        below = self.hi is None or x < self.hi or (self.hi_closed and x == self.hi)
        return above and below


def coefficients(equation: n.Equation, variable: str) -> tuple[Fraction, Fraction, Fraction]:
    diff = n.equation_difference(equation, variable)
    if diff is None or any(degree > 2 and coeff for degree, coeff in diff.items()):
        raise n.MathDomainError("not a quadratic inequality")
    a, b, c = (diff.get(d, Fraction(0)) for d in (2, 1, 0))
    if a == 0:
        raise n.MathDomainError("not a quadratic inequality")
    return a, b, c


def _rational_sqrt(value: Fraction) -> Fraction | None:
    if value < 0:
        return None
    num, den = value.numerator, value.denominator
    rn, rd = _isqrt(num), _isqrt(den)
    return Fraction(rn, rd) if rn * rn == num and rd * rd == den else None


def _isqrt(value: int) -> int:
    import math
    return math.isqrt(value)


def rational_roots(a: Fraction, b: Fraction, c: Fraction) -> tuple[Fraction, ...]:
    """Sorted distinct real roots; raises when they are irrational."""
    disc = b * b - 4 * a * c
    if disc < 0:
        return ()
    root = _rational_sqrt(disc)
    if root is None:
        raise n.MathDomainError("目前只核验根为有理数的二次不等式")
    return tuple(sorted({(-b - root) / (2 * a), (-b + root) / (2 * a)}))


def solution_set(a: Fraction, b: Fraction, c: Fraction, relation: str) -> tuple[Interval, ...]:
    """Exact solution set from the roots and the sign of ``a``."""
    roots = rational_roots(a, b, c)
    holds = _SATISFIES[relation]
    closed = relation in {"ge", "le"}
    points = [None, *roots, None]
    intervals: list[Interval] = []
    for lo, hi in zip(points, points[1:]):
        probe = _probe(lo, hi)
        if holds(a * probe * probe + b * probe + c):
            intervals.append(Interval(lo, closed and lo is not None, hi, closed and hi is not None))
    for root in roots:  # isolated touching points such as (x-2)^2 <= 0
        if closed and not any(i.contains(root) for i in intervals):
            intervals.append(Interval(root, True, root, True))
    return normalize(intervals)


def _probe(lo: Fraction | None, hi: Fraction | None) -> Fraction:
    if lo is None and hi is None:
        return Fraction(0)
    if lo is None:
        return hi - 1
    if hi is None:
        return lo + 1
    return (lo + hi) / 2


def normalize(intervals) -> tuple[Interval, ...]:
    """Merge overlapping or touching intervals into a canonical tuple."""
    key = lambda i: (float("-inf") if i.lo is None else i.lo, not i.lo_closed)
    merged: list[Interval] = []
    for item in sorted(intervals, key=key):
        if merged:
            last = merged[-1]
            touches = last.hi is None or item.lo is None or item.lo < last.hi or (
                item.lo == last.hi and (last.hi_closed or item.lo_closed))
            if touches:
                if last.hi is None or (item.hi is not None and (item.hi < last.hi or (item.hi == last.hi and not item.hi_closed))):
                    hi, hi_closed = last.hi, last.hi_closed
                elif item.hi == last.hi:
                    hi, hi_closed = last.hi, last.hi_closed or item.hi_closed
                else:
                    hi, hi_closed = item.hi, item.hi_closed
                merged[-1] = Interval(last.lo, last.lo_closed, hi, hi_closed)
                continue
        merged.append(item)
    return tuple(merged)


def _frac_latex(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    sign = "-" if value < 0 else ""
    return f"{sign}\\frac{{{abs(value.numerator)}}}{{{value.denominator}}}"


def render(intervals: tuple[Interval, ...], variable: str) -> str:
    if not intervals:
        return "无解"
    if intervals == (Interval(None, False, None, False),):
        return f"{variable} 为任意实数"
    if len(intervals) == 2 and intervals[0].lo is None and intervals[1].hi is None and intervals[0].hi == intervals[1].lo \
            and not intervals[0].hi_closed and not intervals[1].lo_closed:
        ne = "\\ne"
        return f"{variable} {ne} {_frac_latex(intervals[0].hi)}"
    le, ge = "\\le", "\\ge"
    parts = []
    for item in intervals:
        lo_rel = le if item.lo_closed else "<"
        hi_rel = le if item.hi_closed else "<"
        if item.lo is not None and item.lo == item.hi:
            parts.append(f"{variable} = {_frac_latex(item.lo)}")
        elif item.lo is None:
            parts.append(f"{variable} {hi_rel} {_frac_latex(item.hi)}")
        elif item.hi is None:
            parts.append(f"{variable} {ge if item.lo_closed else '>'} {_frac_latex(item.lo)}")
        else:
            parts.append(f"{_frac_latex(item.lo)} {lo_rel} {variable} {hi_rel} {_frac_latex(item.hi)}")
    return " 或 ".join(parts)


def to_payload(intervals: tuple[Interval, ...]) -> list[dict[str, Any]]:
    frac = lambda v: None if v is None else {"n": v.numerator, "d": v.denominator}
    return [{"lo": frac(i.lo), "lo_closed": i.lo_closed, "hi": frac(i.hi), "hi_closed": i.hi_closed} for i in intervals]


def from_payload(payload) -> tuple[Interval, ...]:
    frac = lambda v: None if v is None else Fraction(v["n"], v["d"])
    return tuple(Interval(frac(i["lo"]), bool(i["lo_closed"]), frac(i["hi"]), bool(i["hi_closed"])) for i in payload)


# ---------------------------------------------------------------- answers

_NUMBER = r"[+-]?\d{1,18}(?:/\d{1,18})?"
_ALL = re.compile(r"^(?:[a-z]\s*(?:为|是|∈)\s*)?(?:全体实数|任意实数|一切实数|所有实数|R|ℝ|\(-∞,\s*\+?∞\))$", re.I)
_NONE = re.compile(r"^(?:无解|无实数解|空集|∅|不存在|no solution)$", re.I)
_REL = {"<": ("hi", False), "<=": ("hi", True), ">": ("lo", False), ">=": ("lo", True)}
_FLIP = {"<": ">", "<=": ">=", ">": "<", ">=": "<="}


def parse_answer(text: str, variable: str) -> tuple[Interval, ...] | None:
    """Read a student's solution set; ``None`` when the text is not one."""
    source = (text.strip().replace("≤", "<=").replace("≥", ">=").replace("＜", "<").replace("＞", ">")
              .replace("≠", "!=").replace("\\le", "<=").replace("\\ge", ">=").replace("\\ne", "!=").replace(" ", ""))
    if _ALL.match(source):
        return (Interval(None, False, None, False),)
    if _NONE.match(source):
        return ()
    parts = [p for p in re.split(r"或|or|∪|,|，|;|；", source) if p]
    intervals: list[Interval] = []
    v = re.escape(variable)
    for part in parts:
        if m := re.fullmatch(rf"{v}!=({_NUMBER})", part):
            x = Fraction(m.group(1))
            intervals += [Interval(None, False, x, False), Interval(x, False, None, False)]
        elif m := re.fullmatch(rf"{v}=({_NUMBER})", part):
            x = Fraction(m.group(1))
            intervals.append(Interval(x, True, x, True))
        elif m := re.fullmatch(rf"({_NUMBER})(<=|<){v}(<=|<)({_NUMBER})", part):
            intervals.append(Interval(Fraction(m.group(1)), m.group(2) == "<=", Fraction(m.group(4)), m.group(3) == "<="))
        elif m := re.fullmatch(rf"{v}(<=|>=|<|>)({_NUMBER})", part):
            side, closed = _REL[m.group(1)]
            x = Fraction(m.group(2))
            intervals.append(Interval(None, False, x, closed) if side == "hi" else Interval(x, closed, None, False))
        elif m := re.fullmatch(rf"({_NUMBER})(<=|>=|<|>){v}", part):
            side, closed = _REL[_FLIP[m.group(2)]]
            x = Fraction(m.group(1))
            intervals.append(Interval(None, False, x, closed) if side == "hi" else Interval(x, closed, None, False))
        else:
            return None
    return normalize(intervals)


# ------------------------------------------------------------ strategy

def solve(parsed) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    from mathtutor.solving.strategies import quadratic
    if not parsed.relation or not isinstance(parsed.ast, n.Equation) or not parsed.variable:
        raise n.MathDomainError("quadratic inequality is missing its relation")
    a, b, c = coefficients(parsed.ast, parsed.variable)
    steps, roots_answer = quadratic.solve(parsed)
    intervals = solution_set(a, b, c, parsed.relation)
    sign = "开口向上" if a > 0 else "开口向下"
    steps = (*steps, {"label": f"二次项系数{'为正' if a > 0 else '为负'}，抛物线{sign}，根据不等号取出解集",
                      "boundary_roots": roots_answer["latex"]})
    final_answer = {"kind": "inequality_set", "variable": parsed.variable, "relation": parsed.relation,
                    "intervals": to_payload(intervals), "latex": render(intervals, parsed.variable)}
    return steps, final_answer


def test_points(roots: tuple[Fraction, ...]) -> list[Fraction]:
    points = list(roots)
    edges = [None, *roots, None]
    points += [_probe(lo, hi) for lo, hi in zip(edges, edges[1:])]
    return points


def verify(problem, candidate):
    from mathtutor.domain.solution import VerificationCheck, VerificationDecision
    checks = []

    def record(name, okay, detail=""):
        checks.append(VerificationCheck(name=name, status="passed" if okay else "failed", detail="" if okay else detail))

    try:
        payload = problem.normalized_ast
        equation = n.from_dict(payload["equation"])
        relation, variable = payload["relation"], payload["variable"]
        record("parse_round_trip", n.to_dict(equation) == payload["equation"] and relation in _SATISFIES, "不等式规范形式不能回放")
        a, b, c = coefficients(equation, variable)
        roots = rational_roots(a, b, c)
        record("domain", True)
        record("step_relation", all(a * r * r + b * r + c == 0 for r in roots) and bool(candidate.steps),
               "边界方程的根代回后不为零")
        answer = candidate.final_answer
        claimed = from_payload(answer["intervals"])
        holds = _SATISFIES[relation]
        agree = all(holds(a * x * x + b * x + c) == any(i.contains(x) for i in claimed) for x in test_points(roots))
        record("final_answer", agree and answer.get("variable") == variable, "解集与各区间的符号检验不一致")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, n.MathDomainError, n.MathComplexityError) as exc:
        record("domain", False, str(exc))
    required = {"parse_round_trip", "domain", "step_relation", "final_answer"}
    coverage = (required <= {c.name for c in checks if c.status == "passed"}
                and candidate.strategy == "quadratic_inequality" and candidate.problem_id == problem.problem_id
                and candidate.final_answer.get("kind") == "inequality_set")
    record("policy_coverage", coverage, "二次不等式验证策略或必需检查不完整")
    return VerificationDecision.canonicalize(
        candidate_id=candidate.candidate_id, candidate_payload_hash=candidate.payload_hash,
        problem_id=problem.problem_id, problem_content_hash=problem.content_hash,
        policy_id="mt-ver-pol-quadratic-inequality", policy_version="v1",
        verdict="VERIFIED" if all(c.status == "passed" for c in checks) else "FAILED", checks=tuple(checks))


def assess(problem, raw_text: str):
    """(correctness, signals, reason) for a student's set, by exact set equality."""
    payload = problem.normalized_ast
    a, b, c = coefficients(n.from_dict(payload["equation"]), payload["variable"])
    expected = solution_set(a, b, c, payload["relation"])
    answer = parse_answer(raw_text, payload["variable"])
    if answer is None:
        return None
    if answer == expected:
        return "correct", (), ""
    roots = set(rational_roots(a, b, c))
    endpoints = {e for i in answer for e in (i.lo, i.hi) if e is not None}
    probes = test_points(tuple(sorted(roots | endpoints)))
    inside = lambda intervals, x: any(i.contains(x) for i in intervals)
    if answer and all(inside(expected, x) for x in probes if inside(answer, x)):
        return "incorrect", ("missing_root",), "解集还少了一部分，检查另一侧的区间。"
    if endpoints and endpoints <= roots and len(answer) and expected:
        open_closed = normalize([Interval(i.lo, not i.lo_closed if i.lo in roots else i.lo_closed,
                                          i.hi, not i.hi_closed if i.hi in roots else i.hi_closed) for i in answer])
        if open_closed == expected:
            return "incorrect", ("wrong_value",), "边界点是否包含和原不等号不一致。"
        return "incorrect", ("sign_flip",), "边界找对了，但取的区间方向和开口方向、不等号不一致。"
    return "incorrect", ("wrong_value",), "这个解集的边界没有通过原题检验。"


__all__ = ["Interval", "STRATEGY_NAME", "assess", "parse_answer", "render", "solution_set", "solve", "verify"]
