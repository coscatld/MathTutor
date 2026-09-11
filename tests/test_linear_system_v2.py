"""I03/I04: complete task is both coordinates satisfying both original equations."""
from copy import deepcopy
from uuid import uuid4

import pytest

from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import verify_attempt
from mathtutor.solving import parse_problem, solve_problem
from mathtutor.solving.verifier import verify
from mathtutor.solving import nodes as n


def chain(text="x+y=4; x-y=2"):
    parsed = parse_problem(text)
    assert parsed.kind == "parsed", parsed.reason
    problem = MathProblem.canonicalize(problem_type=parsed.problem.problem_type,
        normalized_ast=parsed.problem.normalized_ast, display_latex=parsed.problem.display_latex)
    solution = solve_problem(problem, parsed.problem)
    assert solution.kind == "solved", solution.reason
    return problem, solution.candidate


@pytest.mark.parametrize("text", ["x+y=4; x-y=2", "x+y=4\nx-y=2", "解方程组 x+y=4；x-y=2",
    r"\begin{cases}x+y=4\\x-y=2\end{cases}", "2a+b=5; a-b=1", "y=1;x=3",
    "x/2+y=5/2;x-y=2"])
def test_exact_linear_system_parse_solve_verify_and_roundtrip(text):
    problem, candidate = chain(text)
    assert problem.problem_type == "linear_system"
    assert n.to_dict(n.from_dict(problem.normalized_ast)) == problem.normalized_ast
    decision = verify(problem, candidate)
    assert decision.verdict == "VERIFIED", decision.checks
    assert {check.name for check in decision.checks} == {
        "parse_round_trip", "domain", "step_relation", "final_answer", "completeness", "extraneous_roots", "policy_coverage"}


@pytest.mark.parametrize("text", ["x+y=4;2x+2y=8", "x+y=4;2x+2y=7", "x*y=3;x+y=4",
    "x^2+y=4;x-y=2", "x+y+z=4;x-y=2", "x/y=3;x-y=2", "x+y=4;x-y=2;x=3"])
def test_singular_nonlinear_or_out_of_scope_system_fails_closed(text):
    assert parse_problem(text).kind == "unsupported"


@pytest.mark.parametrize("answer,expected", [("x=3", "partial"), ("3=x", "partial"), ("x=6/2", "partial"),
    ("y=1", "partial"), ("2x=6", "partial"), ("2x+2y=8", "partial"), ("x+y=4;x-y=2", "partial"),
    ("x=3;y=1", "correct"), ("y=1，x=6/2", "correct"), ("x=999;y=1", "incorrect"),
    ("x=3;y=999", "incorrect"), ("2x+2y=9", "incorrect"), ("3", "undetermined")])
def test_partial_values_never_complete_the_system(answer, expected):
    problem, candidate = chain()
    attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(), cycle_id=uuid4(),
                                    raw_text=answer, attempt_index=1)
    assessment = verify_attempt(attempt, problem, candidate)
    assert assessment.correctness.value == expected, assessment
    if expected == "partial":
        assert assessment.remaining_requirements
    if expected == "correct":
        assert any(claim["claim"] == "all_original_equations_satisfied" for claim in assessment.verified_claims)


@pytest.mark.parametrize("tamper", ["missing_variable", "wrong_value", "elimination", "substitution", "extra_step"])
def test_system_release_rejects_incomplete_or_tampered_proof(tamper):
    problem, candidate = chain()
    values = deepcopy(candidate.final_answer)
    steps = deepcopy(list(candidate.steps))
    if tamper == "missing_variable":
        values["values"].pop("y")
    elif tamper == "wrong_value":
        values["values"]["y"] = {"n": 999, "d": 1}
    elif tamper == "elimination":
        steps[0]["result_row"][0] = {"n": 999, "d": 1}
    elif tamper == "substitution":
        steps[3]["residuals"][0] = {"n": 1, "d": 1}
    else:
        steps.append({"kind": "unchecked", "label": "假证明"})
    forged = MathSolutionCandidate.canonicalize(problem.problem_id, "linear_system", tuple(steps), values)
    assert verify(problem, forged).verdict == "FAILED"


def test_system_display_is_minimized_and_l4_prefix_does_not_contain_both_assignments():
    from mathtutor.pedagogy.disclosure import _display_step
    _, candidate = chain()
    displayed = [_display_step(step, index, "x") for index, step in enumerate(candidate.steps)]
    assert all(set(step) == {"display_text", "display_latex"} for step in displayed)
    assert all(step["display_latex"] for step in displayed)
    assert "values" not in str(candidate.steps[:-1])


@pytest.mark.asyncio
@pytest.mark.parametrize("difficulty", [1, 2, 3, 4, 5])
async def test_system_has_verified_practice_templates_and_skill_mapping(difficulty):
    from mathtutor.application.llm_candidate_generator import TemplateCandidateExerciseGenerator
    from mathtutor.application.practice_release import ExerciseReleaseService, labels_for_mapping_ids
    from mathtutor.domain.practice_context import PracticeGenerationContext
    from mathtutor.learning.skills import SKILL_LINEAR_SYSTEM, skill_for_problem
    context = PracticeGenerationContext(student_id=uuid4(), target_skill_ids=(SKILL_LINEAR_SYSTEM,), desired_difficulty=difficulty)
    candidates = await TemplateCandidateExerciseGenerator().generate(context, count=3)
    assert len(candidates) == 3
    for candidate in candidates:
        release = await ExerciseReleaseService().release_candidate(candidate, source_type="TEMPLATE")
        assert skill_for_problem(release.problem) == SKILL_LINEAR_SYSTEM
        assert release.exercise.difficulty == difficulty
        assert SKILL_LINEAR_SYSTEM in labels_for_mapping_ids(release.exercise.target_mapping_ids)["skill_labels"]


def test_system_crosses_json_worker_budget_boundary():
    import json
    from mathtutor.infrastructure.verifier_worker import handle_request_bytes, VerificationWorkerBudget
    from mathtutor.application.verification_backend import VERIFICATION_SCHEMA_VERSION, AUTHORITATIVE_VERIFIER_VERSION
    problem, candidate = chain()
    request = {"schema_version": VERIFICATION_SCHEMA_VERSION, "verification_version": AUTHORITATIVE_VERIFIER_VERSION,
               "request_id": str(uuid4()), "operation": "verify", "problem": problem.model_dump(mode="json"),
               "candidate": candidate.model_dump(mode="json")}
    response, shutdown = handle_request_bytes(json.dumps(request).encode(), VerificationWorkerBudget())
    decoded = json.loads(response)
    assert not shutdown and decoded["status"] == "ok", decoded
    assert decoded["decision"]["verdict"] == "VERIFIED"
