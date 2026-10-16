"""Current request limits agree across chat, offline routing and interpretation.

These are newly authored interaction regressions, not benchmark question/answer
pairs. Scripted providers check the authority boundary without paid model calls.
"""
import json

import pytest

from mathtutor.application.message_intent import ConversationIntent, classify_user_message
from mathtutor.application.state_machine import CycleState
from mathtutor.application.teaching_intent import (
    current_request_text,
    explicit_solution_request,
    negates_solution,
    response_scope_instruction,
    rule_teaching_intent,
)
from test_tutor_language_intent import CONTEXT, interpreter_for, proposal


@pytest.mark.parametrize("text,command", [
    ("请解一下这道题", "request_solution"),
    ("请给我完整解答，并用一个例子说明这个方法", "request_solution"),
    ("Could you solve this equation?", "request_solution"),
    ("Please give a full solution, including an example of the method.", "request_solution"),
    ("只要一个提示", "request_hint"),
    ("Just give me one hint.", "request_hint"),
    ("Give me only a hint, not the full solution.", "request_hint"),
    ("Why can we cancel this factor?", "request_explanation"),
    ("I don't understand this step; can't you explain why it works?", "request_explanation"),
    ("不要给答案，只解释为什么能这么做", "request_explanation"),
    ("不要答案，用另一个例子讲", "request_example"),
])
def test_same_support_request_routes_consistently_in_both_languages(text, command):
    result = classify_user_message(text, cycle_state=CycleState.AWAITING_ATTEMPT)
    assert result.intent == ConversationIntent.TEACHING_REQUEST
    assert result.command == command


@pytest.mark.parametrize("text", [
    "只给一个提示。\n题目：求解这个方程。\n学生最新消息：请给我完整解答。",
    "Only give one hint.\nProblem: Solve this equation.\nStudent's latest message: Give me the full solution.",
    "请给我完整解答，但先别揭示最终结果。",
    "Please solve this problem, but don't finish it for me.",
    "I don't need the answer, don't give me the solution; just one hint.",
])
def test_no_answer_limit_applies_even_when_a_full_solution_request_is_present(text):
    assert negates_solution(text)
    assert not explicit_solution_request(text)
    assert "不要算出或揭示最终答案" in response_scope_instruction(text)


@pytest.mark.parametrize("text,expected", [
    (
        "Problem: Solve this problem.\nConversation:\nStudent: Give the full answer.\n"
        "Tutor: Try first.\nStudent's latest message: Why did you use that formula?",
        "Why did you use that formula?",
    ),
    (
        "请回应学生。\n对话记录：\n学生：告诉我答案。\n学生最新消息：这一步为什么成立？",
        "这一步为什么成立？",
    ),
])
def test_old_solution_requests_do_not_promote_a_current_why_question(text, expected):
    assert current_request_text(text).strip() == expected
    assert not explicit_solution_request(text)
    assert rule_teaching_intent(text, context=CONTEXT).intent == "explanation"
    result = classify_user_message(text, cycle_state=CycleState.AWAITING_ATTEMPT)
    assert result.command == "request_explanation"
    assert "先直接回答" in response_scope_instruction(text)


def test_full_solution_is_allowed_after_an_old_no_answer_request():
    text = ("Respond to the student.\nConversation:\nStudent: Don't give me the answer.\n"
            "Student's latest message: Please give me the complete solution now.")
    assert explicit_solution_request(text)
    assert not negates_solution(text)
    assert "完整推导及最终答案" in response_scope_instruction(text)


def test_quoted_requests_are_discussion_data_rather_than_disclosure_consent():
    text = 'What does "give me the complete solution" mean?'
    assert not explicit_solution_request(text)
    assert rule_teaching_intent(text, context=CONTEXT).intent == "explanation"


@pytest.mark.parametrize("text", [
    "I can solve this problem, but why is the method valid?",
    "我想知道答案为什么是负数。",
])
def test_describing_ones_own_solving_or_asking_for_a_reason_is_not_full_solution_consent(text):
    assert not explicit_solution_request(text)
    assert rule_teaching_intent(text, context=CONTEXT).intent == "explanation"


def test_explaining_the_method_first_does_not_cancel_a_requested_complete_answer():
    text = "先讲思路，然后请给我完整解答。"
    assert explicit_solution_request(text)
    assert rule_teaching_intent(text, context=CONTEXT).intent == "solution"


@pytest.mark.parametrize("text", [
    "Give me the solution, but do not solve it using calculus.",
    "Please give me the full solution, without using derivatives to solve the problem.",
    "请完整解答，但不要用导数解。",
    "请给我完整解答，不要使用导数给出答案。",
    "Solve the equation without rounding the answer.",
    "Give me the full solution, but do not round the final answer.",
])
def test_banning_a_method_still_allows_the_requested_solution(text):
    assert not negates_solution(text)
    assert explicit_solution_request(text)
    assert rule_teaching_intent(text, context=CONTEXT).intent == "solution"


@pytest.mark.parametrize("text", [
    "Give me the solution, but do not give me the final answer yet.",
    "Don't solve it for me, just explain how to start.",
    "请完整解答，但不要告诉我答案。",
    "Explain the next step without giving the answer.",
])
def test_method_exception_does_not_erase_a_real_disclosure_limit(text):
    assert negates_solution(text)
    assert not explicit_solution_request(text)


@pytest.mark.asyncio
async def test_semantic_solution_proposal_cannot_bypass_an_outer_hint_limit():
    text = ("Only provide a hint.\nProblem: Solve the equation.\n"
            "Student's latest message: Give me the complete solution.")
    runtime, provider, _ = interpreter_for(proposal(text, intent="solution", confusion="none"))
    result = await runtime.interpret(text, context=CONTEXT)
    assert result.source == "rules" and result.intent == "hint"
    assert result.fallback_reason == "negated_solution"
    payload = json.loads(provider.calls[0][0][1]["content"])
    assert payload["current_student_request"].strip() == "Give me the complete solution."


@pytest.mark.asyncio
async def test_semantic_default_style_cannot_replace_an_explicit_requested_solution():
    text = "Please give me the complete solution."
    runtime, _, _ = interpreter_for(proposal(text, intent="hint", confusion="none"))
    result = await runtime.interpret(text, context=CONTEXT)
    assert result.intent == "solution" and result.source == "rules"
    assert result.fallback_reason == "explicit_solution_request_preserved"
