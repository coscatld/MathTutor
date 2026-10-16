"""K-12 question bank: catalog by stage, verified practice, demos, learner stage."""
import asyncio

import pytest

from mathtutor.application.function_graph import extract_function_text, graph_for_function, is_graph_request
from mathtutor.application.scene import scene_from_text
from mathtutor.question_bank.service import EMPTY_NOTE, QuestionBankService, load_catalog
from test_tutor_p0 import client_at, send, summary

BANK = QuestionBankService()
DESKTOP = "/api/v2/math-tutor/desktop"


def all_points():
    return [p for t in BANK.catalog["terms"] for u in t["units"] for p in u["points"]]


def test_catalog_covers_every_term_in_textbook_order():
    terms = load_catalog()["terms"]
    assert [t["order"] for t in terms] == list(range(1, 25))
    assert [t["label"] for t in terms[:2]] == ["一年级上册", "一年级下册"]
    assert terms[12]["label"] == "七年级上册" and terms[17]["label"] == "九年级下册"
    assert [t["label"].split(" · ")[1] for t in terms[18:23]] == [
        "必修第一册", "必修第二册", "选择性必修第一册", "选择性必修第二册", "选择性必修第三册"]
    assert all(t["units"] and all(u["points"] for u in t["units"]) for t in terms)
    assert len(all_points()) >= 300


@pytest.mark.parametrize("stage, orders", [("primary", range(1, 13)), ("middle", range(13, 19)), ("high", range(19, 25))])
def test_tree_shows_only_the_chosen_stage(stage, orders):
    tree = BANK.tree(stage)
    assert [t["order"] for t in tree["terms"]] == list(orders) and {t["stage"] for t in tree["terms"]} == {stage}
    assert len(BANK.tree(None)["terms"]) == 24


def test_every_practice_entry_yields_verified_problems_with_stable_ids():
    for point in all_points():
        if not point.get("practice"):
            continue
        problems = asyncio.run(BANK.problems(point["code"]))
        assert problems, point["code"]
        families = {item["family"] for item in point["practice"]}
        assert all(p["family"] in families and p["display_latex"] and 1 <= p["difficulty"] <= 3 for p in problems)
    fresh = QuestionBankService()
    code = "g7a-u3-p2"
    assert asyncio.run(fresh.problems(code)) == asyncio.run(BANK.problems(code))


def test_every_demo_is_a_drawable_request():
    for point in all_points():
        for demo in point.get("demos", ()):
            request = demo["request"]
            assert is_graph_request(request), request
            if scene_from_text(request) is None:
                assert graph_for_function(extract_function_text(request)), request


def test_formerly_empty_points_now_have_honest_reference_content():
    detail = asyncio.run(BANK.point("g1a-u1-p1"))
    assert detail["problems"] == [] and detail["demos"] == [] and detail["note"] == ""
    assert len(detail["reference_problems"]) >= 2
    assert all(not q["verification"]["student_steps_auto_verified"] for q in detail["reference_problems"])
    assert asyncio.run(BANK.point("nope")) is None


def test_learner_stage_drives_the_default_tree_and_validates_grades(tmp_path):
    with client_at(tmp_path / "bank.db") as client:
        settings = client.get(DESKTOP + "/settings/learner").json()
        assert settings["stage"] is None and [s["stage"] for s in settings["stages"]] == ["primary", "middle", "high"]
        assert len(client.get(DESKTOP + "/exercise-bank").json()["terms"]) == 24
        assert client.put(DESKTOP + "/settings/learner", json={"stage": "high", "grade": 7}).status_code == 422
        assert client.put(DESKTOP + "/settings/learner", json={"stage": "high", "grade": 11}).json()["grade"] == 11
        tree = client.get(DESKTOP + "/exercise-bank").json()
        assert tree["stage"] == "high" and [t["order"] for t in tree["terms"]] == list(range(19, 25))
        assert client.get(DESKTOP + "/exercise-bank", params={"stage": "primary"}).json()["terms"][0]["label"] == "一年级上册"
        assert client.get(DESKTOP + "/exercise-bank", params={"stage": "college"}).status_code == 422
        assert client.get(DESKTOP + "/exercise-bank/points/nope").status_code == 404


def test_a_bank_problem_starts_a_verified_tutoring_cycle(tmp_path):
    with client_at(tmp_path / "bank.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        detail = client.get(DESKTOP + "/exercise-bank/points/h1a-u2-p3").json()
        problem = next(p for p in detail["problems"] if p["family"] == "quadratic_inequality")
        send(ws, "submit_problem", "start", {"text": problem["text"]})
        state = summary(client)
        assert state["state"] == "awaiting_attempt" and state["problem_context"]["graphable"] is True
