"""Teacher checks use real SQLite/WS verification and preserve the original task."""
import json
import sqlite3
from contextlib import closing

import pytest

from mathtutor.application.evidence_projection import teaching_evidence
from mathtutor.learning.knowledge_tracing.events import LearningEvent
from test_tutor_p0 import client_at, count, send, summary
from test_teaching_v2 import event_rows, terminal


def stored_context(db, cycle_id):
    with closing(sqlite3.connect(db)) as conn:
        return json.loads(conn.execute("SELECT payload FROM teaching_contexts WHERE cycle_id=?", (cycle_id,)).fetchone()[0])


@pytest.mark.parametrize("problem,answer", [
    ("6*3", "10"), ("3x+1", "5z+6"), ("2x+3=7", "z=5"),
    ("x^2-5x+6=0", "z=3;z=4"), ("x+y=4;x-y=2", "u=6;v=3"),
])
def test_understanding_checks_all_five_families_are_verified_and_do_not_complete_original(tmp_path, problem, answer):
    db = tmp_path / "check.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "original", {"text": problem})
        original = summary(client)
        response = terminal(send(ws, "send_message", "understood", {"text": "我懂了"}))
        check = summary(client)
        assert check["cycle_id"] != original["cycle_id"]
        assert check["problem_context"]["understanding_check"] is True
        assert "两步" in response["payload"]["final_text"]
        assert {"submit_attempt", "skip_diagnostic", "resume_problem"} <= set(check["allowed_next_inputs"])
        assert count(db, "attempts") == count(db, "mastery_evidence") == 0
        send(ws, "submit_attempt", "check-answer", {"answer": answer})
        returned = summary(client)
        assert returned["cycle_id"] == original["cycle_id"]
        assert returned["state"] == "awaiting_attempt"
        assert returned["problem_context"]["lifecycle"] == "active"
        assert returned["evidence_summary"]["independent"] == 0
        assert count(db, "mastery_evidence") == 0
    attempts = [e for e in event_rows(db) if e["event_type"] == "attempt_assessed"]
    assert len(attempts) == 1 and attempts[0]["correctness"] == "correct"
    assert attempts[0]["task_purpose"] == "diagnostic"
    assert stored_context(db, original["cycle_id"])["assessments"] == []


def test_partial_check_survives_restart_then_returns_original_and_request_replay_is_safe(tmp_path):
    db = tmp_path / "resume.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "original", {"text": "2x+3=7"})
        original = summary(client)
        send(ws, "send_message", "understood", {"text": "我懂了"})
        check_id = summary(client)["cycle_id"]
        send(ws, "submit_attempt", "partial", {"answer": "3z=15"})
        assert summary(client)["cycle_id"] == check_id
        assert summary(client)["problem_context"]["lifecycle"] == "active"
        assert summary(client)["problem_context"]["current_subgoal"]["id"] == "isolate"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        assert summary(client)["cycle_id"] == check_id
        assert stored_context(db, check_id)["progress"]
        send(ws, "submit_attempt", "complete", {"answer": "z=5"})
        assert summary(client)["cycle_id"] == original["cycle_id"]
        cycles = count(db, "tutoring_cycles")
        send(ws, "send_message", "understood", {"text": "我懂了"})
        assert count(db, "tutoring_cycles") == cycles
        assert count(db, "attempt_assessments") == 2
        assert count(db, "mastery_evidence") == 0


def test_wrong_check_stays_on_one_item_and_skip_preserves_original_diagnosis(tmp_path):
    db = tmp_path / "wrong.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "original", {"text": "2x+3=7"})
        original = summary(client)
        send(ws, "send_message", "understood", {"text": "我懂了"})
        check_id = summary(client)["cycle_id"]
        reply = terminal(send(ws, "submit_attempt", "wrong", {"answer": "z=-5"}))
        assert "符号" in reply["payload"]["final_text"]
        assert summary(client)["cycle_id"] == check_id
        send(ws, "send_message", "understood-again", {"text": "我懂了"})
        assert summary(client)["cycle_id"] == check_id
        assert count(db, "tutoring_cycles") == 2
        send(ws, "skip_diagnostic", "skip")
        assert summary(client)["cycle_id"] == original["cycle_id"]
        assert summary(client)["diagnosis"]["status"] == "not_started"
        assert stored_context(db, original["cycle_id"])["understanding_checks"][-1]["status"] == "skipped"
        assert count(db, "mastery_evidence") == count(db, "misconception_observations") == 0


@pytest.mark.parametrize("text", ["我不是不懂", "“我懂了”是什么意思？", "还是不懂"])
def test_unresolved_or_quoted_report_does_not_create_a_check(tmp_path, text):
    db = tmp_path / "report.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "original", {"text": "2x+3=7"})
        original = summary(client)["cycle_id"]
        send(ws, "send_message", "report", {"text": text})
        assert summary(client)["cycle_id"] == original
        assert count(db, "attempts") == 0


