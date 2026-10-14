"""Free chat streams, but only sentences whose formulas pass verify_math are shown."""
import json

import httpx

from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from test_tutor_p0 import client_at, send


def sse(*pieces, finish="stop"):
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': p}, 'finish_reason': None}]}, ensure_ascii=False)}"
             for p in pieces]
    lines.append(f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': finish}]})}")
    lines.append(f"data: {json.dumps({'choices': [], 'usage': {'prompt_tokens': 50, 'completion_tokens': 20}})}")
    lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


def bind(requests, streamed, repaired=None):
    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            return httpx.Response(200, text=sse(*streamed), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"content": repaired}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 60, "completion_tokens": 25}})

    async def key():
        return "test-key-not-real"

    state = get_product_state()
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(
        base_url="https://example.invalid/v1", model="m", api_key_resolver=key, transport=httpx.MockTransport(transport)))
    state.controller.chat_responder = TutorChatResponder(state.gateway)


def previews(frames):
    return [f["payload"]["student_message"] for f in frames
            if f["event_type"] == "assistant_delta" and f["payload"].get("status") == "STREAMING"]


def test_verified_sentences_stream_in_and_the_final_message_replaces_them(tmp_path):
    requests = []
    with client_at(tmp_path / "stream.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(requests, ["加法交换律说的是：", "$2+3=3+2$。", "两个数相加，交换位置", "和不变。"])
        frames = send(ws, "send_message", "s", {"text": "加法交换律是什么意思？"})
    shown = previews(frames)
    assert requests[0]["stream"] is True and len(requests) == 1
    assert shown[0] == "加法交换律说的是：$2+3=3+2$。"
    assert shown[-1].endswith("和不变。") and len(shown) >= 2
    final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert final["status"] == "COMPLETED" and final["input_tokens"] == 50
    assert final["final_text"].startswith("> 本段讲解中的 1 处算式已由本地验证器逐一核对")


def test_a_wrong_formula_is_never_previewed_and_the_repair_replaces_it(tmp_path):
    requests = []
    with client_at(tmp_path / "stream.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(requests, ["先通分。", "$\\frac{1}{2}+\\frac{1}{3}=\\frac{2}{5}$。", "所以结果是五分之二。"],
             repaired="先通分：$\\frac{1}{2}+\\frac{1}{3}=\\frac{5}{6}$。")
        frames = send(ws, "send_message", "s", {"text": "分数怎么相加？"})
    shown = previews(frames)
    assert shown and all("2}{5}" not in text for text in shown)
    assert [r.get("stream") for r in requests] == [True, None]
    final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]["final_text"]
    assert "5}{6}" in final and "⚠️" not in final


def test_a_server_that_rejects_streaming_still_answers(tmp_path):
    requests = []

    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            return httpx.Response(400, json={"error": "stream_options not supported"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "交换位置，和不变。"}, "finish_reason": "stop"}]})

    async def key():
        return "test-key-not-real"

    with client_at(tmp_path / "stream.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(
            base_url="https://example.invalid/v1", model="m", api_key_resolver=key, transport=httpx.MockTransport(transport)))
        state.controller.chat_responder = TutorChatResponder(state.gateway)
        frames = send(ws, "send_message", "s", {"text": "加法交换律是什么意思？"})
    assert [r.get("stream") for r in requests] == [True, None]
    final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert final["status"] == "COMPLETED" and "和不变" in final["final_text"]
