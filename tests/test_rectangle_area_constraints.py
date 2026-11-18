import json
import sqlite3
from contextlib import closing
from fractions import Fraction

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.constraint_layer import ConstraintStatus, boundary_response, evaluate_constraints
from mathtutor.solving.elementary_geometry import rectangle_area_task
from mathtutor.solving.parser import parse_problem
from test_extended_verification import _verified
from test_tutor_p0 import client_at, send, summary


@pytest.mark.parametrize("perimeter", ["20", "24", "1", "0.5", "36.125", "999999.999"])
def test_perimeter_only_has_two_exact_positive_examples_with_different_areas(perimeter):
    task = rectangle_area_task(f"一个长方形的周长是{perimeter}，求面积")
    assert task.status == "underdetermined"
    witnesses = task.receipt()["witnesses"]
    assert len(witnesses) == 2
    for witness in witnesses:
        left, right = Fraction(witness["length"]), Fraction(witness["width"])
        assert left > right > 0
        assert 2 * (left + right) == Fraction(witness["perimeter"]) == Fraction(perimeter)
        assert left * right == Fraction(witness["area"])
    assert Fraction(witnesses[0]["area"]) != Fraction(witnesses[1]["area"])
    result = evaluate_constraints(f"一个长方形的周长是{perimeter}，求面积")
    assert result.status is ConstraintStatus.SOFT_FAIL
    assert result.reason == "rectangle_area_underdetermined"
    assert "请补充一条边长，或长宽之间的关系" in boundary_response(result)
    assert "不能可靠地解析" not in boundary_response(result)


@pytest.mark.parametrize("text,answer", [
    ("长方形周长20，长6，求面积", Fraction(24)),
    ("一个长方形的周长是20，宽为3，求面积", Fraction(21)),
    ("已知长方形周长24厘米，长8厘米，求面积", Fraction(32)),
    ("长方形周长为10.5米，宽1.25米，面积是多少？", Fraction(5)),
    ("长方形周长20cm，长6厘米宽4cm，求面积", Fraction(24)),
    ("长方形的周长是20，长6，宽4，求面积", Fraction(24)),
    ("长方形长为5宽为3，求面积", Fraction(15)),
])
def test_complete_feasible_conditions_use_the_existing_arithmetic_solver(text, answer):
    result = evaluate_constraints(text)
    assert result.status in {ConstraintStatus.PASS, ConstraintStatus.REPAIRED}
    assert boundary_response(result) == ""
    problem, candidate = _verified(text)
    assert problem.problem_type == "arithmetic"
    value = candidate.final_answer["value"]
    assert Fraction(value["n"], value["d"]) == answer


@pytest.mark.parametrize("text", [
    "长方形周长0，求面积", "长方形周长-20，求面积",
    "长方形周长20，长0，求面积", "长方形周长20，宽-3，求面积",
    "长方形周长20，长10，求面积", "长方形周长20，长12，求面积",
    "长方形周长20，长6宽3，求面积",
])
def test_nonpositive_or_contradictory_data_is_infeasible_not_missing(text):
    result = evaluate_constraints(text)
    assert result.reason == "rectangle_area_infeasible"
    assert "不能构成边长为正的长方形" in boundary_response(result)
    assert result.boundary_receipt["witnesses"] == []
    assert parse_problem(text).kind != "parsed"


@pytest.mark.parametrize("text", [
    "长方形周长20，长是宽的两倍，求面积",
    "长方形周长20，长宽相等，求面积",
    "长方形周长20，长6米，宽4厘米，求面积",
    "长方形周长20米，长6厘米，求面积",
    "长方形周长20，长6，求面积再减2",
    "长方形周长20，求最大面积", "长方形周长20，求面积范围",
    "正方形周长20，求面积", "三角形周长20，求面积",
    "长方形周长20，长6，且边长必须是整数，求面积",
    "长方形周长9999999，求面积", "长方形周长1e20，求面积",
    "长方形周长__import__('os')，求面积",
])
def test_unknown_conditions_shapes_and_units_are_not_silently_discarded(text):
    assert rectangle_area_task(text) is None
    assert not evaluate_constraints(text).reason.startswith("rectangle_area_")


@pytest.mark.parametrize("text", ["长方形长为5宽为3，求面积", "正方形边长为4的面积", "长方形长为0宽为3，求面积"])
def test_existing_geometry_is_not_blanket_classified_as_missing_conditions(text):
    assert rectangle_area_task(text) is None
    assert "不能唯一确定面积" not in boundary_response(evaluate_constraints(text))


@pytest.mark.parametrize("perimeter", ["20", "24"])
def test_actual_chat_explains_nonuniqueness_and_persists_checked_examples(tmp_path, perimeter):
    database = tmp_path / "geometry.db"
    question = f"一个长方形的周长是{perimeter}，求面积"
    class NoModel:
        is_configured = True
        async def respond(self, *args, **kwargs):
            raise AssertionError("Complete rectangle constraints are decided locally")
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.chat_responder = NoModel()
        frames = send(ws, "send_message", "perimeter-only", {"text": question})
        complete = next(frame["payload"] for frame in frames if frame["event_type"] == "assistant_complete")
        assert "长宽之间的关系" in complete["final_text"] and "周长相同但面积不同" in complete["final_text"]
        assert complete["status"] == "COMPLETED" and complete["steps_used"] == 0
        with closing(sqlite3.connect(database)) as conn:
            saved = conn.execute("SELECT content, continuation_context FROM conversation_messages WHERE role='tutor' AND turn_id='perimeter-only'").fetchone()
            assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM mastery_evidence").fetchone()[0] == 0
        receipt = json.loads(saved[1])["math_boundary"]["constraint_receipt"]
        assert receipt == rectangle_area_task(question).receipt()
        assert "24" in complete["final_text"] if perimeter == "20" else "34.56" in complete["final_text"]
    with client_at(database) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        replay = send(ws, "send_message", "perimeter-only", {"text": question})
        assert any(frame.get("payload", {}).get("final_text") == saved[0] for frame in replay)
        send(ws, "send_message", "complete-new-question", {"text": "换题：长方形周长20，长6，求面积"})
        assert summary(client)["state"] == "awaiting_attempt"
