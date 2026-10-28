"""Synthetic engineering checks, not student/model efficacy measurements."""
from uuid import uuid4

import pytest

from mathtutor.api.product_state import reset_product_state, get_product_state
from mathtutor.application.initial_assessment import ITEMS, item_at
from mathtutor.application.multiple_choice import resolve_choice
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import verify_attempt
from test_phase5_e2e_offer_flow import _client, _send, _collect

PREFIX = "/api/v2/math-tutor/desktop/initial-assessment"


def graded_choices(index, run_id):
    item, problem, candidate = item_at(index, run_id)
    return [(option["id"], verify_attempt(parse_student_attempt(attempt_submission_id=uuid4(),
        student_id=uuid4(), cycle_id=uuid4(), raw_text=resolve_choice(item["choices"], option["id"], item["choices"]["version"]), attempt_index=1), problem, candidate).correctness.value)
        for option in item["choices"]["options"]]


@pytest.mark.parametrize("index", range(len(ITEMS)))
def test_each_initial_item_has_exactly_one_verifier_correct_choice(index):
    outcomes = [result for _, result in graded_choices(index, "test")]
    assert sorted(outcomes) == ["correct", "incorrect", "incorrect", "incorrect"]


@pytest.mark.parametrize("family", ["arithmetic", "linear", "polynomial", "quadratic", "linear_system"])
@pytest.mark.parametrize("difficulty", [1, 2, 3, 4, 5])
def test_practice_templates_have_unique_verified_choices(family, difficulty):
    from mathtutor.application.llm_candidate_generator import _parameterized_templates
    from mathtutor.application.multiple_choice import make_choices
    from mathtutor.domain.problem import MathProblem
    from mathtutor.solving.parser import parse_problem
    from mathtutor.solving.solver import solve_problem
    from mathtutor.solving.verifier import verify
    for statement in _parameterized_templates(family, difficulty):
        parsed = parse_problem(statement).problem
        problem = MathProblem.canonicalize(problem_type=parsed.problem_type, normalized_ast=parsed.normalized_ast, display_latex=parsed.display_latex)
        candidate = solve_problem(problem, parsed).candidate
        assert verify(problem, candidate).verdict == "VERIFIED"
        choices = make_choices(problem, candidate, salt="test")
        assert len({o["text"] for o in choices["options"]}) == 4


def test_initial_answers_restart_idempotency_unknown_and_delete(tmp_path):
    reset_product_state()
    path = tmp_path / "initial.db"
    with _client(path) as client:
        assert client.get(PREFIX).json()["status"] == "not_started"
        data = client.post(PREFIX + "/start").json()
        assert client.post(PREFIX + "/start").json() == data
        q = data["question"]
        body = {"run_id": data["run_id"], "index": 0, "option_id": "unsure", "version": q["choices"]["version"]}
        assert client.post(PREFIX + "/answer", json={**body, "version": "stale"}).status_code == 409
        first = client.post(PREFIX + "/answer", json=body).json()
        assert first["answered"] == 1
        assert client.post(PREFIX + "/answer", json=body).json() == first
        assert client.post(PREFIX + "/answer", json={**body, "option_id": "A"}).status_code == 409
    reset_product_state()
    with _client(path) as client:
        data = client.get(PREFIX).json()
        assert data["answered"] == 1
        for index in range(1, 10):
            option = next(key for key, result in graded_choices(index, data["run_id"]) if result == "correct")
            q = data["question"]
            response = client.post(PREFIX + "/answer", json={"run_id": data["run_id"], "index": index, "option_id": option, "version": q["choices"]["version"]})
            assert response.status_code == 200, response.text
            data = response.json()
        assert data["status"] == "completed"
        result = data["result"]
        assert result["dkt"]["probability"] is None
        assert result["skills"][0]["starting_difficulty"] == 2
        assert result["skills"][0]["unknown"] == 1
        assert all(row["starting_difficulty"] == 3 for row in result["skills"][1:])
        assert client.get("/api/v2/math-tutor/desktop/student-evidence").json()["items"] == []
        # Initial rule feeds the real invite generator, not just the result UI.
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_problem", {"text": "2x+3=7"})
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": "2"})
            _collect(ws)
        assert client.get("/api/v2/math-tutor/offers").json()[0]["difficulty"] == 3
        assert client.post("/api/v2/math-tutor/desktop/privacy/educational-history").status_code == 200
        assert client.get(PREFIX).json()["status"] == "not_started"
        assert client.post(PREFIX + "/answer", json=body).status_code == 409
    reset_product_state()


