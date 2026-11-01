"""Exact affine algebra for two equations in two variables; no symbolic guessing."""
from __future__ import annotations

from fractions import Fraction
from functools import reduce

from mathtutor.solving import nodes as n
from mathtutor.solving.budget import fraction_add, fraction_sub, fraction_mul, fraction_div


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
            return tuple(reduce(fraction_add, (value[index] for value in values), Fraction(0))
                         for index in range(len(variables) + 1))
        if isinstance(item, n.Mul):
            result = (*zeros, Fraction(1))
            for factor in item.factors:
                right = walk(factor, depth + 1)
                if any(result[:-1]) and any(right[:-1]):
                    raise n.MathDomainError("当前方程组只支持一次项，不支持未知数乘积")
                result = tuple(fraction_add(fraction_mul(result[i], right[-1]), fraction_mul(right[i], result[-1]))
                               for i in range(len(variables))) + (fraction_mul(result[-1], right[-1]),)
            return result
        if isinstance(item, n.Div):
            if n.variables(item.den):
                raise n.MathDomainError("方程组分母不能包含未知数")
            denominator = n.evaluate(item.den).to_fraction()
            if not denominator:
                raise n.MathDomainError("division by zero")
            return tuple(fraction_div(value, denominator) for value in walk(item.num, depth + 1))
        if isinstance(item, n.Pow) and not n.variables(item):
            return (*zeros, n.evaluate(item).to_fraction())
        raise n.MathDomainError("当前仅支持二元一次方程组")
    return walk(node)


def equation_row(equation: n.Equation, variables: tuple[str, ...]) -> tuple[Fraction, ...]:
    left, right = affine(equation.lhs, variables), affine(equation.rhs, variables)
    return tuple(fraction_sub(left[index], right[index]) for index in range(len(variables))) + (fraction_sub(right[-1], left[-1]),)


def system_rows(ast: n.LinearSystem):
    if not isinstance(ast, n.LinearSystem) or len(ast.equations) != 2:
        raise n.MathDomainError("当前需要两个一次方程")
    variables = tuple(sorted(n.variables(ast)))
    if len(variables) != 2:
        raise n.MathDomainError("当前方程组必须恰好有两个未知数")
    rows = tuple(equation_row(eq, variables) for eq in ast.equations)
    if fraction_sub(fraction_mul(rows[0][0], rows[1][1]), fraction_mul(rows[1][0], rows[0][1])) == 0:
        raise n.MathDomainError("该方程组没有唯一解，当前验证策略不支持无解或无穷多解")
    return variables, rows


def independent_values(ast: n.LinearSystem) -> dict[str, Fraction]:
    """Small exact Gaussian elimination, also used for partial-claim checks."""
    variables, rows = system_rows(ast)
    matrix = [list(row) for row in rows]
    if matrix[0][0] == 0:
        matrix.reverse()
    scale = matrix[0][0]
    matrix[0] = [fraction_div(value, scale) for value in matrix[0]]
    scale = matrix[1][0]
    matrix[1] = [fraction_sub(matrix[1][i], fraction_mul(scale, matrix[0][i])) for i in range(3)]
    second = fraction_div(matrix[1][2], matrix[1][1])
    first = fraction_sub(matrix[0][2], fraction_mul(matrix[0][1], second))
    return dict(zip(variables, (first, second)))
