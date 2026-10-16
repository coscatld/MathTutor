"""Advanced operations retain the original task through the real Tutor path."""
import json

import pytest

from mathtutor.application.constraint_layer import ConstraintStatus, evaluate_constraints
from mathtutor.application.message_intent import ConversationIntent, classify_user_message
from mathtutor.application.state_machine import CycleState
from test_math_tool_loop import answer, bind, tool_call
from test_tutor_p0 import client_at, count, send, summary


@pytest.mark.parametrize("text", [
    "How do I differentiate x^2?",
    "Differentiate x².",
    "Find the derivative of sin(x).",
    "Find the minimum of x^2+1.",
    "Find the extremum of x².",
    "Where are the stationary points of f(x)=x^3-x?",
    "如何对 x^2 求导？",
    "求 x^2+1 的最小值。",
    "求 x² 的最值。",
    "这个函数在什么条件下有极值？",
])
def test_advanced_operations_are_not_algebra_simplification_or_english_variable_ambiguity(text):
    for state in (None, CycleState.AWAITING_ATTEMPT):
        routed = classify_user_message(text, cycle_state=state)
        assert routed.intent == ConversationIntent.MATH_PROBLEM
    constraint = evaluate_constraints(text)
    assert constraint.status == ConstraintStatus.SOFT_FAIL
    assert constraint.reason == "unsupported_operation" and constraint.parse is None
    assert constraint.raw_text == text


@pytest.mark.parametrize("text", [
    "How do I differentiate frogs and toads?",
    "What are the limits of this app?",
    "What integral role does language play in learning?",
    "How many files are allowed at maximum?",
])
def test_ordinary_uses_of_operation_words_do_not_force_a_math_problem(text):
    assert classify_user_message(text).intent == ConversationIntent.GENERAL_CHAT


@pytest.mark.parametrize("text", ["How do I differentiate x^2?", "Differentiate x²."])
def test_default_middle_school_user_gets_the_original_derivative_task_and_local_tool(tmp_path, text):
    requests = []
    replies = [tool_call("derivative(x^2,x)", "2*x"),
               answer("Apply the power rule: lower the exponent by one and multiply by the original exponent.")]
    with client_at(tmp_path / "derivative.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "differentiate", {"text": text})
        restored = summary(client)
        assert restored["problem_context"]["display_text"] == text
        assert restored["recovery_problem"] is None
        assert restored["messages"][0]["content"] == text
        assert count(tmp_path / "derivative.db", "attempt_assessments") == 0
    assert len(requests) == 2
    assert requests[0].get("tools") and not requests[0].get("stream")
    assert requests[0]["messages"][-1]["content"] == text
    receipt = json.loads(next(message for message in requests[1]["messages"] if message["role"] == "tool")["content"])
    assert receipt == {"status": "verified", "signals": ["exact_polynomial_derivative"]}
    terminal = next(frame["payload"] for frame in frames if frame["event_type"] == "assistant_complete")
    assert terminal["tool_calls_count"] == 1


def test_nonpolynomial_derivative_remains_unchecked_on_the_same_real_tool_path(tmp_path):
    requests = []
    replies = [tool_call("derivative(sin(x),x)", "cos(x)"), answer("The derivative of sine is cosine.")]
    with client_at(tmp_path / "trigonometric.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "differentiate", {"text": "Find the derivative of sin(x)."})
    receipt = json.loads(next(message for message in requests[1]["messages"] if message["role"] == "tool")["content"])
    assert receipt["status"] == "unchecked"
    terminal = next(frame["payload"] for frame in frames if frame["event_type"] == "assistant_complete")
    assert terminal["verification_notice"] == "本段讲解未经逐句数学核验。"
