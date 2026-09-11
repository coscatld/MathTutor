"""Normalized mathematical AST shared by parser, solver and verifier.

Canonical invariants (enforced by the builder functions ``num/add/mul/pow/
div`` — never construct nodes directly):

- :class:`Rational` values are always reduced with a positive denominator
  (zero is ``(0, 1)``).
- :class:`Add` has at least two terms, is sorted by :func:`node_key`
  (numeric terms last), contains no nested :class:`Add` and no zero terms.
- :class:`Mul` has at least two factors; the numeric coefficient, if any,
  is the first factor; contains no nested :class:`Mul`, no ``1`` factor and
  collapses to :class:`Num` when the product is a literal.
- :class:`Pow` has integer exponent ``>= 2`` and a non-numeric, non-power
  base. Division is an explicit :class:`Div` node; its denominator must be
  a literal for a problem to stay inside the MVP families (a variable in
  the denominator is UNSUPPORTED).

Serialization (:func:`to_dict` / :func:`from_dict`) is invertible and is
what ``MathProblem.normalized_ast`` stores; the verifier's
``parse_round_trip`` check replays it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math
from typing import Any, Literal


class MathDomainError(Exception):
    """A mathematical domain violation (e.g. division by zero)."""


class MathComplexityError(Exception):
    """The expression exceeds the MVP node/depth budget."""


@dataclass(frozen=True, slots=True)
class Rational:
    """Exact rational value, always in canonical reduced form (n, d), d > 0."""

    n: int
    d: int

    def __init__(self, n: int, d: int = 1) -> None:
        if d == 0:
            raise MathDomainError("division by zero")
        if d < 0:
            n, d = -n, -d
        g = math.gcd(abs(n), d)
        object.__setattr__(self, "n", n // g)
        object.__setattr__(self, "d", d // g)

    def to_fraction(self) -> Fraction:
        return Fraction(self.n, self.d)

    @classmethod
    def from_fraction(cls, value: Fraction) -> "Rational":
        return cls(value.numerator, value.denominator)

    def to_dict(self) -> dict[str, int]:
        return {"n": self.n, "d": self.d}

    @classmethod
    def from_dict(cls, payload: dict[str, int]) -> "Rational":
        return cls(payload["n"], payload["d"])

    def __add__(self, other: "Rational") -> "Rational":
        return Rational.from_fraction(self.to_fraction() + other.to_fraction())

    def __sub__(self, other: "Rational") -> "Rational":
        return Rational.from_fraction(self.to_fraction() - other.to_fraction())

    def __mul__(self, other: "Rational") -> "Rational":
        return Rational.from_fraction(self.to_fraction() * other.to_fraction())

    def __truediv__(self, other: "Rational") -> "Rational":
        if other.n == 0:
            raise MathDomainError("division by zero")
        return Rational.from_fraction(self.to_fraction() / other.to_fraction())

    def __neg__(self) -> "Rational":
        return Rational(-self.n, self.d)

    def __pow__(self, exp: int) -> "Rational":
        if not isinstance(exp, int) or exp < 0:
            raise TypeError("Rational powers require a non-negative integer exponent")
        return Rational(self.n**exp, self.d**exp)

    def __lt__(self, other: "Rational") -> bool:
        return self.to_fraction() < other.to_fraction()

    def __le__(self, other: "Rational") -> bool:
        return self.to_fraction() <= other.to_fraction()

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Rational) and self.n == other.n and self.d == other.d

    def __hash__(self) -> int:
        return hash((self.n, self.d))

    def __repr__(self) -> str:
        return f"R({self.n}/{self.d})"


ZERO = Rational(0, 1)
ONE = Rational(1, 1)


# ---------------------------------------------------------------------------
# AST nodes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Num:
    value: Rational


@dataclass(frozen=True, slots=True)
class Var:
    name: str


@dataclass(frozen=True, slots=True)
class Add:
    terms: tuple["Node", ...]


@dataclass(frozen=True, slots=True)
class Mul:
    factors: tuple["Node", ...]


@dataclass(frozen=True, slots=True)
class Pow:
    base: "Node"
    exp: int


@dataclass(frozen=True, slots=True)
class Div:
    num: "Node"
    den: "Node"


@dataclass(frozen=True, slots=True)
class Equation:
    lhs: "Node"
    rhs: "Node"


@dataclass(frozen=True, slots=True)
class LinearSystem:
    equations: tuple[Equation, ...]


Node = Num | Var | Add | Mul | Pow | Div | Equation | LinearSystem
NodeKind = Literal["num", "var", "add", "mul", "pow", "div", "equation", "linear_system"]

_MAX_NODES = 512
_MAX_DEPTH = 64
_MAX_POLY_DEGREE = 64  # resource budget for polynomial expansion


def node_key(node: Node) -> tuple:
    """Deterministic total order for canonical sorting (numbers last)."""
    if isinstance(node, Num):
        return (5, node.value.n, node.value.d)
    if isinstance(node, Var):
        return (0, node.name)
    if isinstance(node, Pow):
        return (1, node_key(node.base), node.exp)
    if isinstance(node, Add):
        return (3, tuple(node_key(t) for t in node.terms))
    if isinstance(node, Mul):
        return (4, tuple(node_key(f) for f in node.factors))
    if isinstance(node, Div):
        return (2, node_key(node.num), node_key(node.den))
    if isinstance(node, Equation):
        return (6, node_key(node.lhs), node_key(node.rhs))
    if isinstance(node, LinearSystem):
        return (7, tuple(node_key(eq) for eq in node.equations))
    raise TypeError(f"unknown node: {node!r}")


def _sort(terms: list[Node]) -> list[Node]:
    return sorted(terms, key=node_key)


def num(value: int | Rational) -> Node:
    return Num(value if isinstance(value, Rational) else Rational(value))


def var(name: str) -> Node:
    return Var(name)


def _split_coefficient(term: Node) -> tuple[Rational, Node | None]:
    """Split a term into (scalar coefficient, rest) so like terms combine.

    In a canonical product the numeric coefficient is the first factor; a
    bare number is ``(value, None)``.
    """
    if isinstance(term, Num):
        return (term.value, None)
    if isinstance(term, Mul) and isinstance(term.factors[0], Num):
        if len(term.factors) == 1:
            return (term.factors[0].value, None)
        return (term.factors[0].value, Mul(term.factors[1:]))
    return (ONE, term)


def add(*nodes: Node) -> Node:
    """Canonical sum: flatten, combine like terms and literals, drop zeros."""
    stack: list[Node] = []
    for node in nodes:
        if isinstance(node, Add):
            stack.extend(node.terms)
        else:
            stack.append(node)
    total = ZERO
    groups: dict[tuple, list[Rational]] = {}
    bases: dict[tuple, Node | None] = {}
    for term in stack:
        if isinstance(term, Num):
            total = total + term.value
            continue
        coeff, base = _split_coefficient(term)
        key = node_key(base)
        groups.setdefault(key, []).append(coeff)
        bases[key] = base
    result: list[Node] = []
    for key, coeffs in groups.items():
        combined = sum(coeffs, ZERO)
        if combined == ZERO:
            continue
        base = bases[key]
        if base is None:
            total = total + combined
        else:
            result.append(mul(num(combined), base))
    if total != ZERO:
        result.append(Num(total))
    if not result:
        return Num(ZERO)
    result = _sort(result)
    if len(result) == 1:
        return result[0]
    return Add(tuple(result))


def mul(*nodes: Node) -> Node:
    """Canonical product: flatten, fold literals, merge equal bases into powers."""
    stack: list[Node] = []
    for node in nodes:
        if isinstance(node, Mul):
            stack.extend(node.factors)
        else:
            stack.append(node)
    total = ONE
    rest: list[Node] = []
    for factor in stack:
        if isinstance(factor, Num):
            total = total * factor.value
        else:
            rest.append(factor)
    if total.n == 0:
        return Num(ZERO)
    groups: dict[tuple, list[Node]] = {}
    for factor in rest:
        groups.setdefault(node_key(factor), []).append(factor)
    merged: list[Node] = []
    for _key, items in groups.items():
        if len(items) == 1:
            merged.append(items[0])
            continue
        base = items[0]
        if isinstance(base, Var):
            merged.append(Pow(base, len(items)))
        elif isinstance(base, Pow):
            merged.append(Pow(base.base, base.exp * len(items)))
        else:
            merged.append(Pow(base, len(items)))  # equal Adds/Divs multiply via a power
    result: list[Node] = []
    if total != ONE:
        result.append(Num(total))
    result.extend(_sort(merged))
    if not result:
        return Num(ONE)
    if len(result) == 1:
        return result[0]
    return Mul(tuple(result))


def pow(base: Node, exp: int) -> Node:
    if exp < 2:
        raise ValueError("canonical Pow requires exp >= 2")
    if isinstance(base, (Num, Pow)):
        raise ValueError("canonical Pow base must be a non-numeric, non-power node")
    return Pow(base, exp)


def div(num_node: Node, den_node: Node) -> Node:
    """Canonical division; folds literals and rejects literal zero divisors."""
    if isinstance(den_node, Num) and den_node.value == ZERO:
        raise MathDomainError("division by zero")
    if isinstance(num_node, Num) and isinstance(den_node, Num):
        return Num(num_node.value / den_node.value)
    if isinstance(den_node, Num) and den_node.value == ONE:
        return num_node
    return Div(num_node, den_node)


def eq(lhs: Node, rhs: Node) -> Node:
    return Equation(lhs, rhs)


# ---------------------------------------------------------------------------
# Serialization (the normalized_ast payload)
# ---------------------------------------------------------------------------


def to_dict(node: Node) -> dict[str, Any]:
    if isinstance(node, LinearSystem):
        return {"kind": "linear_system", "equations": [to_dict(eq) for eq in node.equations]}
    if isinstance(node, Num):
        return {"kind": "num", "value": node.value.to_dict()}
    if isinstance(node, Var):
        return {"kind": "var", "name": node.name}
    if isinstance(node, Add):
        return {"kind": "add", "terms": [to_dict(t) for t in node.terms]}
    if isinstance(node, Mul):
        return {"kind": "mul", "factors": [to_dict(f) for f in node.factors]}
    if isinstance(node, Pow):
        return {"kind": "pow", "base": to_dict(node.base), "exp": node.exp}
    if isinstance(node, Div):
        return {"kind": "div", "num": to_dict(node.num), "den": to_dict(node.den)}
    if isinstance(node, Equation):
        return {"kind": "equation", "lhs": to_dict(node.lhs), "rhs": to_dict(node.rhs)}
    raise TypeError(f"unknown node: {node!r}")


def from_dict(payload: dict[str, Any]) -> Node:
    kind = payload["kind"]
    if kind == "num":
        return Num(Rational.from_dict(payload["value"]))
    if kind == "var":
        return Var(payload["name"])
    if kind == "add":
        return add(*(from_dict(t) for t in payload["terms"]))
    if kind == "mul":
        return mul(*(from_dict(f) for f in payload["factors"]))
    if kind == "pow":
        return pow(from_dict(payload["base"]), payload["exp"])
    if kind == "div":
        return div(from_dict(payload["num"]), from_dict(payload["den"]))
    if kind == "equation":
        return eq(from_dict(payload["lhs"]), from_dict(payload["rhs"]))
    if kind == "linear_system":
        equations = tuple(from_dict(item) for item in payload["equations"])
        if len(equations) != 2 or not all(isinstance(item, Equation) for item in equations):
            raise ValueError("二元一次方程组必须包含两个方程")
        return LinearSystem(equations)
    raise ValueError(f"unknown node kind: {kind!r}")


# ---------------------------------------------------------------------------
# Variables, evaluation, polynomial expansion
# ---------------------------------------------------------------------------


def variables(node: Node) -> frozenset[str]:
    """Distinct variable names in the tree (variables inside Div denominators
    are excluded from MVP families at classification time, not here)."""
    if isinstance(node, LinearSystem):
        return frozenset().union(*(variables(eq) for eq in node.equations))
    if isinstance(node, Num):
        return frozenset()
    if isinstance(node, Var):
        return frozenset({node.name})
    if isinstance(node, Add):
        return frozenset().union(*(variables(t) for t in node.terms))
    if isinstance(node, Mul):
        return frozenset().union(*(variables(f) for f in node.factors))
    if isinstance(node, Pow):
        return variables(node.base)
    if isinstance(node, Div):
        return variables(node.num) | variables(node.den)
    if isinstance(node, Equation):
        return variables(node.lhs) | variables(node.rhs)
    raise TypeError(f"unknown node: {node!r}")


def evaluate(node: Node) -> Rational:
    """Exact evaluation for the arithmetic family (no variables allowed)."""
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Add):
        return sum((evaluate(t) for t in node.terms), ZERO)
    if isinstance(node, Mul):
        result = ONE
        for factor in node.factors:
            result = result * evaluate(factor)
        return result
    if isinstance(node, Pow):
        return evaluate(node.base) ** node.exp
    if isinstance(node, Div):
        return evaluate(node.num) / evaluate(node.den)
    raise MathDomainError(f"expression contains a variable: {to_latex(node)}")


def _poly_add(a: dict[int, Fraction], b: dict[int, Fraction]) -> dict[int, Fraction]:
    out = dict(a)
    for deg, coeff in b.items():
        out[deg] = out.get(deg, Fraction(0)) + coeff
    return _trim(out)


def _poly_sub(a: dict[int, Fraction], b: dict[int, Fraction]) -> dict[int, Fraction]:
    out = dict(a)
    for deg, coeff in b.items():
        out[deg] = out.get(deg, Fraction(0)) - coeff
    return _trim(out)


def _poly_mul(a: dict[int, Fraction], b: dict[int, Fraction]) -> dict[int, Fraction]:
    out: dict[int, Fraction] = {}
    for d1, c1 in a.items():
        for d2, c2 in b.items():
            deg = d1 + d2
            if deg > _MAX_POLY_DEGREE:
                raise MathComplexityError(f"expanded degree exceeds {_MAX_POLY_DEGREE}")
            out[deg] = out.get(deg, Fraction(0)) + c1 * c2
    return _trim(out)


def _trim(poly: dict[int, Fraction]) -> dict[int, Fraction]:
    trimmed = {deg: c for deg, c in poly.items() if c != 0}
    if not trimmed:
        return {0: Fraction(0)}
    return trimmed


def poly_coeffs(node: Node, var_name: str) -> dict[int, Fraction] | None:
    """Coefficient vector of ``node`` as a polynomial in ``var_name``.

    Returns ``None`` when the node is not a single-variable polynomial with
    rational coefficients (multi-variable terms, variables in a denominator,
    non-integer powers). Degree is capped by :data:`_MAX_POLY_DEGREE`.
    """
    if isinstance(node, Num):
        return {0: node.value.to_fraction()}
    if isinstance(node, Var):
        if node.name != var_name:
            return None
        return {1: Fraction(1)}
    if isinstance(node, Add):
        result: dict[int, Fraction] = {}
        for term in node.terms:
            coeffs = poly_coeffs(term, var_name)
            if coeffs is None:
                return None
            result = _poly_add(result, coeffs)
        return result
    if isinstance(node, Mul):
        result: dict[int, Fraction] = {0: Fraction(1)}
        for factor in node.factors:
            coeffs = poly_coeffs(factor, var_name)
            if coeffs is None:
                return None
            result = _poly_mul(result, coeffs)
        return result
    if isinstance(node, Pow):
        base = poly_coeffs(node.base, var_name)
        if base is None:
            return None
        result: dict[int, Fraction] = {0: Fraction(1)}
        for _ in range(node.exp):
            result = _poly_mul(result, base)
        return result
    if isinstance(node, Div):
        den = poly_coeffs(node.den, var_name)
        if den is None or any(degree > 0 for degree in den):
            return None  # variable in the denominator: out of the MVP families
        num = poly_coeffs(node.num, var_name)
        if num is None:
            return None
        factor = den[0]
        return {degree: coeff / factor for degree, coeff in num.items()}
    raise TypeError(f"unknown node: {node!r}")


def equation_difference(equation: Equation, var_name: str) -> dict[int, Fraction] | None:
    """Coefficients of (lhs - rhs) as a polynomial in ``var_name``."""
    lhs = poly_coeffs(equation.lhs, var_name)
    if lhs is None:
        return None
    rhs = poly_coeffs(equation.rhs, var_name)
    if rhs is None:
        return None
    return _poly_sub(lhs, rhs)


# ---------------------------------------------------------------------------
# LaTeX rendering
# ---------------------------------------------------------------------------


def _render(node: Node, parent: NodeKind | None = None) -> str:
    if isinstance(node, Num):
        if node.value.d == 1:
            return str(node.value.n)
        return f"\\frac{{{node.value.n}}}{{{node.value.d}}}"
    if isinstance(node, Var):
        return node.name
    if isinstance(node, Add):
        pieces: list[tuple[str, str]] = []
        for term in node.terms:
            sign = " + "
            if isinstance(term, Num) and term.value.n < 0:
                sign = " - "
                term = Num(-term.value)
            elif isinstance(term, Mul) and isinstance(term.factors[0], Num) and term.factors[0].value.n < 0:
                sign = " - "
                term = Mul((Num(-term.factors[0].value),) + term.factors[1:])
            pieces.append((sign, _render(term, "add")))
        body = ""
        for index, (sign, rendered) in enumerate(pieces):
            if index == 0:
                body += ("-" if sign == " - " else "") + rendered
            else:
                body += sign + rendered
        return f"({body})" if parent in {"mul", "pow", "div"} else body
    if isinstance(node, Mul):
        factors = node.factors
        if isinstance(factors[0], Num):
            head = _render(factors[0])
            if factors[0].value == ONE:
                head = ""
            elif factors[0].value == Rational(-1, 1):
                head = "-"
            body = head + "".join(_render(f, "mul") for f in factors[1:])
        else:
            body = " \\cdot ".join(_render(f, "mul") for f in factors)
        # A product is atomic in additions/divisions; only a power needs parens.
        return f"({body})" if parent == "pow" else body
    if isinstance(node, Pow):
        base = _render(node.base, "pow")
        return f"({base})^{{{node.exp}}}" if not isinstance(node.base, (Num, Var)) else f"{base}^{{{node.exp}}}"
    if isinstance(node, Div):
        return f"\\frac{{{_render(node.num)}}}{{{_render(node.den)}}}"
    if isinstance(node, Equation):
        return f"{_render(node.lhs)} = {_render(node.rhs)}"
    raise TypeError(f"unknown node: {node!r}")


def to_latex(node: Node) -> str:
    if isinstance(node, LinearSystem):
        return r"\begin{cases}" + r" \\ ".join(to_latex(eq) for eq in node.equations) + r"\end{cases}"
    return _render(node)


def poly_to_latex(coeffs: dict[int, Fraction], var_name: str) -> str:
    """Render a coefficient vector as a polynomial expression."""
    if coeffs == {0: Fraction(0)}:
        return "0"
    parts: list[str] = []
    for degree in sorted(coeffs, reverse=True):
        coeff = coeffs[degree]
        if coeff == 0:
            continue
        abs_coeff = abs(coeff)
        if degree == 0:
            abs_part = (
                str(abs_coeff.numerator)
                if abs_coeff.denominator == 1
                else f"\\frac{{{abs_coeff.numerator}}}{{{abs_coeff.denominator}}}"
            )
        elif degree == 1:
            if abs_coeff == 1:
                abs_part = var_name
            elif abs_coeff.denominator == 1:
                abs_part = f"{abs_coeff.numerator}{var_name}"
            else:
                abs_part = f"\\frac{{{abs_coeff.numerator}}}{{{abs_coeff.denominator}}}{var_name}"
        else:
            power = f"{var_name}^{{{degree}}}"
            if abs_coeff == 1:
                abs_part = power
            elif abs_coeff.denominator == 1:
                abs_part = f"{abs_coeff.numerator}{power}"
            else:
                abs_part = f"\\frac{{{abs_coeff.numerator}}}{{{abs_coeff.denominator}}}{power}"
        if not parts:
            parts.append(("-" if coeff < 0 else "") + abs_part)
        else:
            parts.append((" + " if coeff > 0 else " - ") + abs_part)
    return "".join(parts)


__all__ = [
    "Add",
    "Div",
    "Equation",
    "LinearSystem",
    "MathComplexityError",
    "MathDomainError",
    "Mul",
    "Num",
    "ONE",
    "Pow",
    "Rational",
    "Var",
    "ZERO",
    "add",
    "div",
    "eq",
    "equation_difference",
    "evaluate",
    "from_dict",
    "mul",
    "node_key",
    "num",
    "poly_coeffs",
    "poly_to_latex",
    "pow",
    "to_dict",
    "to_latex",
    "var",
    "variables",
]
