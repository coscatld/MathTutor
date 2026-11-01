"""Real parser/verifier and durable WS tests for work beyond valid restatement."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import verify_attempt
from mathtutor.pedagogy.planner import CycleAssistance
from mathtutor.pedagogy.teaching_plan import (
    initial_context, apply_assessment, choose_plan, assessment_feedback,
)
from mathtutor.pedagogy.student_evidence_view import progress_view, assessment_view
from test_teaching_recovery_v2 import context_row
from test_teaching_v2 import terminal
from test_tutor_p0 import client_at, send, summary, count


def problem(text="2x+3=7"):
    result = asyncio.run(MathTutorApplicationService().submit_problem(text))
    return result, initial_context(result.problem, result.candidate)


def assess(result, context, text):
    attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(),
        cycle_id=uuid4(), raw_text=text, attempt_index=1)
    assessment = verify_attempt(attempt, result.problem, result.candidate)
    return apply_assessment(context, assessment, text, CycleAssistance())


@pytest.mark.parametrize("task,text", [
    ("2x+3=7", "2x+3=7"),
    ("2x+3=7", "2x+3+0=7"),
    ("2x+3=7", "7=3+2x"),
    ("x^2-5x+6=0", "x^2-5x+6+0=0"),
    ("x+y=4;x-y=2", "x+y+0=4"),
])
def test_canonical_restatements_preserve_math_and_both_counts(task, text):
    result, context = problem(task)
    context.update(stuck_count=2, help_without_progress=2)
    updated, record = assess(result, context, text)
    assert record["math_validity"] == "valid"
    assert record["progress_kind"] == "restatement"
    assert record["semantic_evidence_keys"]
    assert updated["stuck_count"] == updated["help_without_progress"] == 2
    assert updated["subgoals"] == context["subgoals"]
    assert updated["progress"][-1]["progress_kind"] == "restatement"
    assert "有效的重述" in assessment_feedback(record)
    assert not context["progress"]  # pure transformation


def test_new_alternative_equation_need_not_complete_a_named_goal():
    result, context = problem()
    context.update(stuck_count=2, help_without_progress=2)
    updated, record = assess(result, context, "2x+1=5")
    assert record["math_validity"] == "valid"
    assert record["progress_kind"] == "new_verified_step"
    assert updated["stuck_count"] == updated["help_without_progress"] == 0
    assert updated["subgoals"][0]["status"] == "pending"
    assert updated["current_subgoal_index"] == 0


@pytest.mark.parametrize("repeated", ["2x=4", "4=2x", "2x+0=4"])
def test_repeated_verified_intermediate_does_not_clear_new_help(repeated):
    result, context = problem()
    context, first = assess(result, context, "2x=4")
    assert first["progress_kind"] == "new_verified_step"
    context.update(stuck_count=2, help_without_progress=2)
    updated, record = assess(result, context, repeated)
    assert record["progress_kind"] == "restatement"
    assert record["semantic_evidence_keys"] == first["semantic_evidence_keys"]
    assert updated["stuck_count"] == updated["help_without_progress"] == 2
    assert len(updated["progress"]) == 2


@pytest.mark.parametrize("task,first,repeated,next_answer", [
    ("x+y=4;x-y=2", "x=3", "3=x", "y=1"),
    ("x^2-5x+6=0", "x=2", "2", "x=3"),
])
def test_only_new_verified_requirement_resets_counts(task, first, repeated, next_answer):
    result, context = problem(task)
    context.update(stuck_count=2, help_without_progress=2)
    context, record = assess(result, context, first)
    assert record["progress_kind"] == "new_requirement"
    assert context["stuck_count"] == context["help_without_progress"] == 0
    context.update(stuck_count=2, help_without_progress=2)
    context, record = assess(result, context, repeated)
    assert record["progress_kind"] == "restatement"
    assert context["stuck_count"] == context["help_without_progress"] == 2
    context, record = assess(result, context, next_answer)
    assert record["progress_kind"] == "new_requirement"
    assert context["stuck_count"] == context["help_without_progress"] == 0


def test_first_complete_answer_resets_counts_and_completes_task():
    result, context = problem()
    context.update(stuck_count=2, help_without_progress=2)
    context, record = assess(result, context, "x=2")
    assert record["progress_kind"] == "new_requirement"
    assert context["lifecycle"] == "completed"
    assert all(goal["status"] == "verified" for goal in context["subgoals"])
    assert context["stuck_count"] == context["help_without_progress"] == 0


@pytest.mark.parametrize("text,validity", [("x=3", "invalid"), ("暂时还没有步骤", "unknown")])
def test_rejected_and_uncheckable_work_never_reset_counts(text, validity):
    result, context = problem()
    context.update(stuck_count=2, help_without_progress=2)
    context, record = assess(result, context, text)
    assert record["math_validity"] == validity
    assert record["progress_kind"] == "unknown" and not record["semantic_evidence_keys"]
    assert context["stuck_count"] == context["help_without_progress"] == 2
    assert not context["progress"]


@pytest.mark.parametrize("legacy_text,expected", [("2x=4", "restatement"), ("旧格式无法恢复的步骤", "unknown")])
def test_old_records_remain_readable_without_fabricating_novelty(legacy_text, expected):
    result, context = problem()
    context, _ = assess(result, context, "2x=4")
    old = context["progress"][0]
    for key in ("progress_kind", "progress_policy_version", "semantic_evidence_keys"):
        old.pop(key)
    old["verified_claims"][0].pop("equation")
    old["text"] = legacy_text
    before = deepcopy(old)
    context.update(stuck_count=2, help_without_progress=2)
    context, record = assess(result, context, "2x+0=4")
    assert record["progress_kind"] == expected
    assert context["stuck_count"] == context["help_without_progress"] == 2
    assert context["progress"][0] == before
    if expected == "unknown":
        assert "这一步新增了什么" in assessment_feedback(record)


def test_explicit_understanding_only_resets_stuck_not_help_or_goals():
    _, context = problem()
    context.update(stuck_count=2, help_without_progress=2)
    action = SimpleNamespace(action="GIVE_HINT", effective_assistance_level=1)
    updated, _ = choose_plan(context, action, "我明白了")
    assert updated["stuck_count"] == 0
    assert updated["help_without_progress"] == 2
    assert updated["subgoals"] == context["subgoals"]


def test_writer_sees_progress_kind_without_reference_answer_or_internal_keys():
    result, context = problem()
    context, record = assess(result, context, "2x+3+0=7")
    projected = progress_view(context["progress"])[0]
    assert projected["progress_kind"] == "restatement"
    assert projected["verified_claims"] == [{"claim": "equivalent_equation"}]
    assert "semantic_evidence_keys" not in projected
    view = assessment_view([record])[0]
    assert view["progress_kind"] == "restatement"
    assert "semantic_evidence_keys" not in view
    assert "equation" not in view["verified_steps"][0]


def test_two_helps_restatement_restart_and_next_help_keep_support(tmp_path):
    db = tmp_path / "progress.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        cycle = summary(client)["cycle_id"]
        send(ws, "send_message", "help1", {"text": "我不会，给个提示"})
        send(ws, "send_message", "help2", {"text": "还是不懂，再给个提示"})
        before = context_row(db, cycle)
        assert before["stuck_count"] >= 2 and before["help_without_progress"] == 2
        frames = send(ws, "submit_attempt", "restatement", {"answer": "2x+3+0=7"})
        saved = context_row(db, cycle)
        assert saved["stuck_count"] == before["stuck_count"]
        assert saved["help_without_progress"] == before["help_without_progress"]
        assert saved["assessments"][-1]["progress_kind"] == "restatement"
        assert saved["assessments"][-1]["math_validity"] == "valid"
        assert saved["subgoals"][0]["status"] == "pending"
        assert "有效的重述" in terminal(frames)["payload"]["final_text"]
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        assert context_row(db, cycle) == saved
        assert send(ws, "submit_attempt", "restatement", {"answer": "2x+3+0=7"}) == frames
        assert context_row(db, cycle) == saved and count(db, "attempts") == 1
        next_frames = send(ws, "request_hint", "help3")
        plan = summary(client)["teaching_plan"]
        assert plan["strategy"] in {"smaller_step", "offer_alternative"}
        assert "REPEATED_EXPLICIT_STUCK" in plan["reason_codes"]
        assert "request_solution" in plan["exit_options"]
        assert not plan["allow_target_answer"] and plan["max_assistance_level"] < 5
        text = terminal(next_frames)["payload"]["final_text"]
        assert "x=2" not in text.replace(" ", "")


def test_repeated_intermediate_after_restart_is_not_new_progress(tmp_path):
    db = tmp_path / "repeat.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        cycle = summary(client)["cycle_id"]
        send(ws, "submit_attempt", "step", {"answer": "2x=4"})
        first = context_row(db, cycle)["progress"][-1]
        assert first["progress_kind"] == "new_verified_step"
        send(ws, "request_hint", "help1")
        send(ws, "request_hint", "help2")
        before = context_row(db, cycle)
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_attempt", "repeat", {"answer": "4=2x+0"})
        after = context_row(db, cycle)
        assert after["progress"][-1]["progress_kind"] == "restatement"
        assert after["progress"][-1]["semantic_evidence_keys"] == first["semantic_evidence_keys"]
        assert after["help_without_progress"] == before["help_without_progress"] > 0
        send(ws, "submit_attempt", "done", {"answer": "x=2"})
        done = context_row(db, cycle)
        assert done["lifecycle"] == "completed" and summary(client)["state"] == "solved"
        assert done["help_without_progress"] == done["stuck_count"] == 0


def test_composite_attempt_and_help_uses_verified_equation_not_raw_prose(tmp_path):
    db = tmp_path / "composite.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        cycle = summary(client)["cycle_id"]
        send(ws, "send_message", "help1", {"text": "我不会，给个提示"})
        send(ws, "send_message", "help2", {"text": "还是不懂，再给个提示"})
        before = context_row(db, cycle)
        frames = send(ws, "send_message", "repeat-and-help", {"text": "我的步骤：2x+3+0=7，给个提示"})
        saved = context_row(db, cycle)
        record = saved["assessments"][-1]
        assert record["math_validity"] == "valid" and record["progress_kind"] == "restatement"
        assert "给个提示" in record["raw_text"]
        assert saved["stuck_count"] == before["stuck_count"] >= 2
        assert saved["help_without_progress"] >= before["help_without_progress"] == 2
        assert "REPEATED_EXPLICIT_STUCK" in saved["last_plan"]["reason_codes"]
        assert not saved["last_plan"]["allow_target_answer"]
        assert "x=2" not in terminal(frames)["payload"]["final_text"].replace(" ", "")
