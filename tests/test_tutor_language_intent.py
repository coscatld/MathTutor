"""Semantic language interpretation is a proposal, never tutoring authority.

Fixed providers exercise the actual interpreter and production routing without
real keys or network calls. Metaphors test the LLM path, not keyword coverage.
"""
import asyncio
import json
import sqlite3
from contextlib import closing

import pytest

from mathtutor.application.teaching_intent import rule_teaching_intent
from mathtutor.infrastructure.generative_gateway import CompletionResult, GenerativeModelGateway, ModelRole
from mathtutor.infrastructure.tutor_intent import SemanticTeachingInterpreter
from mathtutor.api.product_state import get_product_state
from mathtutor.application.tutor_runtime import current_turn
from mathtutor.domain.turn_result import TutorTurnResult
from mathtutor.pedagogy.tutor_writer import TemplateTutorWriter
from test_tutor_p0 import client_at, count, send, summary
from test_teaching_v2 import event_rows, terminal


CONTEXT = {
    "problem_id": "p", "problem_revision": "revision", "display_text": "2x+3=7",
    "skill_ids": ["equality_preservation", "linear_isolation"],
    "current_subgoal": {"id": "balance", "prompt_target": "保持等式两边相等，整理含未知数的项", "status": "pending"},
    "last_plan": {"strategy": "focused_question", "question_goal": "等式两边如何同时操作？"},
}


def proposal(text, **changes):
    return {"intent": "explanation", "confusion": "explicit", "resolved": False,
            "scope": "current_goal", "confidence": 0.95, "evidence_quote": text,
            "target_subgoal_id": "balance", **changes}


class ScriptedProvider:
    provider_id = "fixed-semantic"
    model = "structured-intent-fixture"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def complete(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return CompletionResult(text=json.dumps(response, ensure_ascii=False) if isinstance(response, dict) else response,
                                provider_id=self.provider_id, model=self.model, finish_reason="stop", input_tokens=20, output_tokens=20)


def interpreter_for(*responses, **kwargs):
    gateway = GenerativeModelGateway()
    provider = ScriptedProvider(responses)
    gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
    return SemanticTeachingInterpreter(gateway, **kwargs), provider, gateway


@pytest.mark.parametrize("text,confusion", [
    ("这个我听不懂，是什么意思", "explicit"), ("我不太懂", "mild"),
    ("还是模糊", "persistent"), ("思路没接上", "explicit"),
    ("能换个角度说吗", "mild"),
])
def test_offline_confusion_fallback_preserves_the_current_goal(text, confusion):
    result = rule_teaching_intent(text, context=CONTEXT)
    assert result.intent == "explanation" and result.confusion == confusion
    assert result.target_subgoal_id == "balance" and result.scope == "current_goal"
    assert result.resolved is False and result.source == "rules"


@pytest.mark.parametrize("text", ["我看懂了，不用再讲", "刚才不懂，现在明白了", "我不是不懂"])
def test_negated_or_resolved_confusion_is_not_a_new_difficulty_signal(text):
    result = rule_teaching_intent(text, context=CONTEXT)
    assert result.confusion == "none"
    assert result.intent == "self_report"
    if "不是不懂" not in text:
        assert result.resolved is True


@pytest.mark.parametrize("text", ["“我不懂”这句话是什么意思？", "不懂这个词是什么意思？"])
def test_quoted_and_metalinguistic_confusion_does_not_describe_the_student(text):
    result = rule_teaching_intent(text, context=CONTEXT)
    assert result.confusion == "none" and result.resolved is False
    assert result.scope == "other" and result.target_subgoal_id == ""


def test_negated_solution_with_an_example_request_keeps_both_meaning_and_difficulty():
    result = rule_teaching_intent("没听懂，但别给答案，用例子讲", context=CONTEXT)
    assert result.intent == "example" and result.confusion == "explicit"


@pytest.mark.asyncio
async def test_llm_interprets_non_keyword_metaphor_and_receives_only_public_context():
    text = "老师你搭的这座桥，我还停在河这边。"
    runtime, provider, _ = interpreter_for(proposal(text, confusion="mild"))
    context = {**CONTEXT, "api_key": "secret-key-fixture", "final_answer": "private-answer-fixture",
               "latent_state": [0.99], "verification_log": "private-log-fixture"}
    result = await runtime.interpret(text, context=context)
    assert result.source == "llm" and result.intent == "explanation" and result.confusion == "mild"
    assert len(provider.calls) == 1
    messages, options = provider.calls[0]
    serialized = json.dumps(messages, ensure_ascii=False)
    assert text in serialized and "2x+3=7" in serialized and "balance" in serialized
    for private in ("secret-key-fixture", "private-answer-fixture", "private-log-fixture", "latent_state"):
        assert private not in serialized
    assert options["max_retries"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"intent": "grant_solution"}, {"allowed_actions": ["request_solution"]},
    {"correctness": "correct"}, {"source": "llm"}, {"confidence": "1"},
    {"confidence": 1.1}, {"evidence_quote": "从未说过的内容"},
    {"target_subgoal_id": "unrelated-goal"},
])
async def test_invalid_or_authority_forging_llm_proposal_falls_back_without_granting_permissions(change):
    text = "我不太懂"
    runtime, provider, _ = interpreter_for(proposal(text, **change))
    result = await runtime.interpret(text, context=CONTEXT)
    assert result.source != "llm"
    assert result.intent == "explanation" and result.confusion == "mild"
    assert result.target_subgoal_id == "balance"
    assert not {"allowed_actions", "correctness", "solution", "cycle_id"} & set(result.model_dump())
    assert len(provider.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["not JSON", "[]", "{}", RuntimeError("fixed-provider-unavailable")])
