"""All maths/tool capability combinations share one budget; providers are offline fakes."""
import json
from types import SimpleNamespace

import pytest

from mathtutor.application.tutor_runtime import (
    complete_math_tools, current_turn, request_token_estimate, completion_token_estimate,
)
from mathtutor.domain.turn_result import TutorTurnResult
from mathtutor.infrastructure.generative_gateway import CompletionResult, GenerativeModelGateway, ModelRole
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.infrastructure.vision import content_token_estimate

MODES = [(True, False), (False, True), (True, True), (False, False)]


async def verify(_expression, _answer):
    return SimpleNamespace(status="verified", signals=())


class Extension:
    file_task = False
    def definitions(self):
        return [{"type": "function", "function": {"name": "ext_example", "description": "Offline test",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}}]
    async def execute(self, *_args):
        return {"ok": True, "authority": "reference_only"}


class Provider:
    provider_id, model, supports_native_tools = "offline", "budget-test", True
    def __init__(self, responses): self.responses, self.calls = iter(responses), []
    async def complete(self, messages, **kwargs):
        self.calls.append(json.loads(json.dumps({"messages": messages, **kwargs})))
        return next(self.responses)


def final(**usage):
    return CompletionResult(text="说明完成。", finish_reason="stop", provider_id="offline", model="budget-test", **usage)


def call_for(use_verify, draw):
    name, args = ("verify_math", {"expression": "1+1", "answer": "2"}) if use_verify else (
        ("draw_scene", {"title": "Point", "objects": [{"id": "p", "type": "point", "x": "1", "y": "1"}]}) if draw else
        ("ext_example", {}))
    # A native argument string is output on the first call and history on the next.
    args["padding"] = "argument bytes " * 30
    return CompletionResult(text="", finish_reason="tool_calls", provider_id="offline", model="budget-test",
        tool_calls=({"id": "bounded-call", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}},))


@pytest.mark.asyncio
@pytest.mark.parametrize("use_verify,draw", MODES)
@pytest.mark.parametrize("extension", [False, True])
@pytest.mark.parametrize("previous", ["", "已有可靠片段。"])
async def test_nonpositive_remaining_allowance_makes_zero_calls(use_verify, draw, extension, previous):
    provider = Provider([])
    turn = TutorTurnResult(max_total_tokens=1, final_text=previous)
    token = current_turn.set(turn)
    try:
        with pytest.raises(RuntimeError, match="token budget"):
            await complete_math_tools(provider, [{"role": "user", "content": "Test"}], verify=verify if use_verify else None,
                                      draw=draw, extension_executor=Extension() if extension else None)
    finally:
        current_turn.reset(token)
    assert provider.calls == [] and turn.steps_used == 0 and turn.finish_reason == "TOKEN_LIMIT"
    assert turn.status == ("PARTIAL" if previous else "FAILED") and turn.final_text == previous
    assert turn.max_total_tokens == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("use_verify,draw", MODES[:3])
@pytest.mark.parametrize("extension", [False, True])
async def test_missing_usage_charges_schemas_tool_arguments_and_history_before_second_call(use_verify, draw, extension):
    initial = [{"role": "user", "content": [{"type": "text", "text": "check the image"},
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "x" * 20000}}]}]
    first = call_for(use_verify, draw)
    provider = Provider([first, final()])
    turn = TutorTurnResult(max_total_tokens=200000)
    token = current_turn.set(turn)
    try:
        await complete_math_tools(provider, initial, verify=verify if use_verify else None, draw=draw,
                                  extension_executor=Extension() if extension else None)
    finally:
        current_turn.reset(token)
    assert len(provider.calls) == 2
    expected = sum(request_token_estimate(call["messages"], call.get("tools")) for call in provider.calls)
    assert turn.input_tokens == expected and turn.usage_estimated
    assert turn.output_tokens == completion_token_estimate(first) + completion_token_estimate(final())
    assert turn.output_tokens > len(final().text.encode())
    # Exactly enough for the second request's input, but no positive output allowance.
    cap = request_token_estimate(provider.calls[0]["messages"], provider.calls[0]["tools"]) + completion_token_estimate(first)
    cap += request_token_estimate(provider.calls[1]["messages"], provider.calls[1]["tools"])
    limited = TutorTurnResult(max_total_tokens=cap)
    provider = Provider([first, final()])
    token = current_turn.set(limited)
    try:
        with pytest.raises(RuntimeError, match="token budget"):
            await complete_math_tools(provider, initial, verify=verify if use_verify else None, draw=draw,
                                      extension_executor=Extension() if extension else None)
    finally:
        current_turn.reset(token)
    assert len(provider.calls) == 1 and limited.steps_used == 1
    assert limited.finish_reason == "TOKEN_LIMIT" and limited.status != "COMPLETED"
    assert limited.max_total_tokens == cap


