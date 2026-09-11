"""Partial coordinates/valid elimination never mark the whole system completed."""
from mathtutor.solving import nodes as n
from mathtutor.solving.linear_system import equation_row, independent_values, system_rows
from mathtutor.solving.strategies import _common as c


def verify_system_attempt(problem_ast, answer, base):
    from mathtutor.learning.attempt_verifier import AttemptAssessment, Correctness
    try:
        variables, _ = system_rows(problem_ast)
        expected = independent_values(problem_ast)
        ast = answer.parsed.ast if answer.parsed else None
        equations = ast.equations if isinstance(ast, n.LinearSystem) else (ast,) if isinstance(ast, n.Equation) else ()
        if not equations:
            return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason="请说明每个数对应哪个未知数，例如 x=3；y=1", **base)
        claims = {}
        intermediates = []
        for eq in equations:
            if not n.variables(eq).issubset(variables):
                return AttemptAssessment(correctness=Correctness.INCORRECT, signals=("wrong_family",), reason="出现原题没有的未知数", **base)
            row = equation_row(eq, variables)
            if sum(row[i] * expected[name] for i, name in enumerate(variables)) != row[-1]:
                return AttemptAssessment(correctness=Correctness.INCORRECT, score=0.0,
                    signals=("wrong_value",), invalid_claims=({"claim": "system_equation", "equation": n.to_dict(eq)},),
                    reason="这一步不能由原方程组的解满足", **base)
            assignment = None
            if isinstance(eq.lhs, n.Var) and not n.variables(eq.rhs):
                assignment = (eq.lhs.name, n.evaluate(eq.rhs).to_fraction())
            elif isinstance(eq.rhs, n.Var) and not n.variables(eq.lhs):
                assignment = (eq.rhs.name, n.evaluate(eq.lhs).to_fraction())
            if assignment:
                name, value = assignment
                if name in claims and claims[name] != value:
                    return AttemptAssessment(correctness=Correctness.INCORRECT, score=0.0, signals=("conflicting_claims",), **base)
                claims[name] = value
            else:
                intermediates.append({"claim": "valid_system_intermediate", "equation": n.to_dict(eq)})
        verified = tuple({"claim": "variable_value", "variable": name, "value": c.frac_to_dict(value)} for name, value in claims.items()) + tuple(intermediates)
        remaining = tuple({"claim": "solve_variable", "variable": name} for name in variables if name not in claims)
        if not remaining and claims == expected:
            return AttemptAssessment(correctness=Correctness.CORRECT, score=1.0,
                verified_claims=verified + ({"claim": "all_original_equations_satisfied"},), **base)
        return AttemptAssessment(correctness=Correctness.PARTIAL, score=0.5, verified_claims=verified,
            remaining_requirements=remaining, signals=("missing_variable",) if claims else ("equivalent_equation",),
            reason="已验证局部结果；还需要求出其余未知数并代回原方程组", **base)
    except (TypeError, ValueError, KeyError, ZeroDivisionError, n.MathDomainError, n.MathComplexityError) as exc:
        return AttemptAssessment(correctness=Correctness.UNDETERMINED, reason=f"方程组作答暂时无法验证：{exc}", **base)
