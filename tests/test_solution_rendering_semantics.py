import json
import re
import sqlite3
from contextlib import closing
from fractions import Fraction

import pytest

from mathtutor.pedagogy.disclosure import display_solution
from mathtutor.solving import nodes
from test_extended_verification import _verified
from test_tutor_p0 import client_at, send


def parseable(latex):
    return latex.replace(r"\le", "<=").replace(r"\ge", ">=")


@pytest.mark.parametrize("coeffs", [{}, {0: Fraction(0)}, {0: Fraction(0), 1: Fraction(0)}, {4: Fraction(0)}])
def test_zero_polynomial_is_never_an_empty_side(coeffs):
    assert nodes.poly_to_latex(coeffs, "z") == "0"


@pytest.mark.parametrize("relation", ["<", "<=", ">", ">="])
@pytest.mark.parametrize("left,right", [("2x+3", "7"), ("-2z+3", "7"), ("0", "-3y"), ("3(t-2)+5", "2t+8")])
def test_every_displayed_inequality_step_has_the_same_verified_solution_set(relation, left, right):
    _, candidate = _verified(left + relation + right)
    before = candidate.model_dump(mode="json")
    shown = display_solution(candidate)
    for step in shown["steps"]:
        latex = step["display_latex"]
        assert latex.strip() and not latex.strip().endswith(("=", "<", ">", r"\le", r"\ge"))
        _, rendered = _verified(parseable(latex))
        assert rendered.final_answer["kind"] == "inequality"
        assert rendered.final_answer["relation"] == candidate.final_answer["relation"]
        assert rendered.final_answer["boundary"] == candidate.final_answer["boundary"]
        assert rendered.final_answer["variable"] == candidate.final_answer["variable"]
    assert display_solution(candidate.model_copy(update={"strategy": ""})) == shown
    assert candidate.model_dump(mode="json") == before


def test_negative_division_flips_only_at_the_negative_division_step():
    _, candidate = _verified("-2x+3<=7")
    shown = display_solution(candidate)["steps"]
    assert [step["display_latex"] for step in shown] == [r"-2x - 4 \le 0", r"-2x \le 4", r"x \ge -2"]
    assert "除以负数，不等号反向" in shown[-1]["display_text"]
    assert "等号右边" not in shown[1]["display_text"].replace("不等号右边", "")


@pytest.mark.parametrize("text", ["3(x-2)+5=2x+8", "5z-7=2z+5", "-3y=0", "0=4t", "x-x"])
def test_equations_and_polynomials_keep_zero_and_their_original_meaning(text):
    _, candidate = _verified(text)
    for step in display_solution(candidate)["steps"]:
        assert step["display_latex"].strip()
        _, rendered = _verified(step["display_latex"])
        if candidate.strategy == "polynomial":
            assert step["display_latex"] == "0"
            assert rendered.final_answer["value"] == {"n": 0, "d": 1}
        else:
            assert rendered.final_answer == candidate.final_answer


@pytest.mark.parametrize("text", ["2x+3<7", "-2x+3<=7", "3(x-2)+5=2x+8"])
def test_real_hint_and_complete_solution_keep_relations_and_replay(tmp_path, text):
    database = tmp_path / "rendering.db"
    _, candidate = _verified(text)
    expected_steps = display_solution(candidate)["steps"]
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": text})
        send(ws, "request_hint", "hint-one")
        send(ws, "request_hint", "hint-two")
        hint_frames = send(ws, "request_hint", "hint-three")
        hint = next(frame["payload"]["final_text"] for frame in hint_frames if frame["event_type"] == "assistant_complete")
        if candidate.strategy == "linear_inequality":
            assert expected_steps[0]["display_latex"] in hint
            for formula in re.findall(r"\\\(\s*(.*?)\s*\\\)", hint):
                _, parsed = _verified(parseable(formula))
                assert parsed.final_answer["kind"] == "inequality"
        frames = send(ws, "request_solution", "full-solution")
        final = next(frame["payload"] for frame in frames if frame["event_type"] == "assistant_complete")
        assert final["status"] == "COMPLETED"
        for step in expected_steps:
            assert step["display_latex"] in final["final_text"]
        with closing(sqlite3.connect(database)) as conn:
            context = conn.execute("SELECT continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='full-solution'").fetchone()[0]
        approved = json.loads(context)["approved_solution_text"]
        assert all(step["display_latex"] in approved for step in expected_steps)
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        replay = send(ws, "request_solution", "full-solution")
        assert any(frame.get("payload", {}).get("final_text") == final["final_text"] for frame in replay)