@pytest.mark.asyncio
@pytest.mark.parametrize("use_verify,draw", MODES)
@pytest.mark.parametrize("extension", [False, True])
@pytest.mark.parametrize("input_usage,output_usage", [(0, 0), (3, 4), (None, 0), (0, None)])
async def test_reported_usage_wins_independently_including_zero(use_verify, draw, extension, input_usage, output_usage):
    response = final(input_tokens=input_usage, output_tokens=output_usage)
    provider, turn = Provider([response]), TutorTurnResult()
    token = current_turn.set(turn)
    try:
        await complete_math_tools(provider, [{"role": "user", "content": "hello"}], verify=verify if use_verify else None,
                                  draw=draw, extension_executor=Extension() if extension else None)
    finally:
        current_turn.reset(token)
    assert turn.input_tokens == (input_usage if input_usage is not None else request_token_estimate(provider.calls[0]["messages"], provider.calls[0]["tools"]))
    assert turn.output_tokens == (output_usage if output_usage is not None else completion_token_estimate(response))
    assert turn.usage_estimated is (input_usage is None or output_usage is None)
    assert turn.status == "COMPLETED"


@pytest.mark.asyncio
@pytest.mark.parametrize("extension", [False, True])
async def test_provider_overrun_is_not_a_completed_answer(extension):
    provider = Provider([final(input_tokens=100001, output_tokens=1)])
    turn = TutorTurnResult(max_total_tokens=100000)
    token = current_turn.set(turn)
    try:
        with pytest.raises(RuntimeError, match="token budget"):
            await complete_math_tools(provider, [], verify=verify, extension_executor=Extension() if extension else None)
    finally:
        current_turn.reset(token)
    assert len(provider.calls) == 1 and turn.finish_reason == "TOKEN_LIMIT" and turn.status == "FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["math", "chat", "auxiliary"])
async def test_explicit_zero_output_cap_is_not_replaced_by_gateway_default(mode):
    gateway = GenerativeModelGateway(InMemorySecretStore())
    provider = Provider([])
    role = ModelRole.PRACTICE_GENERATOR if mode == "auxiliary" else ModelRole.TUTOR_WRITER
    gateway.register_provider(role, provider)
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        with pytest.raises(RuntimeError, match="budget"):
            await gateway.complete(role, [{"role": "user", "content": "test"}], max_tokens=0,
                                   **({"math_verify": verify} if mode == "math" else {}))
    finally:
        current_turn.reset(token)
    assert provider.calls == [] and turn.steps_used == 0 and turn.finish_reason == "TOKEN_LIMIT"


def test_request_estimate_counts_bounded_images_and_native_call_history():
    history = [{"role": "assistant", "content": "", "tool_calls": [{"id": "x", "function": {"arguments": "many bytes"}}]},
               {"role": "tool", "tool_call_id": "x", "content": "receipt"},
               {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:" + "x" * 100000}}]}]
    base = sum(content_token_estimate(row["content"]) + 16 for row in history)
    assert request_token_estimate(history) == base + content_token_estimate(json.dumps(history[0]["tool_calls"], ensure_ascii=False))
    assert request_token_estimate(history) < 10000