def test_verified_cross_item_error_changes_hint_and_actual_practice_structure(tmp_path):
    from mathtutor.solving.parser import parse_problem
    from mathtutor.solving import nodes as n
    db = tmp_path / "history.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "p1", {"text": "2x+3=7"})
        send(ws, "submit_attempt", "a1", {"answer": "2x=10"})
        send(ws, "send_message", "p2", {"text": "换题：3x+2=11"})
        send(ws, "submit_attempt", "a2", {"answer": "3x=13"})
        send(ws, "send_message", "p3", {"text": "换题：4x+1=9"})
        send(ws, "request_hint", "hint")
        plan = summary(client)["teaching_plan"]
        assert "REPEATED_VERIFIED_ERROR" in plan["reason_codes"]
        assert "移项或常数处理" in plan["student_guidance"]
        assert plan["max_assistance_level"] == 2
        response = terminal(send(ws, "request_practice", "practice"))
        assert "先练等式两边" in response["payload"]["final_text"]
        offer_id = summary(client)["active_offer"]["offer_id"]
        offer = next(row for row in client.get("/api/v2/math-tutor/offers").json() if row["offer_id"] == offer_id)
        assert offer["basis"]["reason_code"] == "verified_error_history"
        assert len(offer["evidence_ids"]) == 2
        send(ws, "accept_practice_offer", "start", {"offer_id": offer_id})
        statement = summary(client)["problem_context"]["display_text"]
        parsed = parse_problem(statement)
        assert parsed.kind == "parsed"
        assert n.variables(parsed.problem.ast.lhs) and n.variables(parsed.problem.ast.rhs)


def test_retries_assistance_diagnostics_and_invalidated_errors_cannot_invent_recurring_cause():
    def error(identity, **changes):
        return LearningEvent(event_id=identity, event_type="attempt_assessed", student_id="a", session_id="s",
            cycle_id=identity, problem_id=identity, problem_revision=identity, item_family_id="linear",
            skill_ids=("equality_preservation",), assessment_id=identity, attempt_id=identity,
            evidence_kind="independent", correctness="incorrect", misconception_codes=("wrong_operation",), **changes)
    rows = [error("valid"), error("retry", prior_task_attempt=True), error("check", task_purpose="diagnostic"),
            error("help", target_answer_exposed_before_attempt=True), error("old")]
    rows.append(LearningEvent(event_id="invalidation", event_type="evidence_invalidated", student_id="a", session_id="s",
        cycle_id="old", problem_id="old", problem_revision="old", item_family_id="linear", invalidates_event_id="old"))
    assert teaching_evidence(rows, ("equality_preservation",))["verified_error_counts"] == {"wrong_operation": 1}


@pytest.mark.asyncio
@pytest.mark.parametrize("focus", ["equality_preservation", "signed_operations"])
@pytest.mark.parametrize("difficulty", range(1, 6))
async def test_focused_practice_at_each_difficulty_passes_the_full_release_gate(focus, difficulty):
    from mathtutor.application.adaptive_practice import practice_context_from_assembled
    from mathtutor.application.llm_candidate_generator import TemplateCandidateExerciseGenerator
    from mathtutor.application.practice_release import ExerciseReleaseService
    from mathtutor.repositories.practice_repository import InMemoryPracticeRepository
    from test_adaptive_practice import _assembled
    context = practice_context_from_assembled(_assembled(), target_skill_ids=("LINEAR_EQUATION",), desired_difficulty=difficulty)
    context = context.model_copy(update={"foundation_focus": focus})
    candidates = await TemplateCandidateExerciseGenerator().generate(context)
    released = await ExerciseReleaseService(repository=InMemoryPracticeRepository()).release_candidate(candidates[0], source_type="TEMPLATE")
    assert released.problem.problem_type == "linear"
    assert released.release.status == "released"
    assert released.ref.problem_content_hash == released.problem.content_hash


@pytest.mark.parametrize("interruption", ["before_grounding", "after_verified_binding", "after_grounding"])
def test_interrupted_check_initialization_preserves_diagnostic_provenance_and_parent_after_restart(tmp_path, monkeypatch, interruption):
    from mathtutor.api.product_state import get_product_state
    db = tmp_path / "interrupted-check.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "original", {"text": "2x+3=7"})
        original = summary(client)["cycle_id"]
        controller = get_product_state().controller
        if interruption == "after_verified_binding":
            original_method = controller.sessions.store_verified
            async def interrupted(*args, **kwargs):
                await original_method(*args, **kwargs)
                raise RuntimeError("simulated process loss after verified binding")
            monkeypatch.setattr(controller.sessions, "store_verified", interrupted)
        else:
            original_method = controller._submit_problem
            async def interrupted(*args, **kwargs):
                if interruption == "after_grounding":
                    await original_method(*args, **kwargs)
                raise RuntimeError("simulated process loss around grounding")
            monkeypatch.setattr(controller, "_submit_problem", interrupted)
        result = terminal(send(ws, "send_message", "understood", {"text": "我懂了"}))
        assert result["event_type"] == "assistant_error"
        child = summary(client)
        assert child["cycle_id"] != original
        context = stored_context(db, child["cycle_id"])
        assert context["understanding_check"] and context["diagnostic_item"]
        assert context["resume_parent_cycle_id"] == original
        assert "resume_problem" in child["allowed_next_inputs"]
        assert count(db, "attempt_assessments") == 0
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        assert summary(client)["cycle_id"] == child["cycle_id"]
        if interruption == "before_grounding":
            assert "skip_diagnostic" in summary(client)["allowed_next_inputs"]
            assert "submit_attempt" not in summary(client)["allowed_next_inputs"]
            send(ws, "skip_diagnostic", "skip")
        else:
            send(ws, "submit_attempt", "check-answer", {"answer": "z=5"})
            attempts = [event for event in event_rows(db) if event["event_type"] == "attempt_assessed"]
            assert len(attempts) == 1 and attempts[0]["task_purpose"] == "diagnostic"
        assert summary(client)["cycle_id"] == original
        assert summary(client)["state"] == "awaiting_attempt"
        assert summary(client)["evidence_summary"]["independent"] == 0
        assert count(db, "mastery_evidence") == 0


