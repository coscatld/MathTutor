"""Scene v2 whitelist compiler and evaluator."""
import math

import pytest

from mathtutor.application.scene_expr import (
    SceneExprError, compile_expr, evaluate, point_refs, variables)

X, Y = {"k": "var", "n": "x"}, {"k": "var", "n": "y"}


def num(v):
    return {"k": "num", "v": float(v)}


@pytest.mark.parametrize("source, ast", [
    ("2x", {"k": "op", "o": "*", "a": [num(2), X]}),
    ("x(x+1)", {"k": "op", "o": "*", "a": [X, {"k": "op", "o": "+", "a": [X, num(1)]}]}),
    ("-x^2", {"k": "neg", "a": [{"k": "op", "o": "^", "a": [X, num(2)]}]}),
    ("2sin(x)", {"k": "op", "o": "*", "a": [num(2), {"k": "fn", "f": "sin", "a": [X]}]}),
    ("|x|+|y|", {"k": "op", "o": "+", "a": [{"k": "fn", "f": "abs", "a": [X]}, {"k": "fn", "f": "abs", "a": [Y]}]}),
    ("kx", {"k": "op", "o": "*", "a": [{"k": "var", "n": "k"}, X]}),
    ("atan2(y,x)", {"k": "fn", "f": "atan2", "a": [Y, X]}),
    ("dist(P,A)+P.x", {"k": "op", "o": "+", "a": [{"k": "geo", "f": "dist", "p": ["P", "A"]}, {"k": "coord", "p": "P", "c": "x"}]}),
    ("pi", num(math.pi)),
    ("\\frac{x}{2}", {"k": "op", "o": "/", "a": [X, num(2)]}),
    ("x²", {"k": "op", "o": "^", "a": [X, num(2)]}),
])
def test_exact_ast_shapes(source, ast):
    assert compile_expr(source) == ast


@pytest.mark.parametrize("source", [
    "2(x+1)", "2|x|", "\\sqrt{x^2+1}", "\\frac{\\sqrt{3}}{2}x", "3×x÷2", "x−1", "2·x", "x\\cdot y", "\\pi x",
    "\\sin x", "e^x", "x^{2}+1", "min(x,1)+max(y,2)", "angle(A,B,C)", "area(A,B,C,D)", "mid_x(A,B)+mid_y(A,B)",
    "slope(P,A1)", "sign(x)+floor(x)+ceil(x)+ln(x)+log(x)+exp(x)", "asin(x)+acos(x)+atan(x)+tan(x)+cos(x)",
])
def test_accepts_whitelisted_input(source):
    compile_expr(source)


@pytest.mark.parametrize("source", [
    "__import__('os')", "open(x)", "x.__class__", "eval(x)", "lambda: 1", "x;y", "x#", "foo_bar(x)", "x+", "",
    "\\int x", "dist(1+2,A)", "angle(A,B)", "min(x)", "sin(x,y)", "(" * 50 + "x" + ")" * 50, "+".join(["x"] * 300),
    "x" * 500, "P.z",
])
def test_rejects_everything_else(source):
    with pytest.raises(SceneExprError):
        compile_expr(source)


def test_error_is_a_value_error_with_chinese_text():
    with pytest.raises(ValueError, match="看不懂"):
        compile_expr("open(x)")


def test_too_deep_is_rejected_even_when_short():
    with pytest.raises(SceneExprError, match="太深|太长"):
        compile_expr("-" * 60 + "x")


def test_variables_and_point_refs():
    ast = compile_expr("a*x + dist(P,Q) + R.y")
    assert variables(ast) == {"a", "x"}
    assert point_refs(ast) == {"P", "Q", "R"}


def test_rename_maps_theta_to_s():
    assert variables(compile_expr("2(1+cos θ)", rename={"θ": "s"})) == {"s"}
    assert variables(compile_expr("\\theta")) == {"θ"}


@pytest.mark.parametrize("source, env, value", [
    ("2x+1", {"x": 3}, 7), ("x^2/4+y^2/3", {"x": 2, "y": 0}, 1), ("log(100)", {}, 2), ("ln(e)", {}, 1),
    ("(-8)^(1/3)", {}, -2), ("sign(-3)+abs(-2)", {}, 1), ("min(1,2)+max(1,2)", {}, 3), ("atan2(1,1)", {}, math.pi / 4),
])
def test_evaluator_values(source, env, value):
    assert evaluate(compile_expr(source), env) == pytest.approx(value)


def test_geometric_functions():
    points = {"A": (0.0, 0.0), "B": (3.0, 0.0), "C": (3.0, 4.0), "V": (0.0, 5.0)}
    assert evaluate(compile_expr("dist(A,C)"), points=points) == pytest.approx(5)
    assert evaluate(compile_expr("slope(A,C)"), points=points) == pytest.approx(4 / 3)
    assert evaluate(compile_expr("angle(A,B,C)"), points=points) == pytest.approx(90)
    assert evaluate(compile_expr("area(A,B,C)"), points=points) == pytest.approx(6)
    assert evaluate(compile_expr("area(C,B,A)"), points=points) == pytest.approx(6)
    assert evaluate(compile_expr("mid_x(A,C)+mid_y(A,C)"), points=points) == pytest.approx(3.5)
    assert evaluate(compile_expr("C.x*C.y"), points=points) == pytest.approx(12)
    assert evaluate(compile_expr("slope(A,V)"), points=points) is None


@pytest.mark.parametrize("source, env", [
    ("1/x", {"x": 0}), ("sqrt(x)", {"x": -1}), ("ln(0)", {}), ("(-8)^(1/2)", {}), ("asin(2)", {}), ("exp(1000)", {}),
    ("k*x", {"x": 1}),
])
def test_undefined_values_are_none(source, env):
    assert evaluate(compile_expr(source), env) is None
