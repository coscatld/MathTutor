"""Real SDK dispatch and authenticated WS integration; no network or model fees."""
import asyncio
import json
import math

import httpx
import pytest
from pydantic import BaseModel, Field, ValidationError

from mathtutor.extensions import ExecutionContext, ExtensionManifest, ExtensionRegistry, StrictArguments
from mathtutor.extensions.builtin import default_registry
from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
from test_tutor_p0 import client_at, send, count


CTX = ExecutionContext(owner_id="alice", conversation_id="lesson")


def manifest(id="example.echo", kind="tool"):
    return ExtensionManifest(id=id, version="1.0.0", name="示例", description="受控示例", kind=kind)


class Arguments(StrictArguments):
    value: int = Field(ge=0, le=10)


async def echo(args, context):
    return {"value": args.value}


def registry_for(handler=echo, **kwargs):
    registry = ExtensionRegistry()
    registry.register_tool(manifest(), name="ext_echo", input_model=Arguments, handler=handler, **kwargs)
    return registry


@pytest.mark.parametrize("raw", [
    {"api_version": "v2"}, {"kind": "shell"}, {"id": "../escape"}, {"version": "latest"},
    {"command": "python module.py"}, {"permissions": ["all"]},
])
def test_manifest_is_versioned_and_not_an_executable_install_spec(raw):
    with pytest.raises(ValidationError):
        ExtensionManifest.model_validate({**manifest().model_dump(), **raw})


def test_registry_rejects_names_duplicates_unbounded_schemas_and_sync_handlers():
    registry = registry_for()
    with pytest.raises(ValueError):
        registry.register_tool(manifest(), name="ext_other", input_model=Arguments, handler=echo)
    with pytest.raises(ValueError):
        registry.register_tool(manifest("example.other"), name="ext_echo", input_model=Arguments, handler=echo)
    for name in ("verify_math", "draw_scene", "shell", "ext_../read"):
        with pytest.raises(ValueError):
            registry.register_tool(manifest("example.other"), name=name, input_model=Arguments, handler=echo)
    class OpenArguments(BaseModel):
        value: int
    with pytest.raises(ValueError):
        registry.register_tool(manifest("example.open"), name="ext_open", input_model=OpenArguments, handler=echo)
    with pytest.raises(ValueError):
        registry.register_tool(manifest("example.sync"), name="ext_sync", input_model=Arguments, handler=lambda a, c: {})


@pytest.mark.asyncio
@pytest.mark.parametrize("args", [{"value": "2"}, {"value": True}, {"value": 12}, {"value": 2, "owner_id": "bob"}, None])
async def test_input_strict_and_no_owner_smuggling(args):
    receipt = await registry_for().bind(CTX).execute("ext_echo", args)
    assert receipt["code"] == "INVALID_ARGUMENTS"


@pytest.mark.asyncio
@pytest.mark.parametrize("value,code", [(math.nan, "INVALID_RESULT"), ((1, 2), "INVALID_RESULT"),
    ({1: "not-a-string-key"}, "INVALID_RESULT"), ("x" * 5000, "RESULT_TOO_LARGE")])
async def test_output_json_and_byte_limits(value, code):
    async def bad(args, context): return value
    receipt = await registry_for(bad).bind(CTX).execute("ext_echo", {"value": 2})
    assert receipt["code"] == code and "result" not in receipt


@pytest.mark.asyncio
async def test_timeout_cancellation_unknown_tools_and_exception_redaction():
    async def slow(args, context):
        await asyncio.sleep(2)
    executor = registry_for(slow, timeout_seconds=.01).bind(CTX)
    assert (await executor.execute("ext_echo", {"value": 2}))["code"] == "TOOL_TIMEOUT"
    assert (await executor.execute("ext_unknown", {}))["code"] == "EXTENSION_UNAVAILABLE"
    async def throws(args, context): raise RuntimeError("/private/secret-key.txt")
    receipt = await registry_for(throws).bind(CTX).execute("ext_echo", {"value": 1})
    assert receipt["code"] == "TOOL_FAILED" and "private" not in json.dumps(receipt)
    async def cancelled(args, context): raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await registry_for(cancelled).bind(CTX).execute("ext_echo", {"value": 2})


