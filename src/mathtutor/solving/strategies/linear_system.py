"""Replayable elimination then substitution for a unique two-variable system."""
from mathtutor.solving.linear_system import system_rows
from mathtutor.solving.strategies import _common as c
from mathtutor.solving import nodes as n

STRATEGY_NAME = "mt-linear-system-v1"


def solve(parsed):
    variables, rows = system_rows(parsed.ast)
    (a, b, rhs), (d, e, other) = rows
    determinant = a * e - d * b
    first = (rhs * e - other * b) / determinant
    second = (rhs - a * first) / b if b else (other - d * first) / e
    values = {variables[0]: c.frac_to_dict(first), variables[1]: c.frac_to_dict(second)}
    row_json = [[c.frac_to_dict(value) for value in row] for row in rows]
    eliminated = [determinant, 0 * determinant, rhs * e - other * b]
    substitute_row = 0 if b else 1
    row = rows[substitute_row]
    steps = (
        {"label": "消元：将两个方程作等价线性组合", "kind": "eliminate",
         "source_rows": row_json, "factors": [c.frac_to_dict(e), c.frac_to_dict(-b)],
         "result_row": [c.frac_to_dict(value) for value in eliminated], "variable": variables[0]},
        {"label": f"求出 {variables[0]} 的值", "kind": "solve_variable", "variable": variables[0], "value": c.frac_to_dict(first)},
        {"label": "代回一个原方程，保留另一个未知数继续求解", "kind": "back_substitution",
         "source_row_index": substitute_row, "variable": variables[1],
         "coefficient": c.frac_to_dict(row[1]), "rhs": c.frac_to_dict(row[2] - row[0] * first)},
        {"label": "将两个未知数的值代回原来的两个方程", "kind": "substitution",
         "values": values, "residuals": [c.frac_to_dict(0 * determinant), c.frac_to_dict(0 * determinant)]},
    )
    latex = ",\\quad ".join(f"{name}={n.to_latex(n.num(n.Rational.from_fraction(value)))}" for name, value in zip(variables, (first, second)))
    return steps, {"kind": "assignments", "values": values, "latex": latex}
