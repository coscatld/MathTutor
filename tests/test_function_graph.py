"""Server-computed function graphs: safe parsing, disclosure and evidence."""
import json
import re

import pytest

from mathtutor.application.function_graph import (
    GraphInputError, extract_function_text, graph_for_function, graph_for_problem, is_graph_request,
    summarize_graph_blocks)
from mathtutor.solving.parser import parse_problem
from test_tutor_p0 import client_at, send, summary


def spec(text):
    return json.loads(re.search(r"```mathtutor-graph\n(.*?)\n```", text, re.S).group(1))


def labels(text):
    return [mark["label"] for mark in spec(text)["marks"]]


@pytest.mark.parametrize("text, expression", [
    ("画出 y=x^2-2x-3 的图像", "x^2-2x-3"), ("画出y=sqrt(x)的图像", "sqrt(x)"),
    ("f(x)=sin(x)", "sin(x)"), ("画 x^3-x 的图像", "x^3-x"), ("画出这道题的函数图像", "")])
def test_extracts_the_typed_function(text, expression):
    assert extract_function_text(text) == expression


def test_graph_requests_are_recognized_without_catching_teaching_requests():
    assert all(map(is_graph_request, ["画出这道题的函数图像", "帮我画一下 y=x^2", "这个图像是什么样"]))
    assert not any(map(is_graph_request, ["给我提示", "2x+3=7", "我懂了"]))


@pytest.mark.parametrize("source", ["__import__('os')", "x+", "2a", "open(x)", "x" * 200])
def test_parser_rejects_anything_outside_the_whitelist(source):
    with pytest.raises(GraphInputError):
        graph_for_function(source)


def test_quadratic_marks_exact_points_and_hides_zeros_when_asked():
    shown = labels(graph_for_function("x^2-2x-3"))
    assert shown == ["与 y 轴交点 (0, -3)", "与 x 轴交点 (-1, 0)", "与 x 轴交点 (3, 0)", "顶点 (1, -4)"]
    hidden = graph_for_function("x^2-2x-3", reveal=False)
    assert labels(hidden) == ["与 y 轴交点 (0, -3)", "顶点 (1, -4)"]


def test_asymptote_splits_the_curve_and_periodic_functions_keep_a_readable_window():
    assert len(spec(graph_for_function("1/x"))["series"][0]["segments"]) == 2
    assert spec(graph_for_function("sin(x)"))["x_range"] == [-10.0, 10.0]


@pytest.mark.parametrize("text, hidden, revealed", [
    ("2x+3=7", ["与纵轴交点 (0, -4)"], ["与纵轴交点 (0, -4)", "与横轴交点 (2, 0)"]),
    ("x^2-5x+6=0", ["与纵轴交点 (0, 6)", "顶点 (5/2, -1/4)"],
     ["与纵轴交点 (0, 6)", "与横轴交点 (2, 0)", "与横轴交点 (3, 0)", "顶点 (5/2, -1/4)"]),
    ("2u+v=19;u-v=2", [], ["交点 (7, 5)"]),
    ("3a+2(a+4)", [], ["与纵轴交点 (0, 8)", "与横轴交点 (-8/5, 0)"]),
])
def test_problem_graph_marks_the_answer_only_when_revealed(text, hidden, revealed):
    problem = parse_problem(text).problem
    assert labels(graph_for_problem(problem.problem_type, problem.normalized_ast, reveal=False)) == hidden
    assert labels(graph_for_problem(problem.problem_type, problem.normalized_ast, reveal=True)) == revealed


def test_simplification_graph_does_not_print_the_simplified_answer_early():
    problem = parse_problem("3a+2(a+4)").problem
    assert "5a" not in graph_for_problem(problem.problem_type, problem.normalized_ast, reveal=False)
    assert "y = 5a + 8" in graph_for_problem(problem.problem_type, problem.normalized_ast, reveal=True)


def test_model_context_sees_a_placeholder_instead_of_points():
    text = "前文\n" + graph_for_function("2x+1")
    assert summarize_graph_blocks(text) == "前文\n**函数图像**：y = 2x + 1\n\n[已展示函数图像：y = 2x + 1]"


def test_graph_of_open_problem_is_recorded_help_and_hides_the_root(tmp_path):
    with client_at(tmp_path / "graph.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        free = send(ws, "send_message", "free", {"text": "画出 y=x^2-2x-3 的图像"})
        assert any(f["payload"].get("action") == "SHOW_GRAPH" for f in free)
        send(ws, "submit_problem", "p", {"text": "x^2-5x+6=0"})
        assert summary(client)["problem_context"]["graphable"] is True
        graph = send(ws, "send_message", "g", {"text": "画出这道题的函数图像"})
        content = next(f["payload"]["student_message"] for f in graph if f["payload"].get("action") == "SHOW_GRAPH")
        assert "与横轴交点 (" not in content and "顶点 (5/2, -1/4)" in content
        typed = send(ws, "send_message", "typed", {"text": "画出 y=x^2-5x+6 的图像"})
        assert "与 x 轴交点 (" not in json.dumps(typed, ensure_ascii=False)
        delivery = next(f["delivery_id"] for f in graph if f.get("delivery_id"))
        ws.send_json({"type": "delivery_presented", "delivery_id": delivery})
        send(ws, "submit_attempt", "a", {"answer": "x=2或x=3"})
        assert summary(client)["evidence_summary"]["assisted"] == 1
        after = send(ws, "send_message", "g2", {"text": "画出这道题的函数图像"})
        assert "与横轴交点 (2, 0)" in json.dumps(after, ensure_ascii=False)


def test_unknown_function_gets_guidance_not_an_error(tmp_path):
    with client_at(tmp_path / "graph.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        result = send(ws, "send_message", "g", {"text": "画出函数图像"})
        assert not [f for f in result if f["event_type"] == "turn_error"]
        assert "画出 y = x^2 - 2x - 3 的图像" in json.dumps(result, ensure_ascii=False)
        assert "SHOW_GRAPH" not in json.dumps(result)
