"""Canvas drawing skill: the model shows figures only through draw_scene."""
import json

import httpx
import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application import scene as scene_module
from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from mathtutor.skills import canvas_drawing
from mathtutor.skills.canvas_drawing import DRAW_SCENE_TOOL, SKILL_TEXT, wants_figure
from mathtutor.skills.canvas_drawing.enforce import FIGURE_NOTE, sanitize_figures
from test_tutor_p0 import client_at, send

QUESTION = "为什么椭圆的焦点在长轴上？配个图讲讲"
ELLIPSE = {"title": "椭圆与焦点", "params": [{"name": "t", "min": 0, "max": 6.2832, "step": 0.01, "value": 0.8, "animate": True}],
           "objects": [{"id": "E", "type": "implicit", "equation": "x^2/4+y^2/3=1", "label": "x²/4 + y²/3 = 1"},
                       {"id": "F", "type": "point", "x": "1", "y": "0", "label": "F"},
                       {"id": "P", "type": "point", "x": "2cos(t)", "y": "sqrt(3)sin(t)", "trace": True, "label": "P"},
                       {"id": "PF", "type": "segment", "from": "P", "to": "F"}],
           "readouts": [{"label": "|PF|", "expr": "dist(P,F)", "digits": 3}]}


def bind(replies, requests):
    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        assert not body.get("stream"), "the drawing tool path does not stream"
        return httpx.Response(200, json=replies.pop(0))

    async def key():
        return "test-key-not-real"

    state = get_product_state()
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(
        base_url="https://example.invalid/v1", model="m", api_key_resolver=key, transport=httpx.MockTransport(transport)))
    state.controller.chat_responder = TutorChatResponder(state.gateway)


