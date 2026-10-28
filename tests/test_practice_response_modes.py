"""Synthetic API/SQLite checks for transfer evidence and option exposure."""
import json
import sqlite3
from contextlib import closing
from fractions import Fraction
from uuid import UUID

import pytest

from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.security.scopes import DEV_STUDENT_ID
from test_phase5_e2e_offer_flow import _client, _send, _collect

SESSION = "/api/v2/math-tutor/sessions/e2e-1"
OFFERS = "/api/v2/math-tutor/offers"


@pytest.fixture(autouse=True)
def isolated_state():
    reset_product_state()
    yield
    reset_product_state()


def begin_transfer(client, ws, help_kind=None):
    _send(ws, "submit_problem", {"text": "2x+3=7"})
    _collect(ws)
    if help_kind:
        _send(ws, "request_hint", {})
        _collect(ws)
        if help_kind == "solution":
            _send(ws, "request_solution", {})
            _collect(ws)
    _send(ws, "submit_attempt", {"answer": "2"})
    _collect(ws)
    offer = client.get(OFFERS).json()[0]
    assert offer["response_mode"] == "free_response"
    assert offer["observation_kind"] == "independent_transfer"
    return offer


def accept(client, ws, offer):
    _send(ws, "accept_practice_offer", {"offer_id": offer["offer_id"]})
    frames = _collect(ws)
    assert not any(f["event_type"] == "turn_error" for f in frames), frames
    return client.get(SESSION).json()


def answer_for(client, offer):
    async def load():
        repo = get_product_state().practice_repository
        saved = await repo.load_offer(UUID(offer["offer_id"]))
        release = await repo.load_release(saved.exercise_release_id)
        _, candidate, _ = await repo.load_exact_verified(release)
        value = candidate.final_answer["roots"][0]["value"]
        return str(Fraction(value["n"], value["d"]))
    return client.portal.call(load)


def completed_offer(client, offer):
    return next(row for row in client.get(OFFERS).json() if row["offer_id"] == offer["offer_id"])


@pytest.mark.parametrize("help_kind,purpose", [(None, "A1"), ("hint", "A2"), ("solution", "B")])
def test_unseen_transfer_has_no_options_and_first_correct_is_independent_after_restart(tmp_path, help_kind, purpose):
    path = tmp_path / "transfer.db"
    with _client(path) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            offer = begin_transfer(client, ws, help_kind)
            assert offer["purpose"] == purpose
            saved = accept(client, ws, offer)
            context = saved["problem_context"]
            assert not context.get("choices")
            assert context["response_mode"] == "free_response"
            assert not context["options_exposed"]
            assert "request_options" in saved["allowed_next_inputs"]
            answer = answer_for(client, offer)
    reset_product_state()
    with _client(path) as client:
        assert client.get(SESSION).json()["problem_context"] == context
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_attempt", {"answer": answer})
            assert not any(f["event_type"] == "turn_error" for f in _collect(ws))
        summary = completed_offer(client, offer)["result_summary"]
        assert summary["independent_correct"] == summary["first_free_response"] == 1
        assert summary["diagnostic_correct"] == summary["helped"] == 0


@pytest.mark.parametrize("typed", [True, False])
def test_requesting_options_is_sticky_diagnostic_for_typed_and_selected_answers(tmp_path, typed):
    path = tmp_path / "exposure.db"
    with _client(path) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            offer = begin_transfer(client, ws)
            accept(client, ws, offer)
            for _ in range(2):
                _send(ws, "request_options", {})
                assert not any(f["event_type"] == "turn_error" for f in _collect(ws))
            context = client.get(SESSION).json()["problem_context"]
            choices = context["choices"]
            assert context["options_exposed"] and context["observation_kind"] == "diagnostic"
            answer = answer_for(client, offer)
            option = next(o for o in choices["options"] if Fraction(o["text"]) == Fraction(answer))
    reset_product_state()
    with _client(path) as client:
        assert client.get(SESSION).json()["problem_context"]["choices"] == choices
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_attempt", {"answer": answer} if typed else {
                "choice_id": option["id"], "choice_version": choices["version"]})
            assert not any(f["event_type"] == "turn_error" for f in _collect(ws))
        summary = completed_offer(client, offer)["result_summary"]
        assert summary["diagnostic_correct"] == 1
        assert summary["independent_correct"] == summary["first_free_response"] == 0
        async def history():
            return await get_product_state().student_state.events(DEV_STUDENT_ID)
        facts = client.portal.call(history)
        assert sum(e.event_type == "options_exposed" for e in facts) == 1
        assert facts[-1].student_id == DEV_STUDENT_ID


