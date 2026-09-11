"""Fine labels describe verifiable operations, not guessed mastery or scope."""
from dataclasses import replace
from uuid import uuid4

import pytest

from mathtutor.application.problem_context import build_problem_context
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import VerifiedSolutionRef
from mathtutor.learning.skill_graph import (
    GRAPH_VERSION, SKILLS, STEP_MAPPING_VERSION, Skill, graph_edges,
    skill_details, skills_for_solution_step, skills_for_subgoal, validate_graph,
)
from mathtutor.solving import parse_problem, solve_problem, verify


def solved(text):
    parsed = parse_problem(text).problem
    assert parsed is not None, text
    problem = MathProblem.canonicalize(parsed.problem_type, parsed.normalized_ast, parsed.display_latex)
    candidate = solve_problem(problem, parsed).candidate
    assert candidate is not None
    decision = verify(problem, candidate)
    assert decision.verdict == "VERIFIED", decision
    reference = VerifiedSolutionRef(verification_log_id=uuid4(), problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash, solution_candidate_id=candidate.candidate_id,
        solution_payload_hash=candidate.payload_hash, policy_id=decision.policy_id,
        policy_version=decision.policy_version, attestation_hash="test-repository-binding")
    return problem, candidate, reference


@pytest.mark.parametrize("skill_id", sorted(SKILLS))
def test_all_thirteen_nodes_have_honest_executable_diagnostics(skill_id):
    skill = SKILLS[skill_id]
    assert len(SKILLS) == 13
    assert skill.definition and skill.common_errors and skill.supported_families
    assert skill.version == GRAPH_VERSION == "mt-skills-v2"
    for diagnostic in skill.diagnostics:
        problem, _, _ = solved(diagnostic.problem_text)
        assert problem.problem_type == diagnostic.verifier_family
        assert diagnostic.interpretation_limit
        assert diagnostic.assessment_scope in {"joint_task", "component"}
    assert skill_details([skill_id, skill_id, "unmapped"]) == [skill_details([skill_id])[0]]


def test_prerequisite_related_and_membership_edges_are_distinct():
    edges = graph_edges()
    assert {e["kind"] for e in edges} == {"prerequisite", "related", "part_of"}
    assert all(edge["target"].startswith("family:") for edge in edges if edge["kind"] == "part_of")
    a, b = Skill("a", "A", related=("b",)), Skill("b", "B", related=("a",))
    assert validate_graph({"a": a, "b": b})  # Related is not a causal prerequisite.
    with pytest.raises(ValueError, match="cycle"):
        validate_graph({"a": replace(a, prerequisites=("b",)), "b": replace(b, prerequisites=("a",))})
    with pytest.raises(ValueError, match="related"):
        validate_graph({"a": a})


def test_linear_subgoals_and_steps_do_not_repeat_family_labels():
    problem, candidate, _ = solved("2x+3=7")
    assert skills_for_subgoal(problem, "balance") == ("equality_preservation",)
    assert skills_for_subgoal(problem, "isolate") == ("linear_isolation", "substitution_check")
    assert skills_for_solution_step(problem, candidate.steps[0]) == ("equality_preservation",)
    assert skills_for_solution_step(problem, candidate.steps[-1]) == ("equality_preservation", "linear_isolation")
    assert skills_for_solution_step(problem, {"label": "I claim mastery", "skill_ids": ["linear_isolation"]}) == ()
    assert skills_for_subgoal(problem, "unknown_goal") == ()


def test_quadratic_reference_steps_do_not_claim_unobserved_factorisation():
    problem, candidate, _ = solved("x^2-5x+6=0")
    assert skills_for_solution_step(problem, candidate.steps[0]) == ("quadratic_discriminant",)
    assert skills_for_solution_step(problem, candidate.steps[1]) == ("quadratic_roots",)
    assert "factorisation" not in skills_for_subgoal(problem, "method", candidate)
    assert "只交根不能" in SKILLS["factorisation"].diagnostics[0].interpretation_limit


def test_system_maps_four_real_steps_and_both_subgoals():
    problem, candidate, _ = solved("2x+y=7;x-y=2")
    assert [skills_for_solution_step(problem, step) for step in candidate.steps] == [
        ("system_elimination", "equality_preservation"), ("linear_isolation",),
        ("system_substitution",), ("system_completeness", "substitution_check")]
    assert set(skills_for_subgoal(problem, "eliminate")).isdisjoint({"system_completeness", "substitution_check"})
    assert "system_completeness" in skills_for_subgoal(problem, "remaining")


