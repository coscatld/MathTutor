"""Exact, bounded polynomial derivative checks for the local math tool.

This is a conclusion checker, not a general CAS or a proof of a function's
properties. ``derivative(expression, x)`` deliberately requires an explicit
operation and variable, so an equation, a function value, or a prose claim
cannot accidentally be interpreted as a derivative. Unsupported functions,
parameters and variable denominators stay unchecked.

Only a whitelisted Python *syntax tree* is read; no Python code is evaluated.
All coefficients are exact fractions and all operations have resource bounds.
"""

from __future__ import annotations

import ast
from fractions import Fraction
import re

MAX_EXPRESSION_CHARS = 200
MAX_DEGREE = 12
MAX_AST_NODES = 128
MAX_DEPTH = 20
MAX_COEFFICIENT_BITS = 4096

_REQUEST = re.compile(r"^derivative\(\s*(.+)\s*,\s*([A-Za-z])\s*\)$", re.S)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


class UnsupportedCalculus(ValueError):
    """The operation cannot be decided by this bounded polynomial checker."""


Polynomial = dict[int, Fraction]


def _bounded(coefficients: Polynomial) -> Polynomial:
    result = {degree: coefficient for degree, coefficient in coefficients.items() if coefficient}
    if any(degree > MAX_DEGREE for degree in result):
        raise UnsupportedCalculus("polynomial_degree_budget")
    if any(max(abs(c.numerator).bit_length(), c.denominator.bit_length()) > MAX_COEFFICIENT_BITS
           for c in result.values()):
        raise UnsupportedCalculus("coefficient_budget")
    return result


def _add(left: Polynomial, right: Polynomial, scale: int = 1) -> Polynomial:
    result = dict(left)
    for degree, coefficient in right.items():
        result[degree] = result.get(degree, Fraction(0)) + scale * coefficient
    return _bounded(result)


def _multiply(left: Polynomial, right: Polynomial) -> Polynomial:
    result: Polynomial = {}
    for a, ca in left.items():
        for b, cb in right.items():
            if a + b > MAX_DEGREE:
                raise UnsupportedCalculus("polynomial_degree_budget")
            result[a + b] = result.get(a + b, Fraction(0)) + ca * cb
    return _bounded(result)


def _parse_polynomial(text: str, variable: str) -> Polynomial:
    if not text or len(text) > MAX_EXPRESSION_CHARS:
        raise UnsupportedCalculus("expression_length_budget")
    # Avoid silently treating function names, parameters or attributes as
    # implicit products. The only identifier permitted is the chosen variable.
    if any(identifier != variable for identifier in _IDENTIFIER.findall(text)):
        raise UnsupportedCalculus("polynomial_variables_or_functions")
    source = text.replace("−", "-").replace("×", "*").replace("·", "*").replace("÷", "/")
    source = source.replace("^", "**")
    # Conventional 3x, 2(x+1), x(x+1), and (x+1)(x-1) are safe products.
    source = re.sub(rf"(?<=[0-9)])(?={re.escape(variable)})", "*", source)
    source = re.sub(rf"(?<=[0-9){re.escape(variable)}])(?=\()", "*", source)
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise UnsupportedCalculus("polynomial_syntax") from exc
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        raise UnsupportedCalculus("polynomial_node_budget")

    def visit(node: ast.AST, depth: int = 0) -> Polynomial:
        if depth > MAX_DEPTH:
            raise UnsupportedCalculus("polynomial_depth_budget")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            literal = ast.get_source_segment(source, node) or ""
            # Exclude booleans, hex, scientific notation, nan/inf and other
            # Python literals; decimal text is converted directly to Fraction.
            if not re.fullmatch(r"(?:\d+(?:\.\d*)?|\.\d+)", literal):
                raise UnsupportedCalculus("polynomial_number_syntax")
            return _bounded({0: Fraction(literal)})
        if isinstance(node, ast.Name) and node.id == variable:
            return {1: Fraction(1)}
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand, depth + 1)
            return value if isinstance(node.op, ast.UAdd) else {d: -c for d, c in value.items()}
        if isinstance(node, ast.BinOp):
            left = visit(node.left, depth + 1)
            if isinstance(node.op, ast.Pow):
                # Read the literal exponent without evaluating nested powers.
                if not (isinstance(node.right, ast.Constant) and type(node.right.value) is int
                        and 1 <= node.right.value <= MAX_DEGREE):
                    raise UnsupportedCalculus("polynomial_power_budget")
                result = {0: Fraction(1)}
                for _ in range(node.right.value):
                    result = _multiply(result, left)
                return result
            right = visit(node.right, depth + 1)
            if isinstance(node.op, ast.Add):
                return _add(left, right)
            if isinstance(node.op, ast.Sub):
                return _add(left, right, -1)
            if isinstance(node.op, ast.Mult):
                return _multiply(left, right)
            if isinstance(node.op, ast.Div):
                if set(right) != {0} or right[0] == 0:
                    raise UnsupportedCalculus("polynomial_denominator")
                return _bounded({d: c / right[0] for d, c in left.items()})
        raise UnsupportedCalculus("polynomial_syntax")

    return visit(tree.body)


