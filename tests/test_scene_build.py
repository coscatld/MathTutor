"""Scene v2 definitions: validation, ranges, marks and the fenced block."""
import json
import re

import pytest

from mathtutor.application.function_graph import graph_for_function, summarize_graph_blocks
from mathtutor.application.scene import MODEL_NOTE, SceneError, build_scene, render_scene
from mathtutor.application.scene_expr import evaluate

ELLIPSE = {
    "title": "椭圆上的动点到焦点的距离",
    "params": [{"name": "t", "min": 0, "max": "2pi", "step": 0.01, "value": 0.8, "animate": True}],
    "objects": [
        {"id": "E", "type": "implicit", "equation": "x^2/4+y^2/3=1", "label": "x²/4 + y²/3 = 1"},
        {"id": "F", "type": "point", "x": "1", "y": "0", "label": "F"},
        {"id": "P", "type": "point", "x": "2cos(t)", "y": "sqrt(3)sin(t)", "trace": True},
        {"id": "PF", "type": "segment", "from": "P", "to": "F"},
    ],
    "readouts": [{"label": "|PF|", "expr": "dist(P,F)"}],
}


def scene_of(text):
    return json.loads(re.search(r"```mathtutor-scene\n(.*?)\n```", text, re.S).group(1))


def test_ellipse_scene_matches_the_contract():
    scene = build_scene(ELLIPSE, source="deterministic")
    assert scene["v"] == 2 and scene["source"] == "deterministic" and scene["equal_aspect"] is True
    assert scene["params"][0] == {"name": "t", "min": 0, "max": pytest.approx(6.283185), "step": 0.01, "value": 0.8,
                                  "animate": True, "label": "t"}
    assert [o["type"] for o in scene["objects"]] == ["implicit", "point", "point", "segment"]
    assert scene["objects"][2]["trace"] is True
    assert scene["readouts"][0]["digits"] == 3
    assert scene["marks"] == []  # parameters present: no static marks
    lo, hi = scene["x_range"]
    assert -2.6 < lo < -2 and 2 < hi < 2.6
    points = {"P": (evaluate(scene["objects"][2]["x"], {"t": 0}), evaluate(scene["objects"][2]["y"], {"t": 0})),
              "F": (1.0, 0.0)}
    assert evaluate(scene["readouts"][0]["expr"], {"t": 0}, points) == pytest.approx(1)


def test_parameter_free_scene_marks_intersections_unless_hidden():
    definition = {"objects": [{"id": "f", "type": "function", "expr": "y=2x+1"}, {"id": "g", "type": "function", "expr": "-x+4"}]}
    labels = [m["label"] for m in build_scene(definition)["marks"]]
    assert labels[0] == "交点 (1, 3)" and "与 x 轴交点 (4, 0)" in labels
    hidden = build_scene(definition, reveal=False)
    assert hidden["marks"] == [] and "暂不标出" in hidden["note"]
    assert build_scene(definition, source="model")["marks"] == []


def test_implicit_axis_intercepts():
    scene = build_scene({"objects": [{"id": "C", "type": "implicit", "equation": "x^2+y^2=4"}]})
    assert {m["label"] for m in scene["marks"]} == {"与 x 轴交点 (-2, 0)", "与 x 轴交点 (2, 0)", "与 y 轴交点 (0, -2)", "与 y 轴交点 (0, 2)"}


def test_region_relation_and_polar_curve():
    scene = build_scene({"objects": [{"id": "R", "type": "region", "inequality": "x^2+y^2<=4"},
                                     {"id": "Q", "type": "parametric", "r": "2(1+cos θ)"}]})
    region, polar = scene["objects"]
    assert region["relation"] == "le"
    assert polar["s_range"][0] == 0 and polar["x"]["a"][1] == {"k": "fn", "f": "cos", "a": [{"k": "var", "n": "s"}]}
    assert evaluate(polar["x"], {"s": 0}) == pytest.approx(4)


