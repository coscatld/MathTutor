import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest
from test_tutor_p0 import client_at, send

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.application.network_qa import NetworkQA, NetworkReply
from mathtutor.application.network_chat import merge_continuation_context, network_reply
from mathtutor.application.exploration_evidence import text_hash
from mathtutor.application.state_machine import CycleState
from mathtutor.infrastructure.zhihu import ZhihuError
from mathtutor.security.allowlist import SecurityViolationError, validate_client_envelope
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

ROOT = "/api/v2/math-tutor/desktop/recommendations"


def test_network_message_opt_in_binding_and_receipt(tmp_path):
    database = tmp_path / "online.db"
    calls = []

    async def answer(owner, **options):
        calls.append((owner, options))
        return NetworkReply("这是带来源的联网解释。", "answered", "分数通分", ({"source_id": "frozen-source"},),
                            ({"claim_id": "c1", "text": "这是带来源的联网解释。", "accepted": True},))

    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.network_qa = SimpleNamespace(maybe_respond=answer)
        send(ws, "send_message", "offline", {"text": "你好"})
        assert not calls
        frames = send(ws, "send_message", "online", {"text": "分数为什么要通分", "network_search": True, "reply_language": "zh"})
        assert any("带来源的联网解释" in str(frame) for frame in frames)
        assert len(calls) == 1
        send(ws, "send_message", "online", {"text": "分数为什么要通分", "network_search": True, "reply_language": "zh"})
        assert len(calls) == 1
        with closing(sqlite3.connect(database)) as conn:
            contexts = [json.loads(row[0]) for row in conn.execute("SELECT continuation_context FROM conversation_messages WHERE role='tutor'") if row[0]]
        assert any(row.get("network_evidence", {}).get("sources") == [{"source_id": "frozen-source"}] for row in contexts)
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"}, session="active")
        send(ws, "send_message", "guarded", {"text": "分数为什么要通分", "network_search": True}, session="active")
        assert len(calls) == 1


def test_unsupported_network_receipt_survives_real_chat_fallback_and_replay(tmp_path):
    database = tmp_path / "fallback.db"
    calls = []
    source = {"source_id": "source-a", "text": "一段材料", "text_sha256": text_hash("一段材料")}
    rejected = {"claim_id": "c1", "text": "未被支持的结论", "accepted": False,
                "reasons": ["insufficient_support"], "evidence": [{"source_id": "source-a", "quote": "一段材料"}]}
    async def answer(owner, **options):
        calls.append(owner)
        return NetworkReply("联网证据尚不足。", "unsupported", "概率概念", (source,), (rejected,))
    class Responder:
        is_configured = True
        async def respond(self, text, **kwargs):
            return "这是原有问答的概念解释。"
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        controller = get_product_state().controller
        controller.network_qa = SimpleNamespace(maybe_respond=answer)
        controller.chat_responder = Responder()
        payload = {"text": "概率这个概念是什么意思？", "network_search": True}
        frames = send(ws, "send_message", "fallback", payload)
        assert any("原有问答的概念解释" in str(frame) and "联网证据尚不足" in str(frame) for frame in frames)
        with closing(sqlite3.connect(database)) as conn:
            rows = conn.execute("SELECT content,continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='fallback'").fetchall()
        assert len(rows) == 1
        context = json.loads(rows[0][1])
        assert context["kind"] == "chat" and context["raw_text"] == "这是原有问答的概念解释。"
        assert context["network_evidence"]["sources"] == [source]
        assert context["network_evidence"]["claims"] == [rejected]
        assert context["network_evidence"]["network_text_sha256"] == text_hash("联网证据尚不足。")
        replay = send(ws, "send_message", "fallback", payload)
        assert len(calls) == 1
        assert any(rows[0][0] == frame.get("payload", {}).get(key)
                   for frame in replay for key in ("student_message", "final_text"))
        send(ws, "send_message", "next-offline", {"text": "谢谢"})
        with closing(sqlite3.connect(database)) as conn:
            later = conn.execute("SELECT continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='next-offline'").fetchone()
        assert "network_evidence" not in json.loads(later[0])


