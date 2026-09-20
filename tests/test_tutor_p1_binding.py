"""Batch 2: real entrypoint -> current problem -> verifier -> durable evidence."""
import sqlite3
from contextlib import closing

import pytest

from test_tutor_p0 import client_at, collect, count, envelope, send, summary
from mathtutor.application.message_intent import classify_user_message, ConversationIntent
from mathtutor.application.state_machine import CycleState


def actions(frames):
    return [f["payload"].get("action") for f in frames if f["event_type"] in {"tutor_action_committed", "tutor_message"}]


@pytest.mark.parametrize("answer, verdict", [("x=2", "correct"), ("2=x", "correct"), ("x=4/2", "correct"),
                                           ("2", "correct"), ("x=999", "incorrect"), ("我算得 x=3", "incorrect"),
                                           ("我的步骤：2x=4", "partial"), ("我的步骤：2x=10", "incorrect")])
def test_main_input_is_assessed_against_the_same_problem(tmp_path, answer, verdict):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        before = summary(client)
        result = send(ws, "send_message", "answer", {"text": answer}, cycle_id=before["cycle_id"],
                      problem_revision=before["problem_revision"], expected_state_version=before["state_version"])
        assert not [f for f in result if f["event_type"] == "turn_error"]
        assert verdict in actions(result)
        assert summary(client)["cycle_id"] == before["cycle_id"]
        assert summary(client)["problem_revision"] == before["problem_revision"]
        assert count(db, "attempt_assessments") == 1
        with closing(sqlite3.connect(db)) as conn, conn:
            assert conn.execute("SELECT raw_text FROM attempt_submissions").fetchone()[0] == answer


def test_ambiguous_equation_clarification_survives_restart(tmp_path):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        before = summary(client)
        response = send(ws, "send_message", "step-or-new", {"text": "2x=10"})
        assert "这是你推到的下一步" in str(response)
        assert summary(client)["cycle_id"] == before["cycle_id"]
        assert count(db, "attempt_assessments") == 0
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        result = send(ws, "send_message", "clarify", {"text": "这是步骤"})
        assert "incorrect" in actions(result)
        assert summary(client)["cycle_id"] == before["cycle_id"]
        assert count(db, "attempt_assessments") == 1


