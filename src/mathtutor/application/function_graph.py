"""Server-computed function graphs.

The model never supplies coordinates. A graph comes either from an expression
the student typed (read by a small whitelist parser, never ``eval``) or from
the verified current problem. Points and marked coordinates are computed here
and sent to the client as a ``mathtutor-graph`` fenced block on a
``SHOW_GRAPH`` message; the client only draws them.

Zeros and intersections answer the open problem, so callers pass
``reveal=False`` until it is solved or its solution was shown.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Callable

GRAPH_ACTION = "SHOW_GRAPH"
GRAPH_FENCE = "mathtutor-graph"
GRAPHABLE_TYPES = frozenset({"linear", "quadratic", "polynomial", "linear_system", "linear_inequality",
                             "quadratic_inequality"})

MAX_EXPRESSION_CHARS = 120
MAX_DEPTH = 40
SAMPLES = 241
MAX_MARKS = 8

_GRAPH_REQUEST = re.compile(r"(?:画|作|绘制|绘|看看|看一下|显示|给我).{0,12}(?:图像|图象|函数图|图形|曲线|图)|(?:图像|图象)(?:是什么|长什么样|怎么画)|画(?:出|一下)?\s*(?:y\s*=|f\s*\(\s*x\s*\)|函数)|(?:^|[.!?\n])\s*(?:please\s+|(?:can|could|would)\s+you\s+)?(?:plot|graph)\b|\b(?:draw|show)\s+(?:me\s+)?(?:the\s+|a\s+)?(?:graph|plot|curve)\b", re.I)
_BLOCK = re.compile(r"```" + GRAPH_FENCE + r"\n(.*?)\n```", re.S)
_SCENE_BLOCK = re.compile(r"```mathtutor-scene\n(.*?)\n```", re.S)
# 「画出 x^2/4+y^2/3=1」: a draw verb followed by an equation or inequality in x, y or r.
_DRAW_RELATION = re.compile(r"(?:画|绘制|绘出|作出)(?!了)[^。？?\n]{0,80}?(?:[xyθ][^。？?\n]{0,80}?[=<>≤≥＝]|[=<>≤≥＝][^。？?\n]{0,80}?[xyθ]|(?<![A-Za-z])r\s*[=＝])")
_VISUAL = re.compile(r"数形结合|可视化|动画|演示|动点|轨迹")
_SHAPES = r"椭圆|抛物线|双曲线|圆|三角形|四边形|正方形|矩形|直线|线段|切线|焦点|动点|轨迹|向量|正弦|余弦|正切|函数|曲线|坐标|区域|不等式"
_MATH_CONTENT = re.compile(r"[A-Za-z0-9]|" + _SHAPES)
_SOLVE_ONLY = re.compile(r"怎么解|求解|解方程|解不等式|计算|化简")


class GraphInputError(ValueError):
    """The text names no function this module can draw."""


_DRAW_GEOMETRY = re.compile(r"(?:画出|画一下|画|绘制|作出|演示)[^。？?]{0,40}?(?:(?<![A-Za-z])[A-Z]\s*[(（][^()（）]*[,，]|三角形\s*[A-Z]{3}|四边形\s*[A-Z]{4}|线段\s*[A-Z]{2}|向量\s*[A-Z]{2})")


def is_graph_request(text: str) -> bool:
    text = str(text or "")
    if _GRAPH_REQUEST.search(text) or _DRAW_RELATION.search(text):
        return True
    if _DRAW_GEOMETRY.search(text):
        return True  # 画出三角形 ABC，A(0,0)…; 画出点 P(…)
    if _SOLVE_ONLY.search(text):
        return False
    if re.search(r"(?:画|绘制|绘出|作出)(?!了)[^。？?\n]{0,30}(?:" + _SHAPES + r")", text):
        return True
    if _VISUAL.search(text) and _MATH_CONTENT.search(_VISUAL.sub("", text)):
        return True
    return "运动" in text and bool(re.search(_SHAPES.replace("|函数", "").replace("|坐标", ""), text))


_CHOOSE_EXAMPLE = re.compile(
    r"(?:都(?:可以|行|好)|随便(?:一个)?|任意(?:一个)?|任选(?:一个)?|你(?:来)?(?:定|选|决定)|"
    r"你看着(?:办|画)|选个(?:简单的|例子)|(?:画|开始)吧|可以|好(?:的|啊)?|行)[。！!，,\s]*")


def resolve_graph_request(text: str, history: tuple[dict, ...] = ()) -> str | None:
    """Keep a short delegation attached to the immediately preceding request.

    History is persisted and can include the current student message. Never
    search past a different student topic, or redraw an already delivered graph.
    """
    current = str(text or "").strip()
    if is_graph_request(current):
        return current
    if not _CHOOSE_EXAMPLE.fullmatch(current):
        return None
    previous = list(history)
    if previous and previous[-1].get("role") == "student" and previous[-1].get("content", "").strip() == current:
        previous.pop()
    for item in reversed(previous[-20:]):
        if item.get("role") == "tutor" and item.get("action") in {GRAPH_ACTION, "TUTOR_CHAT_FIGURE"}:
            return None
        if item.get("role") == "student":
            request = str(item.get("content", ""))
            if _CHOOSE_EXAMPLE.fullmatch(request.strip()):
                continue
            return request if is_graph_request(request) else None
    return None


# ---------------------------------------------------------------------------
# Whitelist expression parser (student-typed functions of x)
# ---------------------------------------------------------------------------

_FUNCTIONS: dict[str, Callable[[float], float]] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "sqrt": math.sqrt, "abs": abs,
    "ln": math.log, "log": math.log10, "exp": math.exp,
}
_CONSTANTS = {"pi": math.pi, "π": math.pi, "e": math.e}
_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)|(sqrt|sin|cos|tan|abs|ln|log|exp|pi|π|e|x)|([-+*/^()|]))")
_SUPERSCRIPTS = {"²": "^2", "³": "^3"}
_REPLACEMENTS = {"×": "*", "·": "*", "÷": "/", "−": "-", "–": "-", "（": "(", "）": ")", "√": "sqrt", "Ｘ": "x", "X": "x"}


def _tokens(source: str) -> list[str]:
    text = source
    for old, new in {**_SUPERSCRIPTS, **_REPLACEMENTS}.items():
        text = text.replace(old, new)
    text = re.sub(r"\\(?:left|right)", "", text).replace("\\cdot", "*").replace("\\times", "*")
    text = re.sub(r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"((\1)/(\2))", text)
    text = re.sub(r"\\sqrt\{([^{}]*)\}", r"sqrt(\1)", text)
    text = re.sub(r"\\(sin|cos|tan|ln|log|exp|pi)", r"\1", text).replace("{", "(").replace("}", ")")
    tokens, pos = [], 0
    text = text.strip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise GraphInputError(f"看不懂「{text[pos:pos + 6]}」，目前只支持关于 x 的函数")
        tokens.append(match.group(0).strip())
        pos = match.end()
    return tokens


class _Parser:
    """Pratt parser over the whitelist tokens; output is a nested tuple tree."""

    def __init__(self, tokens: list[str]):
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> str | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected: str | None = None) -> str:
        token = self.peek()
        if token is None or (expected is not None and token != expected):
            raise GraphInputError("式子不完整，请检查括号和运算符")
        self.pos += 1
        return token

    def parse(self):
        tree = self.expr(0)
        if self.peek() is not None:
            raise GraphInputError("式子里有多余的部分")
        return tree

    def expr(self, depth):
        if depth > MAX_DEPTH:
            raise GraphInputError("式子太复杂了")
        node = self.term(depth)
        while self.peek() in {"+", "-"}:
            node = (self.take(), node, self.term(depth))
        return node

    def term(self, depth):
        node = self.unary(depth)
        while True:
            token = self.peek()
            if token in {"*", "/"}:
                node = (self.take(), node, self.unary(depth))
            elif token is not None and token not in {"+", "-", ")", "^", "|"} or token == "|" and self._opens_bar():
                node = ("*", node, self.unary(depth))  # implicit multiplication: 2x, x(x+1)
            else:
                return node

    def _opens_bar(self) -> bool:
        # |x| juxtaposed after a factor: 2|x| — treat as a new absolute value.
        return self.tokens[:self.pos].count("|") % 2 == 0

    def unary(self, depth):
        if self.peek() in {"+", "-"}:
            sign = self.take()
            operand = self.unary(depth + 1)
            return ("neg", operand) if sign == "-" else operand
        return self.power(depth)

    def power(self, depth):
        base = self.primary(depth)
        if self.peek() == "^":
            self.take()
            return ("^", base, self.unary(depth + 1))
        return base

    def primary(self, depth):
        token = self.take()
        if token == "(":
            node = self.expr(depth + 1)
            self.take(")")
            return node
        if token == "|":
            node = self.expr(depth + 1)
            self.take("|")
            return ("abs", node)
        if token in _FUNCTIONS:
            if self.peek() == "(":
                return (token, self.primary(depth + 1))
            return (token, self.power(depth + 1))
        if token == "x":
            return ("x",)
        if token in _CONSTANTS:
            return ("const", _CONSTANTS[token])
        try:
            return ("const", float(token))
        except ValueError:
            raise GraphInputError("式子不完整，请检查括号和运算符") from None


def _evaluate(node, x: float) -> float | None:
    try:
        value = _eval(node, x)
    except (ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None
    return value if isinstance(value, float) and math.isfinite(value) else None


def _eval(node, x: float) -> float:
    kind = node[0]
    if kind == "x":
        return float(x)
    if kind == "const":
        return float(node[1])
    if kind == "neg":
        return -_eval(node[1], x)
    if kind in _FUNCTIONS:
        return float(_FUNCTIONS[kind](_eval(node[1], x)))
    left, right = _eval(node[1], x), _eval(node[2], x)
    if kind == "+":
        return left + right
    if kind == "-":
        return left - right
    if kind == "*":
        return left * right
    if kind == "/":
        return left / right
    if kind == "^":
        if left < 0 and right != int(right):
            fraction = Fraction(right).limit_denominator(9)
            if fraction.denominator % 2 == 1 and math.isclose(float(fraction), right):
                return -((-left) ** right)  # odd root of a negative number
            raise ValueError("even root of a negative number")
        return float(left ** right)
    raise ValueError(kind)


def _display(node) -> str:
    kind = node[0]
    if kind == "x":
        return "x"
    if kind == "const":
        value = node[1]
        return "π" if value == math.pi else "e" if value == math.e else _number(value)
    if kind == "neg":
        return f"-{_wrap(node[1], 2)}"
    if kind in _FUNCTIONS:
        return f"|{_display(node[1])}|" if kind == "abs" else f"{kind}({_display(node[1])})"
    if kind == "^":
        return f"{_wrap(node[1], 3)}^{_wrap(node[2], 3)}"
    if kind == "*" and node[2][0] not in {"const"} and node[1][0] == "const":
        return f"{_wrap(node[1], 2)}{_wrap(node[2], 2)}"
    level = {"+": 1, "-": 1, "*": 2, "/": 2}[kind]
    return f"{_wrap(node[1], level)} {kind} {_wrap(node[2], level + (kind in '-/'))}"


def _wrap(node, level: int) -> str:
    own = {"+": 1, "-": 1, "*": 2, "/": 2, "neg": 2, "^": 3}.get(node[0], 4)
    text = _display(node)
    return f"({text})" if own < level else text


def parse_function(source: str):
    """Return ``(display, evaluate)`` for one function of x typed by a student."""
    source = str(source or "").strip().rstrip("。.，,")
    if not source or len(source) > MAX_EXPRESSION_CHARS:
        raise GraphInputError("请写出要画的函数，例如 y = x^2 - 2x - 3")
    tree = _Parser(_tokens(source)).parse()
    return _display(tree), lambda x, tree=tree: _evaluate(tree, x)


def extract_function_text(text: str) -> str:
    """The expression after ``y =`` / ``f(x) =``; empty when none was typed."""
    raw = str(text or "")
    match = re.search(r"(?:(?<![A-Za-z])y|f\s*[(（]\s*x\s*[)）])\s*[=＝]\s*([^，,。；;：:\n]+)", raw)
    if match:
        expression = match.group(1)
    else:
        match = re.search(r"(?:画|作|绘制|绘)(?:出|一下)?(?:函数)?\s*([-+*/^()|.\dxX²³√π\s]+?)\s*(?:的|$)", raw)
        if not match or "x" not in match.group(1).lower():
            return ""
        expression = match.group(1)
    expression = re.split(r"的|图像|图象|图形|曲线|在|，|。", expression)[0]
    return expression.strip()


# ---------------------------------------------------------------------------
# Sampling and marked points
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Curve:
    label: str
    evaluate: Callable[[float], float | None]


def _number(value: float) -> str:
    fraction = Fraction(value).limit_denominator(12)
    if abs(float(fraction) - value) < 1e-9:
        if fraction.denominator == 1:
            return str(fraction.numerator)
        return f"{fraction.numerator}/{fraction.denominator}"
    return f"≈{value:.2f}".rstrip("0").rstrip(".")


def _point(x: float, y: float) -> str:
    return f"({_number(x)}, {_number(y)})"


def _snap(value: float) -> float:
    fraction = Fraction(value).limit_denominator(12)
    return float(fraction) if abs(float(fraction) - value) < 1e-7 else value


def _bisect(f, a: float, b: float) -> float | None:
    fa = f(a)
    for _ in range(80):
        middle = (a + b) / 2
        fm = f(middle)
        if fa is None or fm is None:
            return None
        if fm == 0 or b - a < 1e-12:
            return middle
        if (fa < 0) == (fm < 0):
            a, fa = middle, fm
        else:
            b = middle
    return (a + b) / 2


def _zeros(f, lo: float, hi: float, steps: int = 2000) -> list[float]:
    found: list[float] = []
    width = (hi - lo) / steps
    previous_x, previous_y = lo, f(lo)
    for index in range(1, steps + 1):
        x = lo + index * width
        y = f(x)
        if previous_y is not None and y is not None:
            if previous_y == 0:
                found.append(previous_x)
            elif (previous_y < 0) != (y < 0) and abs(y - previous_y) < 1e6:
                root = _bisect(f, previous_x, x)
                if root is not None and abs(f(root) or 0) < 1e-6:
                    found.append(root)
        previous_x, previous_y = x, y
    # Touching zeros (double roots) show up as tiny |f| minima.
    for x in _extrema(f, lo, hi, steps):
        y = f(x)
        if y is not None and abs(y) < 1e-9:
            found.append(x)
    unique: list[float] = []
    for root in sorted(_snap(r) for r in found):
        if not unique or abs(root - unique[-1]) > 1e-6:
            unique.append(root)
    return unique


def _extrema(f, lo: float, hi: float, steps: int = 2000) -> list[float]:
    width = (hi - lo) / steps
    values = [(lo + i * width, f(lo + i * width)) for i in range(steps + 1)]
    found = []
    for (_, a), (x, b), (_, c) in zip(values, values[1:], values[2:]):
        if None in (a, b, c):
            continue
        if (b < a and b <= c) or (b > a and b >= c):
            left, right = x - width, x + width
            for _ in range(60):  # golden-section-free ternary refinement
                m1, m2 = left + (right - left) / 3, right - (right - left) / 3
                y1, y2 = f(m1), f(m2)
                if y1 is None or y2 is None:
                    break
                if (y1 < y2) == (b < a):
                    right = m2
                else:
                    left = m1
            found.append(_snap((left + right) / 2))
    return found


def _ranges(curves: list[Curve], focus: list[float]) -> tuple[list[float], list[float]]:
    if focus:
        lo, hi = min(focus), max(focus)
        pad = max(3.0, (hi - lo) * 0.4)
        lo, hi = math.floor(lo - pad), math.ceil(hi + pad)
    else:
        lo, hi = -10.0, 10.0
    if hi - lo < 10:
        middle = (hi + lo) / 2
        lo, hi = math.floor(middle - 5), math.ceil(middle + 5)
    ys = sorted(y for curve in curves for i in range(SAMPLES)
                if (y := curve.evaluate(lo + (hi - lo) * i / (SAMPLES - 1))) is not None)
    if not ys:
        return [lo, hi], [-10.0, 10.0]
    low, high = ys[int(len(ys) * 0.05)], ys[int(len(ys) * 0.95) - (len(ys) > 1)]
    low, high = min(low, 0.0), max(high, 0.0)
    # Keep the key points (zeros, vertex, intercepts) readable rather than
    # letting steep arms stretch the axis; still within the sampled range.
    keys = [y for x in focus for curve in curves if (y := curve.evaluate(x)) is not None]
    if keys:
        key_low, key_high = min(*keys, 0.0), max(*keys, 0.0)
        reach = max(key_high - key_low, 4.0) * 1.5
        low, high = max(low, key_low - reach), min(high, key_high + reach)
    span = max(high - low, 4.0)
    return [lo, hi], [round(low - span * 0.12, 3), round(high + span * 0.12, 3)]


def _segments(curve: Curve, x_range: list[float], y_range: list[float]) -> list[list[list[float]]]:
    lo, hi = x_range
    span = y_range[1] - y_range[0]
    segments: list[list[list[float]]] = []
    current: list[list[float]] = []
    previous = None
    for index in range(SAMPLES):
        x = lo + (hi - lo) * index / (SAMPLES - 1)
        y = curve.evaluate(x)
        jump = previous is not None and y is not None and abs(y - previous) > span * 3
        if y is None or jump:
            if len(current) > 1:
                segments.append(current)
            current = []
        if y is not None:
            current.append([round(x, 4), round(max(min(y, y_range[1] + span), y_range[0] - span), 4)])
        previous = y
    if len(current) > 1:
        segments.append(current)
    return segments


def _block(spec: dict[str, Any]) -> str:
    return f"```{GRAPH_FENCE}\n{json.dumps(spec, ensure_ascii=False, separators=(',', ':'))}\n```"


def _pretty(text: str) -> str:
    return text.replace("^2", "²").replace("^3", "³")


def render_graph(curves: list[Curve], *, title: str, marks: list[dict], focus: list[float],
                 vertical: list[dict] | None = None, note: str = "") -> str:
    x_range, y_range = _ranges(curves, focus)
    title = _pretty(title)
    curves = [Curve(_pretty(c.label), c.evaluate) for c in curves]
    spec = {
        "v": 1, "title": title, "x_range": x_range, "y_range": y_range,
        "series": [{"label": c.label, "segments": _segments(c, x_range, y_range)} for c in curves],
        "vertical": vertical or [], "marks": marks[:MAX_MARKS], "note": note,
    }
    lines = [f"**函数图像**：{title}", "", _block(spec)]
    if note:
        lines += ["", note]
    return "\n".join(lines)


def graph_for_function(source: str, *, reveal: bool = True) -> str:
    display, f = parse_function(source)
    if not any(f(x / 4) is not None for x in range(-40, 41)):
        raise GraphInputError("这个函数在 -10 到 10 之间没有可画的点")
    zeros, extrema = _zeros(f, -50, 50), _extrema(f, -50, 50)
    if len(zeros) + len(extrema) > 6:
        # Periodic or wiggly: keep the default window and mark what is in it.
        zeros = [z for z in zeros if abs(z) <= 10][:4]
        extrema = [x for x in extrema if abs(x) <= 10][:4]
        focus = []
    else:
        focus = [*zeros, *extrema, 0.0]
    marks = []
    y0 = f(0)
    if y0 is not None and not (reveal and abs(y0) < 1e-12):
        marks.append({"x": 0, "y": round(_snap(y0), 6), "label": f"与 y 轴交点 {_point(0, _snap(y0))}"})
    if reveal:
        marks += [{"x": round(z, 6), "y": 0, "label": f"过原点 (0, 0)" if z == 0 else f"与 x 轴交点 {_point(z, 0)}"} for z in zeros[:4]]
    for x in extrema:
        y = f(x)
        if y is not None and (reveal or abs(y) > 1e-9):
            label = f"顶点 {_point(x, _snap(y))}" if len(extrema) == 1 else _point(x, _snap(y))
            marks.append({"x": round(x, 6), "y": round(_snap(y), 6), "label": label})
    note = "" if reveal else "当前题目还没完成，图上暂不标出与 x 轴的交点。"
    return render_graph([Curve(f"y = {display}", f)], title=f"y = {display}", marks=marks, focus=focus, note=note)


# ---------------------------------------------------------------------------
# Graphs of the verified current problem
# ---------------------------------------------------------------------------


def _ast_value(node: dict[str, Any], env: dict[str, Fraction]) -> Fraction:
    kind = node["kind"]
    if kind == "num":
        return Fraction(node["value"]["n"], node["value"]["d"])
    if kind == "var":
        return env[node["name"]]
    if kind == "add":
        return sum((_ast_value(t, env) for t in node["terms"]), Fraction(0))
    if kind == "mul":
        result = Fraction(1)
        for factor in node["factors"]:
            result *= _ast_value(factor, env)
        return result
    if kind == "pow":
        return _ast_value(node["base"], env) ** int(node["exp"])
    if kind == "div":
        return _ast_value(node["num"], env) / _ast_value(node["den"], env)
    raise GraphInputError(f"unsupported node {kind}")


def _variables(node) -> list[str]:
    if isinstance(node, dict):
        own = [str(node["name"])] if node.get("kind") == "var" else []
        return sorted({*own, *(v for value in node.values() for v in _variables(value))})
    if isinstance(node, list):
        return sorted({v for value in node for v in _variables(value)})
    return []


def _difference(equation: dict[str, Any]):
    return lambda env: _ast_value(equation["lhs"], env) - _ast_value(equation["rhs"], env)


def _float_curve(label: str, g: Callable[[Fraction], Fraction]) -> Curve:
    def evaluate(x: float) -> float | None:
        try:
            return float(g(Fraction(x)))
        except (ZeroDivisionError, OverflowError):
            return None
    return Curve(label, evaluate)


def _linear_label(slope: Fraction, intercept: Fraction, x: str, y: str) -> str:
    parts = []
    if slope:
        coefficient = "" if slope == 1 else "-" if slope == -1 else _number(float(slope))
        parts.append(f"{coefficient}{x}")
    if intercept or not parts:
        sign = "-" if intercept < 0 and parts else "+" if parts else ""
        parts.append(f"{sign} {_number(abs(float(intercept)) if parts else float(intercept))}".strip())
    return f"{y} = {' '.join(parts)}"


def _polynomial_label(g: Callable[[Fraction], Fraction], variable: str) -> str | None:
    """Plain-text ``y = ax^2 + bx + c`` when g is a polynomial of degree <= 2."""
    c, p1, m1 = g(Fraction(0)), g(Fraction(1)), g(Fraction(-1))
    a, b = (p1 + m1) / 2 - c, (p1 - m1) / 2
    if any(g(Fraction(t)) != a * t * t + b * t + c for t in (2, -3, 5)):
        return None
    terms = []
    for coefficient, power in ((a, 2), (b, 1), (c, 0)):
        if not coefficient:
            continue
        body = variable + ("^2" if power == 2 else "") if power else ""
        size = abs(coefficient)
        text = (_number(float(size)) if size != 1 or not power else "") + body
        terms.append(("-" if coefficient < 0 else "+", text))
    if not terms:
        return "y = 0"
    first_sign, first = terms[0]
    rest = " ".join(f"{sign} {text}" for sign, text in terms[1:])
    return f"y = {'-' if first_sign == '-' else ''}{first} {rest}".rstrip()


def graph_for_problem(problem_type: str, ast: dict[str, Any], *, reveal: bool) -> str:
    """Graph the verified current problem. ``reveal`` marks the answer points."""
    if problem_type not in GRAPHABLE_TYPES:
        raise GraphInputError("这道题是数值计算，没有可以画的函数图像")
    if problem_type == "linear_system":
        return _system_graph(ast, reveal=reveal)
    inequality = problem_type in {"linear_inequality", "quadratic_inequality"}
    equation = ast["equation"] if inequality else ast
    if problem_type == "polynomial":
        variable = (_variables(ast) or ["x"])[0]
        g = lambda value: _ast_value(ast, {variable: value})
        # The simplified form is this problem's answer: hide it until revealed.
        label = (_polynomial_label(g, variable) if reveal else None) or "y = 原式"
        curve = _float_curve(f"{label}（横轴 {variable}）", g)
        return _curve_graph(curve, variable, reveal=reveal, marks=reveal,
                            note=f"把原式看成关于 {variable} 的函数；化简前后的图像应当完全重合。")
    variable = (_variables(equation) or ["x"])[0]
    diff = _difference(equation)
    g = lambda value: diff({variable: value})
    note = ""
    if inequality:
        relation = {"gt": ">", "ge": "≥", "lt": "<", "le": "≤"}.get(ast.get("relation", ""), "")
        note = f"不等式成立的 {variable}，就是图像落在横轴{'上方' if relation in {'>', '≥'} else '下方'}的那一段。"
    else:
        note = "方程的解，就是图像与横轴交点的横坐标。"
    label = _polynomial_label(g, variable) or "y = 左边 − 右边"
    curve = _float_curve(f"{label}（横轴 {variable}）", g)
    return _curve_graph(curve, variable, reveal=reveal, note=note)


def _curve_graph(curve: Curve, variable: str, *, reveal: bool, note: str, marks: bool = True) -> str:
    f = curve.evaluate
    zeros = _zeros(f, -50, 50)
    extrema = _extrema(f, -50, 50)[:1]
    show_marks, marks = marks, []
    y0 = f(0)
    if y0 is not None and show_marks:
        marks.append({"x": 0, "y": round(_snap(y0), 6), "label": f"与纵轴交点 {_point(0, _snap(y0))}"})
    if reveal:
        marks += [{"x": round(z, 6), "y": 0, "label": f"与横轴交点 {_point(z, 0)}"} for z in zeros]
    for x in extrema if show_marks else ():
        y = f(x)
        if y is not None and (reveal or abs(y) > 1e-9):
            marks.append({"x": round(x, 6), "y": round(_snap(y), 6), "label": f"顶点 {_point(x, _snap(y))}"})
    if not reveal:
        note = (note + " 题目完成或看过答案后，图上会标出关键点。").strip()
    return render_graph([curve], title=curve.label, marks=marks, focus=[*zeros, *extrema, 0.0], note=note)


def _system_graph(ast: dict[str, Any], *, reveal: bool) -> str:
    equations = ast["equations"]
    names = _variables(ast)
    if len(names) != 2 or len(equations) != 2:
        raise GraphInputError("只能画两个未知数的方程组")
    x, y = names
    curves, vertical, lines = [], [], []
    for equation in equations:
        diff = _difference(equation)
        c0 = diff({x: Fraction(0), y: Fraction(0)})
        a = diff({x: Fraction(1), y: Fraction(0)}) - c0
        b = diff({x: Fraction(0), y: Fraction(1)}) - c0
        lines.append((a, b, -c0))
        if b == 0:
            if a == 0:
                raise GraphInputError("方程组里有一条不是直线的式子")
            vertical.append({"x": float(-c0 / a), "label": f"{x} = {_number(float(-c0 / a))}"})
            continue
        slope, intercept = -a / b, -c0 / b
        label = _linear_label(slope, intercept, x, y)
        curves.append(_float_curve(label, lambda value, s=slope, i=intercept: s * value + i))
    (a1, b1, c1), (a2, b2, c2) = lines
    det = a1 * b2 - a2 * b1
    focus = [0.0]
    marks = []
    if det:
        px, py = (c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det
        focus += [float(px)]
        if reveal:
            marks.append({"x": float(px), "y": float(py), "label": f"交点 {_point(float(px), float(py))}"})
    note = f"方程组的解，就是两条直线交点的坐标（横轴 {x}，纵轴 {y}）。"
    if not reveal:
        note += " 题目完成或看过答案后，图上会标出交点。"
    if not curves:
        curves.append(Curve("", lambda value: None))
    return render_graph(curves, title=f"方程组的两条直线（横轴 {x}，纵轴 {y}）", marks=marks,
                        focus=focus + [v["x"] for v in vertical], vertical=vertical, note=note)


def summarize_graph_blocks(text: str) -> str:
    """Replace graph and scene data with a short placeholder before model context."""
    def replace(match: re.Match) -> str:
        try:
            title = json.loads(match.group(1)).get("title", "")
        except (ValueError, AttributeError):
            title = ""
        return f"[已展示函数图像：{title}]"

    def replace_scene(match: re.Match) -> str:
        try:
            title = json.loads(match.group(1)).get("title", "")
        except (ValueError, AttributeError):
            title = ""
        return f"[已展示数形结合图：{title}]"
    return _SCENE_BLOCK.sub(replace_scene, _BLOCK.sub(replace, str(text or "")))


__all__ = [
    "GRAPH_ACTION", "GRAPH_FENCE", "GRAPHABLE_TYPES", "GraphInputError", "extract_function_text",
    "graph_for_function", "graph_for_problem", "is_graph_request", "resolve_graph_request", "parse_function", "summarize_graph_blocks",
]
