"""Generative gateway + secret store tests (§37 gateway/secret group).

The gateway is the ONLY generative surface: providers are addressed by
ROLE, keys resolve through the SecretStore at call time (never stored in
provider objects), and HTTP is mocked via httpx.MockTransport — no real
network, no vendor SDK.
"""

from __future__ import annotations

import json

import httpx
import pytest

from mathtutor.infrastructure.generative_gateway import (
    GenerativeConfigError,
    GenerativeModelGateway,
    GenerativeProviderError,
    GatewayRoleClient,
    ModelRole,
    OpenAICompatibleProvider,
    PRESETS,
)
from mathtutor.infrastructure.secret_store import (
    InMemorySecretStore,
    SecretStoreUnavailableError,
)

pytestmark = pytest.mark.asyncio

_BASE = "https://provider.example/v1"
_SECRET_KEY = "provider-openai-key"


async def _store_with_key() -> InMemorySecretStore:
    store = InMemorySecretStore()
    await store.put(_SECRET_KEY, "sk-test-123")
    return store


def _provider(store, **kwargs) -> OpenAICompatibleProvider:
    async def resolve() -> str | None:
        return await store.get(_SECRET_KEY)

    return OpenAICompatibleProvider(
        base_url=_BASE,
        model="test-model",
        api_key_resolver=resolve,
        provider_id="openai",
        **kwargs,
    )


def _chat_response(content: str, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": finish_reason,
                }
            ]
        },
    )


# ------------------------------------------------------------- secret store


async def test_secret_store_roundtrip():
    store = InMemorySecretStore()
    assert await store.get("k") is None
    await store.put("k", "v")
    assert await store.get("k") == "v"
    await store.delete("k")
    assert await store.get("k") is None


async def test_missing_key_fails_closed():
    store = InMemorySecretStore()  # nothing stored
    provider = _provider(store)
    with pytest.raises(SecretStoreUnavailableError):
        await provider.complete([{"role": "user", "content": "hi"}])


# ------------------------------------------------------------- chat contract


async def test_complete_sends_openai_shape_and_resolves_key():
    store = await _store_with_key()
    seen: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _chat_response("你好，同学！")

    provider = _provider(store, transport=httpx.MockTransport(handler))
    result = await provider.complete(
        [{"role": "system", "content": "你是老师"}, {"role": "user", "content": "题目"}],
        temperature=0.4,
        max_tokens=256,
    )
    assert result.text == "你好，同学！"
    assert result.model == "test-model"
    assert result.finish_reason == "stop"
    assert seen["path"] == "/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-test-123"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["temperature"] == 0.4
    assert seen["body"]["max_tokens"] == 256
    assert seen["body"]["messages"][0]["role"] == "system"


async def test_http_error_raises_provider_error():
    store = await _store_with_key()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad key")

    provider = _provider(store, transport=httpx.MockTransport(handler))
    with pytest.raises(GenerativeProviderError) as excinfo:
        await provider.complete([{"role": "user", "content": "hi"}])
    assert "401" in str(excinfo.value)


async def test_empty_content_raises():
    store = await _store_with_key()
    provider = _provider(store, transport=httpx.MockTransport(lambda req: _chat_response("   ")))
    with pytest.raises(GenerativeProviderError):
        await provider.complete([{"role": "user", "content": "hi"}])


async def test_max_retries_counts_attempts():
    store = await _store_with_key()
    attempts = []

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(request.url.path)
        return httpx.Response(500, text="boom")

    provider = _provider(store, transport=httpx.MockTransport(handler))
    with pytest.raises(GenerativeProviderError):
        await provider.complete(
            [{"role": "user", "content": "hi"}], max_retries=2
        )
    assert len(attempts) == 3  # first + 2 retries


# ------------------------------------------------------------ model discovery


async def test_fetch_models_parses_discovery():
    store = await _store_with_key()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers.get("authorization") == "Bearer sk-test-123"
        return httpx.Response(
            200, json={"data": [{"id": "m-b"}, {"id": "m-a"}]}
        )

    provider = _provider(store, transport=httpx.MockTransport(handler))
    assert await provider.fetch_models() == ["m-a", "m-b"]  # sorted


# ------------------------------------------------------------------ gateway


async def test_gateway_role_client_adapter():
    store = await _store_with_key()
    gateway = GenerativeModelGateway(store)
    gateway.register_openai_compatible(
        ModelRole.TUTOR_WRITER,
        provider_id="openai",
        base_url=_BASE,
        model="test-model",
        secret_key=_SECRET_KEY,
    )
    client = gateway.client_for(ModelRole.TUTOR_WRITER)
    assert client is not None

    # Legacy LLMClient calling convention (what LLMTutorWriter uses).
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return _chat_response("继续加油")

    provider = gateway.provider_for(ModelRole.TUTOR_WRITER)
    assert provider is not None
    provider._transport = httpx.MockTransport(handler)
    text = await client.complete(
        prompt="题目：2x+3=7",
        system_prompt="你是数学老师",
        temperature=0.4,
        max_tokens=512,
        max_retries=0,
    )
    assert text == "继续加油"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "你是数学老师"},
        {"role": "user", "content": "题目：2x+3=7"},
    ]


async def test_gateway_complete_without_provider_fails_closed():
    gateway = GenerativeModelGateway(InMemorySecretStore())
    with pytest.raises(GenerativeConfigError):
        await gateway.complete(ModelRole.PRACTICE_GENERATOR, [{"role": "user", "content": "x"}])
    assert gateway.client_for(ModelRole.PRACTICE_GENERATOR) is None


async def test_gateway_resolve_model_configured_first():
    store = await _store_with_key()
    gateway = GenerativeModelGateway(store)
    gateway.register_openai_compatible(
        ModelRole.PRACTICE_GENERATOR,
        provider_id="openai",
        base_url=_BASE,
        model="explicit-model",
        secret_key=_SECRET_KEY,
    )
    assert await gateway.resolve_model("openai") == "explicit-model"


async def test_gateway_resolve_model_preset_default_then_first_discovered():
    store = await _store_with_key()
    gateway = GenerativeModelGateway(store)

    async def resolve() -> str | None:
        return await store.get(_SECRET_KEY)

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": [{"id": "some-other"}, {"id": PRESETS["deepseek"].default_model}]}
        )

    provider = OpenAICompatibleProvider(
        base_url=_BASE,
        model="",  # no explicit model → discovery decides
        api_key_resolver=resolve,
        provider_id="deepseek",
        transport=httpx.MockTransport(handler),
    )
    gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
    # preset default present in discovery → preferred
    assert await gateway.resolve_model("deepseek") == PRESETS["deepseek"].default_model

    # no preset default in discovery → first discovered (sorted order)
    async def handler2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "z-model"}, {"id": "a-model"}]})

    provider._transport = httpx.MockTransport(handler2)
    assert await gateway.resolve_model("deepseek") == "a-model"


async def test_presets_cover_custom_and_vendors():
    assert "custom" in PRESETS
    assert PRESETS["custom"].custom is True
    assert all(not preset.custom for preset in PRESETS.values() if preset.preset_id != "custom")


def test_configured_roles_listing():
    gateway = GenerativeModelGateway(InMemorySecretStore())
    assert gateway.configured_roles() == []
