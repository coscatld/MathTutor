"""Named examples and contextual/proactive canvas access over the real WS path."""
import json
import re

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.function_graph import resolve_graph_request
from mathtutor.application.scene import example_scene_from_text
from mathtutor.skills.canvas_drawing import can_offer_drawing
from test_canvas_drawing_skill import ELLIPSE, answer, bind, draw_call, message_frame
from test_tutor_p0 import client_at, send, summary


def scene_in(frames):
    payload = message_frame(frames)
    assert payload["action"] in {"SHOW_GRAPH", "TUTOR_CHAT_FIGURE"}
    text = payload["student_message"]
    block = re.search(r"```mathtutor-scene\n(.*?)\n```", text, re.S)
    return json.loads(block.group(1)), text


@pytest.mark.parametrize("text", ["画一个图展示一下双曲线", "画双曲线", "请画一条标准双曲线吧", "随便画一个双曲线"])
def test_named_hyperbola_draws_offline_without_asking_for_an_equation(tmp_path, text):
    with client_at(tmp_path / "curves.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        frames = send(ws, "send_message", "draw", {"text": text})
        scene, shown = scene_in(frames)
    assert scene["source"] == "deterministic"
    assert scene["title"] == "双曲线示例"
    assert {p["name"]: p["value"] for p in scene["params"]} == {"a": 2, "b": 1}
    assert "x²/4 − y² = 1" in shown and "你没有指定具体方程" in shown
    assert "请告诉我" not in shown and "不能直接作图" not in shown
    assert not any(f["event_type"] in {"turn_error", "assistant_error"} for f in frames)


@pytest.mark.parametrize("name", ["椭圆", "抛物线", "反比例函数", "正弦函数", "余弦函数"])
def test_other_standard_examples_have_valid_local_definitions(name):
    scene = example_scene_from_text("画一个" + name)
    assert scene is not None and scene["title"] == name + "示例"


@pytest.mark.parametrize("text", [
    "画出双曲线 x^2/9-y^2/4=1", "画过点(1,2)的双曲线", "画焦点在y轴上的双曲线",
    "画离心率为2的双曲线", "画双曲线和椭圆", "画双曲线的切线", "双曲线是什么", "画单位圆上的动点",
])
def test_examples_never_replace_given_conditions_or_compound_constructions(text):
    assert example_scene_from_text(text) is None


def test_explicit_equation_stays_unchanged(tmp_path):
    with client_at(tmp_path / "explicit.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        scene, shown = scene_in(send(ws, "send_message", "draw", {"text": "画出双曲线 x^2/9-y^2/4=1"}))
    assert scene["params"] == [] and "示例" not in shown
    assert scene["objects"][0]["label"] == "x²/9-y²/4 = 1"


@pytest.mark.parametrize("reply", ["都可以", "你定", "随便一个", "画吧"])
def test_delegation_uses_the_immediately_preceding_request(reply):
    request = "画一个图展示一下双曲线"
    history = ({"role": "student", "content": request},
               {"role": "tutor", "content": "请告诉我要画哪个函数或图形。", "action": "TUTOR_CHAT"},
               {"role": "student", "content": reply})
    assert resolve_graph_request(reply, history) == request
    assert resolve_graph_request(reply) is None
    assert resolve_graph_request(reply, (*history[:-1], {"role": "student", "content": "你好"}, history[-1])) is None
    delivered = ({**history[0]}, {**history[1], "action": "SHOW_GRAPH"}, history[-1])
    assert resolve_graph_request(reply, delivered) is None


def test_delegation_recovers_a_legacy_clarification_after_restart(tmp_path):
    db = tmp_path / "restart.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "send_message", "init", {"text": "你好"})
        state = get_product_state()

        async def seed_legacy_request():
            # Simulate the persisted exchange from 0.6.1 before this fix.
            from mathtutor.security.scopes import DEV_STUDENT_ID
            await state.conversations.append_message(DEV_STUDENT_ID, "p0", role="student",
                content="画一个图展示一下双曲线", event_key="legacy:student")
            await state.conversations.append_message(DEV_STUDENT_ID, "p0", role="tutor",
                content="请告诉我要画哪个函数或图形。", action="TUTOR_CHAT", event_key="legacy:tutor")

        # Use the TestClient's event loop for the async repository.
        client.portal.call(seed_legacy_request)
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        scene, _ = scene_in(send(ws, "send_message", "continue", {"text": "都可以"}))
        assert scene["title"] == "双曲线示例"


@pytest.mark.parametrize("text", ["双曲线是什么？", "为什么椭圆的焦点在长轴上？"])
def test_model_can_proactively_choose_a_canvas_for_a_math_concept(tmp_path, text):
    requests = []
    with client_at(tmp_path / "proactive.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind([draw_call(ELLIPSE), answer("先看这张椭圆示意图。")], requests)
        scene, _ = scene_in(send(ws, "send_message", "concept", {"text": text}))
    assert scene["source"] == "model"
    assert [t["function"]["name"] for t in requests[0]["tools"]] == ["verify_math", "draw_scene"]
    assert any("不要说不能直接作图" in m["content"] for m in requests[0]["messages"] if m["role"] == "system")


def test_short_followup_keeps_canvas_tools_without_a_new_drawing_keyword(tmp_path):
    requests = []
    with client_at(tmp_path / "followup.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind([answer("可以从椭圆的定义来理解。"), draw_call(ELLIPSE), answer("我们结合这张图继续看。")], requests)
        send(ws, "send_message", "concept", {"text": "椭圆的焦点有什么特点？"})
        scene, _ = scene_in(send(ws, "send_message", "delegate", {"text": "都可以"}))
    assert scene["title"] == "椭圆与焦点"
    assert "tools" in requests[1]


def test_unrelated_chat_does_not_inherit_old_math_tools():
    history = ({"role": "student", "content": "双曲线是什么"}, {"role": "tutor", "content": "…"})
    assert can_offer_drawing("都可以", history)
    assert not can_offer_drawing("你好", history)
    assert can_offer_drawing("为什么", (*history, {"role": "student", "content": "都可以"}))
    assert not can_offer_drawing("都可以", (*history, {"role": "student", "content": "明天天气如何"}))
    assert not can_offer_drawing("都可以")


def test_example_does_not_solve_or_disclose_the_active_problem(tmp_path):
    with client_at(tmp_path / "active.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "x^2-5x+6=0"})
        before = summary(client)
        scene, _ = scene_in(send(ws, "send_message", "draw", {"text": "画一个双曲线"}))
        after = summary(client)
    assert scene["marks"] == []
    assert (before["state"], before["state_version"]) == (after["state"], after["state_version"])