def test_arithmetic_fraction_and_polynomial_focus_is_task_specific():
    integer, _, _ = solved("-3+5")
    fraction, candidate, _ = solved("1/2+1/3")
    polynomial, poly_candidate, _ = solved("2(x+3)")
    assert "fraction_operations" not in skills_for_subgoal(integer, "plan")
    assert skills_for_subgoal(fraction, "plan") == ("fraction_operations",)
    assert skills_for_solution_step(fraction, candidate.steps[-1]) == ("fraction_operations",)
    assert skills_for_subgoal(polynomial, "expand") == ("distributive_law",)
    assert skills_for_subgoal(polynomial, "combine") == ("combine_like_terms",)
    assert skills_for_solution_step(polynomial, poly_candidate.steps[0]) == ("distributive_law", "combine_like_terms")


@pytest.mark.parametrize("text,kind,shape", [
    ("2+3", "calculate", "scalar"), ("2(x+3)", "simplify", "polynomial"),
    ("2x+3=7", "solve_equation", "root_set"), ("x^2-4=0", "solve_equation", "root_set"),
    ("2x+y=7;x-y=2", "solve_system", "assignments"),
])
def test_problem_context_projects_task_without_fabricating_source_or_requirements(text, kind, shape):
    problem, candidate, reference = solved(text)
    context = build_problem_context(problem, candidate, cycle_id="cycle", verified_solution_ref=reference)
    assert context["cycle_id"] == "cycle"
    assert context["problem_revision"] == problem.content_hash
    assert context["task_kind"] == kind and context["expected_answer_shape"]["kind"] == shape
    assert context["domain"] == context["units"] == context["precision"] == "unknown"
    assert context["source"] == {"kind": "unknown", "reference": None}
    assert context["original_statement"] == "unknown"
    assert context["full_statement"].startswith(context["task_objective"])
    assert context["normalized_representation"] == problem.normalized_ast
    assert context["skill_label_version"] == STEP_MAPPING_VERSION
    assert context["verification_status"] == "verified"
    assert context["verified_solution_ref"]["solution_payload_hash"] == candidate.payload_hash
    assert context["verification_capability"]["scope"] == "canonical_math_only"
    assert context["student_progress_status"] == "unknown" and context["help_exposure"] == {"status": "unknown"}
    assert all(set(step) == {"step_id", "step_index", "skill_ids", "mapping_status", "verification_status"} for step in context["step_skill_map"])
    assert "final_answer" not in context and "steps" not in context
    if shape == "polynomial":
        assert context["solve_for"]["kind"] == "polynomial_expression"


def test_owner_source_and_constraints_are_preserved_not_claimed_verified():
    problem, candidate, ref = solved("2x+3=7")
    constraints = {"domain": "positive_real", "units": "cm", "precision": {"decimal_places": 2}}
    history = [{"delivery_id": "d1", "target_answer_exposed": True}]
    context = build_problem_context(problem, candidate, verified_solution_ref=ref,
        source_kind="material", source_ref={"document_id": "owner-document", "page": 2},
        original_statement="求长方形未知边长 x，满足 2x+3=7；单位为厘米。", task_constraints=constraints,
        verified_student_steps=[], current_subgoal_id="balance", help_exposure=history,
        unanswered_question={"message_id": "m1", "text": "两边应减去什么？"}, used_examples=[], invitation_source="invite-1")
    assert context["statement_provenance"] == "owner_source" and context["units"] == "cm"
    assert context["precision"] == {"decimal_places": 2}
    assert context["verification_capability"]["additional_constraints_status"] == "unverified"
    assert context["student_progress_status"] == context["example_history_status"] == "known"
    assert context["help_exposure"] == history and context["help_exposure"] is not history
    constraints["precision"]["decimal_places"] = 9
    assert context["precision"]["decimal_places"] == 2


def test_candidate_or_mismatched_reference_cannot_become_verified():
    problem, candidate, ref = solved("2x+3=7")
    context = build_problem_context(problem, candidate)
    assert context["verification_status"] == "unverified" and context["verified_solution_ref"] is None
    assert all(step["verification_status"] == "unverified_candidate" for step in context["step_skill_map"])
    bad_ref = ref.model_copy(update={"problem_content_hash": "different-version"})
    assert build_problem_context(problem, candidate, verified_solution_ref=bad_ref)["verification_reason"] == "reference_binding_mismatch"
    forged_flag = {"status": "verified", **ref.model_dump(mode="json")}
    assert build_problem_context(problem, candidate, verified_solution_ref=forged_flag)["verification_status"] == "unverified"
    tampered = candidate.model_copy(update={"final_answer": {"kind": "roots", "roots": []}})
    assert build_problem_context(problem, tampered, verified_solution_ref=ref)["verification_reason"] == "immutable_payload_mismatch"
    other, _, _ = solved("x+1=4")
    assert build_problem_context(other, candidate, verified_solution_ref=ref)["step_skill_map"] == []
