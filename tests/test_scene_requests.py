"""Scene v2 requests: deterministic 「画出 …」, model-proposed definitions, WebSocket."""
import asyncio
import json
import re

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.function_graph import is_graph_request
from mathtutor.application.scene import MODEL_NOTE, author_scene, parse_definition, scene_from_text, SceneError
from mathtutor.infrastructure.generative_gateway import (
    CompletionResult, GenerativeModelGateway, ModelRole, model_calls_blocked)
from test_tutor_p0 import client_at, send


def kinds(scene):
    return [o["type"] for o in scene["objects"]]


def params(scene):
    return [p["name"] for p in scene["params"]]


@pytest.mark.parametrize("text, types, names", [
    ("画出 x^2/4+y^2/3=1", ["implicit"], []),
    ("画出 x^2/4+y^2/3=1 和 y=kx+1", ["implicit", "function"], ["k"]),
    ("画出圆 (x-1)^2+(y-2)^2=4", ["implicit"], []),
    ("画出 y>x^2-1 的区域", ["region"], []),
    ("画出 x^2+y^2<=4 与 y>=x", ["region", "region"], []),
    ("画出 r=2(1+cos θ)", ["parametric"], []),
    ("画出 y=a*sin(bx)", ["function"], ["a", "b"]),
    ("画出 y=x^2；y=x+2、x^2+y^2=9", ["function", "function", "implicit"], []),
    ("画出 \\frac{x^2}{4}-y^2=1，y=\\sqrt{x}", ["implicit", "function"], []),
])
def test_deterministic_requests(text, types, names):
    scene = scene_from_text(text)
    assert scene is not None and kinds(scene) == types and params(scene) == names
    assert scene["source"] == "deterministic"
    for param in scene["params"]:
        assert (param["min"], param["max"], param["step"], param["value"]) == (-5, 5, 0.1, 1)


def test_region_relation_and_marks():
    scene = scene_from_text("画出 y>x^2-1 的区域")
    assert scene["objects"][0]["relation"] == "gt" and scene["objects"][0]["label"] == "y ＞ x²-1"
    assert "交点 (2, 4)" in [m["label"] for m in scene_from_text("画出 y=x^2 和 y=x+2")["marks"]]
    assert scene_from_text("画出 y=x^2 和 y=x+2", reveal=False)["marks"] == []


@pytest.mark.parametrize("text", [
    "画出 y=x^2-2x-3 的图像", "画出函数图像", "画出这道题的函数图像", "x^2/4+y^2/3=1", "画出 y=open(x)",
    "画出 y=kx+1（k为参数）", "画出 y=a+b+c+d+f*x", "画出 y=s*x",
])
def test_not_deterministic(text):
    assert scene_from_text(text) is None


def test_graph_request_detection():
    assert all(map(is_graph_request, ["画出 x^2/4+y^2/3=1", "画出 r=2(1+cos θ)", "演示椭圆上的动点到焦点的距离",
                                      "用数形结合看 x^2+y^2=1", "点 P 在圆上运动时", "可视化 y=sin(x)"]))
    assert not any(map(is_graph_request, ["演示一下怎么解 2x+3=7", "小明运动了 3 小时", "x^2/4+y^2/3=1 求离心率",
                                          "给我提示", "2x+3=7"]))


VALID = json.dumps({"title": "动点 P", "params": [{"name": "t", "min": 0, "max": 6.28, "step": 0.01, "value": 1, "animate": True}],
                    "objects": [{"id": "C", "type": "implicit", "equation": "x^2+y^2=1"},
                                {"id": "P", "type": "point", "x": "cos(t)", "y": "sin(t)", "trace": True}],
                    "readouts": [{"label": "P 的横坐标", "expr": "P.x"}], "marks": [{"x": 9, "y": 9, "label": "答案"}]})


class FakeProvider:
    provider_id, model = "fake", "fake-model"

    def __init__(self, text, finish="stop"):
        self.text, self.finish, self.calls = text, finish, []

    async def complete(self, messages, *, temperature=0.4, max_tokens=None, max_retries=0, **kwargs):
        self.calls.append(messages)
        return CompletionResult(text=self.text, provider_id="fake", model="fake-model", finish_reason=self.finish)