def test_learning_plan_receipt_is_saved_with_final_network_answer(tmp_path):
    database = tmp_path / "plan-receipt.db"
    text = "已有检查的解释。\n\n接下来怎么学：先看基础概念。"
    receipt = {"policy": "network-learning-receipt-v1", "goal": "probability", "profile_revision": "a" * 64,
               "evidence_ids": ["event-4"], "catalog_version": "catalog-v1",
               "resources": [{"resource_id": "resource-1", "summary_sha256": text_hash("教学摘要")}],
               "final_text_sha256": text_hash(text)}
    async def answer(owner, **options):
        return NetworkReply(text, "answered", "概率学习", planner_receipt=receipt)
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.network_qa = SimpleNamespace(maybe_respond=answer)
        send(ws, "send_message", "plan", {"text": "概率怎么学？", "network_search": True})
        with closing(sqlite3.connect(database)) as conn:
            content, context = conn.execute("SELECT content,continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='plan'").fetchone()
        evidence = json.loads(context)["network_evidence"]
        assert evidence["planner"] == receipt
        assert content == text and text_hash(content) == receipt["final_text_sha256"]


def test_provider_failure_still_commits_a_local_plan_without_unreviewed_chat_rewrite(tmp_path):
    database = tmp_path / "local-plan.db"
    class OfflineClient:
        calls = 0
        async def search(self, *args, **kwargs):
            self.calls += 1
            raise ZhihuError("unavailable", "provider unavailable")
    class Responder:
        is_configured = True
        async def respond(self, *args, **kwargs):
            pytest.fail("A recorded local plan must not be rewritten by the fallback responder")
    provider = OfflineClient()
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.controller.network_qa = NetworkQA(provider, state.verification_backend, planner=state.recommendations.plan_for)
        state.controller.chat_responder = Responder()
        payload = {"text": "下一步怎么学习概率？", "network_search": True}
        frames = send(ws, "send_message", "local-plan", payload)
        with closing(sqlite3.connect(database)) as conn:
            content, context = conn.execute("SELECT content,continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='local-plan'").fetchone()
        evidence = json.loads(context)["network_evidence"]
        assert evidence["status"] == "local_plan"
        assert evidence["planner"]["network_status"] == "unavailable"
        assert evidence["planner"]["network_answer_available"] is False
        assert evidence["planner"]["evidence_ids"] == []
        assert evidence["planner"]["reason_code"] == "outside_assessment_scope"
        assert evidence["network_text"] == content
        assert text_hash(content) == evidence["planner"]["final_text_sha256"]
        assert "暂不可用" in content and "本地学习记录与已审核的资料目录" in content
        assert any(content == frame.get("payload", {}).get(key) for frame in frames for key in ("student_message", "final_text"))
        send(ws, "send_message", "local-plan", payload)
        assert provider.calls == 1


def test_local_calculation_keeps_provider_failure_and_bound_receipt(tmp_path):
    database = tmp_path / "local-example.db"
    question = "请解释分数相加，用 2/3+1/4 举例。"
    class OfflineClient:
        calls = 0
        async def search(self, *args, **kwargs):
            self.calls += 1
            raise ZhihuError("unavailable", "provider unavailable")
    class Responder:
        is_configured = True
        async def respond(self, *args, **kwargs):
            pytest.fail("Verified calculations must not be rewritten by the fallback model")
    provider = OfflineClient()
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.controller.network_qa = NetworkQA(provider, state.verification_backend)
        state.controller.chat_responder = Responder()
        payload = {"text": question, "network_search": True}
        frames = send(ws, "send_message", "calculation", payload)
        with closing(sqlite3.connect(database)) as conn:
            content, context = conn.execute("SELECT content,continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='calculation'").fetchone()
            event_count = conn.execute("SELECT count(*) FROM learning_events").fetchone()[0]
        evidence = json.loads(context)["network_evidence"]
        assert evidence["status"] == "unavailable" and evidence["claims"] == []
        assert len(evidence["calculations"]) == 1
        receipt = evidence["calculations"][0]
        assert receipt["source_text"] == question[receipt["span_start"]:receipt["span_end"]] == "2/3+1/4"
        assert receipt["question_hash"] == text_hash(question)
        assert receipt["source_state"] == "none" and receipt["math_state"] == "correct"
        assert receipt["verification_hash"] and receipt["candidate_hash"]
        assert "11" in receipt["answer_latex"] and "12" in receipt["answer_latex"]
        assert "暂不可用" in content and "核验范围仅限" in content
        assert evidence["network_text_sha256"] == text_hash(content)
        assert event_count == 0
        assert any(content == frame.get("payload", {}).get(key) for frame in frames for key in ("student_message", "final_text"))
        send(ws, "send_message", "calculation", payload)
        assert provider.calls == 1


