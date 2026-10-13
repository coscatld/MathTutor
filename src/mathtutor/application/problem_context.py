"""Read-only, answer-free projection of a canonical task and its provenance.

The caller supplies owner-scoped source/progress from repositories. This module
never extracts instructions from a display string, solves a problem, issues an
attestation, or promotes a candidate to verified. A VerifiedSolutionRef must
already have been resolved by the trusted repository before it is supplied.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from mathtutor.domain.hashing import content_hash
from mathtutor.domain.solution import VerifiedSolutionRef
from mathtutor.learning.skill_graph import (
    GRAPH_VERSION, STEP_MAPPING_VERSION, skill_details, skills_for_problem,
    skills_for_solution_step,
)
from mathtutor.solving import nodes
from mathtutor.solving.verifier import POLICIES

CONTEXT_VERSION = "mt-problem-context-v1"

_TASKS = {
    "arithmetic": ("calculate", "计算表达式的值", "scalar"),
    "polynomial": ("simplify", "展开或合并并给出等价的多项式", "polynomial"),
    "linear": ("solve_equation", "求方程的解", "root_set"),
    "linear_inequality": ("solve_inequality", "求未知数的取值范围", "interval"),
    "quadratic": ("solve_equation", "求方程的完整解集", "root_set"),
    "linear_system": ("solve_system", "求同时满足两个原方程的完整解", "assignments"),
}
_LIMITS = {
    "arithmetic": ("exact_rational", ["rational_arithmetic"], ["approximate_numeric_tolerance", "units"]),
    "polynomial": ("single_variable_rational_coefficients", ["polynomial_equivalence"], ["multivariate_polynomials", "units"]),
    "linear": ("nondegenerate_rational_coefficients", ["equivalent_equation", "rational_root", "original_equation_substitution"],
               ["identity_equations", "inconsistent_constant_equations", "units"]),
    "linear_inequality": ("nondegenerate_rational_coefficients", ["equivalent_transform", "rational_boundary", "relation_direction"],
                          ["quadratic_inequalities", "units"]),
    "quadratic": ("real_roots_rational_coefficients", ["rational_or_quadratic_surd_roots", "complete_real_root_set", "original_equation_substitution"],
                  ["complex_roots", "units", "approximate_numeric_tolerance"]),
    "linear_system": ("unique_two_variable_affine_system", ["equivalent_linear_combination", "partial_variable_value", "complete_assignment", "both_original_equations"],
                      ["nonunique_systems", "nonlinear_systems", "more_than_two_variables", "units"]),
}


def _attested_binding(problem, candidate, reference):
    """Validate immutable identity binding, not a caller-created 'verified' flag."""
    if not isinstance(reference, VerifiedSolutionRef):
        return False, "no_repository_reference"
    if not candidate:
        return False, "candidate_unavailable"
    policy = POLICIES.get(problem.problem_type)
    expected = (str(problem.problem_id), problem.content_hash, str(candidate.candidate_id),
                candidate.payload_hash, policy.policy_id if policy else None, policy.version if policy else None)
    actual = (str(reference.problem_id), reference.problem_content_hash,
              str(reference.solution_candidate_id), reference.solution_payload_hash,
              reference.policy_id, reference.policy_version)
    if actual != expected or candidate.problem_id != problem.problem_id or not reference.attestation_hash:
        return False, "reference_binding_mismatch"
    if (candidate.payload_hash != content_hash({"problem_id": candidate.problem_id, "strategy": candidate.strategy,
                                               "steps": candidate.steps, "final_answer": candidate.final_answer})
            or problem.content_hash != content_hash({"schema_version": problem.schema_version,
                "canonicalization_version": problem.canonicalization_version,
                "problem_type": problem.problem_type, "normalized_ast": problem.normalized_ast})):
        return False, "immutable_payload_mismatch"
    return True, "repository_reference_bound"


def _constraint(constraints, key):
    value = constraints.get(key)
    return deepcopy(value) if value not in (None, "", [], {}) else "unknown"


def build_problem_context(
    problem, candidate=None, *, cycle_id=None, verified_solution_ref=None,
    source_ref=None, source_kind="unknown", original_statement=None,
    task_constraints=None, current_subgoal_id=None, verified_student_steps=None,
    unanswered_question=None, help_exposure=None, used_examples=None,
    invitation_source=None,
) -> dict[str, Any]:
    """Build the common Writer/semantic/planner task envelope.

    ``domain``, ``units`` and ``precision`` are requested constraints, so they
    remain unknown unless persisted facts supply them. ``verification_domain``
    describes implementation coverage, not an invented student requirement.
    No final answer, coefficient transform, reference-step text, or hidden
    worked example is projected; disclosure remains the only answer channel.
    """
    family = problem.problem_type
    kind, objective, shape = _TASKS.get(family, ("unknown", "unknown", "unknown"))
    policy = POLICIES.get(family)
    domain, capabilities, unsupported = _LIMITS.get(family, ("unknown", [], []))
    constraints = task_constraints or {}
    try:
        from mathtutor.solving.parser import stored_math_ast
        variables = sorted(nodes.variables(nodes.from_dict(stored_math_ast(problem.normalized_ast))))
    except (KeyError, TypeError, ValueError, nodes.MathDomainError, nodes.MathComplexityError):
        variables = []
    bound, reason = _attested_binding(problem, candidate, verified_solution_ref)
    candidate_matches = bool(candidate and candidate.problem_id == problem.problem_id)
    step_map = []
    if candidate_matches:
        for index, step in enumerate(candidate.steps):
            skill_ids = skills_for_solution_step(problem, step)
            step_map.append({"step_id": f"reference-step-{index + 1}", "step_index": index,
                             "skill_ids": list(skill_ids), "mapping_status": "rule_mapped" if skill_ids else "unknown",
                             "verification_status": "verified" if bound else "unverified_candidate"})
    source_known = source_kind in {"manual", "material", "practice", "diagnostic", "imported"}
    source = {"kind": source_kind if source_known else "unknown", "reference": deepcopy(source_ref)}
    source_statement = original_statement if isinstance(original_statement, str) and original_statement.strip() else None
    projected_skills = list(skills_for_problem(problem))
    detail_ids = list(dict.fromkeys(projected_skills + [key for step in step_map for key in step["skill_ids"]]))
    return {
        "schema_version": CONTEXT_VERSION, "problem_id": str(problem.problem_id),
        "cycle_id": str(cycle_id) if cycle_id is not None else None,
        "problem_revision": problem.content_hash, "canonicalization_version": problem.canonicalization_version,
        "source": source, "source_ref": deepcopy(source_ref),
        "original_statement": source_statement or "unknown",
        "full_statement": source_statement or f"{objective}：{problem.display_latex}",
        "statement_provenance": "owner_source" if source_statement else "canonical_task_projection",
        "display_text": problem.display_latex, "normalized_representation": deepcopy(problem.normalized_ast),
        "task_type": family, "task_kind": kind, "task_objective": objective,
        "solve_for": {"kind": "polynomial_expression" if family == "polynomial" else "variables" if variables else "expression_value" if family == "arithmetic" else "unknown",
                      "variables": variables},
        "domain": _constraint(constraints, "domain"), "units": _constraint(constraints, "units"),
        "precision": _constraint(constraints, "precision"),
        "expected_answer_shape": {"kind": shape, "variables": variables,
                                  "requires_all_targets": family in {"linear", "quadratic", "linear_system"}},
        "skill_ids": projected_skills, "skill_details": skill_details(detail_ids),
        "skill_graph_version": GRAPH_VERSION, "skill_label_version": STEP_MAPPING_VERSION,
        "step_skill_map": step_map,
        "verified_solution_ref": verified_solution_ref.model_dump(mode="json") if bound else None,
        "verification_status": "verified" if bound else "unsupported" if not policy else "unverified",
        "verification_reason": reason,
        "verification_capability": {
            "policy_id": policy.policy_id if policy else None, "policy_version": policy.version if policy else None,
            "verification_domain": domain, "supported_checks": list(capabilities),
            "required_checks": list(policy.required_checks) if policy else [], "unsupported": list(unsupported),
            "scope": "canonical_math_only", "canonical_math_verified": bound,
            "additional_constraints_status": "unverified" if any(_constraint(constraints, k) != "unknown" for k in ("domain", "units", "precision")) else "unknown",
        },
        "current_subgoal_id": current_subgoal_id,
        "verified_student_steps": deepcopy(verified_student_steps or []),
        "student_progress_status": "known" if verified_student_steps is not None else "unknown",
        "unanswered_question": deepcopy(unanswered_question),
        "help_exposure": deepcopy(help_exposure) if help_exposure is not None else {"status": "unknown"},
        "used_examples": deepcopy(used_examples or []),
        "example_history_status": "known" if used_examples is not None else "unknown",
        "invitation_source": deepcopy(invitation_source),
    }
