"""On maths questions the model may call verify_math; the app runs it and returns a receipt."""
import json

import httpx

from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from test_tutor_p0 import client_at, send


def bind(replies, requests):
    def transport(request):
        body = json.loads(request.content)
        requests.append(body)
        if body.get("stream"):
            text = "加法交换律：交换位置，和不变。"
            chunks = [f"data: {json.dumps({'choices': [{'delta': {'content': text}, 'finish_reason': 'stop'}]}, ensure_ascii=False)}",
                      "data: [DONE]"]
            return httpx.Response(200, text="\n\n".join(chunks) + "\n\n", headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=replies.pop(0))

    async def key():
        return "test-key-not-real"

    state = get_product_state()
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(
        base_url="https://example.invalid/v1", model="m", api_key_resolver=key, transport=httpx.MockTransport(transport)))
    state.controller.chat_responder = TutorChatResponder(state.gateway)


def tool_call(expression, answer):
    return {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "verify_math", "arguments": json.dumps({"expression": expression, "answer": answer})}}]},
        "finish_reason": "tool_calls"}], "usage": {"prompt_tokens": 40, "completion_tokens": 10}}


def answer(text):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 60, "completion_tokens": 20}}


def test_model_checks_its_claim_and_corrects_it_before_answering(tmp_path):
    requests = []
    replies = [tool_call("1/2+1/3", "2/5"), answer("先通分：$\\frac{1}{2}+\\frac{1}{3}=\\frac{5}{6}$。")]
    with client_at(tmp_path / "tools.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind(replies, requests)
        frames = send(ws, "send_message", "q", {"text": "计算 1/2+1/3 为什么要通分？"})
        traces = client.get("/api/v2/math-tutor/desktop/diagnostics/turns").json()["turns"]
    assert requests[0]["tools"][0]["function"]["name"] == "verify_math"
    receipt = next(m for m in requests[1]["messages"] if m["role"] == "tool")
    assert json.loads(receipt["content"])["status"] == "refuted"
    final = next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]
    assert final["status"] == "COMPLETED" and final["tool_calls_count"] == 1
    assert "5}{6}" in final["final_text"] and "⚠️" not in final["final_text"]
    assert traces[0]["details"]["tools"] == {"verify_math": 1}


def test_bad_tool_arguments_get_a_rejection_receipt_not_an_error(tmp_path):
    requests = []
    bad = {"choices": [{"message": {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
        "name": "run_python", "arguments": "{}"}}]}, "finish_reason": "tool_calls"}]}
    with client_at(tmp_path / "tools.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind([bad, answer("通分是为了让分母相同。")], requests)
        frames = send(ws, "send_message", "q", {"text": "计算 1/2+1/3 为什么要通分？"})
    receipt = json.loads(next(m for m in requests[1]["messages"] if m["role"] == "tool")["content"])
    assert receipt["status"] == "rejected"
    assert next(f for f in frames if f["event_type"] == "assistant_complete")["payload"]["status"] == "COMPLETED"


def test_everyday_chat_gets_no_tools_and_keeps_streaming(tmp_path):
    requests = []
    with client_at(tmp_path / "tools.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind([], requests)
        send(ws, "send_message", "q", {"text": "加法交换律是什么意思？"})
    assert requests[0].get("stream") is True and "tools" not in requests[0]
