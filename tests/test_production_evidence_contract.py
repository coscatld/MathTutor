"""EXP-W02-001: production chronology, first submission and immutable target records."""
from contextlib import closing
import json
import sqlite3

import pytest
from sqlalchemy import select
from mathtutor.learning.knowledge_tracing.service import StudentStateService
from mathtutor.learning.knowledge_tracing.schema import learning_predictions


def context(**changes):
    return dict(dict(session_id="session", cycle_id="cycle", problem_id="problem", problem_revision="canonical",
        item_family_id="linear", skill_ids=["divide_nonzero"]), **changes)


@pytest.fixture
async def service():
    result = await StudentStateService.create_memory()
    yield result
    await result.engine.dispose()


async def submit(service, identity, **changes):
    return await service.record_submission("alice", event_id=identity, response_fingerprint=identity, **context(**changes))


async def assess(service, identity, submission="", **changes):
    return await service.record_attempt("alice", **context(), assessment_id=identity, attempt_id=identity,
        correctness="correct", submission_event_id=submission, **changes)


async def test_failed_judge_submission_reserves_first_position(service):
    await submit(service, "failed-before-assessment")
    await submit(service, "second")
    event = await assess(service, "a2", "second")
    assert event.prior_task_attempt and not event.independent_target
    assert len(await service.events("alice")) == 3


def test_real_judge_failure_preserves_submission_without_promoting_retry(tmp_path, monkeypatch):
    from test_tutor_p0 import client_at, send
    from mathtutor.application.verification_backend import InProcessVerificationBackend, VerificationTimeoutError
    from mathtutor.infrastructure.verifier_worker import VerifierWorkerManager
    db = tmp_path / "judge-failure.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "parent", {"text": "2x+3=7"})
        async def fail(*args, **kwargs):
            raise VerificationTimeoutError("synthetic judge timeout")
        with monkeypatch.context() as patch:
            patch.setattr(InProcessVerificationBackend, "verify_attempt", fail)
            patch.setattr(VerifierWorkerManager, "verify_attempt", fail)
            send(ws, "submit_attempt", "fails", {"answer": "3"})
        send(ws, "submit_attempt", "retry-new-answer", {"answer": "2"})
    with closing(sqlite3.connect(db)) as conn:
        rows = [json.loads(x[0]) for x in conn.execute("SELECT payload FROM learning_events ORDER BY event_seq")]
    submissions = [e for e in rows if e["event_type"] == "attempt_submitted"]
    assessed = [e for e in rows if e["event_type"] == "attempt_assessed"]
    assert len(submissions) == 2 and len(assessed) == 1
    assert assessed[0]["prior_task_attempt"]
    assert predictions(db)[0]["prediction_label"] is None


async def test_submission_retry_reuses_slot_and_assessment_is_at_most_once(service):
    first = await submit(service, "s1")
    assert await submit(service, "s1") == first
    event = await assess(service, "a1", "s1")
    assert event.independent_target
    assert await assess(service, "a1", "s1") == event
    with pytest.raises(ValueError, match="already assessed"):
        await assess(service, "other-assessment", "s1")
    assert len(await service.events("alice")) == 2


async def test_wrong_submission_binding_is_rejected(service):
    await submit(service, "s1", problem_revision="different")
    with pytest.raises(ValueError, match="binding"):
        await assess(service, "a1", "s1")


async def test_invalidated_assessment_does_not_erase_submission_history(service):
    event = await assess(service, "a1")
    await service.invalidate("alice", event_id="correction", invalidates_event_id=event.event_id)
    second = await assess(service, "a2")
    assert second.prior_task_attempt and not second.independent_target


async def test_repeated_correct_answer_does_not_upgrade_public_evidence(service):
    from mathtutor.application.evidence_projection import public_evidence, teaching_evidence
    await service.record_attempt("alice", **context(), assessment_id="wrong", attempt_id="wrong", correctness="incorrect")
    await assess(service, "right")
    history = await service.events("alice")
    assert public_evidence(history)["independent"] == 1
    assert teaching_evidence(history, ["divide_nonzero"])["independent_correct_items"] == 0


async def test_different_conversation_cannot_reopen_first_slot(service):
    await submit(service, "old", session_id="older", cycle_id="older-cycle")
    await submit(service, "current")
    event = await assess(service, "current", "current")
    assert event.prior_task_attempt and not event.independent_target


