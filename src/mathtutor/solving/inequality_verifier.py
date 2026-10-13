"""Replay the linear transforms, then check the range against an independent solution."""
from __future__ import annotations

from mathtutor.domain.solution import VerificationCheck, VerificationDecision
from mathtutor.solving import nodes as n
from mathtutor.solving.strategies import _common as c
from mathtutor.solving.strategies.inequality import solved_form


def verify_inequality(problem, candidate):
    checks = []

    def record(name, okay, detail=""):
        checks.append(VerificationCheck(name=name, status="passed" if okay else "failed", detail=detail if not okay else ""))

    try:
        payload = problem.normalized_ast
        equation_payload = payload.get("equation") if isinstance(payload, dict) else None
        equation = n.from_dict(equation_payload)
        relation = payload.get("relation")
        variable = payload.get("variable")
        record(
            "parse_round_trip",
            isinstance(equation, n.Equation) and n.to_dict(equation) == equation_payload and relation in {"gt", "ge", "lt", "le"} and isinstance(variable, str),
            "不等式规范形式不能回放",
        )
        kept, boundary = solved_form(equation, variable, relation)
        record("domain", True)
        lhs, rhs = c.equation_sides(equation, variable)
        current = {"lhs": c.coeffs_to_dict(lhs), "rhs": c.coeffs_to_dict(rhs)}
        step_ok = bool(candidate.steps)
        for step in candidate.steps:
            transform = step.get("transform") if isinstance(step, dict) else None
            if not isinstance(transform, dict) or step.get("before") != current:
                step_ok = False
                break
            after = c.apply_transform(current, transform)
            if step.get("after") != after:
                step_ok = False
                break
            current = after
        record("step_relation", step_ok, "移项或系数化步骤不能回放")
        answer = candidate.final_answer
        claimed = c.frac_from_dict(answer["boundary"]) if isinstance(answer, dict) and isinstance(answer.get("boundary"), dict) else None
        record(
            "final_answer",
            isinstance(answer, dict) and answer.get("kind") == "inequality" and answer.get("relation") == kept
            and answer.get("variable") == variable and claimed == boundary,
            "取值范围与独立求解不一致",
        )
    except (KeyError, TypeError, ValueError, ZeroDivisionError, n.MathDomainError, n.MathComplexityError) as exc:
        record("domain", False, str(exc))
    required = {"parse_round_trip", "domain", "step_relation", "final_answer"}
    coverage = (
        required <= {check.name for check in checks if check.status == "passed"}
        and candidate.strategy == "linear_inequality"
        and candidate.problem_id == problem.problem_id
        and candidate.final_answer.get("kind") == "inequality"
    )
    record("policy_coverage", coverage, "不等式验证策略或必需检查不完整")
    return VerificationDecision.canonicalize(
        candidate_id=candidate.candidate_id,
        candidate_payload_hash=candidate.payload_hash,
        problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash,
        policy_id="mt-ver-pol-linear-inequality",
        policy_version="v1",
        verdict="VERIFIED" if all(check.status == "passed" for check in checks) else "FAILED",
        checks=tuple(checks),
    )