def test_first_key_configuration_required_once_and_owner_isolation(tmp_path):
    from mathtutor.api.auth_deps import require_student_owner
    from mathtutor.security.scopes import StudentOwnerScope, PrincipalScope
    reset_product_state()
    with _client(tmp_path / "owners.db") as client:
        settings_path = "/api/v2/math-tutor/desktop/settings"
        assert not client.get(settings_path).json()["initial_assessment_required"]
        saved = client.put(settings_path, json={"preset_id": "openai", "api_key": "synthetic-key-not-a-real-secret"})
        assert saved.status_code == 200 and saved.json()["initial_assessment_required"]
        data = client.get(PREFIX).json()
        assert client.get(settings_path).json()["initial_assessment_required"]
        # A different authenticated owner cannot read/answer this run.
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="other", username="other", role="student"), student_id="other")
        assert client.get(PREFIX).json()["status"] == "not_started"
        body = {"run_id": data["run_id"], "index": 0, "option_id": "A", "version": data["question"]["choices"]["version"]}
        assert client.post(PREFIX + "/answer", json=body).status_code == 409
        client.app.dependency_overrides.clear()
        assert client.post(PREFIX + "/skip", json={"run_id": data["run_id"]}).status_code == 200
        assert not client.get(settings_path).json()["initial_assessment_required"]
        rotated = client.put(settings_path, json={"preset_id": "openai", "api_key": "synthetic-replacement-key"})
        assert rotated.status_code == 200 and not rotated.json()["initial_assessment_required"]
        assert client.post("/api/v2/math-tutor/desktop/privacy/educational-history").status_code == 200
        assert client.get(PREFIX).json()["status"] == "not_started"
        assert client.post(PREFIX + "/answer", json=body).status_code == 409
    reset_product_state()


def test_rule_difficulty_is_bounded_and_repeated_success_cannot_replace_failure():
    from mathtutor.application.practice_policy import select_difficulty
    from mathtutor.domain.practice_context import AttemptSummaryEntry, PracticeGenerationContext
    def entry(problem, correctness):
        return AttemptSummaryEntry(skill_id="LINEAR_EQUATION", problem_id=problem, correctness=correctness, effective_assistance_level=0, attempt_index=1)
    context = PracticeGenerationContext(student_id=uuid4(), target_skill_ids=("LINEAR_EQUATION",),
        recent_attempt_summary=tuple(entry(str(i), "incorrect") for i in range(3)))
    assert select_difficulty(context, purpose="D", baseline=3)[0] == 2
    repeated = context.model_copy(update={"recent_attempt_summary": (*context.recent_attempt_summary, *(entry(str(i), "correct") for i in range(3)))})
    assert select_difficulty(repeated, purpose="D", baseline=3)[0] == 2
    correct = context.model_copy(update={"recent_attempt_summary": tuple(entry(str(i), "correct") for i in range(3))})
    assert select_difficulty(correct, purpose="D", baseline=3)[0] == 4
    assert select_difficulty(correct, purpose="D", baseline=3, requested=1)[0] == 1


def test_practice_choices_bind_and_roundtrip_without_answer_key(tmp_path):
    reset_product_state()
    with _client(tmp_path / "choices.db") as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_problem", {"text": "2x+3=7"})
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": "2"})
            _collect(ws)
            offer = client.get("/api/v2/math-tutor/offers").json()[0]
            # Exercise the explicit option-exposure branch; new transfer
            # invitations now begin as free response.
            _send(ws, "accept_practice_offer", {"offer_id": offer["offer_id"]})
            _collect(ws)
            _send(ws, "request_options", {})
            _collect(ws)
            session = client.get("/api/v2/math-tutor/sessions/e2e-1").json()
            choices = session["problem_context"]["choices"]
            assert len(choices["options"]) == 4
            assert not {"correct", "correct_id", "answer_key"}.intersection(choices)
            _send(ws, "submit_attempt", {"choice_id": "A", "choice_version": "stale"})
            frames = _collect(ws)
            assert any(f["event_type"] == "turn_error" for f in frames)
            _send(ws, "submit_attempt", {"choice_id": "A", "choice_version": choices["version"]})
            frames = _collect(ws)
            assert not any(f["event_type"] == "turn_error" for f in frames)
        profile = client.get("/api/v2/math-tutor/desktop/student-summary").json()
        # The original free-response task remains independent; selecting an
        # option on its child practice creates a separate diagnostic record.
        assert profile["evidence_summary"]["independent"] == 1
        assert profile["evidence_summary"]["diagnostic"] == 1
        accepted = next(row for row in client.get("/api/v2/math-tutor/offers").json()
            if row["offer_id"] == offer["offer_id"])
        assert accepted["result_summary"]["independent_correct"] == 0
        assert accepted["result_summary"]["observations"] == 1
        rows = client.get("/api/v2/math-tutor/desktop/student-evidence").json()["items"]
        assert len(rows) == 2
        assert rows[0]["correctness"] in {"correct", "incorrect"}
        assert rows[0]["first_target"] is False  # separate MC task; not legacy DKT label
    reset_product_state()
    with _client(tmp_path / "choices.db") as client:
        restored = client.get("/api/v2/math-tutor/sessions/e2e-1").json()
        assert restored["problem_context"]["choices"] == choices
    reset_product_state()


@pytest.mark.parametrize("answer, expected", [("2, 4", "correct"), ("4，2", "correct"),
    ("2, 2", "partial"), ("2, 5", "incorrect"), ("1/0, 4", "undetermined")])
def test_exact_root_set_grading_preserves_partial_and_unknown(answer, expected):
    _, problem, candidate = item_at(7, "root-regression")
    attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(),
        cycle_id=uuid4(), raw_text=answer, attempt_index=1)
    assert verify_attempt(attempt, problem, candidate).correctness.value == expected
