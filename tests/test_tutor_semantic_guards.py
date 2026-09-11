"""Bounded language context, explicit disclosure consent and usage accounting."""
import json

import pytest

from mathtutor.application.tutor_runtime import current_turn
from mathtutor.domain.turn_result import TutorTurnResult
from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole
from mathtutor.infrastructure.tutor_intent import SemanticTeachingInterpreter
from test_tutor_language_intent import CONTEXT, ScriptedProvider, interpreter_for, proposal


@pytest.mark.asyncio
async def test_visible_history_is_bounded_and_does_not_include_hidden_fields():
    text = "你上一句说的是什么意思"
    runtime, provider, _ = interpreter_for(proposal(text, confusion="mild"))
    context = {**CONTEXT, "stuck_count": 4, "help_without_progress": 2,
        "recent_teaching": {"strategy": "analogy", "question_goal": "等式保持", "support_mode": "guided",
                            "full_solution": "HIDDEN_FULL_SOLUTION", "private_reasoning": "HIDDEN_REASONING"},
        "recent_messages": [{"role": "tutor", "content": "oldest-hidden-from-window"},
                            {"role": "student", "content": "上一步没跟上", "api_key": "HIDDEN_KEY"},
                            {"role": "tutor", "content": "等式两边像天平" + "。" * 700, "solver_steps": "HIDDEN_SOLVER"},
                            {"role": "student", "content": "你说天平是什么意思？"}]}
    assert (await runtime.interpret(text, context=context)).source == "llm"
    sent = json.loads(provider.calls[0][0][1]["content"])["context"]
    assert len(sent["recent_messages"]) == 3
    assert all(len(row["content"]) <= 600 and set(row) == {"role", "content"} for row in sent["recent_messages"])
    assert sent["recent_teaching"]["strategy"] == "analogy" and sent["stuck_count"] == 4
    assert sent["help_without_progress"] == 2
    serialized = json.dumps(sent)
    assert "HIDDEN_" not in serialized and "oldest-hidden-from-window" not in serialized


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["我不懂", "我已经看了答案", "你刚才讲的结论是什么意思", "答案为什么是这样"])
async def test_llm_solution_proposal_requires_explicit_student_disclosure_request(text):
    runtime, _, _ = interpreter_for(proposal(text, intent="solution", confusion="none"))
    result = await runtime.interpret(text, context=CONTEXT)
    assert result.source == "rules" and result.intent == "ambiguous"
    assert result.fallback_reason == "explicit_solution_confirmation_required"


@pytest.mark.asyncio
async def test_explicit_solution_request_can_be_interpreted_but_confers_no_permission():
    text = "请给我完整解答"
    runtime, _, _ = interpreter_for(proposal(text, intent="solution", confusion="none"))
    result = await runtime.interpret(text, context=CONTEXT)
    assert result.source == "llm" and result.intent == "solution"
    assert "allowed_actions" not in result.model_dump()


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["", "unknown", "length", "max_tokens", "tool_calls", "content_filter"])
async def test_only_completed_semantic_json_is_accepted(finish):
    text = "我不太懂"
    class FinishedProvider(ScriptedProvider):
        async def complete(self, messages, **kwargs):
            result = await super().complete(messages, **kwargs)
            return result.model_copy(update={"finish_reason": finish})
    gateway = GenerativeModelGateway()
    gateway.register_provider(ModelRole.TUTOR_WRITER, FinishedProvider([proposal(text)]))
    result = await SemanticTeachingInterpreter(gateway).interpret(text, context=CONTEXT)
    assert result.source == "rules" and result.intent == "explanation"
    assert result.fallback_reason == "incomplete_semantic_output"


@pytest.mark.asyncio
async def test_semantic_call_charges_shared_usage_without_stealing_writer_steps():
    text = "我不太懂"
    runtime, provider, _ = interpreter_for(proposal(text))
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        first = await runtime.interpret(text, context=CONTEXT)
        second = await runtime.interpret(text, context=CONTEXT)
    finally:
        current_turn.reset(token)
    assert first.source == "llm" and second.source == "rules_budget"
    assert len(provider.calls) == 1 and turn.semantic_calls_used == 1
    assert turn.steps_used == 0 and turn.input_tokens == turn.output_tokens == 20
    assert turn.final_text == "" and turn.status == "COMPLETED"


@pytest.mark.asyncio
async def test_small_shared_budget_preserves_writer_reserve_without_provider_call():
    runtime, provider, _ = interpreter_for()
    turn = TutorTurnResult(max_total_tokens=2048)
    token = current_turn.set(turn)
    try:
        result = await runtime.interpret("我不太懂", context=CONTEXT)
    finally:
        current_turn.reset(token)
    assert result.source == "rules_budget" and not provider.calls
    assert turn.steps_used == turn.semantic_calls_used == 0
