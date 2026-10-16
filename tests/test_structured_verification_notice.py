"""Real SQLite/WebSocket receipts stay separate from exact answer text."""
from contextlib import closing
import json
import sqlite3

import pytest

from mathtutor.api.math_tutor_ws import _to_student_frame
from mathtutor.api.product_state import get_product_state
from mathtutor.application.verification_notice import verification_notice_fields
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from mathtutor.pedagogy.events import assert_no_forbidden_fields
from mathtutor.application.controller import MathTutorEvent, MathTutorEventType
from test_tutor_p0 import client_at, send, summary


NOTICE = "本段讲解未经逐句数学核验。"
REQUEST = "Check the student solution.\nProblem: A box contains 9 red and 8 blue balls. How many balls?\nStudent: 9+8=17.\nIs the answer incorrect? Write only Yes or No."


class FixedResponse:
    provider_id, model = "offline", "receipt-regression"

    def __init__(self, text="No"):
        self.text, self.calls = text, 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        return CompletionResult(text=self.text, provider_id=self.provider_id, model=self.model,
                                finish_reason="stop", input_tokens=10, output_tokens=10)


def terminal(frames):
    return next(frame for frame in reversed(frames) if frame["event_type"] in
                {"assistant_complete", "assistant_partial", "assistant_error"})


def test_exact_answer_notice_survives_delivery_sqlite_replay_and_restart(tmp_path):
    db = tmp_path / "receipt.db"
    provider = FixedResponse()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        frames = send(ws, "send_message", "answer", {"text": REQUEST})
        result = terminal(frames)
        assert result["event_type"] == "assistant_complete"
        assert result["payload"]["final_text"] == "No"
        assert result["payload"]["verification_notice"] == NOTICE
        delta = [frame["payload"] for frame in frames if frame["event_type"] == "assistant_delta"][-1]
        assert delta["student_message"] == "No" and delta["verification_notice"] == NOTICE
        saved = summary(client)["messages"][-1]
        assert saved["content"] == "No" and saved["verification_notice"] == NOTICE
        assert "continuation_context" not in saved
        assert send(ws, "send_message", "answer", {"text": REQUEST}) == frames
        assert provider.calls == 1
    with closing(sqlite3.connect(db)) as conn:
        body, raw_context = conn.execute("SELECT content, continuation_context FROM conversation_messages WHERE role='tutor'").fetchone()
        context = json.loads(raw_context)
        assert body == "No" and context["verification_notice"] == NOTICE
        context["private_receipt_fixture"] = "must-stay-private"
        conn.execute("UPDATE conversation_messages SET continuation_context=? WHERE role='tutor'", (json.dumps(context),))
        conn.commit()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        restored = summary(client)
        assert restored["messages"][-1]["content"] == "No"
        assert restored["messages"][-1]["verification_notice"] == NOTICE
        assert "must-stay-private" not in json.dumps(restored)
        assert send(ws, "send_message", "answer", {"text": REQUEST}) == frames


@pytest.mark.parametrize("kept_delta", [False, True])
def test_crash_after_approved_snapshot_recovers_notice_without_a_new_model_call(tmp_path, kept_delta):
    db = tmp_path / "crash.db"
    provider = FixedResponse()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        frames = send(ws, "send_message", "answer", {"text": REQUEST})
    # Model a lost process after approved body/context storage, before the final
    # frame journal write.  The second variant retains the body frame but loses
    # its notice, so equal body bytes cannot hide a missing receipt.
    kept = [frame for frame in frames if frame["event_type"] == "assistant_delta"][-1:] if kept_delta else []
    for frame in kept:
        frame["payload"].pop("verification_notice", None)
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE turn_requests SET status='RUNNING', frames=? WHERE request_id='answer'", (json.dumps(kept),))
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        recovered = send(ws, "send_message", "answer", {"text": REQUEST})
        result = terminal(recovered)
        assert result["event_type"] == "assistant_partial"
        assert result["payload"]["final_text"] == "No"
        assert result["payload"]["verification_notice"] == NOTICE
        assert result["payload"]["error_code"] == "REQUEST_INTERRUPTED"
        delta = [frame["payload"] for frame in recovered if frame["event_type"] == "assistant_delta"][-1]
        assert delta["student_message"] == "No" and delta["verification_notice"] == NOTICE
        assert summary(client)["messages"][-1]["verification_notice"] == NOTICE
        assert send(ws, "send_message", "answer", {"text": REQUEST}) == recovered
        assert provider.calls == 1


def test_refuted_formula_keeps_its_prominent_body_warning_after_restart(tmp_path):
    db = tmp_path / "refuted.db"
    provider = FixedResponse("先算 $3+4=8$。")
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        frames = send(ws, "send_message", "wrong", {"text": "加法交换律是什么意思？"})
        body = terminal(frames)["payload"]["final_text"]
        assert body.startswith("> ⚠️") and "核验未通过" in body
        assert not terminal(frames)["payload"].get("verification_notice")
        assert summary(client)["messages"][-1]["content"] == body
    with client_at(db) as client:
        restored = summary(client)["messages"][-1]
        assert restored["content"] == body and not restored.get("verification_notice")


@pytest.mark.parametrize("context", [None, "not JSON", "[]", '{"verification_notice": {"secret": "private"}}'])
def test_invalid_stored_receipts_do_not_expose_context_objects(context):
    assert verification_notice_fields(context) == {}


def test_event_projection_allows_only_a_string_public_receipt():
    frame = _to_student_frame(MathTutorEvent(type=MathTutorEventType.CONTENT, source="test", content="No",
        metadata={"verification_notice": NOTICE, "raw_text": "PRIVATE", "model_reasoning": "PRIVATE"}))
    assert frame["payload"]["verification_notice"] == NOTICE
    assert_no_forbidden_fields(frame)
    assert "PRIVATE" not in json.dumps(frame)
    bad = _to_student_frame(MathTutorEvent(type=MathTutorEventType.CONTENT, source="test", content="No",
        metadata={"verification_notice": {"model_reasoning": "PRIVATE"}}))
    assert "verification_notice" not in bad["payload"]
