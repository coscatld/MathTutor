"""Formulas in model explanations go through verify_math before delivery."""
import asyncio
import json

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.math_claims import anchor_for, certify, certify_and_annotate, extract_statements
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.pedagogy.tutor_writer import TutorWriterCandidate
from mathtutor.solving.parser import parse_problem
from test_tutor_p0 import client_at, send, summary

BACKEND = InProcessVerificationBackend()


def run(text, anchor=None):
    return asyncio.run(certify(text, BACKEND, anchor=anchor))


def refuted(result):
    return [statement.shown for statement, _ in result.refuted]


@pytest.mark.parametrize("text, verified", [
    ("两边同时减 3：$2x+3-3=7-3$，得到 $2x=4$，再除以 2：$x=2$。代回检验 $2\\times 2+3=7$。", 3),
    ("完全平方公式：$(x+1)^2=x^2+2x+1$。", 1),
    ("由 $x^2-5x+6=0$ 得 $(x-2)(x-3)=0$，所以 $x=2$ 或 $x=3$。", 2),
    ("x = 7 - 3 = 4", 1),
    ("$\\frac{1}{2}+\\frac{1}{3}=\\frac{5}{6}$", 1),
    ("比如 $3x=6$，两边除以 3 得 $x=2$。例如 $x+1=5$，所以 $x=4$。", 2),
])
def test_correct_formulas_are_verified(text, verified):
    result = run(text)
    assert (result.verified, result.refuted) == (verified, [])


@pytest.mark.parametrize("text, wrong, reason", [
    ("先算 $3\\times 4+2=15$，再看下一步。", "3\\times 4+2=15", "计算结果不对"),
    ("展开得 $(x+1)^2 = x^2+1$。", "(x+1)^2 = x^2+1", "两边不是恒等的"),
    ("由 $x^2-5x+6=0$ 得 $(x-2)(x-3)=0$，所以 $x=2$。", "x=2", "漏掉了解"),
])
def test_wrong_formulas_are_refuted_with_a_reason(text, wrong, reason):
    result = run(text)
    assert [(s.shown, why) for s, why in result.refuted] == [(wrong, reason)]


def test_bound_problem_anchors_the_derivation():
    problem = parse_problem("x^2-5x+6=0").problem
    assert anchor_for(problem) == ("quadratic", "x^(2) - 5x + 6 = 0")
    assert refuted(run("两边减 3 得 $2x=10$。", ("linear", "2x+3=7"))) == ["2x=10"]
    assert run("配方得 $(x-5/2)^2=1/4$。", anchor_for(problem)).verified == 1
    assert anchor_for(parse_problem("3+4").problem) is None


def test_premise_without_anchor_and_prose_are_not_claims():
    assert run("两边同时减 3，得到 $2x=10$，所以 $x=5$。").refuted == []
    assert extract_statements("等式两边同时减去相同的数，等式仍然成立。") == []
    assert extract_statements("If x is positive, use the formula.") == []


def test_notice_reports_the_outcome_and_marks_refuted_formulas_in_place():
    good, _ = asyncio.run(certify_and_annotate("得到 $2x=4$，所以 $x=2$。", BACKEND, anchor=("linear", "2x+3=7")))
    assert good.startswith("> 本段讲解中的 2 处算式已由本地验证器逐一核对；文字说明未经核验。")
    bad, _ = asyncio.run(certify_and_annotate("> 本段讲解未经逐句数学核验。\n\n先算 $3+4=8$。", BACKEND))
    assert bad.count("> ") == 1 and bad.startswith("> ⚠️ 本段讲解中有 1 处算式没有通过")
    assert "$3+4=8$（⚠️ 核验未通过：「3+4=8」计算结果不对）" in bad
    plain, _ = asyncio.run(certify_and_annotate("同类项可以合并。", BACKEND))
    assert plain == "> 本段讲解未经逐句数学核验。\n\n同类项可以合并。"


class StepWriter:
    def __init__(self, text):
        self.text = text

    async def write(self, **kwargs):
        return TutorWriterCandidate(text=self.text, writer_version="model-step-writer")


def test_teaching_path_replaces_a_refuted_model_step_with_the_verified_template(tmp_path):
    with client_at(tmp_path / "claims.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        get_product_state().controller.writer = StepWriter(
            "等式两边同时减去同一个数仍然相等。比如 $5+2=8$，两边减 2 得 $5=8-2$。原方程两边该同时减几？")
        frames = send(ws, "request_hint", "hint")
        shown = [f["payload"]["student_message"] for f in frames if f["event_type"] == "assistant_delta"][-1]
        assert "5+2=8" not in shown and "核验" not in shown
        saved = next(m for m in summary(client)["messages"] if m.get("turn_id") == "hint")
        assert saved["content"] == shown