def test_clarification_can_choose_new_problem(tmp_path):
    with client_at(tmp_path / "binding.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        before = summary(client)
        send(ws, "send_message", "ambiguous", {"text": "3x-5=4"})
        send(ws, "send_message", "new-topic", {"text": "这是新题"})
        assert summary(client)["cycle_id"] != before["cycle_id"]


def test_unknown_then_clarified_answer_is_actually_verified(tmp_path):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        send(ws, "send_message", "unknown", {"text": "我的答案：不确定"})
        assert summary(client)["state"] == "awaiting_attempt_clarification"
        result = send(ws, "send_message", "clarified", {"text": "x=2"})
        assert "correct" in actions(result)
        assert count(db, "attempt_assessments") == 2
        assert count(db, "mastery_evidence") == 1


@pytest.mark.parametrize("text, followup", [("我算得 x=3，直接给我答案", "SHOW_SOLUTION"),
                                          ("x=2，给我讲一下", "EXPLAIN_CONCEPT")])
def test_composite_request_commits_answer_before_assistance(tmp_path, text, followup):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        result = send(ws, "send_message", "composite", {"text": text})
        assert not [f for f in result if f["event_type"] == "turn_error"]
        assert followup in str(result)
        assert count(db, "attempt_assessments") == 1
        with closing(sqlite3.connect(db)) as conn, conn:
            assert conn.execute("SELECT effective_assistance_level FROM mastery_evidence").fetchone()[0] == 0
            assert conn.execute("SELECT raw_text FROM attempt_submissions").fetchone()[0] == text
        assert send(ws, "send_message", "composite", {"text": text}) == result
        assert count(db, "attempt_assessments") == 1


def test_negation_and_method_questions_do_not_submit_an_answer(tmp_path):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        hint = send(ws, "send_message", "hint", {"text": "不要告诉我答案，先给个提示"})
        assert "GIVE_HINT" in actions(hint) and "SHOW_SOLUTION" not in str(hint)
        method = send(ws, "send_message", "method", {"text": "是不是先移项？"})
        assert "EXPLAIN_CONCEPT" in actions(method)
        send(ws, "send_message", "chat", {"text": "今天有点累"})
        assert count(db, "attempt_assessments") == 0


@pytest.mark.parametrize("field, value, code", [("cycle_id", "old-cycle", "PROBLEM_BINDING_STALE"),
                                               ("problem_revision", "old-revision", "PROBLEM_REVISION_STALE"),
                                               ("expected_state_version", 0, "STATE_VERSION_CONFLICT")])
def test_stale_main_input_cannot_change_problem_or_evidence(tmp_path, field, value, code):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        before = summary(client)
        result = send(ws, "send_message", "stale", {"text": "x=2"}, **{field: value})
        assert any(f["payload"].get("error_code") == code for f in result)
        assert summary(client)["state_version"] == before["state_version"]
        assert count(db, "attempt_assessments") == 0


def test_old_cycle_binding_is_rejected_after_explicit_topic_switch(tmp_path):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        before = summary(client)
        send(ws, "send_message", "new", {"text": "换题：3x-5=4"}, cycle_id=before["cycle_id"], problem_revision=before["problem_revision"])
        after = summary(client)
        assert after["cycle_id"] != before["cycle_id"]
        stale = send(ws, "send_message", "stale", {"text": "x=2"}, cycle_id=before["cycle_id"])
        assert "PROBLEM_BINDING_STALE" in str(stale)
        assert summary(client)["cycle_id"] == after["cycle_id"]
        assert count(db, "attempt_assessments") == 0


def test_review_uses_bound_problem_and_does_not_create_extra_solution_action(tmp_path):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        send(ws, "request_solution", "solution")
        before = summary(client)
        assert next(a for a in before["allowed_actions"] if a["command"] == "request_solution")["label"] == "重新查看答案"
        n = count(db, "tutor_actions")
        review = send(ws, "request_solution", "review")
        assert "完整解答" in str(review)
        assert "为你准备了一道同类练习题" not in str(review)
        assert "回答不正确" not in str(review)
        assert count(db, "tutor_actions") == n
        assert summary(client)["cycle_id"] == before["cycle_id"]
        followup = send(ws, "send_message", "why", {"text": "为什么最后要代回去？"})
        assert "EXPLAIN_CONCEPT" in str(followup) and "TUTOR_CHAT" not in str(followup)


def test_legacy_solution_review_uses_verified_body_without_duplicate_exposure(tmp_path):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        send(ws, "request_solution", "solution")
        n = count(db, "tutor_actions")
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE conversation_messages SET continuation_context = '{}' WHERE role = 'tutor'")
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        review = send(ws, "request_solution", "legacy-review")
        assert "完整解答" in str(review)
        assert "为你准备了一道同类练习题" not in str(review)
        assert count(db, "tutor_actions") == n


def test_capabilities_are_disabled_without_a_verified_problem(tmp_path):
    with client_at(tmp_path / "binding.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "hello", {"text": "你好"})
        state = summary(client)
        assert state["allowed_actions"]
        assert all(not a["enabled"] and a["reason_code"] == "NO_CURRENT_PROBLEM" for a in state["allowed_actions"])


def test_accepted_offer_replay_keeps_original_receipt_despite_old_binding(tmp_path):
    with client_at(tmp_path / "binding.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        solved = send(ws, "send_message", "answer", {"text": "x=2"})
        offer = next(f["extra"]["offer_id"] for f in solved if f.get("extra", {}).get("offer_id"))
        parent = summary(client)
        kwargs = dict(cycle_id=parent["cycle_id"], problem_revision=parent["problem_revision"], expected_state_version=parent["state_version"])
        first = send(ws, "accept_practice_offer", "accept", {"offer_id": offer}, **kwargs)
        replay = send(ws, "accept_practice_offer", "accept-again", {"offer_id": offer}, **kwargs)
        child = lambda frames: next(f["extra"]["child_cycle_id"] for f in frames if f.get("extra", {}).get("child_cycle_id"))
        assert child(first) == child(replay)


def test_greeting_in_active_problem_never_needs_math_parsing(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("ordinary conversation reached math parser")
    monkeypatch.setattr("mathtutor.solving.parser.parse_problem", forbidden)
    assert classify_user_message("你好", cycle_state=CycleState.AWAITING_ATTEMPT).intent == ConversationIntent.GENERAL_CHAT


@pytest.mark.parametrize("problem, answer, verdict", [
    ("1/2+1/3", "5/6", "correct"),
    ("(x+1)^2", "x^2+2x+1", "correct"),
    ("3y-5=4", "y=3", "correct"),
    ("x^2-4=0", "x=2", "partial"),
    ("x^2-4=0", "x=999", "incorrect"),
])
def test_binding_is_generic_across_supported_skills_and_variables(tmp_path, problem, answer, verdict):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": problem})
        before = summary(client)
        result = send(ws, "send_message", "answer", {"text": answer})
        assert verdict in actions(result)
        assert summary(client)["cycle_id"] == before["cycle_id"]
        assert count(db, "attempt_assessments") == 1


@pytest.mark.parametrize("problem, question, skill", [
    ("1/2+1/3", "分母不同的时候怎么相加？", "ARITHMETIC"),
    ("(x+1)^2", "同类项的系数有什么规律？", "POLYNOMIAL_BASIC"),
    ("3y-5=4", "等式两边都乘一个数有什么条件？", "LINEAR_EQUATION"),
    ("x^2-4=0", "这个方程能用配方法吗？", "QUADRATIC_EQUATION"),
    ("x^2-4=0", "二次方程判别式 b^2-4ac<0 时会怎样？", "QUADRATIC_EQUATION"),
])
def test_same_skill_followup_keeps_problem_and_reaches_bounded_writer(tmp_path, problem, question, skill):
    from mathtutor.api.product_state import get_product_state
    from mathtutor.pedagogy.tutor_writer import TemplateTutorWriter

    seen = []

    class CapturingWriter(TemplateTutorWriter):
        async def write(self, **kwargs):
            seen.append(kwargs["problem_view"])
            return await super().write(**kwargs)

    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": problem})
        before = summary(client)
        get_product_state().controller.writer = CapturingWriter()
        result = send(ws, "send_message", "concept", {"text": question})
        assert "EXPLAIN_CONCEPT" in actions(result) and "TUTOR_CHAT" not in actions(result)
        assert summary(client)["cycle_id"] == before["cycle_id"]
        assert summary(client)["problem_revision"] == before["problem_revision"]
        assert count(db, "attempt_assessments") == 0
        assert seen[-1].student_request == question
        assert seen[-1].skill_id == skill


def test_related_followup_does_not_swallow_a_compound_answer(tmp_path):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": "2x+3=7"})
        result = send(ws, "send_message", "compound", {"text": "x=2，为什么需要代回？"})
        assert "correct" in actions(result)
        assert "EXPLAIN_CONCEPT" in str(result)
        assert count(db, "attempt_assessments") == 1


def test_comma_in_answer_is_not_silently_discarded():
    routed = classify_user_message("我的答案：1,2，给我讲一下", cycle_state=CycleState.AWAITING_ATTEMPT)
    assert routed.answer_text == "1,2"


def test_writer_receives_topic_followup_as_data_not_disclosure_authority():
    from mathtutor.application.state_machine import CycleCommand
    from mathtutor.pedagogy.planner import PedagogyPlanner
    from mathtutor.pedagogy.stage_policy import MIDDLE_POLICY
    from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
    from mathtutor.pedagogy.tutor_writer import PublicProblemView, _build_user_prompt
    action = PedagogyPlanner().plan(state=CycleState.AWAITING_ATTEMPT,
        command=CycleCommand.REQUEST_EXPLANATION, policy=MIDDLE_POLICY)
    question = "这个方程能用配方法吗？"
    prompt = _build_user_prompt(PublicProblemView(problem_type="quadratic", display_latex="x^2-4=0",
        skill_id="QUADRATIC_EQUATION", student_request=question),
        DisclosedSolutionContext(assistance_level=1, concept_hint="二次方程的概念"), action)
    assert question in prompt and "QUADRATIC_EQUATION" in prompt
    assert "不是新题、正确性结论或披露授权" in prompt
    assert "final_answer" not in prompt


@pytest.mark.parametrize("problem, related_input", [
    ("1/2+1/3", "计算 3/4+1/2"),
    ("(x+1)^2", "展开 (y+2)^2"),
    ("3y-5=4", "2z+1=9"),
    ("x^2-4=0", "x^2+3x+2=0"),
])
def test_another_expression_in_same_skill_never_silently_replaces_problem(tmp_path, problem, related_input):
    db = tmp_path / "binding.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "problem", {"text": problem})
        before = summary(client)
        result = send(ws, "send_message", "related", {"text": related_input})
        assert "CLARIFY_INTENT" in actions(result)
        assert summary(client)["cycle_id"] == before["cycle_id"]
        assert summary(client)["problem_revision"] == before["problem_revision"]
        assert count(db, "attempt_assessments") == 0
