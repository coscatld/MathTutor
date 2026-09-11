"""System release authority: unique domain, replayed elimination, both original equations."""
from mathtutor.domain.solution import VerificationCheck, VerificationDecision
from mathtutor.solving import nodes as n
from mathtutor.solving.linear_system import system_rows, independent_values
from mathtutor.solving.strategies import _common as c


def verify_system(problem, candidate):
    checks = []
    def record(name, okay, detail=""):
        checks.append(VerificationCheck(name=name, status="passed" if okay else "failed", detail=detail if not okay else ""))
    try:
        ast = n.from_dict(problem.normalized_ast)
        record("parse_round_trip", n.to_dict(ast) == problem.normalized_ast)
        variables, rows = system_rows(ast)
        record("domain", True)
        expected = independent_values(ast)
        claimed = {name: c.frac_from_dict(value) for name, value in candidate.final_answer["values"].items()}
        record("completeness", set(claimed) == set(variables), "必须给出两个未知数")
        record("final_answer", claimed == expected, "完整解与独立消元计算不一致")
        residuals = [row[0] * claimed.get(variables[0], 0) + row[1] * claimed.get(variables[1], 0) - row[2] for row in rows]
        record("extraneous_roots", set(claimed) == set(variables) and all(value == 0 for value in residuals), "解不能同时满足原方程")
        steps = candidate.steps
        step_ok = len(steps) == 4 and [step.get("kind") for step in steps] == ["eliminate", "solve_variable", "back_substitution", "substitution"]
        if step_ok:
            source = tuple(tuple(c.frac_from_dict(value) for value in row) for row in steps[0]["source_rows"])
            factors = tuple(c.frac_from_dict(value) for value in steps[0]["factors"])
            result = tuple(c.frac_from_dict(value) for value in steps[0]["result_row"])
            replayed = tuple(rows[0][i] * factors[0] + rows[1][i] * factors[1] for i in range(3))
            step_ok = (source == rows and factors == (rows[1][1], -rows[0][1]) and result == replayed
                       and result[0] != 0 and result[1] == 0 and result[0] * claimed[variables[0]] == result[2])
            step_ok = step_ok and steps[0]["variable"] == variables[0]
            step_ok = step_ok and steps[1]["variable"] == variables[0] and c.frac_from_dict(steps[1]["value"]) == claimed[variables[0]]
            row = rows[steps[2]["source_row_index"]]
            step_ok = (step_ok and steps[2]["variable"] == variables[1]
                       and c.frac_from_dict(steps[2]["coefficient"]) == row[1] != 0
                       and c.frac_from_dict(steps[2]["rhs"]) == row[2] - row[0] * claimed[variables[0]])
            step_ok = step_ok and {name: c.frac_from_dict(value) for name, value in steps[3]["values"].items()} == claimed
            step_ok = step_ok and tuple(c.frac_from_dict(value) for value in steps[3]["residuals"]) == tuple(residuals)
        record("step_relation", step_ok, "消元或代回步骤不完整/不能回放")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError, n.MathDomainError, n.MathComplexityError) as exc:
        record("domain", False, str(exc))
    required = {"parse_round_trip", "domain", "step_relation", "final_answer", "completeness", "extraneous_roots"}
    coverage = (required <= {check.name for check in checks if check.status == "passed"}
                and candidate.strategy == "linear_system" and candidate.problem_id == problem.problem_id
                and candidate.final_answer.get("kind") == "assignments")
    record("policy_coverage", coverage, "方程组验证策略或必需检查不完整")
    return VerificationDecision.canonicalize(candidate_id=candidate.candidate_id,
        candidate_payload_hash=candidate.payload_hash, problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash, policy_id="mt-ver-pol-linear-system", policy_version="v1",
        verdict="VERIFIED" if all(check.status == "passed" for check in checks) else "FAILED", checks=tuple(checks))
