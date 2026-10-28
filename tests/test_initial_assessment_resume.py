"""Real owner-scoped API/SQLite checks for student-requested placement resume."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import reset_product_state
from mathtutor.application.initial_assessment import ASSESSMENT_VERSION, LEGACY_V1_VERSION
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from test_phase5_e2e_offer_flow import _client, _collect, _send

PREFIX = "/api/v2/math-tutor/desktop/initial-assessment"


@pytest.fixture(autouse=True)
def isolated_state():
    reset_product_state()
    yield
    reset_product_state()


def answer(client, data):
    question = data["question"]
    return {"run_id": data["run_id"], "index": question["index"],
        "option_id": "unsure", "version": question["choices"]["version"]}


def resume_body(data):
    return {"run_id": data["run_id"], "version": data["assessment_version"]}


def stored(path):
    with closing(sqlite3.connect(path)) as conn:
        return json.loads(conn.execute("SELECT payload FROM initial_assessments LIMIT 1").fetchone()[0])


def replace_stored(path, payload):
    with closing(sqlite3.connect(path)) as conn:
        with conn:
            conn.execute("UPDATE initial_assessments SET payload = ?", (json.dumps(payload),))


def test_three_answers_skip_restart_resume_preserves_run_and_other_learning(tmp_path):
    path = tmp_path / "resume.db"
    with _client(path) as client:
        data = client.post(PREFIX + "/start").json()
        first_answer = answer(client, data)
        for _ in range(3):
            response = client.post(PREFIX + "/answer", json=answer(client, data))
            assert response.status_code == 200, response.text
            data = response.json()
        fourth_question = data["question"]
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_problem", {"text": "2x+3=7"})
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": "2"})
            _collect(ws)
        evidence = client.get("/api/v2/math-tutor/desktop/student-evidence").json()
        assert len(evidence["items"]) == 1
        session = client.get("/api/v2/math-tutor/sessions/e2e-1").json()
        assert client.post(PREFIX + "/skip", json={"run_id": data["run_id"]}).status_code == 200
        saved = stored(path)
        skipped = client.get(PREFIX).json()
        assert skipped["status"] == "skipped" and skipped["answered"] == 3
        assert skipped["can_resume"] and skipped["question"] is None
        # Merely starting/configuring again must not undo the student's deferral.
        assert client.post(PREFIX + "/start").json() == skipped
        assert not client.get("/api/v2/math-tutor/desktop/settings").json()["initial_assessment_required"]
    reset_product_state()
    with _client(path) as client:
        assert client.get(PREFIX).json() == skipped
        response = client.post(PREFIX + "/resume", json=resume_body(skipped))
        assert response.status_code == 200, response.text
        resumed = response.json()
        assert resumed["run_id"] == skipped["run_id"]
        assert resumed["status"] == "in_progress" and resumed["answered"] == 3
        assert resumed["question"] == fourth_question
        assert stored(path)["answers"] == saved["answers"]
        assert client.post(PREFIX + "/resume", json=resume_body(skipped)).json() == resumed
        assert client.post(PREFIX + "/answer", json={**first_answer, "option_id": "A"}).status_code == 409
        assert stored(path)["answers"] == saved["answers"]
        assert client.get("/api/v2/math-tutor/desktop/student-evidence").json() == evidence
        assert client.get("/api/v2/math-tutor/sessions/e2e-1").json() == session


def test_resume_is_owner_scoped_and_does_not_create_another_owners_run(tmp_path):
    with _client(tmp_path / "owners.db") as client:
        data = client.post(PREFIX + "/start").json()
        client.post(PREFIX + "/skip", json={"run_id": data["run_id"]})
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="other", username="other", role="student"), student_id="other")
        try:
            assert client.post(PREFIX + "/resume", json=resume_body(data)).status_code == 409
            assert client.get(PREFIX).json()["status"] == "not_started"
            other = client.post(PREFIX + "/start").json()
            assert client.post(PREFIX + "/resume", json=resume_body(data)).status_code == 409
            assert client.get(PREFIX).json() == other
        finally:
            client.app.dependency_overrides.clear()
        assert client.get(PREFIX).json()["status"] == "skipped"
        assert client.post(PREFIX + "/resume", json=resume_body(data)).json()["run_id"] == data["run_id"]


@pytest.mark.parametrize("changed", ["policy_version", "assessment_version"])
def test_incompatible_run_and_stale_client_version_keep_saved_answers(tmp_path, changed):
    path = tmp_path / "version.db"
    with _client(path) as client:
        data = client.post(PREFIX + "/start").json()
        data = client.post(PREFIX + "/answer", json=answer(client, data)).json()
        client.post(PREFIX + "/skip", json={"run_id": data["run_id"]})
        before = stored(path)
        assert client.post(PREFIX + "/resume", json={**resume_body(data), "version": "stale"}).status_code == 409
        assert stored(path) == before
        incompatible = {**before, changed: "older-incompatible-version"}
        replace_stored(path, incompatible)
        public = client.get(PREFIX).json()
        assert not public["can_resume"] and public["question"] is None
        assert "已有作答保留" in public["compatibility_notice"]
        assert client.post(PREFIX + "/resume", json=resume_body(public)).status_code == 409
        assert client.post(PREFIX + "/start").json()["status"] == "skipped"
        assert stored(path) == incompatible


def test_original_v1_runs_resume_without_rewriting_saved_choices(tmp_path):
    assert ASSESSMENT_VERSION == LEGACY_V1_VERSION
    path = tmp_path / "legacy.db"
    with _client(path) as client:
        data = client.post(PREFIX + "/start").json()
        data = client.post(PREFIX + "/answer", json=answer(client, data)).json()
        client.post(PREFIX + "/skip", json={"run_id": data["run_id"]})
        old = stored(path)
        old.pop("assessment_version")
        replace_stored(path, old)
        public = client.get(PREFIX).json()
        assert public["can_resume"] and public["assessment_version"] == LEGACY_V1_VERSION
        assert client.post(PREFIX + "/resume", json=resume_body(public)).json()["answered"] == 1
        assert stored(path)["answers"] == old["answers"]


def test_incompatible_active_run_can_be_deferred_without_discarding_answers(tmp_path):
    path = tmp_path / "old-active.db"
    with _client(path) as client:
        data = client.post(PREFIX + "/start").json()
        data = client.post(PREFIX + "/answer", json=answer(client, data)).json()
        before = {**stored(path), "assessment_version": "incompatible-old-set"}
        replace_stored(path, before)
        public = client.get(PREFIX).json()
        assert public["status"] == "in_progress" and public["question"] is None
        assert public["compatibility_notice"]
        assert client.get("/api/v2/math-tutor/desktop/settings").json()["initial_assessment_required"]
        assert client.post(PREFIX + "/skip", json={"run_id": data["run_id"]}).status_code == 200
        assert stored(path) == {**before, "status": "skipped"}
        assert not client.get("/api/v2/math-tutor/desktop/settings").json()["initial_assessment_required"]


def test_completed_run_cannot_be_retested_or_skipped_backwards(tmp_path):
    path = tmp_path / "completed.db"
    with _client(path) as client:
        data = client.post(PREFIX + "/start").json()
        first_answer = answer(client, data)
        for _ in range(data["total"]):
            data = client.post(PREFIX + "/answer", json=answer(client, data)).json()
        assert data["status"] == "completed" and not data["can_resume"]
        before = stored(path)
        assert client.post(PREFIX + "/resume", json=resume_body(data)).json() == data
        assert client.post(PREFIX + "/skip", json={"run_id": data["run_id"]}).status_code == 200
        assert client.post(PREFIX + "/start").json() == data
        assert client.post(PREFIX + "/answer", json={**first_answer, "option_id": "A"}).status_code == 409
        assert stored(path) == before


def test_duplicate_resume_and_skip_answer_interleavings_preserve_first_answer(tmp_path):
    path = tmp_path / "tabs.db"
    with _client(path) as client:
        data = client.post(PREFIX + "/start").json()
        body = answer(client, data)
        client.post(PREFIX + "/skip", json={"run_id": data["run_id"]})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.post(PREFIX + "/resume", json=resume_body(data)), range(2)))
        assert all(r.status_code == 200 for r in responses)
        assert responses[0].json() == responses[1].json()
        assert stored(path)["answers"] == []
        assert client.post(PREFIX + "/answer", json=body).json()["answered"] == 1
        client.post(PREFIX + "/skip", json={"run_id": data["run_id"]})
        assert client.post(PREFIX + "/answer", json={**body, "index": 1}).status_code == 409
        assert client.post(PREFIX + "/resume", json=resume_body(data)).json()["answered"] == 1
        assert client.post(PREFIX + "/answer", json={**body, "option_id": "A"}).status_code == 409
        assert len(stored(path)["answers"]) == 1
