"""Fixed v2 acceptance cases through real owner-scoped SQLite and WebSocket.

Only untrusted writer/generator boundaries are replaced. Routing, disclosure,
verification, learning commits, capabilities and persisted messages stay real.
"""
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.api.math_tutor_ws import _message_projection
from mathtutor.application.adaptive_practice import CandidateExercise
from mathtutor.application.controller import USER_COMMANDS, _parse_envelope
from mathtutor.pedagogy.tutor_writer import TemplateTutorWriter, TutorWriterCandidate
from mathtutor.security.allowlist import validate_client_envelope
from mathtutor.solving.parser import parse_problem

from test_tutor_p0 import client_at, count, envelope, send, summary
from test_teaching_v2 import event_rows, terminal


def content(frames):
    return terminal(frames)["payload"]["final_text"]


def test_i09_bare_number_requires_a_specific_task_before_grounding(tmp_path):
    db = tmp_path / "bare-number.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        seeded_problems = count(db, "math_problems")
        text = content(send(ws, "send_message", "number", {"text": "391"}))
        assert "391" in text
        assert re.search(r"题目|要求|计算什么|做什么|什么任务", text), text
        assert count(db, "math_problems") == seeded_problems
        assert count(db, "attempts") == 0
        assert summary(client)["problem_context"] is None


def test_c05_all_observed_enabled_capabilities_are_public_parseable_commands(tmp_path):
    db = tmp_path / "capabilities.db"
    observed = set()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        def inspect():
            state = summary(client)
            for action in state["allowed_actions"]:
                if not action["enabled"]:
                    continue
                name = action["command"]
                assert name in USER_COMMANDS
                request = envelope(name, "capability-check")
                validate_client_envelope(request)
                assert _parse_envelope(json.dumps(request))[0] == name
                observed.add(name)
            return state

        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        inspect()
        send(ws, "request_practice", "practice")
        offer = inspect()["active_offer"]["offer_id"]
        send(ws, "accept_practice_offer", "accept", {"offer_id": offer})
        inspect()
        send(ws, "resume_problem", "return")
        inspect()
        send(ws, "start_diagnostic", "diagnostic")
        inspect()
        send(ws, "submit_attempt", "diagnostic-error", {"answer": "0"})
        inspect()
        send(ws, "skip_diagnostic", "skip")
        assert "request_foundation" in inspect()["allowed_next_inputs"]
        send(ws, "request_foundation", "foundation")
        offer = inspect()["active_offer"]["offer_id"]
        send(ws, "decline_practice_offer", "decline", {"offer_id": offer})
        inspect()
        send(ws, "submit_attempt", "correct", {"answer": "2"})
        inspect()
        # Advance the fixture's clock past the actual review window. No label
        # or skill is invented; the real successful event remains the authority.
        with closing(sqlite3.connect(db)) as conn, conn:
            rows = conn.execute("SELECT event_id,payload FROM learning_events WHERE event_type='attempt_assessed'").fetchall()
            for event_id, payload in rows:
                event = json.loads(payload)
                event["occurred_at"] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
                conn.execute("UPDATE learning_events SET payload=? WHERE event_id=?", (json.dumps(event), event_id))
        assert "request_review" in inspect()["allowed_next_inputs"]
        send(ws, "end_problem", "end")
        inspect()
    assert {"request_hint", "request_explanation", "request_example", "request_solution",
            "request_practice", "request_foundation", "request_review", "accept_practice_offer",
            "decline_practice_offer", "resume_problem", "start_diagnostic", "skip_diagnostic", "end_problem"} <= observed


@pytest.mark.parametrize("claim", ["你写得对", "你做得不错", "你已经掌握", "你这一步是正确的", "答对了", "思路正确"])
def test_t01_hint_never_publishes_an_unobserved_student_success(tmp_path, claim):
    db = tmp_path / "praise.db"
    class UnsupportedPraiseWriter:
        calls = 0
        async def write(self, **kwargs):
            self.calls += 1
            assert kwargs["problem_view"].verified_progress == ()
            return TutorWriterCandidate(text=f"{claim}。接着考虑等式两边的运算。", writer_version="adversarial-fixed")
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        writer = UnsupportedPraiseWriter()
        get_product_state().controller.writer = writer
        text = content(send(ws, "request_hint", "hint"))
        assert writer.calls == 1
        assert claim not in text
        assert re.search(r"等式|运算|常数项|系数", text), text
        assert summary(client)["cycle_id"] == original["cycle_id"]
        assert count(db, "attempts") == 0
        assert not [e for e in event_rows(db) if e["event_type"] == "attempt_assessed"]


def test_t05_system_example_is_verified_same_skill_material(tmp_path):
    db = tmp_path / "same-skill.db"
    class RecordingWriter:
        views = []
        async def write(self, **kwargs):
            self.views.append(kwargs["problem_view"])
            return await TemplateTutorWriter().write(**kwargs)
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "x+y=4;x-y=2"})
        original = summary(client)
        writer = RecordingWriter()
        get_product_state().controller.writer = writer
        text = content(send(ws, "request_example", "example"))
        assert len(writer.views) == 1
        view = writer.views[0]
        assert view.problem_type == "linear_system"
        example = view.approved_example
        assert example and example.get("kind") != "teacher_error_example"
        parsed = parse_problem(example["problem"])
        assert parsed.kind == "parsed" and parsed.problem.problem_type == "linear_system"
        assert example["problem"] != view.display_latex
        assert example["solution"] in text
        assert "分母" not in text and "通分" not in text
        assert summary(client)["cycle_id"] == original["cycle_id"]
        assert count(db, "attempts") == 0


