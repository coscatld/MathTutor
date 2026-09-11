"""V2 public learning paths through real owner-scoped SQLite and WebSocket."""
import json
import sqlite3
import pytest

from test_tutor_p0 import client_at, send, summary, count


def terminal(frames):
    return next(f for f in reversed(frames) if f["event_type"] in {"assistant_complete", "assistant_error", "assistant_partial"})


def event_rows(db):
    with sqlite3.connect(db) as conn:
        return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM learning_events ORDER BY event_seq")]


def test_independent_completion_invitation_is_separate_and_restart_safe(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        first = summary(client)
        send(ws, "send_message", "a", {"text": "x=2"})
        done = summary(client)
        assert done["state"] == "solved"
        assert done["cycle_id"] == first["cycle_id"]
        assert done["active_offer"]["purpose"] == "A1"
        assert done["problem_context"]["lifecycle"] == "completed"
        send(ws, "decline_practice_offer", "no", {"offer_id": done["active_offer"]["offer_id"]})
        assert summary(client)["state"] == "solved"
        assert summary(client)["active_offer"] is None
    with client_at(db) as client:
        restored = summary(client)
        assert restored["problem_context"] == done["problem_context"]
        assert restored["active_offer"] is None
    attempts = [e for e in event_rows(db) if e["event_type"] == "attempt_assessed"]
    assert len(attempts) == 1 and attempts[0]["evidence_kind"] == "independent"


def test_practice_without_completion_and_return_to_original(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        send(ws, "request_practice", "invite")
        offered = summary(client)
        assert offered["state"] == "awaiting_attempt"
        assert offered["active_offer"]["purpose"] == "D"
        send(ws, "accept_practice_offer", "yes", {"offer_id": offered["active_offer"]["offer_id"]})
        child = summary(client)
        assert child["cycle_id"] != original["cycle_id"]
        assert "resume_problem" in child["allowed_next_inputs"]
        send(ws, "resume_problem", "return")
        resumed = summary(client)
        assert resumed["cycle_id"] == original["cycle_id"]
        assert resumed["state"] == "awaiting_attempt"


def test_solution_delivery_is_not_reflection_or_mastery(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        shown = terminal(send(ws, "request_solution", "solution"))
        assert shown["delivery_id"]
        ws.send_json({"type": "delivery_presented", "delivery_id": shown["delivery_id"]})
        state = summary(client)
        assert state["state"] == "solution_shown"
        assert state["active_offer"]["purpose"] == "B"
        assert count(db, "attempts") == 0
        assert not any(e["event_type"] == "attempt_assessed" for e in event_rows(db))


def test_repeated_stuck_changes_strategy_without_fabricated_praise(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        send(ws, "send_message", "h1", {"text": "我不会，给个提示"})
        first = summary(client)["teaching_plan"]
        send(ws, "send_message", "h2", {"text": "还是没懂，再给个提示"})
        second = summary(client)["teaching_plan"]
        assert first["strategy"] != second["strategy"]
        assert "REPEATED_EXPLICIT_STUCK" in second["reason_codes"]
        assert "end_problem" in second["exit_options"]
        assert "前几步是对的" not in json.dumps(summary(client), ensure_ascii=False)


def test_optional_diagnosis_skip_is_not_wrong_answer(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        send(ws, "start_diagnostic", "diagnose")
        diagnosing = summary(client)
        assert diagnosing["cycle_id"] != original["cycle_id"]
        assert diagnosing["diagnosis"]["status"] == "running"
        assert "skip_diagnostic" in diagnosing["allowed_next_inputs"]
        send(ws, "skip_diagnostic", "skip")
        restored = summary(client)
        assert restored["cycle_id"] == original["cycle_id"]
        assert restored["diagnosis"]["status"] == "skipped"
        assert count(db, "attempts") == 0


@pytest.mark.parametrize("first,second", [("x=3", "y=1"), ("y=1", "x=3")])
def test_system_accumulates_verified_coordinates_but_not_premature_completion(tmp_path, first, second):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "x+y=4\nx-y=2"})
        cycle = summary(client)["cycle_id"]
        send(ws, "send_message", "first", {"text": first})
        partial = summary(client)
        assert partial["cycle_id"] == cycle
        assert partial["state"] == "awaiting_retry"
        assert partial["active_offer"] is None
        send(ws, "send_message", "second", {"text": second})
        assert summary(client)["state"] == "solved"
        assert count(db, "attempts") == 2


def test_topic_followups_never_replace_bound_problem(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "x+y=4;x-y=2"})
        cycle = summary(client)["cycle_id"]
        for i, text in enumerate(["为什么可以消元？", "能用代入法吗？", "等式两边为什么要同时乘？", "先不计算，解释一下系数"]):
            send(ws, "send_message", f"q{i}", {"text": text})
            assert summary(client)["cycle_id"] == cycle
        assert count(db, "attempts") == 0


def test_quoted_confusion_does_not_request_math_explanation_or_add_help(tmp_path):
    from mathtutor.api.product_state import get_product_state
    class MustNotTeach:
        async def write(self, **kwargs):
            raise AssertionError("A quoted language discussion must not request math teaching")
    db = tmp_path / "quoted.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        cycle = summary(client)["cycle_id"]
        get_product_state().controller.writer = MustNotTeach()
        response = terminal(send(ws, "send_message", "quote", {"text": "“我不懂”这句话是什么意思？"}))
        assert response["event_type"] == "assistant_complete"
        assert summary(client)["cycle_id"] == cycle
        assert count(db, "attempts") == count(db, "tutor_actions") == count(db, "teaching_deliveries") == 0


def test_final_disclosure_downgrade_is_consistent_across_action_delivery_and_evidence(tmp_path, monkeypatch):
    from mathtutor.pedagogy.output_guard import GuardedTutorUtterance
    import mathtutor.pedagogy.quality_guard as quality
    async def approved_downgrade(*args):
        return GuardedTutorUtterance(text="请先指出等式两边可以做什么相同运算？", action="GIVE_HINT", assistance_level=1,
            fallback_used=True, leak="simulated_material_unavailable")
    monkeypatch.setattr(quality, "enforce_teaching_quality", approved_downgrade)
    db = tmp_path / "downgrade.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        answer = terminal(send(ws, "request_solution", "solution"))
        current = summary(client)
        assert current["state"] == "awaiting_attempt" and current["active_offer"] is None
        assert current["teaching_plan"]["max_assistance_level"] == 1
        assert "x=2" not in answer["payload"]["final_text"]
        with sqlite3.connect(db) as conn:
            assert conn.execute("SELECT action,effective_assistance_level,solution_visibility FROM tutor_actions").fetchall() == [("GIVE_HINT", 1, "hint")]
        assert all(not e["target_answer_exposed"] for e in event_rows(db) if e["event_type"].startswith("help_"))


def test_explicit_no_answer_overrides_a_final_step_demonstration(tmp_path):
    db = tmp_path / "no-answer.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2+3"})
        frames = send(ws, "send_message", "hint", {"text": "我还是不懂，不要答案，给个提示"})
        current = summary(client)
        assert current["teaching_plan"]["max_assistance_level"] == 1
        assert "5" not in terminal(frames)["payload"]["final_text"]
        assert not any(e["target_answer_exposed"] for e in event_rows(db))


