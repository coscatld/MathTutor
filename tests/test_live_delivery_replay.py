"""Saved production responses are regression fixtures, never semantic gold."""
import json
from pathlib import Path

import httpx
import pytest

from mathtutor.application.tutor_runtime import complete_tutor, current_turn
from mathtutor.domain.turn_result import TutorTurnResult, FinishReason
from mathtutor.infrastructure.generative_gateway import (
    CompletionResult, GenerativeProviderError, OpenAICompatibleProvider,
)

ORIGINAL = Path(__file__).resolve().parents[1] / "tests/fixtures/sanitized_rag_release/original"


@pytest.mark.asyncio
async def test_saved_discriminant_exhausts_steps_not_total_tokens():
    rows = [json.loads((ORIGINAL / f"request-{n:03}.json").read_text(encoding="utf-8")) for n in (14, 15)]
    class Replay:
        provider_id = "deepseek"
        model = "deepseek-flash"
        calls = 0
        async def complete(self, messages, **kwargs):
            row = rows[self.calls]
            assert messages[0] == rows[0]["messages"][0]
            if self.calls:
                assert messages[-2]["content"] == "从中断处继续，不重复已有内容。"
                assert messages[-3]["content"] == rows[0]["response"]["text"]
            assert kwargs == row["parameters"]
            self.calls += 1
            return CompletionResult(**row["response"])
    provider = Replay()
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        response = await complete_tutor(provider, rows[0]["messages"], **rows[0]["parameters"])
    finally:
        current_turn.reset(token)
    assert provider.calls == turn.steps_used == turn.max_steps == 2
    assert turn.finish_reason == FinishReason.TOKEN_LIMIT
    assert turn.max_total_tokens - turn.input_tokens - turn.output_tokens == 13477
    assert rows[0]["response"]["text"] in response.text
    assert response.text.endswith("接")
    assert "续写接缝待核对" in response.text
    assert turn.status == "PARTIAL"


@pytest.mark.asyncio
@pytest.mark.parametrize("number", [13, 18, 20, 21, 22, 24])
async def test_saved_incomplete_errors_never_enter_continuation(number):
    row = json.loads((ORIGINAL / f"request-{number:03}.json").read_text(encoding="utf-8"))
    assert row["error_category"] == "response_incomplete"
    class Replay:
        calls = 0
        async def complete(self, *args, **kwargs):
            self.calls += 1
            # Original records lack the exact exception message/raw response.
            raise GenerativeProviderError("saved response_incomplete (raw cause unknown)")
    provider = Replay()
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        with pytest.raises(GenerativeProviderError):
            await complete_tutor(provider, row["messages"], **row["parameters"])
    finally:
        current_turn.reset(token)
    assert provider.calls == 1
    assert turn.steps_used == 1  # A last-chance instruction can occur on call 1.
    assert turn.finish_reason == FinishReason.PROVIDER_ERROR
    assert turn.status == "FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize("finish", ["length", "stop"])
async def test_empty_response_preserves_safe_diagnostics(finish):
    # Synthetic parser contract, NOT a reconstruction of missing original HTTP.
    async def key():
        return "test-only"
    def reply(request):
        return httpx.Response(200, json={"model": "server-model", "choices": [{
            "finish_reason": finish, "message": {"content": "", "reasoning_content": "private reasoning"}}],
            "usage": {"prompt_tokens": 76, "completion_tokens": 512,
                      "completion_tokens_details": {"reasoning_tokens": 512}}})
    provider = OpenAICompatibleProvider(base_url="https://example.invalid/v1", model="requested",
        api_key_resolver=key, transport=httpx.MockTransport(reply))
    with pytest.raises(GenerativeProviderError) as caught:
        await provider.complete([{"role": "user", "content": "synthetic"}], max_tokens=512)
    diagnostic = caught.value.diagnostics
    assert diagnostic["finish_reason"] == finish
    assert diagnostic["content_chars"] == 0
    assert diagnostic["reasoning_chars"] == 17
    assert diagnostic["usage"]["completion_tokens"] == 512
    assert diagnostic["server_model"] == "server-model"
    assert "private reasoning" not in json.dumps(diagnostic)
    assert "test-only" not in json.dumps(diagnostic)


@pytest.mark.asyncio
@pytest.mark.parametrize("tools", [None, [{"type": "function", "function": {"name": "read_source"}}]])
async def test_deepseek_bounded_text_and_tools_reserve_output_for_visible_answer(tools):
    async def key():
        return "test-only"
    def reply(request):
        payload = json.loads(request.content)
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["max_tokens"] == 512
        assert payload["temperature"] == .4
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "answer"}}]})
    provider = OpenAICompatibleProvider(base_url="https://example.invalid/v1", model="deepseek-flash",
        provider_id="deepseek", api_key_resolver=key, transport=httpx.MockTransport(reply))
    assert (await provider.complete([{"role": "user", "content": "synthetic"}], max_tokens=512, tools=tools)).text == "answer"


def test_final_schema_explains_existing_quote_identity_contract():
    from mathtutor.application.knowledge_tools import Final
    schema = Final.model_json_schema()["$defs"]["Claim"]["properties"]
    assert "text == evidence[0].quote" in schema["kind"]["description"]
    assert "summary" in schema["kind"]["description"]