async def test_first_assessment_label_and_frozen_record_cannot_be_overwritten(service):
    before = await service.prepare_prediction("alice", prediction_id="presentation:cycle", at_presentation=True, **context())
    await submit(service, "s1")
    await service.record_attempt("alice", **context(), attempt_id="a1", assessment_id="a1", correctness="incorrect",
        submission_event_id="s1", prediction_id="presentation:cycle")
    await submit(service, "s2")
    await assess(service, "a2", "s2", prediction_id="presentation:cycle")
    after = await service.presentation("alice", "cycle")
    assert after["prediction_label"] == 0
    assert after["assessment_id"] == "a1"
    assert after["frozen_forecast"] == before["frozen_forecast"]
    assert after["frozen_forecast"]["probability"] is None
    assert after["frozen_forecast"]["visible_event_boundary"] == 0
    assert await service.presentation("bob", "cycle") is None


def predictions(db):
    with closing(sqlite3.connect(db)) as conn:
        return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM learning_predictions")]


def test_real_display_help_retry_and_restart_keep_one_forecast(tmp_path):
    from test_tutor_p0 import client_at, send, summary
    db = tmp_path / "contract.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        frames = send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        assert not [f for f in frames if f["event_type"] == "turn_error"]
        rows = predictions(db)
        assert len(rows) == 1 and rows[0]["prediction_timing"] == "before_task_display"
        frozen = rows[0]["frozen_forecast"]
        send(ws, "request_hint", "help")
        send(ws, "submit_attempt", "wrong", {"answer": "3"})
        send(ws, "submit_attempt", "right", {"answer": "2"})
        assert predictions(db)[0]["frozen_forecast"] == frozen
        assert len(predictions(db)) == 1
    with client_at(db) as client:
        assert summary(client)["state"] in {"practice_offer_pending", "solved", "reflection"}
        assert predictions(db)[0]["frozen_forecast"] == frozen


def test_persistence_failure_prevents_problem_content_emission(tmp_path, monkeypatch):
    from test_tutor_p0 import client_at, send, summary
    async def fail(*args, **kwargs):
        raise RuntimeError("synthetic disk failure")
    monkeypatch.setattr(StudentStateService, "prepare_prediction", fail)
    with client_at(tmp_path / "failure.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        frames = send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        assert not any(f.get("payload", {}).get("action") == "verified" for f in frames)
        assert predictions(tmp_path / "failure.db") == []
        assert summary(client)["problem_context"] is None
    with client_at(tmp_path / "failure.db") as client:
        assert summary(client)["problem_context"] is None


@pytest.mark.parametrize("route", ["practice", "diagnostic"])
def test_practice_and_diagnostic_display_use_frozen_child_record(tmp_path, route):
    from test_tutor_p0 import client_at, send, summary
    db = tmp_path / "child.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "parent", {"text": "2x+3=7"})
        parent = summary(client)
        if route == "practice":
            send(ws, "request_practice", "invite")
            offer = summary(client)["active_offer"]["offer_id"]
            send(ws, "accept_practice_offer", "accept", {"offer_id": offer})
        else:
            send(ws, "start_diagnostic", "diagnose")
        child = summary(client)
        assert child["cycle_id"] != parent["cycle_id"]
        rows = predictions(db)
        assert len(rows) == 2
        forecast = next(row for row in rows if row["item_context"]["cycle_id"] == child["cycle_id"])
        assert forecast["prediction_timing"] == "before_task_display"
        frozen_child = forecast["frozen_forecast"]
        assert forecast["prediction_label"] is None
        if frozen_child["coverage_status"] == "mapped_source_skills":
            assert isinstance(frozen_child["probability"], float) and 0 < frozen_child["probability"] < 1
            assert frozen_child["learning_effect_verified"] is False
            assert frozen_child["probability_source"] == "assist2009_trained_dkt"
        else:
            assert frozen_child["probability"] is None
        send(ws, "skip_diagnostic" if route == "diagnostic" else "resume_problem", "back")
        assert summary(client)["cycle_id"] == parent["cycle_id"]
        assert predictions(db) == rows


def test_practice_forecast_failure_keeps_offer_unaccepted_and_parent_visible(tmp_path, monkeypatch):
    from test_tutor_p0 import client_at, send, summary
    db = tmp_path / "practice-failure.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "parent", {"text": "2x+3=7"})
        send(ws, "request_practice", "invite")
        parent = summary(client)
        async def fail(*args, **kwargs):
            raise RuntimeError("synthetic disk failure")
        monkeypatch.setattr(StudentStateService, "prepare_prediction", fail)
        send(ws, "accept_practice_offer", "accept", {"offer_id": parent["active_offer"]["offer_id"]})
        after = summary(client)
        assert after["cycle_id"] == parent["cycle_id"] and after["state"] == parent["state"]
        assert after["active_offer"] == parent["active_offer"]
        assert len(predictions(db)) == 1
