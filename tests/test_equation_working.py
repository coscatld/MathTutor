"""Student equation working through the exact judge, writer projection and durable WS path."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from mathtutor.learning.knowledge_tracing.events import LearningEvent
from mathtutor.pedagogy.student_evidence_view import assessment_view
from test_phase4_learning import _assessment
from test_tutor_p0 import client_at, send, summary


# Expected verdict, first failing physical line (when submitting working), and diagnostic signal.
LINEAR = "2x+3=7"
_CASES_FILE = Path(__file__).resolve().parents[1] / "benchmarks/steps/cases.json"
CASES = [
    (row["id"], row["problem"], row["answer"], row["verdict"], row["issue_line"], row["signal"])
    for row in json.loads(_CASES_FILE.read_text(encoding="utf-8"))
]


@pytest.mark.parametrize("case", CASES, ids=lambda row: row[0])
def test_equation_working(case):
    _, problem, answer, expected, bad_line, signal = case
    _, _, result = _assessment(answer, problem)
    assert result.correctness.value == expected
    if signal:
        assert signal in result.signals
    if bad_line:
        assert result.remaining_requirements[0]["line"] == bad_line
        assert f"第 {bad_line} 行" in result.reason
        assert all(claim["line"] < bad_line for claim in result.verified_claims)
        if expected == "incorrect":
            assert result.invalid_claims[0]["line"] == bad_line
        else:
            assert not result.invalid_claims and result.score is None


@pytest.mark.parametrize("case_name, command", [
    ("translated-unit-slope", "submit_attempt"),
    ("variable-on-both-sides", "submit_attempt"),
    ("right-route", "submit_attempt"),
    ("reverse-route", "send_message"),
    ("wrong-first-right-last", "send_message"),
    ("late-sign", "submit_attempt"),
    ("combine-like-terms", "submit_attempt"),
    ("domain-cancelled", "submit_attempt"),
    ("squared-extra", "submit_attempt"),
    ("wrong-closed-endpoint", "submit_attempt"),
])
def test_working_ws_feedback_and_persisted_evidence(tmp_path, case_name, command):
    _, problem, answer, expected, bad_line, _ = next(case for case in CASES if case[0] == case_name)
    db = tmp_path / "working.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": problem})
        payload = {"text" if command == "send_message" else "answer": answer}
        frames = send(ws, command, "work", payload)
        assert not any(frame["event_type"] == "turn_error" for frame in frames)
        assert send(ws, command, "work", payload) == frames
        saved = summary(client)
        feedback = "\n".join(m.get("content", "") for m in saved["messages"]
                             if m.get("turn_id") == "work" and m["role"] == "tutor")
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute("SELECT correctness FROM attempt_assessments").fetchall() == [(expected,)]
        evidence = conn.execute("SELECT correctness, score, effective_assistance_level FROM mastery_evidence").fetchall()
        context = json.loads(conn.execute("SELECT payload FROM teaching_contexts").fetchone()[0])
        events = conn.execute("SELECT payload FROM learning_events WHERE event_type='attempt_assessed'").fetchall()
        event, = [LearningEvent.model_validate_json(payload) for payload, in events]
    assert (event.independent_target and event.correctness == "correct") == (expected == "correct")
    record = context["assessments"][-1]
    public = assessment_view([record])[0]
    assert (record["task_completion"] == "complete") == (expected == "correct")
    assert (context["lifecycle"] == "completed") == (expected == "correct")
    if expected == "undetermined":
        assert evidence == []
    else:
        assert evidence == [(expected, {"partial": 0.5, "correct": 1.0, "incorrect": 0.0}[expected], 0)]
    if bad_line:
        assert f"第 {bad_line} 行" in feedback
        assert public["working_feedback"] in feedback
        assert public["remaining_requirements"][0]["line"] == bad_line
        assert "expected" not in json.dumps(public)
    else:
        assert feedback


def test_working_limits_and_divisor_scope():
    _, _, over = _assessment("\n".join(["2x=4"] * 16 + ["x=2"]), LINEAR)
    assert over.correctness.value == "undetermined"
    assert "16" in over.reason
    _, _, canceled = _assessment("x=2+0/(x-2)", LINEAR)
    assert canceled.correctness.value == "undetermined" and "定义域" in canceled.reason
    _, _, limited = _assessment("x<2 或 x>3" + " " * 220 + "或 x=2", "x^2-5x+6>0")
    assert limited.correctness.value != "correct"


def test_replay_single_legacy_equation_uses_original_sides():
    from mathtutor.learning import verify_attempt
    from test_phase4_learning import _answer_attempt, _verified_chain
    problem, _, candidate, _ = _verified_chain(LINEAR)
    attempt = _answer_attempt("2x=x+2")
    old_step = dict(attempt.parsed_steps[0])
    old_step.pop("isolated_variable")
    result = verify_attempt(attempt.model_copy(update={"parsed_steps": (old_step,)}), problem, candidate)
    assert result.correctness.value == "partial"



def test_interval_membership_preserves_variable_and_system_relations():
    problem = "x^2-1<=0"
    assert _assessment("x∈[-1,1]", problem)[2].correctness.value == "correct"
    assert _assessment("y∈[-1,1]", problem)[2].correctness.value == "undetermined"
    assert _assessment("(1.5,+∞)", "2x>3")[2].correctness.value == "correct"
    assert _assessment("(x)=2,y=1", "x+y=3;x-y=1")[2].correctness.value == "correct"
    assert _assessment("x<1+1\ny<1+0", "x+y=3;x-y=1")[2].correctness.value != "correct"



def test_first_error_reaches_actual_writer_prompt(tmp_path):
    from test_teaching_recovery_v2 import install_writer
    from test_tutor_output_contract_integration import Replies

    provider = Replies("请重新核对第二行等式两边的常数项。")
    with client_at(tmp_path / "writer.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": LINEAR})
        send(ws, "submit_attempt", "attempt", {"answer": "2x=4\n2x=10"})
        install_writer(provider)
        send(ws, "request_hint", "hint", {})
    messages = provider.calls[0][0]
    prompt = next(row["content"] for row in messages if row["role"] == "user")
    section = next(line for line in prompt.splitlines() if line.startswith("最近作答与明确验证结论："))
    record, = json.loads(section.split("：", 1)[1])
    assert "第 2 行" in record["working_feedback"]
    assert record["verified_steps"] == [{"claim": "equivalent_equation", "line": 1}]
    assert record["invalid_claims"][0]["line"] == 2
    assert "expected" not in section