@pytest.mark.parametrize("change, message", [
    ({"objects": [{"id": "P", "type": "point", "x": "Q.x", "y": "0"}, {"id": "Q", "type": "point", "x": "1", "y": "1"}]}, "点 Q"),
    ({"objects": [{"id": "s1", "type": "segment", "from": "A", "to": "B"}]}, "from"),
    ({"objects": [{"id": "A", "type": "point", "x": "0", "y": "0"}, {"id": "L", "type": "tangent", "of": "A", "at": "1"}]}, "函数"),
    ({"objects": [{"id": "A", "type": "point", "x": "0", "y": "0"}, {"id": "T", "type": "polygon", "points": ["A", "A"]}]}, "至少 3"),
    ({"objects": [{"id": "f", "type": "function", "expr": "k*x"}]}, "未定义的字母 k"),
    ({"objects": [{"id": "f", "type": "function", "expr": "x+y"}]}, "未定义的字母 y"),
    ({"objects": [{"id": "P", "type": "point", "x": "x", "y": "0"}]}, "未定义的字母 x"),
    ({"objects": [{"id": "C", "type": "parametric", "x": "cos(x)", "y": "sin(s)"}]}, "未定义的字母 x"),
    ({"objects": [{"id": "E", "type": "implicit", "equation": "x<1"}]}, "关系符号"),
    ({"objects": [{"id": "a-b", "type": "implicit", "equation": "x=1"}]}, "id"),
    ({"objects": [{"id": "E", "type": "implicit", "equation": "x=1"}, {"id": "E", "type": "implicit", "equation": "y=1"}]}, "重复"),
    ({"objects": [{"id": "E", "type": "script", "equation": "x=1"}]}, "不支持"),
    ({"objects": [{"id": f"O{i}", "type": "implicit", "equation": "x=1"} for i in range(41)]}, "最多"),
    ({"params": [{"name": n} for n in "abcdf"], "objects": [{"id": "E", "type": "implicit", "equation": "x=1"}]}, "最多"),
    ({"params": [{"name": "x"}], "objects": [{"id": "E", "type": "implicit", "equation": "x=1"}]}, "单个字母"),
    ({"params": [{"name": "k", "min": 1, "max": 0}], "objects": [{"id": "E", "type": "implicit", "equation": "x=1"}]}, "下界"),
    ({"params": [{"name": "k", "value": 9}], "objects": [{"id": "E", "type": "implicit", "equation": "x=1"}]}, "初值"),
    ({"params": [{"name": "k", "step": 0}], "objects": [{"id": "E", "type": "implicit", "equation": "x=1"}]}, "步长"),
    ({"objects": [{"id": "E", "type": "implicit", "equation": "x=1"}], "readouts": [{"expr": "1"}] * 9}, "读数最多"),
    ({"objects": [{"id": "E", "type": "implicit", "equation": "x=1"}], "x_range": [1, 1]}, "下界"),
    ({"objects": [{"id": "E", "type": "implicit", "equation": "open(x)=1"}]}, "看不懂"),
])
def test_validation_errors(change, message):
    with pytest.raises(SceneError, match=message):
        build_scene(change)


def test_points_may_use_earlier_points_and_other_objects_any_point():
    scene = build_scene({"params": [{"name": "t", "min": 0, "max": 1, "value": 0.5}], "objects": [
        {"id": "S", "type": "segment", "from": "A", "to": "M"},
        {"id": "A", "type": "point", "x": "0", "y": "0"},
        {"id": "B", "type": "point", "x": "4", "y": "2"},
        {"id": "M", "type": "point", "x": "mid_x(A,B)", "y": "mid_y(A,B)+t"},
        {"id": "O", "type": "circle", "center": "A", "radius": "dist(A,M)"},
        {"id": "W", "type": "text", "x": "M.x", "y": "M.y", "text": "中点"},
    ], "readouts": [{"label": "∠", "expr": "angle(A,M,B)", "digits": 10}]})
    assert scene["equal_aspect"] is True and scene["readouts"][0]["digits"] == 10


def test_model_scene_is_labelled_and_text_is_sanitized():
    scene = build_scene({"title": "![x](http://e)`<b>`" + "长" * 80, "marks": [{"x": 1, "y": 2, "label": "答案"}],
                         "objects": [{"id": "E", "type": "implicit", "equation": "x=1", "label": "a*b<c"}]}, source="model")
    assert scene["note"] == MODEL_NOTE and scene["marks"] == []
    assert not re.search(r"[`\[\]<>]", scene["title"]) and len(scene["title"]) <= 60
    assert scene["objects"][0]["label"] == "a·b＜c"
    text = render_scene(scene)
    assert text.startswith("**数形结合**：") and text.endswith(MODEL_NOTE)
    assert scene_of(text) == scene


def test_placeholder_replaces_scene_and_graph_blocks_before_model_context():
    scene = build_scene({"title": "单位圆", "objects": [{"id": "C", "type": "implicit", "equation": "x^2+y^2=1"}]})
    text = "前文\n" + render_scene(scene) + "\n" + graph_for_function("2x+1")
    summary = summarize_graph_blocks(text)
    assert "[已展示数形结合图：单位圆]" in summary and "[已展示函数图像：y = 2x + 1]" in summary
    assert "mathtutor-scene" not in summary and '"k"' not in summary