@pytest.mark.asyncio
async def test_unregister_revokes_live_binding_and_inflight_result():
    registry = registry_for()
    executor = registry.bind(CTX)
    assert executor.definitions()
    assert registry.unregister("example.echo")
    assert executor.definitions() == []
    assert (await executor.execute("ext_echo", {"value": 2}))["code"] == "EXTENSION_UNAVAILABLE"
    started, release = asyncio.Event(), asyncio.Event()
    async def pending(args, context):
        started.set()
        await release.wait()
        return "old-result"
    registry = registry_for(pending)
    task = asyncio.create_task(registry.bind(CTX).execute("ext_echo", {"value": 1}))
    await started.wait()
    registry.unregister("example.echo")
    release.set()
    assert (await task)["code"] == "EXTENSION_REVOKED"


@pytest.mark.asyncio
async def test_call_limit_and_context_never_give_mastery_authority():
    registry = registry_for()
    executor = registry.bind(CTX)
    for _ in range(4):
        result = await executor.execute("ext_echo", {"value": 2})
        assert result["ok"] and result["authority"] == "reference_only"
    assert executor.definitions() == []
    assert (await executor.execute("ext_echo", {"value": 2}))["code"] == "EXTENSION_CALL_LIMIT"
    assert set(CTX.model_dump()) == {"owner_id", "conversation_id"}
    with pytest.raises(ValidationError):
        ExecutionContext(owner_id="alice", conversation_id="lesson", tools=["shell"])


@pytest.mark.asyncio
async def test_bundled_example_is_exact_and_skills_need_server_activation():
    registry = default_registry()
    assert registry.skill_instruction() == ""
    registry.set_skill_enabled("mathtutor.stepwise-explanation", True)
    assert "一个关键联系" in registry.skill_instruction()
    registry.set_skill_enabled("mathtutor.stepwise-explanation", False)
    assert registry.skill_instruction() == ""
    result = await registry.bind(CTX).execute("ext_length_convert", {"value": "2.5", "from_unit": "km", "to_unit": "m"})
    assert result["result"]["output"] == {"value": "2500.0", "unit": "m"}


