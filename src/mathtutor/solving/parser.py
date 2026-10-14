"""Text/LaTeX problem parser for the MVP problem families.

Grammar (Pratt parser; implicit multiplication between number·variable,
number·group, closing-paren·primary):

::

    expr    := term (('+' | '-') term)*
    term    := factor (('*' | '/' | implicit) factor)*
    factor  := ('-' | '+')* primary ('^' factor)?     -- ^ binds tighter than unary minus
    primary := NUMBER | VARIABLE | '\\frac{expr}{expr}' | '(' expr ')'

Outcomes (design doc §6.2 fail-closed semantics):

- juxtaposed same-kind primaries (``2 3``, ``x y``) -> :data:`ambiguous`
  (true semantic ambiguity: two readings, two answers);
- ill-formed / unknown characters / incomplete syntax -> :data:`unparseable`
  (parser failure, NOT clarification);
- parses but is outside the MVP families (square roots, degree > 2,
  multiple variables, a variable in a denominator, budget overflow) ->
  :data:`unsupported`.

The :func:`parse_problem` result carries the canonical AST, its normalized
dict and display LaTeX; the ``MathProblem`` domain record is built by the
application service on top of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from mathtutor.solving import nodes as n

MAX_TOKENS = 256
ProblemType = Literal["arithmetic", "polynomial", "linear", "quadratic", "linear_system", "linear_inequality",
                      "quadratic_inequality"]
ParseKind = Literal["parsed", "ambiguous", "unsupported", "unparseable"]


class AmbiguityError(Exception):
    """Two same-kind primaries are adjacent: the readings disagree on the answer."""


class ParseError(Exception):
    """The grammar cannot read this string. That is not semantic ambiguity."""


class UnsupportedError(Exception):
    """Input parses but is outside the MVP problem families."""


@dataclass(frozen=True, slots=True)
class ParsedProblem:
    """Canonical parse result consumed by solver and verifier."""

    problem_type: ProblemType
    ast: n.Node
    normalized_ast: dict[str, Any]
    display_latex: str
    variable: str | None  # canonical variable name for polynomial families
    relation: str | None = None  # set for a linear inequality; the AST stays the boundary equation


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    kind: ParseKind
    problem: ParsedProblem | None = None
    reason: str = ""

    @classmethod
    def ok(cls, problem: ParsedProblem) -> "ParseOutcome":
        return cls("parsed", problem)

    @classmethod
    def ambiguous(cls, reason: str) -> "ParseOutcome":
        return cls("ambiguous", None, reason)

    @classmethod
    def unsupported(cls, reason: str) -> "ParseOutcome":
        return cls("unsupported", None, reason)

    @classmethod
    def unparseable(cls, reason: str) -> "ParseOutcome":
        return cls("unparseable", None, reason)


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Token:
    kind: str  # number | var | plus | minus | star | slash | caret | equals | lparen | rparen | frac | sqrt
    value: Any = None
    pos: int = 0


class _Tokenizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0
        self.tokens: list[_Token] = []
        self.count = 0

    def _push(self, token: _Token) -> None:
        self.count += 1
        if self.count > MAX_TOKENS:
            raise UnsupportedError(f"输入超出记号预算（{MAX_TOKENS}）")
        self.tokens.append(token)

    def tokenize(self) -> list[_Token]:
        while self.pos < len(self.text):
            ch = self.text[self.pos]
            if ch.isspace():
                self.pos += 1
                continue
            if ch == "\\":
                self._command()
                continue
            if ch.isdigit() or ch == ".":
                self._number()
                continue
            if "a" <= ch.lower() <= "z":
                self.tokens.append(_Token("var", ch, self.pos))
                self.pos += 1
                continue
            if ch == "+":
                self.tokens.append(_Token("plus", pos=self.pos))
                self.pos += 1
                continue
            if ch in {"-", "\u2212"}:
                self.tokens.append(_Token("minus", pos=self.pos))
                self.pos += 1
                continue
            if ch in {"*", "\u00d7", "\u00b7", "\u22c5"}:
                self.tokens.append(_Token("star", pos=self.pos))
                self.pos += 1
                continue
            if ch in {"/", "\u00f7"}:
                self.tokens.append(_Token("slash", pos=self.pos))
                self.pos += 1
                continue
            if ch == "^":
                self.tokens.append(_Token("caret", pos=self.pos))
                self.pos += 1
                continue
            if ch == "=":
                self.tokens.append(_Token("equals", pos=self.pos))
                self.pos += 1
                continue
            if ch == "(":
                self.tokens.append(_Token("lparen", pos=self.pos))
                self.pos += 1
                continue
            if ch == ")":
                self.tokens.append(_Token("rparen", pos=self.pos))
                self.pos += 1
                continue
            raise ParseError(f"无法识别的字符 {ch!r}（位置 {self.pos}）")
        return self.tokens

    def _number(self) -> None:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos < len(self.text) and self.text[self.pos] == ".":
            self.pos += 1
            digits = 0
            while self.pos < len(self.text) and self.text[self.pos].isdigit():
                self.pos += 1
                digits += 1
            if digits == 0:
                raise ParseError(f"小数格式不完整（位置 {start}）")
            value = Fraction(int(self.text[start : self.pos].replace(".", "")), 10**digits)
        else:
            value = Fraction(int(self.text[start : self.pos]), 1)
        self._push(_Token("number", value, start))

    def _command(self) -> None:
        start = self.pos
        self.pos += 1  # skip backslash
        name_start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isalpha():
            self.pos += 1
        command = self.text[name_start : self.pos]
        if command == "frac":
            num_tokens = self._braced_tokens()
            den_tokens = self._braced_tokens()
            self._push(_Token("frac", (num_tokens, den_tokens), start))
        elif command == "sqrt":
            radicand_tokens = self._braced_tokens()
            self._push(_Token("sqrt", radicand_tokens, start))
        elif command in ("cdot", "times"):
            self.tokens.append(_Token("star", pos=start))
        elif command == "div":
            self.tokens.append(_Token("slash", pos=start))
        else:
            raise ParseError(f"不支持的 LaTeX 命令 \\{command}（位置 {start}）")

    def _braced_tokens(self) -> list[_Token]:
        if self.pos >= len(self.text) or self.text[self.pos] != "{":
            raise ParseError(f"缺少 {{ 匹配（位置 {self.pos}）")
        self.pos += 1
        depth = 1
        body = ""
        while self.pos < len(self.text) and depth > 0:
            ch = self.text[self.pos]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    break
            body += ch
            self.pos += 1
        if depth != 0:
            raise ParseError(f"括号不匹配（位置 {self.pos}）")
        sub = _Tokenizer(body)
        return sub.tokenize()


# ---------------------------------------------------------------------------
# Pratt parser
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def peek(self) -> _Token | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> _Token:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def expect(self, kind: str) -> _Token:
        token = self.peek()
        if token is None or token.kind != kind:
            found = token.kind if token else "输入结束"
            raise ParseError(f"语法错误：期望 {kind}，实际为 {found}")
        return self.next()

    def at_end(self) -> bool:
        return self.pos >= len(self.tokens)

    def parse_expression(self) -> n.Node:
        """Handles + / - at the lowest precedence."""
        left = self.parse_term()
        while True:
            token = self.peek()
            if token is None:
                break
            if token.kind == "plus":
                self.next()
                left = n.add(left, self.parse_term())
            elif token.kind == "minus":
                self.next()
                left = n.add(left, n.mul(n.num(-1), self.parse_term()))
            else:
                break
        return left

    def parse_term(self) -> n.Node:
        """Handles * / and implicit multiplication."""
        left = self.parse_factor()
        while True:
            token = self.peek()
            if token is None:
                break
            if token.kind in ("star", "slash"):
                kind = self.next().kind
                right = self.parse_factor()
                left = n.div(left, right) if kind == "slash" else n.mul(left, right)
            elif self._implicit(token):
                right = self.parse_factor()
                left = n.mul(left, right)
            else:
                break
        return left

    def _implicit(self, token: _Token) -> bool:
        """Implicit multiplication (strict: `2 3` and `x y` are ambiguous)."""
        if token.kind not in ("number", "var", "lparen", "frac"):
            return False
        previous = self.tokens[self.pos - 1] if self.pos > 0 else None
        if previous is None:
            return False
        if previous.kind == token.kind:
            raise AmbiguityError(f"相邻的 {previous.kind} 与 {token.kind} 含义不明确（位置 {token.pos}）")
        if previous.kind in ("number", "var", "rparen", "frac"):
            return True  # 2x, 2(x+1), x2, (x+1)2, \frac{1}{2}x, ...
        return False

    def parse_factor(self) -> n.Node:
        """Unary signs, then power: exponentiation binds tighter than '-'."""
        token = self.peek()
        if token is None:
            raise ParseError("意外的输入结束")
        if token.kind == "minus":
            self.next()
            return n.mul(n.num(-1), self.parse_factor())
        if token.kind == "plus":
            self.next()
            return self.parse_factor()
        base = self.parse_primary()
        caret = self.peek()
        if caret is not None and caret.kind == "caret":
            self.next()
            exponent = self.parse_factor()
            if not isinstance(exponent, n.Num) or exponent.value.d != 1:
                raise UnsupportedError("仅支持整数指数")
            exp = exponent.value.n
            if exp < 2:
                raise UnsupportedError("指数必须 ≥ 2（MVP）")
            if isinstance(base, n.Num):
                return n.Num(base.value**exp)
            if isinstance(base, n.Pow):
                return n.pow(base.base, base.exp * exp)
            return n.pow(base, exp)
        return base

    def parse_primary(self) -> n.Node:
        token = self.next()
        if token.kind == "number":
            return n.num(n.Rational.from_fraction(token.value))
        if token.kind == "var":
            return n.var(token.value)
        if token.kind == "lparen":
            inner = self.parse_expression()
            self.expect("rparen")
            return inner
        if token.kind == "frac":
            num_tokens, den_tokens = token.value
            numerator = self._parse_sublist(num_tokens)
            denominator = self._parse_sublist(den_tokens)
            return n.div(numerator, denominator)
        if token.kind == "sqrt":
            raise UnsupportedError("√/\\sqrt 不在 MVP 题族范围内")
        raise ParseError(f"意外的记号 {token.kind}（位置 {token.pos}）")

    def _parse_sublist(self, tokens: list[_Token]) -> n.Node:
        inner = _Parser(tokens)
        node = inner.parse_expression()
        if not inner.at_end():
            raise ParseError("\\frac 内部存在多余的记号")
        return node


# ---------------------------------------------------------------------------
# Family classification
# ---------------------------------------------------------------------------


def _first_variable(node: n.Node) -> str | None:
    variables = n.variables(node)
    if not variables:
        return None
    return sorted(variables)[0]


def _classify_equation(equation: n.Equation) -> tuple[ProblemType, n.Node, str | None] | str:
    variable = _first_variable(equation)
    if variable is None:
        return "方程不含变量（恒等式或矛盾式，MVP 不支持）"
    diff = n.equation_difference(equation, variable)
    if diff is None:
        return "方程含多变量或分母含变量（MVP 不支持）"
    degree = max(diff)
    if degree > 2:
        return f"方程次数为 {degree}，MVP 仅支持一次/二次方程"
    if degree == 0:
        return "方程化简后不含未知数（恒等式或矛盾式，MVP 不支持）"
    if degree == 1:
        return ("linear", equation, variable)
    return ("quadratic", equation, variable)


def _classify_expression(expr: n.Node) -> tuple[ProblemType, n.Node, str | None] | str:
    variables = n.variables(expr)
    if not variables:
        return ("arithmetic", expr, None)
    if len(variables) > 1:
        return "表达式含多个变量（MVP 不支持）"
    variable = sorted(variables)[0]
    coeffs = n.poly_coeffs(expr, variable)
    if coeffs is None:
        return "表达式含变量在分母或非常规结构（MVP 不支持）"
    degree = max(coeffs)
    if degree > 2:
        return f"多项式次数为 {degree}，MVP 仅支持不超过二次"
    return ("polynomial", expr, variable)


_TRAILING_QUESTION = re.compile(r"[?？]+$")
_TRAILING_EQUALS = re.compile(r"=+\s*$")
_LEADING_TASK = re.compile(
    r"^(?:请|帮我)?(?:计算|求解|解方程组|解方程|化简|因式分解|求根(?!号)|求值|求极限|证明|解不等式|展开|求(?!根号))\s*"
)


def normalize_math_problem_text(text: str) -> str:
    """Strip interrogative wrappers so a complete problem is parseable.

    ``2+2=?`` and ``2+2=`` are the same arithmetic problem as ``2+2``.
    Leading task verbs (``求`` / ``解方程``) are wrappers, not tokens.
    """
    compact = " ".join(str(text or "").strip().split())
    compact = _LEADING_TASK.sub("", compact).strip()
    compact = _TRAILING_QUESTION.sub("", compact).strip()
    compact = _TRAILING_EQUALS.sub("", compact).strip()
    return compact


def stored_math_ast(payload: dict[str, Any]) -> dict[str, Any]:
    """Node dict a replay can load. An inequality keeps its relation beside the equation."""
    if isinstance(payload, dict) and payload.get("kind") == "inequality" and isinstance(payload.get("equation"), dict):
        return payload["equation"]
    return payload


def parse_problem(text: str) -> ParseOutcome:
    """Parse a single problem text into a canonical problem (or fail closed)."""
    from mathtutor.solving.extended_text import compile_extended, parse_inequality_text
    compiled = compile_extended(text, _parse_core)
    if compiled is not None:
        return compiled
    inequality = parse_inequality_text(text, _parse_core)
    if inequality is not None:
        return inequality
    return _parse_core(text)


def _parse_core(text: str) -> ParseOutcome:
    """Grammar for the original equation and expression families."""
    system_text = str(text or "").strip().replace(r"\begin{cases}", "").replace(r"\end{cases}", "").replace(r"\\", ";")
    if system_text.count("=") >= 2 and re.search(r"[;；,，\n]", system_text):
        return _parse_linear_system(system_text)
    text = normalize_math_problem_text(text)
    try:
        tokens = _Tokenizer(text).tokenize()
        parser = _Parser(tokens)
        lhs = parser.parse_expression()
        equals = parser.peek()
        if equals is not None and equals.kind == "equals":
            parser.next()
            rhs = parser.parse_expression()
            if not parser.at_end():
                raise ParseError("'=' 只能出现一次")
            ast = n.eq(lhs, rhs)
            classified = _classify_equation(ast)
        else:
            if not parser.at_end():
                remaining = parser.tokens[parser.pos].kind
                raise ParseError(f"表达式结束后仍有记号：{remaining}")
            ast = lhs
            classified = _classify_expression(ast)
    except AmbiguityError as exc:
        return ParseOutcome.ambiguous(str(exc))
    except ParseError as exc:
        return ParseOutcome.unparseable(str(exc))
    except UnsupportedError as exc:
        return ParseOutcome.unsupported(str(exc))
    except n.MathDomainError as exc:
        return ParseOutcome.unsupported(str(exc))
    except n.MathComplexityError as exc:
        return ParseOutcome.unsupported(str(exc))

    if isinstance(classified, str):
        return ParseOutcome.unsupported(classified)

    problem_type, normalized, variable = classified
    return ParseOutcome.ok(
        ParsedProblem(
            problem_type=problem_type,
            ast=normalized,
            normalized_ast=n.to_dict(normalized),
            # Canonical arithmetic builders deliberately fold constants for
            # verification. A task surface must retain the requested operation,
            # not show that folded answer to a student before they attempt it.
            display_latex=(_arithmetic_surface(tokens) if problem_type == "arithmetic" and all(t.kind != "var" for t in tokens)
                       else n.to_latex(normalized)),  # 3x-3x+2 has variables yet simplifies to a number
            variable=variable,
        )
    )


def _arithmetic_surface(tokens: list[_Token]) -> str:
    """Render only tokens already accepted by our grammar; never eval or HTML."""
    result = []
    symbols = {"plus": "+", "minus": "-", "star": r"\cdot", "slash": "/",
               "caret": "^", "lparen": "(", "rparen": ")"}
    for token in tokens:
        if token.kind == "number":
            value = token.value
            result.append(str(value.numerator) if value.denominator == 1
                          else rf"\frac{{{value.numerator}}}{{{value.denominator}}}")
        elif token.kind == "frac":
            numerator, denominator = token.value
            result.append(rf"\frac{{{_arithmetic_surface(numerator)}}}{{{_arithmetic_surface(denominator)}}}")
        else:
            result.append(symbols[token.kind])
    return " ".join(result)


def _parse_linear_system(text: str) -> ParseOutcome:
    from mathtutor.solving.linear_system import system_rows
    parts = [part.strip() for part in re.split(r"[;；,，\n]", text) if part.strip()]
    if len(parts) != 2:
        return ParseOutcome.unsupported("当前仅支持两个方程、两个未知数的线性方程组")
    if len(text) > 4096:
        return ParseOutcome.unsupported("方程组超出输入预算")
    equations = []
    try:
        for part in parts:
            tokens = _Tokenizer(normalize_math_problem_text(part)).tokenize()
            if len(tokens) > MAX_TOKENS:
                raise UnsupportedError("方程组超出记号预算")
            parser = _Parser(tokens)
            lhs = parser.parse_expression()
            parser.expect("equals")
            rhs = parser.parse_expression()
            if not parser.at_end():
                raise ParseError("每个方程只能有一个等号")
            equations.append(n.eq(lhs, rhs))
        ast = n.LinearSystem(tuple(equations))
        system_rows(ast)
        return ParseOutcome.ok(ParsedProblem("linear_system", ast, n.to_dict(ast), n.to_latex(ast), None))
    except AmbiguityError as exc:
        return ParseOutcome.ambiguous(str(exc))
    except ParseError as exc:
        return ParseOutcome.unparseable(str(exc))
    except (UnsupportedError, n.MathDomainError, n.MathComplexityError) as exc:
        return ParseOutcome.unsupported(str(exc))


def parse_linear_equation_fragment(text: str) -> ParseOutcome:
    """Attempt-only parser for a single affine system step; never a solvable new task."""
    from mathtutor.solving.linear_system import equation_row
    try:
        tokens = _Tokenizer(normalize_math_problem_text(text)).tokenize()
        if len(tokens) > MAX_TOKENS:
            raise UnsupportedError("作答超出记号预算")
        parser = _Parser(tokens)
        lhs = parser.parse_expression()
        parser.expect("equals")
        rhs = parser.parse_expression()
        if not parser.at_end():
            raise ParseError("每个方程只能有一个等号")
        ast = n.eq(lhs, rhs)
        variables = tuple(sorted(n.variables(ast)))
        if len(variables) != 2:
            return ParseOutcome.unsupported("需要二元一次式")
        equation_row(ast, variables)
        return ParseOutcome.ok(ParsedProblem("linear_system", ast, n.to_dict(ast), n.to_latex(ast), None))
    except (AmbiguityError, ParseError, UnsupportedError, n.MathDomainError, n.MathComplexityError) as exc:
        return ParseOutcome.unsupported(str(exc))


__all__ = [
    "AmbiguityError",
    "ParseError",
    "ParseOutcome",
    "ParsedProblem",
    "parse_problem",
    "normalize_math_problem_text",
]
