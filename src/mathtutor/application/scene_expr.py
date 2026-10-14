"""Whitelist compiler for Scene v2 expressions (see docs/SCENE_SPEC.md).

Strings come from the student or from a model-proposed scene definition.
Both are untrusted: a small tokenizer accepts only numbers, single-letter
variables, whitelisted function names, ``P.x`` point coordinates and the
geometric functions, and a Pratt parser builds the JSON AST the client
evaluates. Nothing is ever passed to ``eval``.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any

MAX_CHARS = 400
MAX_DEPTH = 40
MAX_NODES = 400

UNARY_FUNCTIONS = ("sin", "cos", "tan", "asin", "acos", "atan", "sqrt", "abs", "ln", "log", "exp", "floor", "ceil", "sign")
BINARY_FUNCTIONS = ("min", "max", "atan2")
GEO_FUNCTIONS = {"dist": (2, 2), "slope": (2, 2), "angle": (3, 3), "area": (3, 40), "mid_x": (2, 2), "mid_y": (2, 2)}
_CONSTANTS = {"pi": math.pi, "π": math.pi, "e": math.e}
# Longest first, so ``asin`` wins over ``a``·``sin`` inside one word.
_NAMES = sorted([*UNARY_FUNCTIONS, *BINARY_FUNCTIONS, *GEO_FUNCTIONS, "pi"], key=len, reverse=True)
_POINT_ID = re.compile(r"[A-Za-z0-9]{1,8}")

_TOKEN = re.compile(r"\s*(?:(\d+(?:\.\d+)?|\.\d+)|([A-Za-z][A-Za-z0-9]*\.[xy])(?![A-Za-z0-9_])|([A-Za-z_][A-Za-z0-9_]*|[πθ])|([-+*/^()|,]))")
_REPLACEMENTS = {
    "²": "^2", "³": "^3", "×": "*", "·": "*", "⋅": "*", "÷": "/", "−": "-", "–": "-", "（": "(", "）": ")",
    "，": ",", "√": "sqrt", "｜": "|", "＋": "+", "－": "-",
}
_LATEX_WORDS = {
    "cdot": "*", "times": "*", "div": "/", "pi": "pi", "theta": "θ", "sin": "sin", "cos": "cos", "tan": "tan",
    "arcsin": "asin", "arccos": "acos", "arctan": "atan", "ln": "ln", "log": "log", "exp": "exp",
}


class SceneExprError(ValueError):
    """An expression outside the Scene v2 whitelist."""


def normalize(source: str) -> str:
    text = str(source or "")
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    text = re.sub(r"\\(?:left|right)\b|\\[,;:! ]", "", text)
    for _ in range(20):  # innermost first, so nested \frac and \sqrt unwrap
        updated = re.sub(r"\\[dt]?frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"((\1)/(\2))", text)
        updated = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"sqrt(\1)", updated)
        if updated == text:
            break
        text = updated
    text = re.sub(r"\\([A-Za-z]+)", lambda m: f" {_LATEX_WORDS[m.group(1)]} " if m.group(1) in _LATEX_WORDS else m.group(0), text)
    if "\\" in text:
        raise SceneExprError("式子里有不支持的 LaTeX 命令")
    return text.replace("{", "(").replace("}", ")").replace("[", "(").replace("]", ")").strip()


def _split_word(word: str) -> list[tuple[str, str]]:
    """``kx`` → k·x, ``2sin`` handled by the number rule, ``xsin`` → x·sin."""
    if word in _NAMES or word in _CONSTANTS:
        return [("name", word)]
    if "_" in word:
        raise SceneExprError(f"看不懂「{word[:12]}」")
    pieces, index = [], 0
    while index < len(word):
        name = next((n for n in _NAMES if "_" not in n and word.startswith(n, index)), None)
        if name:
            pieces.append(("name", name))
            index += len(name)
        elif word[index].isdigit():
            digits = re.match(r"\d+", word[index:]).group(0)
            pieces.append(("num", digits))
            index += len(digits)
        else:
            pieces.append(("name", word[index]))
            index += 1
    run = 0
    for kind, value in pieces:
        # ``open``/``eval`` are words, not products of four unknowns: allow
        # ``kx`` or ``abx``-style runs only up to two letters plus x, y.
        run = run + 1 if kind == "name" and len(value) == 1 and value not in {"x", "y"} else 0
        if run >= 3:
            raise SceneExprError(f"看不懂「{word[:12]}」，字母之间请用 * 隔开")
    return pieces


def tokenize(source: str) -> list[tuple[str, str]]:
    text = normalize(source)
    if not text:
        raise SceneExprError("式子是空的")
    if len(text) > MAX_CHARS:
        raise SceneExprError("式子太长了")
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            if not text[pos:].strip():
                break
            raise SceneExprError(f"看不懂「{text[pos:pos + 6].strip()}」，只支持白名单里的数学记号")
        number, coord, word, symbol = match.groups()
        if number:
            tokens.append(("num", number))
        elif coord:
            tokens.append(("coord", coord))
        elif word:
            tokens.extend(_split_word(word))
        else:
            tokens.append(("sym", symbol))
        pos = match.end()
    return tokens


def _num(value: float) -> dict[str, Any]:
    if not math.isfinite(value):
        raise SceneExprError("数字太大了")
    return {"k": "num", "v": value}


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]):
        self.tokens = tokens
        self.pos = 0
        self.bars = 0

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def at(self, value: str) -> bool:
        token = self.peek()
        return token is not None and token[0] == "sym" and token[1] == value

    def take(self, value: str | None = None) -> tuple[str, str]:
        token = self.peek()
        if token is None or (value is not None and token != ("sym", value)):
            raise SceneExprError("式子不完整，请检查括号、逗号和运算符")
        self.pos += 1
        return token

    def parse(self) -> dict[str, Any]:
        node = self.expr(0)
        if self.peek() is not None:
            raise SceneExprError("式子里有多余的部分")
        return node

    def expr(self, depth: int) -> dict[str, Any]:
        if depth > MAX_DEPTH:
            raise SceneExprError("式子嵌套太深了")
        node = self.term(depth)
        while self.at("+") or self.at("-"):
            op = self.take()[1]
            node = {"k": "op", "o": op, "a": [node, self.term(depth + 1)]}
            depth += 1
            if depth > MAX_DEPTH:
                raise SceneExprError("式子嵌套太深了")
        return node

    def _starts_factor(self) -> bool:
        token = self.peek()
        if token is None:
            return False
        if token[0] != "sym":
            return True
        if token[1] == "(":
            return True
        # ``2|x|``: a bar opens a new absolute value only outside an open one.
        return token[1] == "|" and self.bars == 0

    def term(self, depth: int) -> dict[str, Any]:
        node = self.unary(depth)
        while True:
            if self.at("*") or self.at("/"):
                op = self.take()[1]
            elif self._starts_factor():
                op = "*"  # implicit multiplication: 2x, 2(x+1), x(x+1), 2sin(x)
            else:
                return node
            depth += 1
            if depth > MAX_DEPTH:
                raise SceneExprError("式子嵌套太深了")
            node = {"k": "op", "o": op, "a": [node, self.unary(depth)]}

    def unary(self, depth: int) -> dict[str, Any]:
        if depth > MAX_DEPTH:
            raise SceneExprError("式子嵌套太深了")
        if self.at("-") or self.at("+"):
            sign = self.take()[1]
            operand = self.unary(depth + 1)
            return {"k": "neg", "a": [operand]} if sign == "-" else operand
        return self.power(depth)

    def power(self, depth: int) -> dict[str, Any]:
        base = self.primary(depth)
        if self.at("^"):
            self.take()
            return {"k": "op", "o": "^", "a": [base, self.unary(depth + 1)]}
        return base

    def arguments(self, depth: int) -> list[dict[str, Any]]:
        self.take("(")
        args = [self.expr(depth + 1)]
        while self.at(","):
            self.take()
            args.append(self.expr(depth + 1))
        self.take(")")
        return args

    def point_ids(self, name: str) -> list[str]:
        self.take("(")
        ids: list[str] = []
        while True:
            start = self.pos
            parts = []
            while (token := self.peek()) is not None and token[0] in {"name", "num"}:
                parts.append(token[1])
                self.pos += 1
            point = "".join(parts)
            if not parts or not _POINT_ID.fullmatch(point):
                self.pos = start
                raise SceneExprError(f"{name}(…) 的参数必须是点的名字，例如 {name}(P,A)")
            ids.append(point)
            if self.at(","):
                self.take()
                continue
            self.take(")")
            return ids

    def primary(self, depth: int) -> dict[str, Any]:
        if depth > MAX_DEPTH:
            raise SceneExprError("式子嵌套太深了")
        kind, value = self.take()
        if kind == "num":
            return _num(float(value))
        if kind == "coord":
            point, axis = value.rsplit(".", 1)
            if not _POINT_ID.fullmatch(point):
                raise SceneExprError(f"点的名字「{point[:12]}」不合法")
            return {"k": "coord", "p": point, "c": axis}
        if kind == "sym":
            if value == "(":
                node = self.expr(depth + 1)
                self.take(")")
                return node
            if value == "|":
                self.bars += 1
                node = self.expr(depth + 1)
                self.take("|")
                self.bars -= 1
                return {"k": "fn", "f": "abs", "a": [node]}
            raise SceneExprError("式子不完整，请检查括号和运算符")
        if value in GEO_FUNCTIONS:
            ids = self.point_ids(value)
            low, high = GEO_FUNCTIONS[value]
            if not low <= len(ids) <= high:
                raise SceneExprError(f"{value}(…) 需要 {low}{'' if low == high else f'~{high}'} 个点")
            return {"k": "geo", "f": value, "p": ids}
        if value in BINARY_FUNCTIONS:
            if not self.at("("):
                raise SceneExprError(f"{value} 后面要写括号，例如 {value}(a,b)")
            args = self.arguments(depth)
            if len(args) != 2:
                raise SceneExprError(f"{value}(…) 需要两个参数")
            return {"k": "fn", "f": value, "a": args}
        if value in UNARY_FUNCTIONS:
            if self.at("("):
                args = self.arguments(depth)
                if len(args) != 1:
                    raise SceneExprError(f"{value}(…) 只接受一个参数")
                return {"k": "fn", "f": value, "a": args}
            return {"k": "fn", "f": value, "a": [self.power(depth + 1)]}
        if value in _CONSTANTS:
            return _num(_CONSTANTS[value])
        if len(value) == 1 and (value.isalpha() or value == "θ"):
            return {"k": "var", "n": value}
        raise SceneExprError(f"看不懂「{value[:12]}」")


def depth(ast: dict[str, Any]) -> int:
    children = ast.get("a") or []
    return 1 + max((depth(child) for child in children), default=0)


def size(ast: dict[str, Any]) -> int:
    return 1 + sum(size(child) for child in ast.get("a") or [])


def _rename(ast: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    if ast["k"] == "var" and ast["n"] in names:
        return {"k": "var", "n": names[ast["n"]]}
    if "a" in ast:
        return {**ast, "a": [_rename(child, names) for child in ast["a"]]}
    return ast


def check_limits(ast: dict[str, Any]) -> dict[str, Any]:
    if size(ast) > MAX_NODES:
        raise SceneExprError("式子太长了")
    if depth(ast) > MAX_DEPTH:
        raise SceneExprError("式子嵌套太深了")
    return ast


def compile_expr(source: str, *, rename: dict[str, str] | None = None) -> dict[str, Any]:
    """Compile one untrusted expression string into the Scene v2 AST."""
    if not isinstance(source, (str, int, float)) or isinstance(source, bool):
        raise SceneExprError("表达式必须是字符串")
    ast = _Parser(tokenize(str(source))).parse()
    if rename:
        ast = _rename(ast, rename)
    return check_limits(ast)


def subtract(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """``left - right`` (``left`` alone when ``right`` is the number 0)."""
    if right == {"k": "num", "v": 0.0}:
        return check_limits(left)
    return check_limits({"k": "op", "o": "-", "a": [left, right]})


def variables(ast: dict[str, Any]) -> set[str]:
    own = {ast["n"]} if ast["k"] == "var" else set()
    return own.union(*(variables(child) for child in ast.get("a") or []))


def point_refs(ast: dict[str, Any]) -> set[str]:
    own = {ast["p"]} if ast["k"] == "coord" else set(ast["p"]) if ast["k"] == "geo" else set()
    return own.union(*(point_refs(child) for child in ast.get("a") or []))


# ---------------------------------------------------------------------------
# Evaluation (server-side: view ranges, marks, tests)
# ---------------------------------------------------------------------------

_UNARY = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan, "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sqrt": math.sqrt, "abs": abs, "ln": math.log, "log": math.log10, "exp": math.exp,
    "floor": math.floor, "ceil": math.ceil, "sign": lambda v: (v > 0) - (v < 0),
}
_BINARY = {"min": min, "max": max, "atan2": math.atan2}


def _power(base: float, exponent: float) -> float:
    if base < 0 and exponent != int(exponent):
        fraction = Fraction(exponent).limit_denominator(9)
        if fraction.denominator % 2 == 1 and math.isclose(float(fraction), exponent):
            return -((-base) ** exponent)  # odd root of a negative number
        raise ValueError("even root of a negative number")
    return float(base ** exponent)


def _geo(name: str, ids: list[str], points: dict[str, tuple[float, float]]) -> float:
    p = [points[i] for i in ids]
    if name == "dist":
        return math.hypot(p[1][0] - p[0][0], p[1][1] - p[0][1])
    if name == "slope":
        return (p[1][1] - p[0][1]) / (p[1][0] - p[0][0])
    if name == "mid_x":
        return (p[0][0] + p[1][0]) / 2
    if name == "mid_y":
        return (p[0][1] + p[1][1]) / 2
    if name == "angle":
        (ax, ay), (bx, by), (cx, cy) = p
        u, v = (ax - bx, ay - by), (cx - bx, cy - by)
        norm = math.hypot(*u) * math.hypot(*v)
        if norm == 0:
            raise ValueError("degenerate angle")
        cosine = max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / norm))
        return math.degrees(math.acos(cosine))
    if name == "area":
        return abs(sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))) / 2
    raise ValueError(name)


def _eval(ast: dict[str, Any], env: dict[str, float], points: dict[str, tuple[float, float]]) -> float:
    kind = ast["k"]
    if kind == "num":
        return float(ast["v"])
    if kind == "var":
        return float(env[ast["n"]])
    if kind == "coord":
        return float(points[ast["p"]][0 if ast["c"] == "x" else 1])
    if kind == "geo":
        return float(_geo(ast["f"], ast["p"], points))
    args = [_eval(child, env, points) for child in ast["a"]]
    if kind == "neg":
        return -args[0]
    if kind == "fn":
        function = _UNARY.get(ast["f"]) or _BINARY[ast["f"]]
        return float(function(*args))
    left, right = args
    op = ast["o"]
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        return left / right
    return _power(left, right)


def evaluate(ast: dict[str, Any], env: dict[str, float] | None = None,
             points: dict[str, tuple[float, float]] | None = None) -> float | None:
    """Value of ``ast``; None when undefined (domain error, division by zero, non-finite)."""
    try:
        value = _eval(ast, env or {}, points or {})
    except (ValueError, ZeroDivisionError, OverflowError, TypeError, KeyError):
        return None
    return value if math.isfinite(value) else None


__all__ = [
    "BINARY_FUNCTIONS", "GEO_FUNCTIONS", "MAX_DEPTH", "MAX_NODES", "SceneExprError", "UNARY_FUNCTIONS",
    "check_limits", "compile_expr", "depth", "evaluate", "normalize", "point_refs", "size", "subtract", "variables",
]
