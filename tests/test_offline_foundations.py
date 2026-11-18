import json
import sqlite3
from contextlib import closing

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.exploration_evidence import text_hash
from mathtutor.application.message_intent import fallback_tutor_reply
from mathtutor.application.network_chat import merge_continuation_context
from mathtutor.application.offline_foundations import offline_concept_reply
from mathtutor.application.tutor_runtime import current_turn
from mathtutor.domain.turn_result import TutorTurnResult
from test_tutor_p0 import client_at, send


@pytest.mark.parametrize("question,expected", [
    ("为什么移项需要变号？不要解某道方程。", "两边都减去 t"),
    ("为什么移项要变号；顺便解释这和生活收支类比的区别", "正负号取决于记账约定"),
    ("分数加法为什么要通分，乘法也要吗？", "不要求先通分"),
    ("讲解去括号时的分配律", "每一项"),
    ("同类项的系数该怎么合并？", "字母部分保持原样"),
])
def test_local_concepts_use_versioned_authored_material_without_a_problem_answer(question, expected):
    reply = offline_concept_reply(question)
    assert reply and expected in reply.text
    assert "知乎" not in reply.text and "MathTutor 内置数学基础" in reply.text
    assert "x=4" not in reply.text
    assert reply.receipt()["text_sha256"] == text_hash(reply.text)
    for ref in reply.references:
        assert ref["provider"] == "mathtutor" and ref["version"] and ref["conditions_version"]
        assert ref["text_sha256"] == text_hash(ref["text"])
        assert ref["explanation"] in reply.text


@pytest.mark.parametrize("question,expected", [
    ("什么是导数？", "内置概念资料也没有覆盖"),
    ("为什么每个紧致拓扑空间都有这个性质？", "设置中配置模型"),
    ("What is a derivative?", "Configure a model in Settings"),
])
def test_uncovered_question_discloses_offline_capabilities(question, expected):
    assert offline_concept_reply(question) is None
    text = fallback_tutor_reply(question)
    assert expected in text
    assert not text.startswith("我在")


def test_local_concept_answer_and_receipt_survive_real_chat_and_replay(tmp_path):
    database = tmp_path / "offline.db"
    question = "为什么移项要变号；顺便解释这和生活收支类比的区别。不要解某道方程。"
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        assert not get_product_state().controller.chat_responder.is_configured
        frames = send(ws, "send_message", "offline-concept", {"text": question})
        final = next(frame["payload"] for frame in frames if frame["event_type"] == "assistant_complete")
        assert final["status"] == "COMPLETED" and final["steps_used"] == 0
        assert "两边都减去 t" in final["final_text"] and "记账约定" in final["final_text"]
        assert "x=4" not in final["final_text"]
        assert not any(frame["event_type"] in {"assistant_error", "turn_error"} for frame in frames)
        replay = send(ws, "send_message", "offline-concept", {"text": question})
        assert any(final["final_text"] == frame.get("payload", {}).get("final_text") for frame in replay)
        with closing(sqlite3.connect(database)) as conn:
            text, context = conn.execute("SELECT content, continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='offline-concept'").fetchone()
            assert conn.execute("SELECT count(*) FROM learning_events").fetchone()[0] == 0
        evidence = json.loads(context)["offline_foundations"]
        assert text == evidence["text"] and text_hash(text) == evidence["text_sha256"]
        assert evidence["references"][0]["provider"] == "mathtutor"
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        replay = send(ws, "send_message", "offline-concept", {"text": question})
        assert any(text == frame.get("payload", {}).get("final_text") for frame in replay)


@pytest.mark.parametrize("question", ["x=", "猜猜x等于多少", "求∫sin(x)dx"])
def test_boundary_persists_on_the_real_turn_without_a_preexisting_context(tmp_path, monkeypatch, question):
    database = tmp_path / "boundary-turn.db"
    observed = []
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        controller = get_product_state().controller
        original = controller._show_math_boundary
        async def record(*args, **kwargs):
            turn = current_turn.get()
            assert isinstance(turn, TutorTurnResult)
            observed.append(hasattr(turn, "continuation_context"))
            return await original(*args, **kwargs)
        monkeypatch.setattr(controller, "_show_math_boundary", record)
        frames = send(ws, "send_message", "boundary", {"text": question})
        final = next(frame["payload"] for frame in frames if frame["event_type"] == "assistant_complete")
        assert observed == [False]
        assert final["status"] == "COMPLETED" and final["error_code"] is None
        with closing(sqlite3.connect(database)) as conn:
            context = conn.execute("SELECT continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='boundary'").fetchone()[0]
        assert json.loads(context)["math_boundary"]["original_question"] == question


def test_actual_turn_merge_keeps_other_receipts_and_tolerates_legacy_context():
    turn = TutorTurnResult()
    merge_continuation_context(turn, {"math_boundary": {"reason": "unsupported"}})
    merge_continuation_context(turn, {"delivery_id": "delivery-one"})
    assert json.loads(turn.continuation_context) == {"math_boundary": {"reason": "unsupported"}, "delivery_id": "delivery-one"}
    turn.continuation_context = "[]"
    merge_continuation_context(turn, {"approved_solution_text": "checked"})
    assert json.loads(turn.continuation_context) == {"approved_solution_text": "checked"}