def test_p04_understood_is_self_report_not_correctness_or_completion(tmp_path):
    db = tmp_path / "self-report.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        send(ws, "send_message", "understood", {"text": "我懂了"})
        after = summary(client)
        assert after["cycle_id"] != original["cycle_id"]
        assert after["problem_context"]["lifecycle"] == "active"
        assert after["problem_context"]["understanding_check"] is True
        assert after["active_offer"] is None
        assert count(db, "attempts") == count(db, "mastery_evidence") == 0
        assert after["evidence_summary"]["independent"] == 0
        with closing(sqlite3.connect(db)) as conn:
            original_context = json.loads(conn.execute("SELECT payload FROM teaching_contexts WHERE cycle_id=?", (original["cycle_id"],)).fetchone()[0])
        assert original_context["lifecycle"] == "active" and original_context["assessments"] == []
        events = event_rows(db)
        assert not [e for e in events if e["event_type"] == "attempt_assessed"]
        reports = [e for e in events if e["event_type"] == "self_explanation"]
        assert len(reports) == 1 and reports[0]["correctness"] is None
        assert reports[0]["cycle_id"] == original["cycle_id"]
        send(ws, "resume_problem", "return")
        assert summary(client)["cycle_id"] == original["cycle_id"]
        assert summary(client)["state"] == "awaiting_attempt"


def test_p02_presented_hint_then_correct_answer_is_assisted_and_offers_a2(tmp_path):
    db = tmp_path / "assisted-completion.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        shown = terminal(send(ws, "request_hint", "hint"))
        assert shown["delivery_id"]
        # The next command follows the presentation ACK on the same socket;
        # no sleep, eventual GET or fabricated help record is used as ordering.
        ws.send_json({"type": "delivery_presented", "delivery_id": shown["delivery_id"]})
        send(ws, "send_message", "answer", {"text": "x=2"})
        after = summary(client)
        assert after["cycle_id"] == original["cycle_id"] and after["state"] == "solved"
        assert after["active_offer"]["purpose"] == "A2"
        assert after["evidence_summary"]["assisted"] == 1
        assert after["evidence_summary"]["independent"] == 0
        events = event_rows(db)
        presented = next(e for e in events if e["event_type"] == "help_presented")
        assessed = next(e for e in events if e["event_type"] == "attempt_assessed")
        assert presented["event_seq"] < assessed["event_seq"]
        assert assessed["evidence_kind"] == "assisted" and not assessed["target_answer_exposed_before_attempt"]
        assert assessed["correctness"] == "correct" and assessed["prior_help_event_ids"]


def test_p05_failed_candidates_keep_the_assessment_but_never_publish_an_empty_offer(tmp_path):
    db = tmp_path / "failed-offer.db"
    class InvalidGenerator:
        calls = 0
        async def generate(self, context, *, count=1):
            self.calls += 1
            assert count <= 3
            return [CandidateExercise(student_id=context.student_id,
                problem_statement="缺少明确题干", skill_ids=context.target_skill_ids,
                difficulty=2, generated_by="fixed-invalid") for _ in range(5)]
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        original = summary(client)
        generator = InvalidGenerator()
        get_product_state().adaptive_practice._generator = generator
        frames = send(ws, "submit_attempt", "correct", {"answer": "2"})
        after = summary(client)
        assert terminal(frames)["event_type"] == "assistant_complete"
        assert after["cycle_id"] == original["cycle_id"] and after["state"] == "solved"
        assert count(db, "attempt_assessments") == 1
        assert generator.calls == 1
        assert count(db, "practice_offers") == 0
        assert after["active_offer"] is None
        assert not {"accept_practice_offer", "decline_practice_offer"} & set(after["allowed_next_inputs"])
        with closing(sqlite3.connect(db)) as conn, conn:
            record = json.loads(conn.execute("SELECT payload FROM practice_recommendations").fetchone()[0])
        assert record["status"] == "FAILED" and record["candidate_count"] == 3


def test_p11_decline_preserves_original_problem_for_followup(tmp_path):
    db = tmp_path / "decline.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        send(ws, "submit_attempt", "correct", {"answer": "2"})
        original = summary(client)
        send(ws, "decline_practice_offer", "decline", {"offer_id": original["active_offer"]["offer_id"]})
        assert summary(client)["active_offer"] is None
        text = content(send(ws, "send_message", "followup", {"text": "为什么等式两边要同时减去 3？"}))
        after = summary(client)
        assert after["cycle_id"] == original["cycle_id"] and after["problem_revision"] == original["problem_revision"]
        assert after["state"] == "solved"
        assert after["active_offer"] is None
        assert "等式" in text
        assert count(db, "attempt_assessments") == 1


def test_d02_failed_writer_request_is_not_presented_help(tmp_path):
    db = tmp_path / "failed-help.db"
    class FailedWriter:
        calls = 0
        async def write(self, **kwargs):
            self.calls += 1
            raise RuntimeError("fixed-writer-unavailable")
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        writer = FailedWriter()
        get_product_state().controller.writer = writer
        frames = send(ws, "request_hint", "failed-hint")
        assert writer.calls == 1
        assert terminal(frames)["event_type"] == "assistant_error"
        assert count(db, "attempts") == 0
        assert count(db, "teaching_deliveries") == 0
        assert not [e for e in event_rows(db) if e["event_type"] in {"help_presented", "help_possibly_exposed"}]


@pytest.mark.parametrize("command,label", [
    ("request_practice", "我想独立练一道"), ("request_foundation", "先补基础"),
    ("request_review", "做一道复习题"), ("resume_problem", "回到原题"),
    ("end_problem", "结束本题"), ("start_diagnostic", "了解当前基础"),
    ("skip_diagnostic", "跳过诊断，继续辅导"),
])
def test_control_action_transcript_uses_visible_chinese_not_wire_command(command, label):
    assert _message_projection(json.dumps(envelope(command, "label")))[0] == label