def test_diagnostic_seed_and_child_focus_commit_or_rollback_together(tmp_path, monkeypatch):
    from mathtutor.api.product_state import get_product_state
    db = tmp_path / "atomic-focus.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "original", {"text": "2x+3=7"})
        original = summary(client)["cycle_id"]
        teaching = get_product_state().controller.sessions.teaching
        original_save = teaching.save
        async def failed_seed(*args, **kwargs):
            if args[2].get("pending_diagnostic_initialization"):
                raise RuntimeError("simulated diagnostic seed commit failure")
            await original_save(*args, **kwargs)
        monkeypatch.setattr(teaching, "save", failed_seed)
        send(ws, "send_message", "understood", {"text": "我懂了"})
        assert summary(client)["cycle_id"] == original
        assert count(db, "tutoring_cycles") == 1
    with client_at(db) as client:
        assert summary(client)["cycle_id"] == original
        assert summary(client)["state"] == "awaiting_attempt"
        assert count(db, "mastery_evidence") == 0


def test_existing_044_context_with_task_context_gets_bound_family_for_focused_practice(tmp_path):
    db = tmp_path / "old-context.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "p1", {"text": "2x+3=7"})
        send(ws, "submit_attempt", "a1", {"answer": "2x=10"})
        send(ws, "send_message", "p2", {"text": "换题：3x+2=11"})
        send(ws, "submit_attempt", "a2", {"answer": "3x=13"})
        send(ws, "send_message", "p3", {"text": "换题：4x+1=9"})
        cycle_id = summary(client)["cycle_id"]
    with closing(sqlite3.connect(db)) as conn, conn:
        context = json.loads(conn.execute("SELECT payload FROM teaching_contexts WHERE cycle_id=?", (cycle_id,)).fetchone()[0])
        assert "task_context" in context
        context.pop("problem_type")
        conn.execute("UPDATE teaching_contexts SET payload=? WHERE cycle_id=?", (json.dumps(context), cycle_id))
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        response = terminal(send(ws, "request_practice", "practice"))
        assert "先练等式两边" in response["payload"]["final_text"]
        assert stored_context(db, cycle_id)["problem_type"] == "linear"
        offer_id = summary(client)["active_offer"]["offer_id"]
        offer = next(row for row in client.get("/api/v2/math-tutor/offers").json() if row["offer_id"] == offer_id)
        assert offer["basis"]["reason_code"] == "verified_error_history"
        assert len(offer["evidence_ids"]) == 2


def test_more_than_five_checks_on_different_parents_keep_getting_fresh_verified_items(tmp_path):
    from mathtutor.solving.parser import parse_problem
    from mathtutor.domain.problem import MathProblem
    db = tmp_path / "many-checks.db"
    revisions = set()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        for index in range(7):
            text = f"2x+{index + 1}={3 * index + 9}"
            send(ws, "send_message", f"parent-{index}", {"text": ("换题：" if index else "") + text})
            parent = summary(client)["cycle_id"]
            reply = terminal(send(ws, "send_message", f"understood-{index}", {"text": "我懂了"}))
            check = summary(client)
            assert check["cycle_id"] != parent
            assert check["problem_context"]["understanding_check"] is True
            parsed = parse_problem(check["problem_context"]["display_text"])
            assert parsed.kind == "parsed"
            canonical = MathProblem.canonicalize(problem_type=parsed.problem.problem_type,
                normalized_ast=parsed.problem.normalized_ast, display_latex=parsed.problem.display_latex)
            assert canonical.content_hash not in revisions
            revisions.add(canonical.content_hash)
            assert "两步" in reply["payload"]["final_text"]
            send(ws, "submit_attempt", f"check-answer-{index}", {"answer": f"z={index + 5}"})
            assert summary(client)["cycle_id"] == parent
            assert summary(client)["state"] == "awaiting_attempt"
        assert count(db, "mastery_evidence") == 0
    checked = [event for event in event_rows(db) if event["event_type"] == "attempt_assessed"]
    assert len(checked) == 7
    assert all(event["task_purpose"] == "diagnostic" and event["correctness"] == "correct" for event in checked)
