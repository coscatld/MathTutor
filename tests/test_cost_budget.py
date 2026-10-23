"""Configured prices give per-turn costs; an exhausted budget falls back to templates."""
import httpx
import pytest

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


@pytest.mark.asyncio
async def test_usage_for_day_survives_a_thousand_zero_rows():
    from datetime import datetime, timezone, timedelta
    from mathtutor.infrastructure.cost_policy import CostPolicyService
    from mathtutor.repositories.turn_trace_repository import TurnTraceRepository
    from mathtutor.security.scopes import DEV_STUDENT_ID

    traces = TurnTraceRepository()
    start, end = CostPolicyService.utc_day_bounds()
    today = start
    yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()

    async def row(turn_id, *, student=DEV_STUDENT_ID, tokens=0, cost=0.0, created=None):
        await traces.record({
            "student_id": student, "conversation_id": "c", "turn_id": turn_id,
            "command": "send_message", "status": "COMPLETED", "finish_reason": "NATURAL_STOP",
            "actions": [], "error_code": "", "latency_ms": 1, "steps_used": 1,
            "input_tokens": tokens, "output_tokens": 0, "usage_estimated": 0,
            "provider": "t", "model": "m", "details": {"cost": cost},
            "created_at": created or f"{today}T12:00:00+00:00",
        })

    await row("expensive", tokens=100, cost=1.0, created=f"{today}T00:00:01+00:00")
    for index in range(1000):
        await row(f"zero-{index}")
    await row("other", student="other-student", tokens=999, cost=9.0)
    await row("yesterday", tokens=999, cost=9.0, created=f"{yesterday}T23:59:59+00:00")

    usage = await traces.usage_for_day(DEV_STUDENT_ID, start=start, end=end)
    assert usage["tokens"] == 100
    assert usage["cost"] == 1.0
    assert usage["turns"] == 1001
    recent = await traces.recent(DEV_STUDENT_ID, limit=1000)
    assert len(recent) == 1000
    policy = CostPolicyService(None)
    policy.update({"input_price_per_mtok": 1.0, "output_price_per_mtok": 1.0, "daily_budget": 1.0})
    assert policy.over_budget(policy.usage_from_aggregate(usage, date=start))
    window = policy.usage_today(recent)
    assert window["cost"] == 0.0

    token_policy = CostPolicyService(None)
    token_policy.update({"daily_token_budget": 100})
    assert token_policy.over_budget(token_policy.usage_from_aggregate(usage, date=start))


@pytest.mark.asyncio
async def test_sqlite_usage_for_day_matches_memory(tmp_path):
    from mathtutor.infrastructure.cost_policy import CostPolicyService
    from mathtutor.infrastructure.db import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db
    from mathtutor.repositories.sqlite_runtime import ensure_student
    from mathtutor.repositories.turn_trace_repository import TurnTraceRepository

    db_file = tmp_path / "usage.db"
    upgrade_db(str(db_file))
    engine = create_db_engine(db_file)
    traces = TurnTraceRepository(engine)
    start, end = CostPolicyService.utc_day_bounds()
    async with traces.uow.transaction() as conn:
        await ensure_student(conn, student_id="student-a")
    await traces.record({
        "student_id": "student-a", "conversation_id": "c", "turn_id": "expensive",
        "command": "send_message", "status": "COMPLETED", "finish_reason": "NATURAL_STOP",
        "actions": [], "error_code": "", "latency_ms": 1, "steps_used": 1,
        "input_tokens": 40, "output_tokens": 10, "usage_estimated": 0,
        "provider": "t", "model": "m", "details": {"cost": 0.5},
        "created_at": f"{start}T01:00:00+00:00",
    })
    for index in range(1000):
        await traces.record({
            "student_id": "student-a", "conversation_id": "c", "turn_id": f"z{index}",
            "command": "send_message", "status": "COMPLETED", "finish_reason": "NATURAL_STOP",
            "actions": [], "error_code": "", "latency_ms": 1, "steps_used": 1,
            "input_tokens": 0, "output_tokens": 0, "usage_estimated": 0,
            "provider": "t", "model": "m", "details": {"cost": 0},
            "created_at": f"{start}T12:00:00+00:00",
        })
    try:
        usage = await traces.usage_for_day("student-a", start=start, end=end)
        assert usage["tokens"] == 50
        assert usage["cost"] == 0.5
        assert usage["turns"] == 1001
        other = await traces.usage_for_day("student-b", start=start, end=end)
        assert other == {"tokens": 0, "cost": 0.0, "turns": 0}
    finally:
        await engine.dispose()


def test_budget_stays_blocked_after_a_thousand_zero_traces(tmp_path):
    import asyncio
    from mathtutor.security.scopes import DEV_STUDENT_ID

    calls = []
    with client_at(tmp_path / "cost.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        bind_model(calls)
        assert client.put(COST, json={"input_price_per_mtok": 2.0, "output_price_per_mtok": 8.0,
                                      "daily_budget": 0.006}).status_code == 200
        first = final(send(ws, "send_message", "a", {"text": "加法交换律是什么意思？"}))
        assert first["estimated_cost"] == 0.006 and len(calls) == 1
        traces = get_product_state().turn_traces

        async def flood():
            for index in range(1000):
                await traces.record({
                    "student_id": DEV_STUDENT_ID, "conversation_id": "c", "turn_id": f"z{index}",
                    "command": "send_message", "status": "COMPLETED", "finish_reason": "NATURAL_STOP",
                    "actions": [], "error_code": "", "latency_ms": 1, "steps_used": 1,
                    "input_tokens": 0, "output_tokens": 0, "usage_estimated": 0,
                    "provider": "t", "model": "m", "details": {"cost": 0},
                })
        asyncio.run(flood())
        second = final(send(ws, "send_message", "b", {"text": "乘法交换律呢？"}))
        assert len(calls) == 1
        assert second["status"] == "COMPLETED" and BUDGET_NOTICE in second["final_text"]
        assert client.get(COST).json()["over_budget"] is True