def tool_call(name, args):
    return {"choices": [{"message": {"content": "", "tool_calls": [{"id": "creator-call", "type": "function",
        "function": {"name": name, "arguments": json.dumps(args)}}]}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def answer(text):
    return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def bind_gateway(state, replies, requests):
    def transport(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))
    async def key(): return "fixture-not-a-real-key"
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(base_url="https://fixture.invalid/v1",
        model="scripted", api_key_resolver=key, transport=httpx.MockTransport(transport)))


def test_registered_handler_executes_in_normal_chat_then_disappears(tmp_path):
    requests, contexts = [], []
    async def custom(args, context):
        contexts.append(context)
        return {"result": "真实处理器已运行", "value": args.value}
    db = tmp_path / "creator.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.extension_registry.register_tool(manifest(), name="ext_echo", input_model=Arguments, handler=custom)
        bind_gateway(state, [tool_call("ext_echo", {"value": 2}), answer("处理器返回了请求的内容。"), answer("已继续交流。")], requests)
        before = count(db, "learning_events")
        frames = send(ws, "send_message", "creator-1", {"text": "调用我配置的演示工具帮我处理一下"})
        assert any("处理器返回" in f.get("payload", {}).get("student_message", "") for f in frames)
        assert contexts[0].owner_id == "local-admin" and contexts[0].conversation_id == "p0"
        receipts = [json.loads(m["content"]) for m in requests[1]["messages"] if m["role"] == "tool"]
        assert receipts[0]["result"]["result"] == "真实处理器已运行" and receipts[0]["authority"] == "reference_only"
        assert state.extension_registry.unregister("example.echo")
        send(ws, "send_message", "creator-2", {"text": "继续交流就好"})
        assert all(t["function"]["name"] != "ext_echo" for t in requests[-1]["tools"])
        assert count(db, "learning_events") == before


@pytest.mark.asyncio
async def test_extension_only_turn_keeps_original_step_and_token_limits():
    from mathtutor.application.tutor_runtime import current_turn, complete_math_tools
    from mathtutor.domain.turn_result import TutorTurnResult
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    class Provider:
        async def complete(self, messages, **kwargs):
            return CompletionResult(text="完成。", finish_reason="stop", provider_id="fixture", model="stub",
                                    input_tokens=10, output_tokens=10)
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        await complete_math_tools(Provider(), [{"role": "user", "content": "演示"}], verify=None,
                                  extension_executor=registry_for().bind(CTX))
        assert turn.max_steps == 2 and turn.steps_used == 1
    finally:
        current_turn.reset(token)
    turn = TutorTurnResult(max_total_tokens=1)
    token = current_turn.set(turn)
    try:
        with pytest.raises(RuntimeError, match="token budget"):
            await complete_math_tools(Provider(), [{"role": "user", "content": "演示"}], verify=None,
                                      extension_executor=registry_for().bind(CTX))
        assert turn.steps_used == 0 and turn.finish_reason == "TOKEN_LIMIT"
    finally:
        current_turn.reset(token)


@pytest.mark.asyncio
async def test_missing_usage_accounts_for_schemas_call_arguments_and_tool_history():
    from mathtutor.application.tutor_runtime import current_turn, complete_math_tools
    from mathtutor.domain.turn_result import TutorTurnResult
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    from mathtutor.infrastructure.vision import content_token_estimate
    calls = []
    class Provider:
        async def complete(self, messages, **kwargs):
            calls.append(json.loads(json.dumps({"messages": messages, "tools": kwargs.get("tools")})))
            if len(calls) == 1:
                return CompletionResult(text="", finish_reason="tool_calls", provider_id="fixture", model="stub",
                    tool_calls=({"id": "echo-1", "type": "function", "function": {
                        "name": "ext_echo", "arguments": '{"value":2}'}},))
            return CompletionResult(text="完成。", finish_reason="stop", provider_id="fixture", model="stub")
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        await complete_math_tools(Provider(), [{"role": "user", "content": "演示"}], verify=None,
                                  extension_executor=registry_for().bind(CTX))
    finally:
        current_turn.reset(token)
    expected = 0
    per_call = []
    for call in calls:
        estimate = sum(content_token_estimate(m.get("content", "")) + 16 for m in call["messages"])
        estimate += sum(content_token_estimate(json.dumps(m["tool_calls"], ensure_ascii=False))
                       for m in call["messages"] if m.get("tool_calls"))
        if call["tools"]:
            estimate += content_token_estimate(json.dumps(call["tools"], ensure_ascii=False))
        per_call.append(estimate)
        expected += estimate
    assert len(calls) == 2 and turn.input_tokens == expected and turn.usage_estimated
    assert turn.output_tokens > len("完成。".encode("utf-8")), "tool arguments also consume output tokens"
    # A cap just below the second request's cumulative cost must stop before
    # another provider call, including when the first response has no usage.
    first_output = turn.output_tokens - len("完成。".encode("utf-8"))
    limited = TutorTurnResult(max_total_tokens=per_call[0] + first_output + per_call[1] - 1)
    calls.clear()
    token = current_turn.set(limited)
    try:
        with pytest.raises(RuntimeError, match="token budget"):
            await complete_math_tools(Provider(), [{"role": "user", "content": "演示"}], verify=None,
                                      extension_executor=registry_for().bind(CTX))
        assert len(calls) == 1 and limited.finish_reason == "TOKEN_LIMIT"
    finally:
        current_turn.reset(token)


def test_server_skill_activation_reaches_actual_prompt(tmp_path):
    requests = []
    with client_at(tmp_path / "skill.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        state.extension_registry.register_skill(manifest("example.skill", "teaching-skill"), instructions="EXPLICIT_SKILL_MARKER")
        bind_gateway(state, [answer("你好。"), answer("可以继续。"), answer("好的。")], requests)
        send(ws, "send_message", "skill-1", {"text": "你好"})
        assert "EXPLICIT_SKILL_MARKER" not in json.dumps(requests[0], ensure_ascii=False)
        state.extension_registry.set_skill_enabled("example.skill", True)
        send(ws, "send_message", "skill-2", {"text": "你好呀"})
        assert "EXPLICIT_SKILL_MARKER" in json.dumps(requests[1], ensure_ascii=False)
        state.extension_registry.unregister("example.skill")
        send(ws, "send_message", "skill-3", {"text": "早上好"})
        assert "EXPLICIT_SKILL_MARKER" not in json.dumps(requests[2], ensure_ascii=False)
