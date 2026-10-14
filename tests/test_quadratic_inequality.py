"""Quadratic inequalities with rational roots: exact solution sets end to end."""
import asyncio
import json

import pytest

from mathtutor.application.math_verification import assess_answer, verified_problem
from mathtutor.application.message_intent import ConversationIntent, classify_user_message
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.solving.parser import parse_problem
from test_tutor_p0 import client_at, send

BACKEND = InProcessVerificationBackend()


def solved(text):
    return asyncio.run(verified_problem(BACKEND, text))


def verdict(problem_text, answer):
    problem, candidate = solved(problem_text)
    result = asyncio.run(assess_answer(BACKEND, problem, candidate, answer))
    return result.correctness.value, result.signals


@pytest.mark.parametrize("text, answer", [
    ("x^2-5x+6>0", "x < 2 或 x > 3"), ("x^2-5x+6<=0", "2 \\le x \\le 3"),
    ("x^2-4x+4<=0", "x = 2"), ("x^2-4x+4>0", "x \\ne 2"), ("x^2+1<0", "无解"),
    ("x^2+1>0", "x 为任意实数"), ("-x^2+4>=0", "-2 \\le x \\le 2"), ("2x^2-x-1<0", "-\\frac{1}{2} < x < 1"),
])
def test_solver_output_is_verified_independently(text, answer):
    problem, candidate = solved(text)
    assert problem.problem_type == "quadratic_inequality"
    assert candidate.final_answer["latex"] == answer


def test_irrational_boundaries_are_rejected_not_approximated():
    outcome = parse_problem("x^2-2>0")
    assert outcome.kind == "unsupported"


@pytest.mark.parametrize("answer, expected", [
    ("x<2或x>3", ("correct", ())), ("x<2, x>3", ("correct", ())), ("3<x或x<2", ("correct", ())),
    ("x≤2或x≥3", ("incorrect", ("wrong_value",))), ("2<x<3", ("incorrect", ("sign_flip",))),
    ("x>3", ("incorrect", ("missing_root",))), ("全体实数", ("incorrect", ("wrong_value",))),
])
def test_student_sets_are_compared_exactly_with_specific_diagnoses(answer, expected):
    assert verdict("x^2-5x+6>0", answer) == expected


def test_touching_and_all_but_one_point_sets():
    assert verdict("x^2-4x+4<=0", "x=2")[0] == "correct"
    assert verdict("x^2-4x+4>0", "x≠2")[0] == "correct"
    assert verdict("x^2-4x+4>0", "x<2或x>2")[0] == "correct"


def test_free_text_solution_sets_route_as_answers_but_new_problems_do_not():
    for text in ("x<2或x>3", "2<x<3", "x≠2", "x>2"):
        assert classify_user_message(text, cycle_state="awaiting_attempt", variable="x").intent == ConversationIntent.ATTEMPT
    assert classify_user_message("2x+1>5", cycle_state="awaiting_attempt", variable="x").intent != ConversationIntent.ATTEMPT


def test_tutoring_flow_gives_specific_feedback_and_a_same_variable_example(tmp_path):
    with client_at(tmp_path / "qi.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "p", {"text": "x^2-5x+6>0"})
        hint = json.dumps(send(ws, "request_hint", "h"), ensure_ascii=False)
        assert "。。" not in hint and "抛物线开口方向" in hint
        wrong = json.dumps(send(ws, "send_message", "w", {"text": "2<x<3"}), ensure_ascii=False)
        assert "区间方向和开口方向" in wrong and "带符号的运算" not in wrong
        example = json.dumps(send(ws, "request_example", "e"), ensure_ascii=False)
        assert "y = 3" in example and "x = 3" not in example
        right = json.dumps(send(ws, "send_message", "r", {"text": "x<2或x>3"}), ensure_ascii=False)
        assert "满足这道题的完整要求" in right
