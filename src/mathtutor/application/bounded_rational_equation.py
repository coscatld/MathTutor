"""Exact answers for a bounded rational equation, with its original domain intact."""
from __future__ import annotations

import re
from fractions import Fraction

from mathtutor.application.input_normalizer import normalize_input
from mathtutor.application.math_verification import ExpressionNotVerifiable, verified_problem
from mathtutor.domain.hashing import content_hash
from mathtutor.solving import nodes as n
from mathtutor.solving.budget import ParseBudget, check_integer, fraction_add, fraction_mul, fraction_div
from mathtutor.solving.parser import AmbiguityError, ParseError, UnsupportedError, parse_equation_with_domain
from mathtutor.solving.quadratic_inequality import Interval, normalize, rational_roots, render, to_payload

_NUMBER = r"[-+]?\d{1,8}(?:/\d{1,8}|\.\d{1,8})?"
_CONDITION = re.compile(rf"(?:且|并且|其中|条件(?:为)?|where|and|given)?\s*([A-Za-z])\s*(≠|!=|<=|>=|≤|≥|<|>|=)\s*({_NUMBER})", re.I)
_ALL = (Interval(None, False, None, False),)


def _bounded(poly):
    result = {degree: value for degree, value in poly.items() if value}
    if max(result, default=0) > 4:
        raise ValueError("rational_polynomial_degree_budget")
    for value in result.values():
        check_integer(value.numerator)
        check_integer(value.denominator)
    return result


def _add(left, right, sign=1):
    result = dict(left)
    for degree, value in right.items():
        result[degree] = fraction_add(result.get(degree, Fraction(0)), sign * value)
    return _bounded(result)


def _mul(left, right):
    result = {}
    for a, ca in left.items():
        for b, cb in right.items():
            if a + b > 4:
                raise ValueError("rational_polynomial_degree_budget")
            result[a + b] = fraction_add(result.get(a + b, Fraction(0)), fraction_mul(ca, cb))
    return _bounded(result)


def _fraction(node, variable):
    one = {0: Fraction(1)}
    if isinstance(node, n.Num):
        return _bounded({0: node.value.to_fraction()}), one
    if isinstance(node, n.Var) and node.name == variable:
        return {1: Fraction(1)}, one
    if isinstance(node, n.Add):
        num, den = {}, one
        for term in node.terms:
            a, b = _fraction(term, variable)
            num, den = _add(_mul(num, b), _mul(a, den)), _mul(den, b)
        return num, den
    if isinstance(node, n.Mul):
        num, den = one, one
        for term in node.factors:
            a, b = _fraction(term, variable)
            num, den = _mul(num, a), _mul(den, b)
        return num, den
    if isinstance(node, n.Div):
        a, b = _fraction(node.num, variable)
        c, d = _fraction(node.den, variable)
        if not c:
            raise ValueError("empty_denominator_domain")
        return _mul(a, d), _mul(b, c)
    if isinstance(node, n.Pow) and 2 <= node.exp <= 4:
        a, b = _fraction(node.base, variable)
        num, den = one, one
        for _ in range(node.exp):
            num, den = _mul(num, a), _mul(den, b)
        return num, den
    raise ValueError("unsupported_rational_expression")


def _evaluate(node, variable, value):
    if isinstance(node, n.Num):
        return node.value.to_fraction()
    if isinstance(node, n.Var) and node.name == variable:
        return value
    if isinstance(node, n.Add):
        result = Fraction(0)
        for term in node.terms:
            result = fraction_add(result, _evaluate(term, variable, value))
        return result
    if isinstance(node, n.Mul):
        result = Fraction(1)
        for factor in node.factors:
            result = fraction_mul(result, _evaluate(factor, variable, value))
        return result
    if isinstance(node, n.Div):
        return fraction_div(_evaluate(node.num, variable, value), _evaluate(node.den, variable, value))
    if isinstance(node, n.Pow) and 2 <= node.exp <= 4:
        result = Fraction(1)
        for _ in range(node.exp):
            result = fraction_mul(result, _evaluate(node.base, variable, value))
        return result
    raise ValueError("unsupported_substitution")


def _roots(poly):
    if max(poly, default=0) > 2:
        raise ValueError("cleared_equation_degree_budget")
    if poly.get(2):
        return rational_roots(poly[2], poly.get(1, Fraction(0)), poly.get(0, Fraction(0)))
    if poly.get(1):
        return (fraction_div(-poly.get(0, Fraction(0)), poly[1]),)
    return ()


def _intersect(left, right):
    result = []
    for a in left:
        for b in right:
            lo = b.lo if a.lo is None else a.lo if b.lo is None else max(a.lo, b.lo)
            hi = b.hi if a.hi is None else a.hi if b.hi is None else min(a.hi, b.hi)
            lo_closed = lo is not None and a.contains(lo) and b.contains(lo)
            hi_closed = hi is not None and a.contains(hi) and b.contains(hi)
            if lo is None or hi is None or lo < hi or (lo == hi and lo_closed and hi_closed):
                result.append(Interval(lo, lo_closed, hi, hi_closed))
    return normalize(result)


def _condition_interval(relation, value):
    if relation in {"≠", "!="}:
        return (Interval(None, False, value, False), Interval(value, False, None, False))
    if relation in {">", ">=", "≥"}:
        return (Interval(value, relation != ">", None, False),)
    if relation in {"<", "<=", "≤"}:
        return (Interval(None, False, value, relation != "<"),)
    return (Interval(value, True, value, True),)


