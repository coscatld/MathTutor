"""Configured prices give per-turn costs; an exhausted budget falls back to templates."""
import httpx

from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.cost_policy import BUDGET_NOTICE
from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from test_tutor_p0 import client_at, send

COST = "/api/v2/math-tutor/desktop/settings/cost"


def bind_model(calls):
    def transport(request):
        calls.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "加法交换律说的是两个数相加，交换位置和不变。"},
                                                      "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})

    async def key():
        return "test-key-not-real"

    state = get_product_state()
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(
        base_url="https://example.invalid/v1", model="m", api_key_resolver=key, transport=httpx.MockTransport(transport)))
    state.controller.chat_responder = TutorChatResponder(state.gateway)


def final(frames):
    return next(f for f in frames if f["event_type"] in {"assistant_complete", "assistant_partial"})["payload"]


def test_without_prices_cost_stays_empty_and_tokens_still_count(tmp_path):
    calls = []
    with client_at(tmp_path / "cost.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind_model(calls)
        payload = final(send(ws, "send_message", "a", {"text": "加法交换律是什么意思？"}))
        assert payload["estimated_cost"] is None
        settings = client.get(COST).json()
        assert settings["today"]["tokens"] == 1500 and settings["today"]["cost"] == 0


def test_priced_turns_record_cost_and_the_budget_blocks_model_calls(tmp_path):
    calls = []
    with client_at(tmp_path / "cost.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind_model(calls)
        assert client.put(COST, json={"input_price_per_mtok": 2.0, "output_price_per_mtok": 8.0,
                                      "daily_budget": 0.006}).status_code == 200
        first = final(send(ws, "send_message", "a", {"text": "加法交换律是什么意思？"}))
        assert first["estimated_cost"] == 0.006 and len(calls) == 1
        assert client.get(COST).json()["over_budget"] is True
        second = final(send(ws, "send_message", "b", {"text": "乘法交换律呢？"}))
        assert len(calls) == 1, "no model call once the budget is used up"
        assert second["status"] == "COMPLETED" and BUDGET_NOTICE in second["final_text"]
        health = client.get("/api/v2/math-tutor/desktop/diagnostics/turns").json()["health"]
        assert health["cost"] == 0.006 and health["budget_blocked_turns"] == 1


def test_invalid_cost_settings_are_rejected(tmp_path):
    with client_at(tmp_path / "cost.db") as client:
        assert client.put(COST, json={"input_price_per_mtok": 1.0}).status_code == 422
        assert client.put(COST, json={"daily_budget": 5.0}).status_code == 422
        assert client.put(COST, json={"daily_token_budget": 10000}).status_code == 200
