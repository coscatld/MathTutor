import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

from mathtutor.pedagogy.teaching_plan import choose_plan
from test_tutor_p0 import client_at, send, summary


def action_frame(frames):
    return next(frame["payload"] for frame in frames if frame["event_type"] == "tutor_action_committed")


@pytest.mark.parametrize("problem,strategy,answer", [
    ("3x-4=8", "常数项移到另一边", "x=4"),
    ("7z+6=20", "常数项移到另一边", "z=2"),
    ("2x+3<7", "改变不等号方向", "x<2"),
    ("3/4+1/8", "分数加减先通分", "7/8"),
    ("x+y=7;x-y=1", "整体倍乘相加减消元", "x=4"),
])
def test_second_hint_supplies_the_next_disclosure_layer_in_the_same_bound_problem(tmp_path, problem, strategy, answer):
    database = tmp_path / "hints.db"
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": problem})
        first_state = summary(client)
        first = action_frame(send(ws, "request_hint", "hint-one"))
        assert first["effective_assistance_level"] == 1
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        frames = send(ws, "request_hint", "hint-two")
        second = action_frame(frames)
        current = summary(client)
        assert current["cycle_id"] == first_state["cycle_id"]
        assert second["action"] == "GIVE_HINT" and second["effective_assistance_level"] == 2
        assert strategy in second["student_message"]
        assert second["student_message"] != first["student_message"]
        assert answer not in second["student_message"].replace(" ", "")
        assert "你想选哪一种" not in second["student_message"]
        assert current["teaching_plan"]["max_assistance_level"] == 2
        assert not current["teaching_plan"]["allow_target_answer"]
        assert send(ws, "request_hint", "hint-two") == frames
        with closing(sqlite3.connect(database)) as conn:
            assert conn.execute("SELECT effective_assistance_level FROM tutor_actions ORDER BY rowid").fetchall() == [(1,), (2,)]
            assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM mastery_evidence").fetchone()[0] == 0
        send(ws, "send_message", "replacement", {"text": "换题：5x-3=12"})
        assert summary(client)["cycle_id"] != first_state["cycle_id"]
        assert action_frame(send(ws, "request_hint", "new-first"))["effective_assistance_level"] == 1


def test_same_layer_repeat_remains_a_choice_not_unbounded_escalation():
    from types import SimpleNamespace
    context = {"current_subgoal_index": 0, "subgoals": [{"id": "balance", "prompt_target": "保持相等"}],
               "skill_ids": ["equality_preservation"], "stuck_count": 0, "help_without_progress": 0,
               "assessments": [], "progress": [], "help_fingerprints": []}
    action = SimpleNamespace(action="GIVE_HINT", effective_assistance_level=2)
    _, plan = choose_plan(context, action)
    context["help_fingerprints"] = [plan.fingerprint]
    _, repeated = choose_plan(context, action)
    assert repeated.support_mode == "choice"
    assert replace(plan, max_assistance_level=1).fingerprint != plan.fingerprint
    assert repeated.max_assistance_level < 5 and not repeated.allow_target_answer
