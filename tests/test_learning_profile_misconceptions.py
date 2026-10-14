"""Diagnosed misconceptions reach the public learning profile."""
from mathtutor.application.learning_profile import active_misconceptions, profile_projection
from mathtutor.learning.knowledge_tracing.events import LearningEvent


def assessed(seq, correctness, *, skill="linear_transpose", codes=(), revision=None, kind="independent"):
    return LearningEvent(
        event_id=f"e{seq}", student_id="alice", session_id="s", cycle_id=f"c{seq}", event_seq=seq,
        event_type="attempt_assessed", occurred_at=f"2026-10-14T00:00:{seq:02d}+00:00",
        problem_id=f"p{seq}", problem_revision=revision or f"r{seq}", item_family_id="linear",
        skill_ids=(skill,), assessment_id=f"a{seq}", attempt_id=f"a{seq}",
        correctness=correctness, evidence_kind=kind, misconception_codes=tuple(codes))


def test_profile_counts_diagnosed_rules_instead_of_fixed_zero():
    history = [assessed(1, "incorrect", codes=("sign_flip",)),
               assessed(2, "incorrect", codes=("wrong_operation", "sign_flip"))]
    profile = profile_projection(history)
    assert profile["active_misconceptions"] == 2
    assert [m["rule_id"] for m in profile["misconceptions"]] == [
        "miscon-sign-error", "miscon-transposition-error"]
    assert profile["misconceptions"][0]["label"] == "符号错误"
    assert all(row["mastery"] is None for row in profile["skills"])


def test_independent_success_on_the_skill_resolves_its_rules():
    history = [assessed(1, "incorrect", codes=("sign_flip",)),
               assessed(2, "incorrect", skill="quadratic_roots", codes=("missing_root",)),
               assessed(3, "correct")]
    assert [m["rule_id"] for m in active_misconceptions(history)] == ["miscon-missing-root"]


def test_assisted_success_and_unknown_signals_do_not_change_rules():
    history = [assessed(1, "incorrect", codes=("sign_flip", "not_a_rule")),
               assessed(2, "correct", kind="assisted")]
    assert [m["rule_id"] for m in active_misconceptions(history)] == ["miscon-sign-error"]
    assert active_misconceptions([assessed(1, "correct", codes=("sign_flip",))]) == []


def test_export_and_profile_share_the_diagnosed_misconceptions(tmp_path):
    from test_tutor_p0 import client_at, send
    with client_at(tmp_path / "export.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        send(ws, "submit_attempt", "wrong", {"answer": "x=-2"})
        profile = client.get("/api/v2/math-tutor/desktop/student-summary").json()
        exported = client.get("/api/v2/math-tutor/desktop/privacy/export").json()["student_summary"]
    assert profile["active_misconceptions"] == 1
    assert [row["rule_id"] for row in exported["active_misconceptions"]] == ["miscon-sign-error"]
    row = exported["active_misconceptions"][0]
    assert row["label"] == "符号错误" and row["status"] == "active" and row["confidence"] is None
    assert row["skill_ids"] == profile["misconceptions"][0]["skill_ids"]
