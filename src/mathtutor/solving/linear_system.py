"""Exact affine algebra for two equations in two variables; no symbolic guessing."""
from __future__ import annotations

from fractions import Fraction

from mathtutor.solving import nodes as n


def affine(node: n.Node, variables: tuple[str, ...]) -> tuple[Fraction, ...]:
    """Coefficients followed by constant; products of variables are unsupported."""
    budget = [0]
    def walk(item, depth=0):
        budget[0] += 1
        if budget[0] > 512 or depth > 64:
            raise n.MathComplexityError("方程组超出计算预算")
        zeros = (Fraction(0),) * len(variables)
        if isinstance(item, n.Num):
            return (*zeros, item.value.to_fraction())
        if isinstance(item, n.Var):
            if item.name not in variables:
                raise n.MathDomainError("方程组含额外未知数")
            return tuple(Fraction(int(name == item.name)) for name in variables) + (Fraction(0),)
        if isinstance(item, n.Add):
            values = [walk(term, depth + 1) for term in item.terms]
            return tuple(sum(value[index] for value in values) for index in range(len(variables) + 1))
        if isinstance(item, n.Mul):
            result = (*zeros, Fraction(1))
            for factor in item.factors:
                right = walk(factor, depth + 1)
                if any(result[:-1]) and any(right[:-1]):
                    raise n.MathDomainError("当前方程组只支持一次项，不支持未知数乘积")
                result = tuple(result[i] * right[-1] + right[i] * result[-1] for i in range(len(variables))) + (result[-1] * right[-1],)
            return result
        if isinstance(item, n.Div):
            if n.variables(item.den):
                raise n.MathDomainError("方程组分母不能包含未知数")
            denominator = n.evaluate(item.den).to_fraction()
            if not denominator:
                raise n.MathDomainError("division by zero")
            return tuple(value / denominator for value in walk(item.num, depth + 1))
        if isinstance(item, n.Pow) and not n.variables(item):
            return (*zeros, n.evaluate(item).to_fraction())
        raise n.MathDomainError("当前仅支持二元一次方程组")
    return walk(node)


def equation_row(equation: n.Equation, variables: tuple[str, ...]) -> tuple[Fraction, ...]:
    left, right = affine(equation.lhs, variables), affine(equation.rhs, variables)
    return tuple(left[index] - right[index] for index in range(len(variables))) + (right[-1] - left[-1],)


def system_rows(ast: n.LinearSystem):
    if not isinstance(ast, n.LinearSystem) or len(ast.equations) != 2:
        raise n.MathDomainError("当前需要两个一次方程")
    variables = tuple(sorted(n.variables(ast)))
    if len(variables) != 2:
        raise n.MathDomainError("当前方程组必须恰好有两个未知数")
    rows = tuple(equation_row(eq, variables) for eq in ast.equations)
    if rows[0][0] * rows[1][1] - rows[1][0] * rows[0][1] == 0:
        raise n.MathDomainError("该方程组没有唯一解，当前验证策略不支持无解或无穷多解")
    return variables, rows


def independent_values(ast: n.LinearSystem) -> dict[str, Fraction]:
    """Small exact Gaussian elimination, also used for partial-claim checks."""
    variables, rows = system_rows(ast)
    matrix = [list(row) for row in rows]
    if matrix[0][0] == 0:
        matrix.reverse()
    scale = matrix[0][0]
    matrix[0] = [value / scale for value in matrix[0]]
    scale = matrix[1][0]
    matrix[1] = [matrix[1][i] - scale * matrix[0][i] for i in range(3)]
    second = matrix[1][2] / matrix[1][1]
    first = matrix[0][2] - matrix[0][1] * second
    return dict(zip(variables, (first, second)))