def _polynomial_text(poly, variable):
    terms = []
    for degree, value in sorted(poly.items()):
        power = "" if degree == 0 else f"*{variable}" if degree == 1 else f"*{variable}^{degree}"
        terms.append(f"({value}){power}")
    return "+".join(terms) or "0"


async def rational_equation_receipt(text: str, backend) -> dict | None:
    """Return a checked answer, or None without weakening the ordinary boundary."""
    if len(text) > 600 or not re.search(r"/|\\frac\b", text):
        return None
    try:
        source = normalize_input(text).normalized.strip().rstrip("。?.")
        parts = re.split(r"[，,；;]\s*", source)
        equation, conditions = parts[0], parts[1:]
        if len(conditions) > 4:
            return None
        ast, divisors = parse_equation_with_domain(equation, budget=ParseBudget(
            max_tokens=96, max_depth=16, max_literal_digits=8, max_text_chars=400))
        variables = set(n.variables(ast)).union(*(n.variables(node) for node in divisors))
        if len(variables) != 1 or not any(n.variables(node) for node in divisors) or len(divisors) > 8:
            return None
        variable = variables.pop()
        explicit_domain = _ALL
        for clause in conditions:
            match = _CONDITION.fullmatch(clause.strip())
            if match is None or match[1] != variable:
                return None
            explicit_domain = _intersect(explicit_domain, _condition_interval(match[2], Fraction(match[3])))
        left_num, left_den = _fraction(ast.lhs, variable)
        right_num, right_den = _fraction(ast.rhs, variable)
        cleared = _add(_mul(left_num, right_den), _mul(right_num, left_den), -1)
        roots = _roots(cleared)
        forbidden = set()
        for node in divisors:
            numerator, _ = _fraction(node, variable)
            if not numerator:
                return None
            forbidden.update(_roots(numerator))
        domain = explicit_domain
        for point in sorted(forbidden):
            domain = _intersect(domain, _condition_interval("≠", point))
        check = {"status": "verified", "kind": "exact_zero_polynomial" if not cleared else "constant_nonzero"}
        if max(cleared, default=0) > 0:
            problem, candidate = await verified_problem(backend, _polynomial_text(cleared, variable) + "=0")
            proposed_roots = candidate.final_answer.get("roots", ())
            actual_roots = tuple(sorted(Fraction(root["value"]["n"], root["value"]["d"])
                                        for root in proposed_roots if root.get("kind") == "rational"))
            if len(actual_roots) != len(proposed_roots) or tuple(sorted(roots)) != actual_roots:
                return None
            check = {"status": "verified", "kind": problem.problem_type, "problem_hash": problem.content_hash,
                     "candidate_hash": candidate.payload_hash}
        accepted, excluded = [], []
        for root in roots:
            if root in forbidden:
                excluded.append({"root": str(root), "reason": "zero_denominator"})
            elif not any(interval.contains(root) for interval in explicit_domain):
                excluded.append({"root": str(root), "reason": "explicit_condition"})
            elif (all(_evaluate(node, variable, root) != 0 for node in divisors)
                  and _evaluate(ast.lhs, variable, root) == _evaluate(ast.rhs, variable, root)):
                accepted.append(root)
            else:
                return None
        solution = domain if not cleared else tuple(Interval(root, True, root, True) for root in accepted)
        receipt = {"status": "verified", "scope": "bounded_rational_equation", "variable": variable,
            "original_ast": n.to_dict(ast), "denominators": [n.to_dict(node) for node in divisors],
            "explicit_conditions": conditions, "domain": to_payload(domain), "domain_latex": render(domain, variable),
            "cleared_coefficients": {str(k): str(v) for k, v in cleared.items()},
            "cleared_latex": n.poly_to_latex(cleared, variable) or "0", "polynomial_verification": check,
            "candidate_roots": [str(root) for root in roots], "excluded_roots": excluded,
            "solution_set": to_payload(solution), "answer": render(solution, variable)}
        receipt["receipt_hash"] = content_hash(receipt)
        return receipt
    except (ParseError, AmbiguityError, UnsupportedError, n.MathDomainError, n.MathComplexityError,
            ExpressionNotVerifiable, ArithmeticError, ValueError, TypeError, KeyError, TimeoutError):
        return None


def render_rational_receipt(receipt: dict) -> str:
    lines = [f"定义域与给定条件：\\({receipt['domain_latex']}\\)。",
             f"在这个范围内通分，原方程等价于 \\({receipt['cleared_latex']}=0\\)。"]
    if not receipt["cleared_coefficients"]:
        lines.append("通分后的差恒为零，因此原方程在上述定义域内恒成立。")
    elif receipt["candidate_roots"]:
        lines.append("候选根：" + "，".join(f"{receipt['variable']}={root}" for root in receipt["candidate_roots"]) + "。")
    for excluded in receipt["excluded_roots"]:
        reason = "使原式的分母为零" if excluded["reason"] == "zero_denominator" else "不满足给定条件"
        lines.append(f"{receipt['variable']}={excluded['root']} {reason}，舍去。")
    answer = "无解" if receipt["answer"] == "无解" else f"\\({receipt['answer']}\\)"
    lines.append(f"已核验结论：{answer}。")
    return "\n\n".join(lines)