def gateway_with(provider):
    gateway = GenerativeModelGateway()
    gateway.register_provider(ModelRole.PRACTICE_GENERATOR, provider)
    return gateway


def test_model_definition_is_compiled_and_labelled():
    provider = FakeProvider("```json\n" + VALID + "\n```")
    scene = asyncio.run(author_scene(gateway_with(provider), "演示单位圆上的动点"))
    assert scene["source"] == "model" and scene["note"] == MODEL_NOTE and scene["marks"] == []
    assert kinds(scene) == ["implicit", "point"] and len(provider.calls) == 1
    system = provider.calls[0][0]["content"]
    assert "只输出一个 JSON" in system and "不要计算交点" in system


@pytest.mark.parametrize("text", [
    "不是 JSON", '{"error":"unsupported"}', "[1,2]",
    VALID.replace("cos(t)", "__import__('os').system('ls')"),
    VALID.replace("cos(t)", "open(t)"),
    VALID.replace('"x^2+y^2=1"', '"eval(x)=1"'),
])
def test_bad_model_output_gives_none(text):
    assert asyncio.run(author_scene(gateway_with(FakeProvider(text)), "演示单位圆上的动点")) is None


def test_truncated_or_blocked_model_gives_none():
    assert asyncio.run(author_scene(gateway_with(FakeProvider(VALID, finish="length")), "演示动点")) is None
    provider = FakeProvider(VALID)

    async def blocked():
        token = model_calls_blocked.set(True)
        try:
            return await author_scene(gateway_with(provider), "演示动点")
        finally:
            model_calls_blocked.reset(token)
    assert asyncio.run(blocked()) is None and provider.calls == []
    assert asyncio.run(author_scene(GenerativeModelGateway(), "演示动点")) is None


def test_parse_definition_drops_model_marks():
    assert "marks" not in parse_definition(VALID)
    with pytest.raises(SceneError):
        parse_definition("")


def message(frames):
    return next(f["payload"]["student_message"] for f in frames if f["payload"].get("action") == "SHOW_GRAPH")


def test_websocket_deterministic_scene(tmp_path):
    with client_at(tmp_path / "scene.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        frames = send(ws, "send_message", "s", {"text": "画出 x^2/4+y^2/3=1 和 y=kx+1"})
        text = message(frames)
        assert "```mathtutor-scene\n" in text
        scene = json.loads(re.search(r"```mathtutor-scene\n(.*?)\n```", text, re.S).group(1))
        assert kinds(scene) == ["implicit", "function"] and params(scene) == ["k"]
        assert not [f for f in frames if f["event_type"] in {"turn_error", "assistant_error"}]
        history = client.get("/api/v2/math-tutor/sessions/p0").json()
        assert history


def test_websocket_model_scene_and_fallback(tmp_path):
    with client_at(tmp_path / "scene.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        provider = FakeProvider(VALID)
        get_product_state().controller.scene_gateway = gateway_with(provider)
        frames = send(ws, "send_message", "m", {"text": "演示单位圆上的动点 P"})
        assert MODEL_NOTE in message(frames) and "mathtutor-scene" in message(frames)
        assert any(f["event_type"] == "assistant_complete" for f in frames)
        provider.text = VALID.replace("cos(t)", "__import__('os')")
        frames = send(ws, "send_message", "bad", {"text": "演示单位圆上的另一个动点 Q"})
        dumped = json.dumps(frames, ensure_ascii=False)
        assert "SHOW_GRAPH" not in dumped and "画出 y = x^2 - 2x - 3 的图像" in dumped
        assert any(f["event_type"] == "assistant_complete" for f in frames)


def test_open_problem_scene_has_no_marks(tmp_path):
    with client_at(tmp_path / "scene.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "x^2-5x+6=0"})
        frames = send(ws, "send_message", "s", {"text": "画出 y=x^2-5x+6 和 y=0"})
        scene = json.loads(re.search(r"```mathtutor-scene\n(.*?)\n```", message(frames), re.S).group(1))
        assert scene["marks"] == [] and "暂不标出" in scene["note"]
        problem = send(ws, "send_message", "g", {"text": "画出这道题的函数图像"})
        assert "mathtutor-graph" in message(problem)