def test_legacy_invitation_keeps_choice_semantics_without_rewriting_history(tmp_path):
    path = tmp_path / "legacy.db"
    with _client(path) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            offer = begin_transfer(client, ws)
            with closing(sqlite3.connect(path)) as db:
                row = db.execute("SELECT payload FROM practice_recommendations WHERE offer_id=?", (offer["offer_id"],)).fetchone()
                payload = json.loads(row[0])
                payload.pop("response_mode")
                payload.pop("observation_kind")
                db.execute("UPDATE practice_recommendations SET payload=? WHERE offer_id=?", (json.dumps(payload), offer["offer_id"]))
                db.commit()
            old = next(o for o in client.get(OFFERS).json() if o["offer_id"] == offer["offer_id"])
            assert old["response_mode"] == "single_choice"
            assert old["observation_kind"] == "diagnostic"
            assert "诊断" in old["observation_goal"]
            context = accept(client, ws, offer)["problem_context"]
            assert len(context["choices"]["options"]) == 4
            _send(ws, "submit_attempt", {"answer": answer_for(client, offer)})
            _collect(ws)
        summary = completed_offer(client, offer)["result_summary"]
        assert summary["diagnostic_correct"] == 1 and summary["independent_correct"] == 0


def test_accept_rolls_back_when_response_snapshot_cannot_be_saved(tmp_path):
    with _client(tmp_path / "atomic.db") as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            offer = begin_transfer(client, ws)
            store = get_product_state().store
            original = store.teaching.save
            async def fail_snapshot(*args, **kwargs):
                if kwargs.get("conn") is not None:
                    raise RuntimeError("synthetic snapshot failure")
                await original(*args, **kwargs)
            store.teaching.save = fail_snapshot
            try:
                _send(ws, "accept_practice_offer", {"offer_id": offer["offer_id"]})
                assert any(f["event_type"] == "turn_error" for f in _collect(ws))
            finally:
                store.teaching.save = original
            assert next(o for o in client.get(OFFERS).json() if o["offer_id"] == offer["offer_id"])["status"] == "ACTIVE"
            assert client.get(SESSION).json()["cycle_id"] == offer["parent_cycle_id"]
            assert accept(client, ws, offer)["problem_context"]["response_mode"] == "free_response"


def test_showing_options_cannot_be_reset_by_reopening_same_task_in_another_cycle(tmp_path):
    with _client(tmp_path / "same-task.db") as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            offer = begin_transfer(client, ws)
            accept(client, ws, offer)
            _send(ws, "request_options", {})
            _collect(ws)
            exposed = client.get(SESSION).json()
            answer = answer_for(client, offer)
            _send(ws, "submit_problem", {"text": exposed["problem_context"]["display_text"]}, session_id="another-cycle")
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": answer}, session_id="another-cycle")
            assert not any(f["event_type"] == "turn_error" for f in _collect(ws))
        async def history():
            return await get_product_state().student_state.events(DEV_STUDENT_ID)
        assessment = next(e for e in reversed(client.portal.call(history)) if e.event_type == "attempt_assessed")
        assert assessment.problem_revision == exposed["problem_revision"]
        assert assessment.options_exposed and not assessment.independent_target
        assert assessment.response_format == "single_choice"


def test_stale_or_foreign_context_cannot_expose_transfer_options(tmp_path, monkeypatch):
    from mathtutor.api.auth_deps import require_student_owner
    from mathtutor.security.scopes import StudentOwnerScope, PrincipalScope
    with _client(tmp_path / "binding.db") as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            offer = begin_transfer(client, ws)
            saved = accept(client, ws, offer)
            ws.send_json({"command":"request_options", "payload":{}, "session_id":"e2e-1", "cycle_id":"stale-cycle"})
            assert any(f["event_type"] == "turn_error" for f in _collect(ws))
            assert not client.get(SESSION).json()["problem_context"].get("choices")
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="other",username="other",role="student"),student_id="other")
        async def other_socket_owner(ws):
            return StudentOwnerScope(principal=PrincipalScope(user_id="other",username="other",role="student"),student_id="other")
        monkeypatch.setattr("mathtutor.api.math_tutor_ws.ws_require_student_owner", other_socket_owner)
        try:
            with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
                ws.send_json({"command":"request_options","payload":{},"session_id":"other-owner-session","cycle_id":saved["cycle_id"]})
                assert any(f["event_type"] == "turn_error" for f in _collect(ws))
        finally:
            client.app.dependency_overrides.clear()
        assert not client.get(SESSION).json()["problem_context"].get("choices")
