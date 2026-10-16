"""Presentation and tool safety through the actual offline product path."""
import json
import asyncio

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from test_math_tool_loop import answer, bind, tool_call
from test_tutor_p0 import client_at, send


class Replies:
    provider_id, model = "offline", "request-contract"

    def __init__(self, *texts):
        self.texts, self.calls = iter(texts), []

    async def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return CompletionResult(text=next(self.texts), finish_reason="stop",
                                provider_id=self.provider_id, model=self.model,
                                input_tokens=10, output_tokens=10)


def test_current_output_slot_reaches_writer_after_default_style(tmp_path):
    provider = Replies("Subtract the same amount from both sides. Which constant can you remove first?")
    with client_at(tmp_path / "format.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        frames = send(ws, "send_message", "two-sentences", {"text":
            "Help the student understand equality. Answer in English.\nConversation:\n"
            "Teacher: Write a long explanation.\nStudent: Why must both sides change?\n"
            "Teacher (maximum two sentences):"})
    assert len(provider.calls) == 1
    system = provider.calls[0][0][0]["content"]
    assert "Use at most 2 sentences." in system
    assert system.index("Use at most 2 sentences.") > system.index("两到四个短段落")
    final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert final["final_text"].startswith("Subtract")
    assert final["verification_notice"]


def test_math_repair_keeps_original_language_and_hint_scope(tmp_path):
    provider = Replies("Try adding $7+5=13$ first.", "Try adding $7+5=12$ first.")
    with client_at(tmp_path / "repair-scope.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        frames = send(ws, "send_message", "repair", {"text":
            "Answer in English in at most two sentences. Only give me one hint: "
            "how can I add 7 and 5 without counting every object?"})
    assert len(provider.calls) == 2
    repair_system = provider.calls[1][0][0]["content"]
    assert "Reply in English" in repair_system
    assert "Use at most 2 sentences." in repair_system
    assert "限制答案披露" in repair_system
    final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert "7+5=12" in final["final_text"] and "7+5=13" not in final["final_text"]


def test_repair_preserves_first_contact_disclosure_limit(tmp_path):
    provider = Replies("先算 $7+5=13$。", "先算 $7+5=12$。")
    with client_at(tmp_path / "first-contact.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.learner_settings.update("high", 11)
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        send(ws, "send_message", "repair", {"text": "已知某函数满足 f(x)=x^3，求它的极值。"})
    assert len(provider.calls) == 2
    assert all("首次接触" in call[0][0]["content"] for call in provider.calls)


def test_continuation_restores_original_language_and_disclosure_request(tmp_path):
    from test_tutor_recovery import ReplayProvider
    request = "Answer in English in at most two sentences. Only give me a hint about the derivative of x^3."
    provider = ReplayProvider([("length", "Start with the power rule."),
                               ("length", "Identify the exponent first."),
                               ("stop", "Then write the factor without evaluating the final derivative.")])
    with client_at(tmp_path / "continue-contract.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        first = send(ws, "send_message", "first", {"text": request})
        assert any(f["event_type"] == "assistant_partial" for f in first)
        second = send(ws, "send_message", "next", {"text": "继续"})
    assert len(provider.calls) == 3
    system = provider.calls[-1][0][0]["content"]
    assert "Reply in English" in system and "Use at most 2 sentences." in system
    assert "限制答案披露" in system
    assert next(f for f in second if f["event_type"] == "assistant_complete")["payload"]["final_text"].startswith("Then")


def test_real_local_dkt_changes_chat_writer_guidance_without_creating_evidence(tmp_path):
    """The same request uses real bundled weights and trusted synthetic facts.

    This proves the wiring, not an improvement in real student learning or
    answer correctness. The provider is a fixed local test double.
    """
    prompts = {}
    for outcome in ("incorrect", "correct"):
        provider = Replies("等式两边要做同一种运算。")
        with client_at(tmp_path / f"dkt-{outcome}.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            state = get_product_state()
            state.learner_settings.update("high", 11)
            state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)

            async def record():
                for i in range(5):
                    await state.student_state.record_attempt("local-admin", session_id=f"prior-{i}",
                        cycle_id=f"prior-cycle-{i}", problem_id=f"prior-item-{i}", problem_revision=f"prior-revision-{i}",
                        item_family_id="linear", skill_ids=("linear_isolation",),
                        assessment_id=f"prior-assessment-{i}", attempt_id=f"prior-attempt-{i}", correctness=outcome)

            asyncio.run(record())
            before = len(asyncio.run(state.student_state.events("local-admin")))
            frames = send(ws, "send_message", "adapt", {"text": "说说一元一次方程的学习方法。"})
            after = len(asyncio.run(state.student_state.events("local-admin")))
            traces = client.get("/api/v2/math-tutor/desktop/diagnostics/turns").json()["turns"]
            adaptation = next(row for row in traces if row["turn_id"] == "adapt")["details"]["adaptation"]
        assert after == before
        assert len(provider.calls) == 1
        assert adaptation["evidence_count"] == 5 and adaptation["model_sha256"]
        assert adaptation["strategy"] == ("smaller_step" if outcome == "incorrect" else "lighter_scaffold")
        assert next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]["status"] == "COMPLETED"
        prompts[outcome] = provider.calls[0][0][0]["content"]
    assert "拆小一档" in prompts["incorrect"]
    assert "可少解释一档" in prompts["correct"]
    assert prompts["incorrect"] != prompts["correct"]


@pytest.mark.parametrize("expression, proposed", [
    ("derivative(x^2,x)", "2*x" + " " * 197 + "+1"),
    ("x=1" + " " * 197 + "+1", "x=1"),
    ("derivative(x^2,x)", 2),
    ("derivative(x^2,x)", ""),
    ("derivative(x^2,x)", {"answer": "2*x"}),
])
def test_tool_never_verifies_a_silently_truncated_or_coerced_claim(tmp_path, expression, proposed):
    requests = []
    replies = [tool_call(expression, proposed), answer("Please write the derivative expression in the supported form.")]
    with client_at(tmp_path / "tool-arguments.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "derivative", {"text": "如何对 (2*x-3)^3 求导？"})
    assert len(requests) == 2, [(f["event_type"], f["payload"].get("final_text")) for f in frames]
    receipt = json.loads(next(m for m in requests[1]["messages"] if m["role"] == "tool")["content"])
    assert receipt["status"] == "rejected"
    assert "200" in receipt["reason"]