def test_teacher_error_analysis_is_verified_but_not_original_task_evidence(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        cycle = summary(client)["cycle_id"]
        send(ws, "send_message", "example", {"text": "给一个错误示例，让我找错"})
        shown = summary(client)
        assert shown["teaching_plan"]["strategy"] == "teacher_error_example"
        assert "教师故意写错" in shown["messages"][-1]["content"]
        send(ws, "send_message", "restatement", {"text": "5z+4=39"})
        with sqlite3.connect(db) as conn:
            saved = json.loads(conn.execute("SELECT payload FROM teaching_contexts WHERE cycle_id=?", (cycle,)).fetchone()[0])
        assert saved["teacher_error_example"]["awaiting_response"]
        send(ws, "send_message", "repair", {"text": "5z=35"})
        repaired = summary(client)
        assert repaired["cycle_id"] == cycle and repaired["state"] == "awaiting_attempt"
        assert repaired["active_offer"] is None
        assert count(db, "mastery_evidence") == 0
        assessments = [e for e in event_rows(db) if e["event_type"] == "attempt_assessed"]
        assert len(assessments) == 2 and all(e["task_purpose"] == "error_analysis" for e in assessments)
        assert assessments[0]["correctness"] == "unknown"
        assert assessments[0]["completion_scope"] == "error_analysis"


@pytest.mark.parametrize("answer", ["x=3，给个提示", "x=2，给个提示"])
def test_committed_assessment_writer_failure_resumes_expression_only_after_restart(tmp_path, answer):
    from mathtutor.api.product_state import get_product_state
    class BrokenWriter:
        async def write(self, **kwargs):
            raise RuntimeError("simulated expression failure after assessment")
    db = tmp_path / "resume.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        get_product_state().controller.writer = BrokenWriter()
        failed = terminal(send(ws, "send_message", "composite", {"text": answer}))
        assert failed["event_type"] == "assistant_partial"  # verified feedback is already approved
        assert count(db, "attempts") == 1
        failed_id = summary(client)["messages"][-1]["message_id"]
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        restored = terminal(send(ws, "send_message", "composite", {"text": answer}))
        assert restored["event_type"] == "assistant_complete"
        assert "仍看这道题" in restored["payload"]["final_text"]
        assert count(db, "attempts") == 1
        assert count(db, "tutor_actions") == 1
        assert summary(client)["messages"][-1]["message_id"] == failed_id
        send(ws, "send_message", "composite", {"text": answer})
        assert count(db, "attempts") == 1 and count(db, "tutor_actions") == 1


def test_verified_prerequisite_gap_enables_foundation_and_keeps_parent(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        assert "request_foundation" not in summary(client)["allowed_next_inputs"]
        send(ws, "send_message", "a", {"text": "我的步骤：2x=10"})
        original = summary(client)
        assert "request_foundation" in original["allowed_next_inputs"]
        send(ws, "request_foundation", "foundation")
        assert summary(client)["active_offer"]["purpose"] == "C"
        offer_id = summary(client)["active_offer"]["offer_id"]
        send(ws, "accept_practice_offer", "yes", {"offer_id": offer_id})
        send(ws, "resume_problem", "return")
        assert summary(client)["cycle_id"] == original["cycle_id"]
        assert summary(client)["state"] == "awaiting_retry"


def test_hint_provider_failure_does_not_strand_processing_state(tmp_path):
    from mathtutor.api.product_state import get_product_state
    class BrokenWriter:
        async def write(self, **kwargs):
            raise RuntimeError("simulated provider failure")
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        before = summary(client)
        get_product_state().controller.writer = BrokenWriter()
        send(ws, "request_hint", "broken")
        failed = summary(client)
        assert failed["state"] == before["state"] == "awaiting_attempt"
        assert "request_hint" in failed["allowed_next_inputs"]
        assert count(db, "teaching_deliveries") == 0
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "request_hint", "recovered")
        assert summary(client)["state"] == "awaiting_attempt"
        assert count(db, "teaching_deliveries") == 1


def test_seen_solution_then_repeat_same_problem_in_new_conversation_is_not_independent(tmp_path):
    db = tmp_path / "v2.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        send(ws, "request_solution", "solution")
        send(ws, "submit_problem", "new-p", {"text": "2x+3=7"}, session="other")
        send(ws, "send_message", "repeat", {"text": "x=2"}, session="other")
        rows = [e for e in event_rows(db) if e["event_type"] == "attempt_assessed"]
        assert rows[-1]["evidence_kind"] == "post_solution"
        assert summary(client, "other")["evidence_summary"]["independent"] == 0


def test_semantic_restatement_does_not_complete_named_subgoal():
    import asyncio
    from mathtutor.application.math_tutor_service import MathTutorApplicationService
    from mathtutor.learning.attempt_parser import parse_student_attempt
    from mathtutor.learning.attempt_verifier import verify_attempt
    from mathtutor.pedagogy.planner import CycleAssistance
    from mathtutor.pedagogy.teaching_plan import initial_context, apply_assessment
    from uuid import uuid4
    result = asyncio.run(MathTutorApplicationService().submit_problem("2x+3=7"))
    attempt = parse_student_attempt(attempt_submission_id=uuid4(), student_id=uuid4(), cycle_id=uuid4(), raw_text="2x+3+0=7", attempt_index=1)
    assessment = verify_attempt(attempt, result.problem, result.candidate)
    context, _ = apply_assessment(initial_context(result.problem, result.candidate), assessment, "2x+3+0=7", CycleAssistance())
    assert context["current_subgoal_index"] == 0
    assert context["subgoals"][0]["status"] == "pending"
    assert context["progress"]