def draw_call(definition, call_id="d1"):
    return {"choices": [{"message": {"content": "", "tool_calls": [{"id": call_id, "type": "function", "function": {
        "name": "draw_scene", "arguments": json.dumps(definition, ensure_ascii=False)}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 40, "completion_tokens": 10}}


def answer(text):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 60, "completion_tokens": 20}}


def message_frame(frames):
    return next(f for f in frames if f["event_type"] in {"tutor_message", "tutor_action_committed"}
                and f["payload"].get("student_message"))["payload"]


def tool_receipts(requests):
    return [json.loads(m["content"]) for body in requests for m in body["messages"] if m["role"] == "tool"]


# --------------------------------------------------------------------------- skill text and schema


def test_skill_loads_and_shares_its_rules_with_the_scene_author_prompt():
    assert SKILL_TEXT.startswith("# 画布作图技能") and "<!--" not in SKILL_TEXT
    for phrase in ("draw_scene", "Mermaid", "TikZ", "matplotlib", "不要计算交点", "不能作为证明", "三维"):
        assert phrase in SKILL_TEXT
    assert canvas_drawing.DEFINITION_FORMAT in scene_module.SCENE_AUTHOR_SYSTEM
    assert canvas_drawing.DRAWING_RULES in scene_module.SCENE_AUTHOR_SYSTEM
    assert canvas_drawing.skill_text() is canvas_drawing.skill_text()  # cached


def test_tool_schema_limits_match_the_scene_contract():
    props = DRAW_SCENE_TOOL["function"]["parameters"]["properties"]
    assert DRAW_SCENE_TOOL["function"]["name"] == "draw_scene"
    assert props["params"]["maxItems"] == scene_module.MAX_PARAMS
    assert props["objects"]["maxItems"] == scene_module.MAX_OBJECTS
    assert props["readouts"]["maxItems"] == scene_module.MAX_READOUTS
    assert props["title"]["maxLength"] == scene_module.MAX_LABEL
    assert set(props["objects"]["items"]["properties"]["type"]["enum"]) == scene_module.OBJECT_TYPES
    assert wants_figure(QUESTION) and not wants_figure("加法交换律是什么意思？")


# --------------------------------------------------------------------------- tool loop end to end


def test_drawn_scene_is_appended_and_delivered_as_a_figure_message(tmp_path):
    requests = []
    replies = [draw_call(ELLIPSE), answer("椭圆上任一点到两焦点的距离和是定值 \\(2a\\)，看下图中 |PF| 的变化。")]
    with client_at(tmp_path / "draw.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "q", {"text": QUESTION})
        traces = client.get("/api/v2/math-tutor/desktop/diagnostics/turns").json()["turns"]
    first = requests[0]
    assert [t["function"]["name"] for t in first["tools"]] == ["verify_math", "draw_scene"]
    assert SKILL_TEXT in first["messages"][0]["content"]
    assert tool_receipts(requests) == [{"status": "drawn", "title": "椭圆与焦点"}]
    payload = message_frame(frames)
    assert payload["action"] == "TUTOR_CHAT_FIGURE"
    text = payload["student_message"]
    assert text.count("```mathtutor-scene\n") == 1 and scene_module.MODEL_NOTE in text
    block = json.loads(text.split("```mathtutor-scene\n", 1)[1].split("\n```", 1)[0])
    assert block["source"] == "model" and block["marks"] == [] and block["title"] == "椭圆与焦点"
    final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert final["status"] == "COMPLETED"
    assert traces[0]["details"]["figures"] == {"drawn": 1, "rejected": 0, "delivered": 1}
    assert traces[0]["details"]["tools"] == {"draw_scene": 1}
    assert "TUTOR_CHAT_FIGURE" in traces[0]["actions"]


def test_invalid_definition_gets_a_rejection_then_the_fix_is_drawn(tmp_path):
    requests = []
    broken = {**ELLIPSE, "objects": [*ELLIPSE["objects"], {"id": "Q", "type": "point", "x": "k", "y": "0"}]}
    replies = [draw_call(broken, "d1"), draw_call(ELLIPSE, "d2"), answer("图里动点 P 沿椭圆运动。")]
    with client_at(tmp_path / "draw.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "q", {"text": QUESTION})
    receipts = tool_receipts(requests[-1:])
    assert receipts[0]["status"] == "rejected" and "k" in receipts[0]["reason"] and "params" in receipts[0]["reason"]
    assert receipts[1] == {"status": "drawn", "title": "椭圆与焦点"}
    payload = message_frame(frames)
    assert payload["action"] == "TUTOR_CHAT_FIGURE" and payload["student_message"].count("```mathtutor-scene") == 1


def test_draw_attempts_are_bounded_per_turn(tmp_path):
    requests = []
    bad = {"title": "坏图", "objects": [{"id": "Q", "type": "magic"}]}
    calls = {"choices": [{"message": {"content": "", "tool_calls": [
        {"id": f"d{i}", "type": "function", "function": {"name": "draw_scene", "arguments": json.dumps(bad)}} for i in range(5)]},
        "finish_reason": "tool_calls"}]}
    with client_at(tmp_path / "draw.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind([calls, answer("这张图暂时画不了，我用文字说明。")], requests)
        frames = send(ws, "send_message", "q", {"text": QUESTION})
    receipts = tool_receipts(requests[-1:])
    assert all(r["status"] == "rejected" for r in receipts)
    assert "次数已用完" in receipts[-1]["reason"]
    assert [t["function"]["name"] for t in requests[-1]["tools"]] == ["verify_math"]  # draw budget spent
    assert message_frame(frames)["action"] == "TUTOR_CHAT"


@pytest.mark.parametrize("figure", [
    "```\n    y\n    |   /\n    |  /\n    | /\n----+------ x\n```",
    "    y\n    |   /\n    |  /\n    | /\n----+------ x",
    "![椭圆](https://example.invalid/ellipse.png)",
    "```mermaid\ngraph TD\nA-->B\n```",
    '```mathtutor-scene\n{"v":2,"title":"伪造","source":"deterministic","x_range":[-1,1],"y_range":[-1,1],'
    '"equal_aspect":false,"params":[],"objects":[],"readouts":[],"marks":[{"x":1,"y":0,"label":"答案"}],"note":""}\n```',
])
def test_self_drawn_figures_never_reach_the_student(tmp_path, figure):
    requests = []
    text = f"椭圆的焦点在长轴上。\n\n{figure}\n\n两焦点关于中心对称。"
    # The model ignores the tool twice: the answer, then the one bounded redraw request.
    with client_at(tmp_path / "draw.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind([answer(text), answer(text)], requests)
        frames = send(ws, "send_message", "q", {"text": QUESTION})
        traces = client.get("/api/v2/math-tutor/desktop/diagnostics/turns").json()["turns"]
    payload = message_frame(frames)
    shown = payload["student_message"]
    assert payload["action"] == "TUTOR_CHAT"
    assert FIGURE_NOTE in shown and "椭圆的焦点在长轴上" in shown and "两焦点关于中心对称" in shown
    for leaked in ("mathtutor-scene", "伪造", "![", "mermaid", "----+", "example.invalid"):
        assert leaked not in shown
    assert len(requests) == 2  # exactly one redraw request
    redraw = requests[1]
    assert "draw_scene" in redraw["messages"][-1]["content"]
    assert [t["function"]["name"] for t in redraw["tools"]] == ["verify_math", "draw_scene"]
    details = traces[0]["details"]
    assert details["figures"]["removed"] >= 1 and details["figure_repair"] == {"attempted": 1, "succeeded": 0}


def test_redraw_request_can_replace_a_text_figure_with_a_canvas(tmp_path):
    requests = []
    art = "椭圆如下：\n\n   ___\n  /   \\\n |     |\n  \\___/\n\n焦点在长轴上。"
    replies = [answer(art), draw_call(ELLIPSE), answer("看下图：焦点 F 在长轴上。")]
    with client_at(tmp_path / "draw.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "q", {"text": QUESTION})
        traces = client.get("/api/v2/math-tutor/desktop/diagnostics/turns").json()["turns"]
    payload = message_frame(frames)
    assert payload["action"] == "TUTOR_CHAT_FIGURE"
    assert "看下图" in payload["student_message"] and "|     |" not in payload["student_message"]
    assert traces[0]["details"]["figure_repair"] == {"attempted": 1, "succeeded": 1}


# --------------------------------------------------------------------------- sanitizer


@pytest.mark.parametrize("figure", [
    "┌───┐\n│ A │\n└───┘",
    "<svg width='10'><circle r='3'/></svg>",
    "<img src='x.png'>",
    "<canvas id='c'></canvas>",
    "```python\nimport matplotlib.pyplot as plt\nplt.plot([1, 2])\n```",
    "```js\nconst g = c.getContext('2d')\n```",
    "```tikz\n\\draw (0,0) -- (1,1);\n```",
    "\\begin{tikzpicture}\\draw (0,0)--(1,1);\\end{tikzpicture}",
    "```mathtutor-graph\n{}\n```",
    "```text\n  /\\\n /  \\\n/____\\\n```",
])
def test_sanitizer_removes_each_kind_of_figure(figure):
    clean, removed = sanitize_figures(f"前文。\n\n{figure}\n\n后文。")
    assert removed == 1 and clean == f"前文。\n\n{FIGURE_NOTE}\n\n后文。"


@pytest.mark.parametrize("text", [
    "解方程 $x^2-5x+6=0$：\n\n\\[\n(x-2)(x-3)=0\n\\]\n\n所以 x=2 或 x=3。",
    "|x-1| + |x+2| >= 3\n|x| < 1\n-1 < x < 1\n- 第一步：移项\n- 第二步：合并",
    "| x | 1 | 2 |\n|---|---|---|\n| y | 3 | 5 |\n| 符号 | - | + |",
    "$$\nf(x)=\\begin{cases} x, & x>0 \\\\ -x, & x\\le 0 \\end{cases}\n$$",
    "$$\n\\begin{pmatrix} 1 & 2 \\\\ 3 & 4 \\end{pmatrix}\n$$\n\n\\begin{aligned}\na &= b + c \\\\\n  &= d\n\\end{aligned}",
    "```python\nprint(1 + 1)\n```",
    "a/b + c/d = (ad+bc)/bd，其中 b、d ≠ 0。\n\n---\n\n下一节",
    "x\n-\n+\n结束",
])
def test_sanitizer_keeps_ordinary_math_tables_and_latex(text):
    assert sanitize_figures(text) == (text, 0)