def check_polynomial_derivative(expression: str, answer: str) -> tuple[str, str] | None:
    """Return (status, signal), or None when this is not a calculus request.

    Verification establishes only equality with the polynomial's derivative
    over the reals. It does not establish extrema, monotonicity, a domain for
    a larger expression, or correctness of surrounding mathematical prose.
    """
    if not expression.strip().startswith("derivative("):
        return None
    request = _REQUEST.fullmatch(expression.strip())
    if not request:
        return "unchecked", "polynomial_derivative_syntax"
    source, variable = request.groups()
    try:
        original = _parse_polynomial(source.strip(), variable)
        proposed = _parse_polynomial(answer.strip(), variable)
        derivative = _bounded({degree - 1: degree * coefficient
                               for degree, coefficient in original.items() if degree})
    except (UnsupportedCalculus, ArithmeticError, RecursionError, ValueError) as exc:
        return "unchecked", str(exc) if isinstance(exc, UnsupportedCalculus) else "polynomial_calculus_undetermined"
    if derivative == proposed:
        return "verified", "exact_polynomial_derivative"
    return "refuted", "polynomial_derivative_mismatch"


def derivative_question_receipt(text: str) -> dict | None:
    """Recognize a complete derivative request and reuse the exact coefficient rule."""
    from mathtutor.application.input_normalizer import normalize_input
    from mathtutor.solving.nodes import poly_to_latex

    source = normalize_input(text).normalized.strip().rstrip("?.。？")
    request = _REQUEST.fullmatch(source)
    if request:
        expression, variable = request.groups()
    else:
        patterns = (
            r"(?:How do I\s+)?differentiate\s+(.+)",
            r"Find the derivative of\s+(.+)",
            r"(?:请)?(?:如何)?对\s*(.+?)\s*求导",
            r"(.+?)\s*(?:的导数|求导)",
            r"(?:对)?(.+?)\s*求导数",
        )
        match = next((m for pattern in patterns if (m := re.fullmatch(pattern, source, re.I))), None)
        if match is None:
            return None
        expression = match[1].strip()
        variables = set(re.findall(r"[A-Za-z]", expression))
        if len(variables) != 1:
            return None
        variable = variables.pop()
    try:
        coefficients = _parse_polynomial(expression, variable)
        derivative = _bounded({degree - 1: degree * coefficient
                               for degree, coefficient in coefficients.items() if degree})
        answer = "+".join(f"({value})*{variable}^{degree}" if degree else f"({value})"
                          for degree, value in sorted(derivative.items())) or "0"
        if check_polynomial_derivative(f"derivative({expression},{variable})", answer) != (
                "verified", "exact_polynomial_derivative"):
            return None
    except (UnsupportedCalculus, ArithmeticError, RecursionError, ValueError):
        return None
    return {"status": "verified", "scope": "polynomial_derivative", "expression": expression,
            "variable": variable, "answer": answer, "display_latex": poly_to_latex(derivative, variable),
            "signal": "exact_polynomial_derivative"}