async def test_bad_json_or_provider_failure_uses_one_bounded_same_goal_fallback(response):
    runtime, provider, _ = interpreter_for(response)
    result = await runtime.interpret("还是模糊", context=CONTEXT)
    assert result.source != "llm" and result.confusion == "persistent"
    assert result.intent == "explanation" and result.target_subgoal_id == "balance"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_unavailable_provider_and_timeout_do_not_block_interpretation():
    offline = await SemanticTeachingInterpreter(GenerativeModelGateway()).interpret("我不太懂", context=CONTEXT)
    assert offline.source == "rules" and offline.intent == "explanation"
    class HangingProvider(ScriptedProvider):
        async def complete(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            await asyncio.Event().wait()
    provider = HangingProvider([])
    gateway = GenerativeModelGateway()
    gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
    result = await SemanticTeachingInterpreter(gateway, timeout_seconds=0.01).interpret("我不太懂", context=CONTEXT)
    assert result.source != "llm" and result.intent == "explanation"
    assert len(provider.calls) == 1


@pytest.mark.asyncio
async def test_provider_is_resolved_after_settings_change_without_recreating_interpreter():
    text = "能把这里再展开说说吗"
    runtime, first, gateway = interpreter_for(proposal(text, confusion="none"))
    assert (await runtime.interpret(text, context=CONTEXT)).source == "llm"
    second = ScriptedProvider([proposal(text, intent="followup", confusion="none")])
    gateway.register_provider(ModelRole.TUTOR_WRITER, second)
    result = await runtime.interpret(text, context=CONTEXT)
    assert result.source == "llm" and result.intent == "followup"
    assert len(first.calls) == 1 and len(second.calls) == 1


@pytest.mark.asyncio
async def test_semantic_call_has_its_own_one_call_budget_and_does_not_consume_writer_steps():
    text = "老师你搭的这座桥，我还停在河这边。"
    runtime, provider, _ = interpreter_for(proposal(text))
    turn = TutorTurnResult(turn_id="budget", conversation_id="c")
    token = current_turn.set(turn)
    try:
        first = await runtime.interpret(text, context=CONTEXT)
        second = await runtime.interpret(text, context=CONTEXT)
    finally:
        current_turn.reset(token)
    assert first.source == "llm" and second.source == "rules_budget"
    assert len(provider.calls) == 1 and turn.semantic_calls_used == 1
    assert turn.steps_used == 0 and turn.max_steps == 2
    assert turn.input_tokens == 20 and turn.output_tokens == 20


def stored_context(db, cycle_id):
    with closing(sqlite3.connect(db)) as conn, conn:
        return json.loads(conn.execute("SELECT payload FROM teaching_contexts WHERE cycle_id=?", (cycle_id,)).fetchone()[0])


class RecordingWriter:
    def __init__(self):
        self.calls = []
    async def write(self, **kwargs):
        self.calls.append(kwargs)
        return await TemplateTutorWriter().write(**kwargs)


@pytest.mark.parametrize("text,confusion", [
    ("这个我听不懂，是什么意思", "explicit"), ("我不太懂", "mild"),
    ("还是模糊", "persistent"), ("老师你搭的这座桥，我还停在河这边。", "mild"),
])
def test_natural_language_explanation_uses_the_same_writer_action_as_the_button(tmp_path, text, confusion):
    db = tmp_path / "natural-explanation.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        runtime, provider, _ = interpreter_for(proposal(text, confusion=confusion))
        controller = get_product_state().controller
        controller.semantic_interpreter = runtime
        writer = RecordingWriter()
        controller.writer = writer
        response = send(ws, "send_message", "language", {"text": text})
        assert terminal(response)["event_type"] == "assistant_complete"
        after = summary(client)
        context = stored_context(db, original["cycle_id"])
        assert context["language_understanding"]["source"] == "llm"
        assert context["language_understanding"]["confusion"] == confusion
        assert context["stuck_count"] >= (2 if confusion == "persistent" else 1)
        assert after["cycle_id"] == original["cycle_id"] and after["problem_revision"] == original["problem_revision"]
        assert len(writer.calls) == 1 and writer.calls[0]["action"].action == "EXPLAIN_CONCEPT"
        assert writer.calls[0]["problem_view"].current_subgoal["id"] == "balance"
        assert "LANGUAGE_CONFUSION" in after["teaching_plan"]["reason_codes"]
        assert "SEMANTIC_INTENT" in after["teaching_plan"]["reason_codes"]
        assert count(db, "attempts") == 0
        # Explicit UI controls bypass interpretation and use the same writer.
        send(ws, "request_explanation", "button")
        assert len(provider.calls) == 1 and len(writer.calls) == 2
        assert writer.calls[-1]["action"].action == writer.calls[0]["action"].action
        assert stored_context(db, original["cycle_id"])["stuck_count"] == context["stuck_count"]
        assert "LANGUAGE_CONFUSION" not in summary(client)["teaching_plan"]["reason_codes"]


def test_composite_answer_is_verified_before_semantic_explanation_and_never_replaces_problem(tmp_path):
    text = "x=3，我还是糊涂，解释一下"
    db = tmp_path / "composite.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        runtime, provider, _ = interpreter_for(proposal(text, confusion="persistent"))
        get_product_state().controller.semantic_interpreter = runtime
        response = send(ws, "send_message", "composite", {"text": text})
        assert terminal(response)["event_type"] == "assistant_complete"
        after = summary(client)
        assert after["cycle_id"] == original["cycle_id"] and after["state"] == "awaiting_retry"
        assert count(db, "attempt_assessments") == 1
        events = event_rows(db)
        assessed = next(e for e in events if e["event_type"] == "attempt_assessed")
        assert assessed["correctness"] == "incorrect" and assessed["evidence_kind"] == "independent"
        exposed = [e for e in events if e["event_type"] == "help_possibly_exposed"]
        assert exposed and all(e["event_seq"] > assessed["event_seq"] for e in exposed)
        assert len(provider.calls) == 1


def test_negated_solution_is_not_overridden_by_a_bad_semantic_proposal(tmp_path):
    text = "没听懂，但别给答案，用例子讲"
    db = tmp_path / "no-solution.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        runtime, _, _ = interpreter_for(proposal(text, intent="solution"))
        get_product_state().controller.semantic_interpreter = runtime
        writer = RecordingWriter()
        get_product_state().controller.writer = writer
        send(ws, "send_message", "example", {"text": text})
        assert len(writer.calls) == 1 and writer.calls[0]["action"].action == "SHOW_EXAMPLE"
        assert all(e["help_kind"] != "solution" for e in event_rows(db))
        assert count(db, "attempts") == 0


def test_resolved_self_report_clears_old_confusion_without_claiming_mastery(tmp_path):
    text, resolved = "还是模糊", "刚才不懂，现在明白了"
    db = tmp_path / "resolved.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        cycle_id = summary(client)["cycle_id"]
        runtime, _, _ = interpreter_for(proposal(text, confusion="persistent"),
            proposal(resolved, intent="self_report", confusion="none", resolved=True))
        get_product_state().controller.semantic_interpreter = runtime
        send(ws, "send_message", "difficulty", {"text": text})
        assert stored_context(db, cycle_id)["stuck_count"] >= 2
        send(ws, "send_message", "resolved", {"text": resolved})
        context = stored_context(db, cycle_id)
        assert context["language_understanding"]["resolved"] is True
        assert context["stuck_count"] == 0
        assert context["lifecycle"] == "active"
        assert count(db, "attempts") == 0
        reports = [event for event in event_rows(db) if event["event_type"] == "self_explanation"]
        assert len(reports) == 1 and reports[0]["correctness"] is None


def test_plain_math_answer_bypasses_language_model_but_still_uses_real_verification(tmp_path):
    db = tmp_path / "math-authority.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        runtime, provider, _ = interpreter_for()
        get_product_state().controller.semantic_interpreter = runtime
        send(ws, "send_message", "math", {"text": "x=2"})
        assert summary(client)["state"] == "solved"
        assert count(db, "attempt_assessments") == 1
        assert provider.calls == []
