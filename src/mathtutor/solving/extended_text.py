"""Closed reductions onto arithmetic or linear problems.

A sentence matches only when every number the reduction needs is present.
Anything else returns None, and the existing recovery scaffold stays in charge.
"""
from __future__ import annotations

import re

from mathtutor.solving import nodes as n
from mathtutor.solving.parser import ParsedProblem, ParseOutcome, normalize_math_problem_text

_HYPOTENUSE = {(3, 4): 5, (4, 3): 5, (6, 8): 10, (8, 6): 10, (5, 12): 13, (12, 5): 13}
_RELATIONS = (
    (">=", "ge", r"\ge"),
    ("<=", "le", r"\le"),
    ("≥", "ge", r"\ge"),
    ("≤", "le", r"\le"),
    (">", "gt", ">"),
    ("<", "lt", "<"),
)


def compile_extended(text: str, parse_core) -> ParseOutcome | None:
    raw = " ".join(str(text or "").strip().split()).strip("？?。")
    if not raw or len(raw) > 80:
        return None
    matched = _compile_template(raw)
    if matched is None:
        return None
    expression, family, display = matched
    outcome = parse_core(expression)
    if outcome.kind != "parsed" or outcome.problem is None or outcome.problem.problem_type != family:
        return ParseOutcome.unsupported("这句话里的数量关系还不能按步骤核验")
    problem = outcome.problem
    if display:
        problem = ParsedProblem(problem.problem_type, problem.ast, problem.normalized_ast, display, problem.variable)
    return ParseOutcome.ok(problem)


def parse_inequality_text(text: str, parse_core) -> ParseOutcome | None:
    compact = normalize_math_problem_text(text).replace("＞", ">").replace("＜", "<")
    if not any(symbol in compact for symbol, _code, _latex in _RELATIONS):
        return None
    residual = compact.replace(">=", "").replace("<=", "")
    if "=" in residual:
        return ParseOutcome.unsupported("不等式里不再同时写等式")
    op = code = latex = None
    left = right = ""
    for symbol, relation, rendered in _RELATIONS:
        if symbol in compact:
            left, right = compact.split(symbol, 1)
            if symbol in right or any(other in f"{left}{right}" for other, _relation, _rendered in _RELATIONS):
                return ParseOutcome.unsupported("只支持一个一次不等式")
            op, code, latex = symbol, relation, rendered
            break
    if op is None or not left.strip() or not right.strip():
        return ParseOutcome.unsupported("不等式两边都要有式子")
    outcome = parse_core(f"{left.strip()}={right.strip()}")
    if outcome.kind != "parsed" or outcome.problem is None or outcome.problem.problem_type not in {"linear", "quadratic"}:
        return ParseOutcome.unsupported("目前只逐步核验一元一次和一元二次不等式")
    parsed = outcome.problem
    family = "linear_inequality" if parsed.problem_type == "linear" else "quadratic_inequality"
    if family == "quadratic_inequality":
        from mathtutor.solving import quadratic_inequality as qi
        try:
            qi.rational_roots(*qi.coefficients(parsed.ast, parsed.variable))
        except n.MathDomainError as exc:
            return ParseOutcome.unsupported(str(exc))
    wrapper = {"kind": "inequality", "relation": code, "variable": parsed.variable, "equation": parsed.normalized_ast}
    display = n.to_latex(parsed.ast).replace("=", latex or op, 1)
    return ParseOutcome.ok(ParsedProblem(family, parsed.ast, wrapper, display, parsed.variable, code))


def _compile_template(text: str):
    found = re.search(r"一个数的(\d+)倍加(\d+)等于(\d+)", text)
    if found:
        return f"{found.group(1)}*x+{found.group(2)}={found.group(3)}", "linear", None
    found = re.search(r"一个数的(\d+)倍减(\d+)等于(\d+)", text)
    if found:
        return f"{found.group(1)}*x-{found.group(2)}={found.group(3)}", "linear", None
    found = re.search(r"买了?(\d+)支.*?每支(\d+)元.*?(?:一共|共)", text)
    if found and re.search(r"多少|几", text):
        return f"{found.group(1)}*{found.group(2)}", "arithmetic", None
    found = re.search(r"买了?(\d+)支.*?又花了?(\d+)元.*?(?:一共|共)(?:花了?)?(\d+)元", text)
    if found:
        return f"{found.group(1)}*x+{found.group(2)}={found.group(3)}", "linear", None
    found = re.search(r"三角形.*?(\d+)\s*度.*?(\d+)\s*度.*?第三", text)
    if found:
        return f"180-{found.group(1)}-{found.group(2)}", "arithmetic", None
    found = re.search(r"长方形.*?长(?:为|是)?(\d+).*?宽(?:为|是)?(\d+).*?(周长|面积)", text)
    if found:
        left, right, kind = found.groups()
        expression = f"2*({left}+{right})" if kind == "周长" else f"{left}*{right}"
        return expression, "arithmetic", None
    found = re.search(r"正方形.*?边长(?:为|是)?(\d+).*?(周长|面积)", text)
    if found:
        side, kind = found.groups()
        expression = f"4*{side}" if kind == "周长" else f"{side}*{side}"
        return expression, "arithmetic", None
    found = re.search(r"直角边.*?(\d+).*?(\d+).*?斜边", text)
    if found:
        pair = (int(found.group(1)), int(found.group(2)))
        length = _HYPOTENUSE.get(pair)
        if length is None:
            return None
        return str(length), "arithmetic", rf"\sqrt{{{pair[0]}^{{2}}+{pair[1]}^{{2}}}}"
    return None
