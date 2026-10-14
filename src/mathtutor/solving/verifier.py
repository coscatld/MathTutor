"""Independent verifier: decisions, never trusts the solver.

Implements the check table of design doc §6.3 over one candidate:

- ``parse_round_trip`` — the canonical AST serialization replays exactly;
- ``domain`` — no zero divisor, equation leading coefficient != 0, no
  variables in arithmetic;
- ``step_relation`` — every recorded step is re-derived independently;
- ``final_answer`` — the independently computed answer equals the
  candidate's claimed answer;
- ``completeness`` — all roots are present (equations);
- ``extraneous_roots`` — every root substitutes back to exactly zero;
- ``policy_coverage`` — the family policy matched, all required checks ran
  and none failed, no unsupported claims.

``VERIFIED`` additionally requires the problem/candidate hash binding to be
consistent; the repository is the only component that can then issue an
attestation (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Iterator

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerificationCheck,
    VerificationDecision,
)
from mathtutor.solving import nodes as n
from mathtutor.solving.strategies import _common as c
from mathtutor.solving.strategies import quadratic as q


@dataclass(frozen=True, slots=True)
class VerificationPolicy:
    policy_id: str
    family: str
    version: str
    required_checks: tuple[str, ...]


POLICIES: dict[str, VerificationPolicy] = {
    "linear_system": VerificationPolicy("mt-ver-pol-linear-system", "linear_system", "v1",
        ("parse_round_trip", "domain", "step_relation", "final_answer", "completeness", "extraneous_roots", "policy_coverage")),
    "arithmetic": VerificationPolicy(
        "mt-ver-pol-arithmetic", "arithmetic", "v1",
        ("parse_round_trip", "domain", "step_relation", "final_answer", "policy_coverage"),
    ),
    "polynomial": VerificationPolicy(
        "mt-ver-pol-polynomial", "polynomial", "v1",
        ("parse_round_trip", "domain", "step_relation", "final_answer", "policy_coverage"),
    ),
    "linear": VerificationPolicy(
        "mt-ver-pol-linear", "linear", "v1",
        ("parse_round_trip", "domain", "step_relation", "final_answer",
         "completeness", "extraneous_roots", "policy_coverage"),
    ),
    "linear_inequality": VerificationPolicy(
        "mt-ver-pol-linear-inequality", "linear_inequality", "v1",
        ("parse_round_trip", "domain", "step_relation", "final_answer", "policy_coverage"),
    ),
    "quadratic_inequality": VerificationPolicy(
        "mt-ver-pol-quadratic-inequality", "quadratic_inequality", "v1",
        ("parse_round_trip", "domain", "step_relation", "final_answer", "policy_coverage"),
    ),
    "quadratic": VerificationPolicy(
        "mt-ver-pol-quadratic", "quadratic", "v1",
        ("parse_round_trip", "domain", "step_relation", "final_answer",
         "completeness", "extraneous_roots", "policy_coverage"),
    ),
}

_ALLOWED_FINAL_KINDS = {
    "arithmetic": {"rational"},
    "polynomial": {"polynomial"},
    "linear": {"roots"},
    "quadratic": {"roots"},
}
_ALLOWED_ROOT_KINDS = {
    "linear": {"rational"},
    "quadratic": {"rational", "surd"},
}


class _Checks:
    def __init__(self) -> None:
        self.results: list[VerificationCheck] = []

    def record(self, name: str, passed: bool, detail: str = "") -> None:
        self.results.append(
            VerificationCheck(name=name, status="passed" if passed else "failed", detail=detail)
        )

    def failed_any(self) -> bool:
        return any(check.status == "failed" for check in self.results)


def _walk(node: n.Node) -> Iterator[n.Node]:
    if isinstance(node, n.Equation):
        yield node
        yield from _walk(node.lhs)
        yield from _walk(node.rhs)
    elif isinstance(node, n.Add):
        yield node
        for term in node.terms:
            yield from _walk(term)
    elif isinstance(node, n.Mul):
        yield node
        for factor in node.factors:
            yield from _walk(factor)
    elif isinstance(node, n.Pow):
        yield node
        yield from _walk(node.base)
    elif isinstance(node, n.Div):
        yield node
        yield from _walk(node.num)
        yield from _walk(node.den)
    else:
        yield node


def _equation_variable(ast: n.Node) -> str | None:
    if not isinstance(ast, n.Equation):
        return None
    variables = n.variables(ast)
    return sorted(variables)[0] if len(variables) == 1 else None


def _polynomial_variable(ast: n.Node) -> str | None:
    variables = n.variables(ast)
    return sorted(variables)[0] if len(variables) == 1 else None


def _quadratic_coeffs(diff: dict[int, Fraction]) -> tuple[Fraction, Fraction, Fraction]:
    return diff.get(2, Fraction(0)), diff.get(1, Fraction(0)), diff.get(0, Fraction(0))


class _Verifier:
    """Stateless per-call verification of (problem, candidate)."""

    def __init__(self, problem: MathProblem, candidate: MathSolutionCandidate) -> None:
        self.problem = problem
        self.candidate = candidate
        self.checks = _Checks()

    # -- check implementations -------------------------------------------------

    def _check_parse_round_trip(self) -> n.Node:
        try:
            ast = n.from_dict(self.problem.normalized_ast)
        except (KeyError, ValueError, TypeError) as exc:
            self.checks.record("parse_round_trip", False, f"canonical AST 不可回放: {exc}")
            raise
        if n.to_dict(ast) == self.problem.normalized_ast:
            self.checks.record("parse_round_trip", True)
        else:
            self.checks.record("parse_round_trip", False, "规范化 AST 序列化回放不一致")
        return ast

    def _check_domain(self, ast: n.Node) -> dict[int, Fraction] | None:
        for node in _walk(ast):
            if isinstance(node, n.Div):
                if not isinstance(node.den, n.Num) or node.den.value == n.ZERO:
                    self.checks.record("domain", False, "分母含变量或分母为零")
                    return None
            if isinstance(node, n.Var) and self.problem.problem_type == "arithmetic":
                self.checks.record("domain", False, "算术题族中出现变量")
                return None
        if self.problem.problem_type in ("linear", "quadratic") and isinstance(ast, n.Equation):
            variable = _equation_variable(ast)
            if variable is None:
                self.checks.record("domain", False, "方程不含变量")
                return None
            diff = n.equation_difference(ast, variable)
            if diff is None:
                self.checks.record("domain", False, "方程不是单变量有理多项式")
                return None
            leading_degree = 2 if self.problem.problem_type == "quadratic" else 1
            if diff.get(leading_degree, Fraction(0)) == 0:
                self.checks.record("domain", False, "方程最高次项系数为零")
                return None
            self.checks.record("domain", True)
            return diff
        self.checks.record("domain", True)
        return {}  # non-equation families: no leading-coefficient requirement

    def _check_step_relation(self, ast: n.Node, diff: dict[int, Fraction] | None) -> dict[int, Fraction] | None:
        family = self.problem.problem_type
        try:
            if family == "arithmetic":
                for step in self.candidate.steps:
                    value = n.evaluate(n.from_dict(step["expr"]))
                    if value != n.Rational.from_dict(step["value"]):
                        self.checks.record("step_relation", False, f"步骤值不一致: {step['label']}")
                        return None
            elif family == "polynomial":
                variable = _polynomial_variable(ast)
                if variable is None:
                    self.checks.record("step_relation", False, "多项式变量缺失")
                    return None
                for step in self.candidate.steps:
                    coeffs = n.poly_coeffs(n.from_dict(step["expr"]), variable)
                    if coeffs != c.coeffs_from_dict(step["coeffs"]):
                        self.checks.record("step_relation", False, f"展开不一致: {step['label']}")
                        return None
            elif family == "linear":
                for step in self.candidate.steps:
                    if "transform" not in step or "before" not in step or "after" not in step:
                        self.checks.record("step_relation", False, "线性方程步骤缺少 transform/before/after")
                        return None
                    if c.apply_transform(step["before"], step["transform"]) != step["after"]:
                        self.checks.record("step_relation", False, f"步骤回放不一致: {step['label']}")
                        return None
                variable = _equation_variable(ast)
                if variable is None:
                    self.checks.record("step_relation", False, "线性方程变量缺失")
                    return None
                diff = n.equation_difference(ast, variable)
                if diff is None or max(diff) != 1:
                    self.checks.record("step_relation", False, "线性方程系数推导失败")
                    return None
            elif family == "quadratic":
                variable = _equation_variable(ast)
                if variable is None:
                    self.checks.record("step_relation", False, "二次方程变量缺失")
                    return None
                diff = n.equation_difference(ast, variable)
                if diff is None or max(diff) != 2:
                    self.checks.record("step_relation", False, "二次方程系数推导失败")
                    return None
                a, b, cc = _quadratic_coeffs(diff)
                for step in self.candidate.steps:
                    if "discriminant" in step:
                        recomputed = q.quad_discriminant(a, b, cc)
                        if recomputed != c.frac_from_dict(step["discriminant"]):
                            self.checks.record("step_relation", False, "判别式步骤不一致")
                            return None
                    elif "roots" in step:
                        if step["roots"] != q.quad_roots(a, b, cc):
                            self.checks.record("step_relation", False, "求根公式步骤不一致")
                            return None
                    else:
                        self.checks.record("step_relation", False, "二次方程步骤结构不识别")
                        return None
            else:
                self.checks.record("step_relation", False, f"未知题族 {family}")
                return None
        except (KeyError, ValueError, TypeError, n.MathDomainError) as exc:
            self.checks.record("step_relation", False, f"步骤回放异常: {exc}")
            return None
        self.checks.record("step_relation", True)
        return diff

    def _check_final_answer(self, ast: n.Node, diff: dict[int, Fraction] | None) -> tuple[Any, ...] | None:
        """Independently compute the expected answer; returns expected roots
        for equations, else None."""
        family = self.problem.problem_type
        final = self.candidate.final_answer
        expected_roots: tuple[Any, ...] | None = None
        try:
            if family == "arithmetic":
                expected = n.evaluate(ast).to_dict()
                if final.get("kind") != "rational" or final.get("value") != expected:
                    self.checks.record("final_answer", False, "最终答案与独立计算不一致")
                    return None
            elif family == "polynomial":
                variable = _polynomial_variable(ast)
                coeffs = n.poly_coeffs(ast, variable) if variable else None
                if coeffs is None or final.get("kind") != "polynomial" or c.coeffs_to_dict(coeffs) != final.get("coeffs"):
                    self.checks.record("final_answer", False, "多项式规范形与独立展开不一致")
                    return None
            elif family == "linear":
                assert diff is not None
                a, b = diff[1], diff.get(0, Fraction(0))
                expected_root = c.rational_root(Fraction(-b, a))
                if final.get("kind") != "roots" or final.get("roots") != (expected_root,):
                    self.checks.record("final_answer", False, "线性方程根与独立求解不一致")
                    return None
                expected_roots = (expected_root,)
            elif family == "quadratic":
                assert diff is not None
                a, b, cc = _quadratic_coeffs(diff)
                expected = q.quad_roots(a, b, cc)
                if final.get("kind") != "roots" or tuple(final.get("roots") or ()) != expected:
                    self.checks.record("final_answer", False, "二次方程根与独立求解不一致")
                    return None
                expected_roots = expected
        except (KeyError, ValueError, TypeError, n.MathDomainError) as exc:
            self.checks.record("final_answer", False, f"独立计算异常: {exc}")
            return None
        self.checks.record("final_answer", True)
        return expected_roots

    def _check_completeness(self, expected_roots: tuple[Any, ...] | None) -> None:
        family = self.problem.problem_type
        if family not in ("linear", "quadratic"):
            self.checks.record("completeness", True)
            return
        claimed = tuple(self.candidate.final_answer.get("roots") or ())
        expected = expected_roots or ()
        if len(claimed) != len(expected):
            self.checks.record("completeness", False, f"根不完整：声明 {len(claimed)} 个，应为 {len(expected)} 个")
            return
        self.checks.record("completeness", True)

    def _check_extraneous_roots(self, diff: dict[int, Fraction] | None) -> None:
        family = self.problem.problem_type
        if family not in ("linear", "quadratic"):
            self.checks.record("extraneous_roots", True)
            return
        assert diff is not None
        for root in self.candidate.final_answer.get("roots") or ():
            try:
                if family == "linear":
                    # diff == a*x + b
                    a = diff.get(1, Fraction(0))
                    b = diff.get(0, Fraction(0))
                    ok = a * c.frac_from_dict(root["value"]) + b == 0
                else:
                    a = diff.get(2, Fraction(0))
                    b = diff.get(1, Fraction(0))
                    cc = diff.get(0, Fraction(0))
                    if root["kind"] == "rational":
                        r = c.frac_from_dict(root["value"])
                        ok = a * r * r + b * r + cc == 0
                    else:
                        rational_part, surd_part = q.quad_eval_surd(
                            a,
                            b,
                            cc,
                            c.frac_from_dict(root["num"]),
                            c.frac_from_dict(root["coeff"]),
                            root["radicand"],
                        )
                        ok = rational_part == 0 and surd_part == 0
            except (KeyError, ValueError, TypeError):
                ok = False
            if not ok:
                self.checks.record("extraneous_roots", False, f"存在增根/假根: {root}")
                return
        self.checks.record("extraneous_roots", True)

    def _check_policy_coverage(self) -> VerificationPolicy | None:
        policy = POLICIES.get(self.problem.problem_type)
        if policy is None:
            self.checks.record("policy_coverage", False, f"题族 {self.problem.problem_type} 没有验证策略")
            return None
        if self.candidate.strategy != self.problem.problem_type:
            self.checks.record("policy_coverage", False, "候选策略与题族不匹配")
            return None
        if self.candidate.problem_id != self.problem.problem_id:
            self.checks.record("policy_coverage", False, "候选解绑定的 problem_id 不一致")
            return None
        if self.candidate.final_answer.get("kind") not in _ALLOWED_FINAL_KINDS[self.problem.problem_type]:
            self.checks.record("policy_coverage", False, "最终答案类型不在题族允许范围内")
            return None
        for root in self.candidate.final_answer.get("roots") or ():
            if root.get("kind") not in _ALLOWED_ROOT_KINDS[self.problem.problem_type]:
                self.checks.record("policy_coverage", False, f"根类型不支持: {root.get('kind')}")
                return None
        executed = {check.name for check in self.checks.results if check.status == "passed"}
        missing = [
            name
            for name in policy.required_checks
            if name != "policy_coverage" and name not in executed  # this check runs now
        ]
        if missing:
            self.checks.record("policy_coverage", False, f"缺少必需检查: {missing}")
            return None
        self.checks.record("policy_coverage", True)
        return policy

    def run(self) -> VerificationDecision:
        try:
            ast = self._check_parse_round_trip()
        except (KeyError, ValueError, TypeError):
            self.checks.record("domain", False, "canonical AST 不可用")
            self.checks.record("step_relation", False, "canonical AST 不可用")
            self.checks.record("final_answer", False, "canonical AST 不可用")
        else:
            diff = self._check_domain(ast)
            if diff is None:
                self.checks.record("final_answer", False, "域检查失败，跳过最终答案核对")
                self.checks.record("completeness", False, "域检查失败，跳过完整性核对")
                self.checks.record("extraneous_roots", False, "域检查失败，跳过回代核对")
            else:
                diff = self._check_step_relation(ast, diff)
                if diff is not None:
                    expected_roots = self._check_final_answer(ast, diff)
                    self._check_completeness(expected_roots)
                    self._check_extraneous_roots(diff)
                else:
                    self.checks.record("final_answer", False, "步骤检查失败，跳过最终答案核对")
                    self.checks.record("completeness", False, "步骤检查失败，跳过完整性核对")
                    self.checks.record("extraneous_roots", False, "步骤检查失败，跳过回代核对")
        policy = self._check_policy_coverage()

        verdict = "VERIFIED" if policy is not None and not self.checks.failed_any() else "FAILED"
        return VerificationDecision.canonicalize(
            problem_id=self.problem.problem_id,
            problem_content_hash=self.problem.content_hash,
            candidate_id=self.candidate.candidate_id,
            candidate_payload_hash=self.candidate.payload_hash,
            policy_id=policy.policy_id if policy else "",
            policy_version=policy.version if policy else "",
            verdict=verdict,
            checks=tuple(self.checks.results),
        )


def verify(problem: MathProblem, candidate: MathSolutionCandidate) -> VerificationDecision:
    """Verify one candidate against its problem. Never mutates anything."""
    if problem.problem_type == "linear_system":
        from mathtutor.solving.linear_system_verifier import verify_system
        return verify_system(problem, candidate)
    if problem.problem_type == "linear_inequality":
        from mathtutor.solving.inequality_verifier import verify_inequality
        return verify_inequality(problem, candidate)
    if problem.problem_type == "quadratic_inequality":
        from mathtutor.solving import quadratic_inequality
        return quadratic_inequality.verify(problem, candidate)
    return _Verifier(problem, candidate).run()