@pytest.mark.parametrize("state", [CycleState.PROBLEM_RECEIVED, CycleState.GROUNDING,
    CycleState.AWAITING_CLARIFICATION, CycleState.UNVERIFIED_BLOCKED, CycleState.AWAITING_ATTEMPT])
async def test_unverified_or_active_cycle_blocks_network_before_any_service_call(state):
    async def answer(*args, **kwargs):
        pytest.fail("An active unverified exercise cannot be bypassed by online knowledge chat")
    request = SimpleNamespace(owner=SimpleNamespace(student_id="student"), session_id="active", conversation_messages=())
    controller = SimpleNamespace(network_qa=SimpleNamespace(maybe_respond=answer))
    result = await network_reply(controller, request, SimpleNamespace(state=state),
        {"text": "下一步怎么学习概率？", "network_search": True})
    assert result is None


async def test_hints_only_blocks_network_in_an_otherwise_open_chat():
    calls = []
    async def answer(*args, **kwargs):
        pytest.fail("Explicit hints-only scope cannot request an online full explanation or plan")
    async def configuration(owner, conversation):
        calls.append((owner, conversation))
        return {"hints_only": True}
    request = SimpleNamespace(owner=SimpleNamespace(student_id="student"), session_id="open", conversation_messages=())
    controller = SimpleNamespace(network_qa=SimpleNamespace(maybe_respond=answer),
                                 knowledge=SimpleNamespace(configuration=configuration))
    assert await network_reply(controller, request, None,
        {"text": "概率怎么学？", "network_search": True}) is None
    assert calls == [("student", "open")]


@pytest.mark.parametrize("previous", ["[]", "null", "not json"])
def test_continuation_merge_handles_legacy_non_object_context(previous):
    turn = SimpleNamespace(continuation_context=previous)
    merge_continuation_context(turn, {"network_evidence": {"status": "unsupported"}})
    merge_continuation_context(turn, {"kind": "chat", "raw_text": "fallback"})
    assert json.loads(turn.continuation_context) == {
        "network_evidence": {"status": "unsupported"}, "kind": "chat", "raw_text": "fallback"}


def test_recommendation_routes_opt_in_owner_and_educational_deletion(tmp_path):
    with client_at(tmp_path / "recommendations.db") as client:
        initial = client.post(ROOT + "/start").json()
        assert initial["enabled"] is False and initial["status"] == "disabled"
        assert initial["plan"]["resources"] and initial["plan"]["evidence_count"] == 0
        response = client.put(ROOT + "/configuration", json={"enabled": True, "goal": "probability"})
        assert response.status_code == 200, response.text
        assert response.json()["goal"] == "probability"
        assert client.post(ROOT + "/start").json()["status"] == "not_configured"
        assert client.put(ROOT + "/configuration", json={"enabled": True, "goal": "private diary"}).status_code == 422
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        assert client.get(ROOT).json()["goal"] == "math_foundations"
        assert client.get(ROOT).json()["enabled"] is False
        client.app.dependency_overrides.clear()
        assert client.get(ROOT).json()["goal"] == "probability"
        response = client.delete(ROOT)
        assert response.status_code == 200 and response.json()["enabled"] is False


@pytest.mark.parametrize("payload", [{"network_search": "true"}, {"network_context": ["private"]},
    {"network_context": "x" * 2001}, {"reply_language": "unsupported"}])
def test_network_payload_rejects_ambiguous_options(payload):
    with pytest.raises(SecurityViolationError):
        validate_client_envelope({"command": "send_message", "payload": payload})