def test_teaching_path_reports_verified_model_formulas(tmp_path):
    with client_at(tmp_path / "claims.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        get_product_state().controller.writer = StepWriter(
            "等式两边同时减去同一个数仍然相等。比如 $5+2=7$，两边减 2 得 $5=7-2$。原方程两边该同时减几？")
        frames = send(ws, "request_hint", "hint")
        shown = [f["payload"]["student_message"] for f in frames if f["event_type"] == "assistant_delta"][-1]
        assert shown.startswith("> 本段讲解中的 2 处算式已由本地验证器逐一核对；文字说明未经核验。")


def test_free_chat_marks_a_wrong_formula(tmp_path):
    class WrongChat:
        async def respond(self, text, **kwargs):
            return "分数相加要先通分：$\\frac{1}{2}+\\frac{1}{3}=\\frac{2}{5}$。"

    with client_at(tmp_path / "chat.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.chat_responder = WrongChat()
        frames = send(ws, "send_message", "chat", {"text": "分数怎么相加？"})
        final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]["final_text"]
        assert final.startswith("> ⚠️ 本段讲解中有 1 处算式没有通过本地验证器核对")
        assert "（⚠️ 核验未通过：" in final
        assert send(ws, "send_message", "chat", {"text": "分数怎么相加？"}) == frames


class FixOnSecondCall:
    def __init__(self):
        self.prompts = []

    async def respond(self, text, **kwargs):
        self.prompts.append((text, kwargs.get("history", ())))
        return "通分以后 $\\frac{1}{2}+\\frac{1}{3}=\\frac{5}{6}$。" if len(self.prompts) > 1 else \
            "通分以后 $\\frac{1}{2}+\\frac{1}{3}=\\frac{2}{5}$。"


def test_free_chat_repairs_a_wrong_formula_once_and_shows_the_checked_answer(tmp_path):
    chat = FixOnSecondCall()
    with client_at(tmp_path / "repair.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.chat_responder = chat
        frames = send(ws, "send_message", "chat", {"text": "分数怎么相加？"})
        final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert final["status"] == "COMPLETED"
    assert final["verification_notice"].startswith("本段讲解中的 1 处算式已由本地验证器逐一核对")
    assert not final["final_text"].startswith("> 本段讲解")
    assert "2}{5}" not in final["final_text"] and "⚠️" not in final["final_text"]
    feedback, history = chat.prompts[1]
    assert "没有通过本地验证器核对" in feedback and "计算结果不对" in feedback
    assert history[-1]["content"].endswith("\\frac{2}{5}$。")


def test_a_failed_repair_call_keeps_the_marked_first_answer(tmp_path):
    class BreaksOnRepair:
        calls = 0

        async def respond(self, text, **kwargs):
            BreaksOnRepair.calls += 1
            if BreaksOnRepair.calls > 1:
                raise RuntimeError("provider down")
            return "先算 $3+4=8$。"

    with client_at(tmp_path / "repair.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.chat_responder = BreaksOnRepair()
        frames = send(ws, "send_message", "chat", {"text": "加法交换律是什么意思？"})
        final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert BreaksOnRepair.calls == 2 and final["status"] == "COMPLETED"
    assert "（⚠️ 核验未通过：「3+4=8」计算结果不对）" in final["final_text"]


def test_knowledge_mode_repairs_with_the_question_and_feedback(tmp_path):
    class Knowledge:
        def __init__(self):
            self.questions = []

        async def respond(self, owner, sid, text, messages, practice=None):
            self.questions.append(text)
            return "资料里的例子：$2\\times 3=6$。" if len(self.questions) > 1 else "资料里的例子：$2\\times 3=5$。"

    knowledge = Knowledge()
    with client_at(tmp_path / "repair.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        asyncio.run(state.knowledge.configure("local-admin", "p0", space_ids=[], mode="knowledge"))
        state.controller.knowledge_qa = knowledge
        frames = send(ws, "send_message", "kq", {"text": "解释这份资料"})
        final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]["final_text"]
    assert knowledge.questions[1].startswith("解释这份资料") and "计算结果不对" in knowledge.questions[1]
    assert "2\\times 3=6" in final and "⚠️" not in final


def test_repair_through_the_real_runtime_gets_one_extra_step_and_completes(tmp_path):
    import httpx
    from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
    from mathtutor.infrastructure.tutor_chat import TutorChatResponder

    answers = iter(["先算 $3+4=8$。", "先算 $3+4=7$。"])
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": next(answers)}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    async def key():
        return "test-key-not-real"

    with client_at(tmp_path / "runtime.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(
            base_url="https://example.invalid/v1", model="m", api_key_resolver=key, transport=httpx.MockTransport(transport)))
        state.controller.chat_responder = TutorChatResponder(state.gateway)
        frames = send(ws, "send_message", "chat", {"text": "加法交换律是什么意思？"})
        final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert len(calls) == 2
    assert final["status"] == "COMPLETED" and final["finish_reason"] in {"NATURAL_STOP", "FINAL_ANSWER"}
    assert "3+4=7" in final["final_text"] and "⚠️" not in final["final_text"]
