"""Real WebSocket/history regressions for unsupported tasks and continuation."""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing

import pytest

from test_tutor_p0 import client_at, send, summary
from mathtutor.api.product_state import get_product_state
from mathtutor.application.problem_recovery import UNVERIFIED_NOTICE
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole


def terminal(frames):
    return next(frame for frame in reversed(frames)
                if frame["event_type"] in {"assistant_complete", "assistant_partial", "assistant_error"})


def events(db):
    with closing(sqlite3.connect(db)) as connection:
        return connection.execute("SELECT count(*) FROM learning_events").fetchone()[0]


@pytest.mark.parametrize("question,expected_type", [
    ("解含参数方程 ax^2+bx+c=0", "quadratic"),
    ("sin(x)=1/2", "linear"),
])
def test_out_of_domain_question_offers_verified_scaffold_without_replacing_original(tmp_path, question, expected_type):
    db = tmp_path / "recovery.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        frames = send(ws, "send_message", "unsupported", {"text": question})
        result = terminal(frames)
        assert result["event_type"] == "assistant_complete"
        recovery = result["recovery_problem"]
        assert recovery["problem_type"] == expected_type
        restored = summary(client)
        assert restored["recovery_problem"] == recovery
        assert restored["problem_revision"] == ""
        assert restored["state"] in {"problem_received", "unsupported"}
        assert restored["messages"][0]["content"] == question
        assert "原题" in restored["messages"][-1]["content"]
        assert not any(action["enabled"] for action in restored["allowed_actions"]
                       if action["command"] in {"request_hint", "request_solution"})
        assert events(db) == 0
        # The student accepts the distinct exercise using the public new-task path.
        accepted = send(ws, "send_message", "accept-scaffold", {"text": "换题：" + recovery["text"]})
        accepted_result = terminal(accepted)
        assert accepted_result["cycle_state"] == "awaiting_attempt"
        after = summary(client)
        assert after["problem_revision"] and after["recovery_problem"] is None
        assert after["messages"][0]["content"] == question
        assert after["evidence_summary"]["independent"] == 0


def test_unparseable_task_preserves_bound_problem_and_empty_evidence(tmp_path):
    db = tmp_path / "bound.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "original", {"text": "3x-4=11"})
        before = summary(client)
        count_before = events(db)
        frames = send(ws, "send_message", "word-task", {"text": "换题：小明买3支铅笔共多少钱？"})
        result = terminal(frames)
        after = summary(client)
        assert result["recovery_problem"]["problem_type"] == "linear"
        assert after["cycle_id"] == before["cycle_id"]
        assert after["problem_revision"] == before["problem_revision"]
        assert after["state"] == before["state"]
        assert events(db) == count_before
        assert after["evidence_summary"]["independent"] == 0
        assert after["messages"][-1]["verification_notice"] == UNVERIFIED_NOTICE.removeprefix("> ")


class ReplayProvider:
    provider_id, model = "offline", "saved-response"

    def __init__(self, responses):
        self.responses, self.calls = iter(responses), []

    async def complete(self, messages, **kwargs):
        self.calls.append((list(messages), kwargs))
        reason, text = next(self.responses)
        return CompletionResult(text=text, finish_reason=reason, provider_id=self.provider_id,
                                model=self.model, input_tokens=10, output_tokens=10)


def test_free_explanation_and_continue_survive_restart_with_raw_boundary(tmp_path):
    db = tmp_path / "continue.db"
    provider = ReplayProvider([("length", "先确定题目中的数量关系。"), ("length", "再把未知数设为x。")])
    question = "求函数y=2x+3的图像，并说明它和直线有什么关系"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        first = send(ws, "send_message", "first", {"text": question})
        result = terminal(first)
        assert result["event_type"] == "assistant_partial"
        assert result["recovery_problem"] is None
        assert result["problem_context"]["lifecycle"] == "discussion"
        body = result["payload"]["final_text"]
        assert not body.startswith(UNVERIFIED_NOTICE)
        assert result["payload"]["verification_notice"] == UNVERIFIED_NOTICE.removeprefix("> ")
        assert summary(client)["messages"][-1]["content"] == body
        assert provider.calls[0][1]["max_tokens"] == 1024
        assert len(provider.calls) == 2 and events(db) == 0
        with closing(sqlite3.connect(db)) as connection:
            saved = json.loads(connection.execute("SELECT continuation_context FROM conversation_messages WHERE role='tutor'").fetchone()[0])
        assert saved["raw_text"] == "先确定题目中的数量关系。\n\n再把未知数设为x。"
        assert saved["unstructured_math"] is True
    resumed_provider = ReplayProvider([("stop", "接下来写出一个等式，先不要计算答案。")])
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, resumed_provider)
        second = send(ws, "send_message", "continue", {"text": "继续"})
        result = terminal(second)
        assert result["event_type"] == "assistant_complete"
        assert UNVERIFIED_NOTICE not in result["payload"]["final_text"]
        assert result["payload"]["verification_notice"] == UNVERIFIED_NOTICE.removeprefix("> ")
        restored = summary(client)
        assert restored["messages"][-1]["content"] == result["payload"]["final_text"]
        prompt = resumed_provider.calls[0][0]
        assert any(message.get("content") == saved["raw_text"] for message in prompt)
        assert "结构化求解器没有编成" in prompt[0]["content"]
        assert not any(message.get("role") == "assistant" and "相关基础题" in str(message.get("content")) for message in prompt)
        assert events(db) == 0


@pytest.mark.parametrize("first,second", [
    (r"先计算 \(x=", r"2\)"), ("Δ=16-16=接", "着算另一项。"),
    ("x=5-", "后面的项仍需填写。"), ("x=5−", "后面的项仍需填写。"),
    (r"\(x=\)", "这一步还缺少右边的值。"), (r"\[16-16=\]。", "还需要补上结果。"),
])
def test_stop_with_open_formula_is_partial_and_continue_cannot_hide_ambiguous_seam(tmp_path, first, second):
    db = tmp_path / "open-formula.db"
    provider = ReplayProvider([("stop", first), ("stop", second), ("stop", "请核对上面的等式。")])
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        first = send(ws, "send_message", "open", {"text": "请解释二次方程的根"})
        initial = terminal(first)
        assert len(provider.calls) == 2
        assert initial["event_type"] == "assistant_partial"
        assert initial["payload"]["error_code"] == "CONTINUATION_BOUNDARY_UNVERIFIED"
        assert "续写接缝待核对" in initial["payload"]["final_text"]
        second = send(ws, "send_message", "uncertain-continue", {"text": "继续"})
        resumed = terminal(second)
        assert resumed["event_type"] == "assistant_partial"
        assert resumed["payload"]["error_code"] == "CONTINUATION_BOUNDARY_UNVERIFIED"
        assert summary(client)["messages"][-1]["status"] == "PARTIAL"
        assert events(db) == 0
