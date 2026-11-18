"""Exact counterexamples for bounded radical inequalities; never a proof of a solution set."""
from __future__ import annotations

import re
from fractions import Fraction

from mathtutor.solving import nodes
from mathtutor.solving.budget import ParseBudget
from mathtutor.solving.parser import parse_problem
from mathtutor.solving.quadratic_inequality import parse_answer, rational_roots

_RADICAL = r"(?:√\s*\(([^()]{1,60})\)|\\sqrt\{([^{}]{1,60})\}|sqrt\(([^()]{1,60})\)|√\s*([A-Za-z]|\d+))"
_INEQUALITY = re.compile(_RADICAL + r"\s*(<=|>=|≤|≥|<|>)\s*([0-9A-Za-z+\-−*/^(). ]{1,80})")
_FINAL = re.compile(r"(?:最终(?:结果)?|解集(?:为|是)|所有解(?:为|是)|solution\s+set\s*(?:is|:))\s*[:：]?\s*"
                    r"([0-9A-Za-z+\-−/ .<>=≤≥或∪]{1,100})", re.I)


def _polynomial(expression, variable):
    parsed = parse_problem(expression, budget=ParseBudget(max_tokens=48, max_depth=10,
        max_literal_digits=8, max_text_chars=120))
    if not parsed.problem or parsed.problem.problem_type not in {"arithmetic", "polynomial"}:
        return None
    if nodes.variables(parsed.problem.ast) - {variable}:
        return None
    values = nodes.poly_coeffs(parsed.problem.ast, variable)
    return values if values is not None and max(values, default=0) <= 2 else None


def _at(polynomial, point):
    return sum((coefficient * point ** degree for degree, coefficient in polynomial.items()), Fraction(0))


def _condition_sets(conditions, variable):
    result = []
    for clause in re.split(r"[；;。\n]", conditions):
        if re.search(r"平方步骤|平方操作|两侧同时平方|两边平方", clause):
            continue
        pattern = rf"{re.escape(variable)}\s*(?:<=|>=|≤|≥|<|>)\s*[-+]?\d+(?:/\d+|\.\d+)?(?![0-9./])"
        matches = re.findall(pattern, clause)
        if re.search(r"整数|正整数|自然数|偶数|奇数|参数|或|\b(?:or|integer|natural|even|odd|parameter)\b", clause, re.I):
            return None
        if re.search(r"限定|假设|给定|已知|只能|仅在|仅考虑|正数|负数|\b(?:only|positive|negative|assuming|given|restricted)\b", clause, re.I) and not matches:
            return None
        if re.search(r"[<>=≤≥≠]", re.sub(pattern, "", clause)):
            return None
        for match in matches:
            parsed = parse_answer(match, variable)
            if parsed is None:
                return None
            result.append(parsed)
    return result


def solution_counterexample(expression: str, answer: str, conditions: str = "") -> dict | None:
    if len(expression) > 200 or len(answer) > 120 or len(conditions) > 500:
        return None
    match = _INEQUALITY.fullmatch(expression.strip().replace("−", "-"))
    if not match:
        return None
    radical = next(value for value in match.groups()[:4] if value is not None)
    relation, right = match.group(5), match.group(6).strip()
    variables = set(re.findall(r"[A-Za-z]", radical + right))
    if len(variables) != 1:
        return None
    variable = variables.pop()
    try:
        intervals = parse_answer(answer, variable)
        domain = _condition_sets(conditions, variable)
        radicand, rhs = _polynomial(radical, variable), _polynomial(right, variable)
        if intervals is None or domain is None or radicand is None or rhs is None or len(intervals) > 4:
            return None
        points = {Fraction(0)}
        for interval in intervals:
            points.update(p for p in (interval.lo, interval.hi) if p is not None)
        try:
            if radicand.get(2):
                points.update(rational_roots(radicand.get(2, 0), radicand.get(1, 0), radicand.get(0, 0)))
            elif radicand.get(1):
                points.add(-radicand.get(0, 0) / radicand[1])
        except (ValueError, ArithmeticError):
            pass
        if any(abs(p) > 1000000 or p.denominator > 1000000 for p in points):
            return None
        points |= {p + direction for p in tuple(points) for direction in (-1, 1)}
        for point in sorted(points):
            if not all(any(interval.contains(point) for interval in bounds) for bounds in domain):
                continue
            p, q = _at(radicand, point), _at(rhs, point)
            if p < 0:
                actual = False
            else:
                comparison = 1 if q < 0 else (p > q * q) - (p < q * q)
                actual = {"<": comparison < 0, "<=": comparison <= 0, "≤": comparison <= 0,
                          ">": comparison > 0, ">=": comparison >= 0, "≥": comparison >= 0}[relation]
            claimed = any(interval.contains(point) for interval in intervals)
            if actual != claimed:
                return {"expression": expression, "answer": answer, "variable": variable,
                        "witness": str(point), "original_satisfied": actual, "answer_contains": claimed,
                        "status": "refuted", "reason": "exact_radical_solution_counterexample"}
    except (ValueError, ArithmeticError, TypeError):
        return None
    return None


def source_solution_counterexample(text: str, conditions: str = "") -> dict | None:
    if len(text) > 2000:
        return None
    first = _INEQUALITY.search(text)
    finals = list(_FINAL.finditer(text))
    if first is None or not finals or first.start() >= finals[-1].start():
        return None
    prefix = text[max(0, first.start() - 20):first.start()]
    if not re.search(r"不等式|inequality", prefix, re.I):
        return None
    final = finals[-1]
    context = text[max(first.end(), final.start() - 20):final.start()]
    suffix = text[final.end():final.end() + 20]
    if re.search(r"部分|某些|例如|比如|候选|错误|不正确|不成立|不对|\b(?:partial|example|candidate|incorrect|wrong|invalid|false)\b", context, re.I) or re.match(
            r"\s*(?:(?:是|这个结论是|这一结论是)?(?:错误|不正确|不成立|不对)|(?:is\s+)?(?:incorrect|wrong|invalid|false|not\s+correct)\b)", suffix, re.I):
        return None
    return solution_counterexample(first.group().strip(), final[1].strip(" ."),
                                   text[:first.start()] + ";" + conditions)


__all__ = ["solution_counterexample", "source_solution_counterexample"]
