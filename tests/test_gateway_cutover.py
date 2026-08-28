"""Generative gateway cutover tests (§6.4 desktop configuration surface).

``GatewayConfigService`` + ``build_tutor_writer`` are the product's wiring
surface: a user picks a PRESET + pastes an API key (only ``custom`` takes
base_url/model), the system resolves the concrete model, and the writer is
LLM-backed only when the gateway is genuinely usable — otherwise the
deterministic template writer (fail closed, A3).

Invariants exercised here:

- the API key lives ONLY in the SecretStore — never in persisted JSON,
  repr output, or error messages;
- both product roles (TUTOR_WRITER / PRACTICE_GENERATOR) are served by the
  SAME provider;
- provider failures and missing secrets degrade to the template writer,
  never to an exception out of the wiring.

HTTP is mocked via httpx.MockTransport (same pattern as test_gateway_secret)
— no real network, no vendor SDK.
"""

from __future__ import annotations

import json

import httpx
import pytest

from mathtutor.domain.tutoring import TutorAction
from mathtutor.infrastructure.gateway_config import (
    GatewayConfigService,
    GatewayConnectionResult,
    build_tutor_writer,
    secret_key_name,
)
from mathtutor.infrastructure.generative_gateway import (
    GenerativeConfigError,
    GenerativeModelGateway,
    GenerativeProviderError,
    ModelRole,
    PRESETS,
)
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
from mathtutor.pedagogy.stage_policy import MIDDLE_POLICY
from mathtutor.pedagogy.tutor_writer import (
    LLMTutorWriter,
    PublicProblemView,
    TemplateTutorWriter,
)
from mathtutor.pedagogy.writer_settings import MathTutorWriterSettings

pytestmark = pytest.mark.asyncio

_SECRET = "sk-test-12345"
_BASE_URL = "https://custom.example/v1"
_CHAT_OK = {
    "choices": [
        {"message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
    ]
}


# ------------------------------------------------------------------ helpers


def _settings(*, enabled: bool = True) -> MathTutorWriterSettings:
    return MathTutorWriterSettings(
        enabled=enabled, model="", timeout_seconds=5.0, max_tokens=256
    )


def _route(*, chat_text: str = "ok", models=None, seen=None, chat_status: int = 200):
    """One handler serving both /models and /chat/completions."""

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/models"):
            if models is None:
                return httpx.Response(500, text="model discovery not mocked")
            return httpx.Response(200, json={"data": [{"id": m} for m in models]})
        if path.endswith("/chat/completions"):
            if seen is not None:
                seen.append(path)
            if chat_status != 200:
                return httpx.Response(chat_status, text="boom")
            return httpx.Response(200, json=_CHAT_OK | {"choices": [
                {"message": {"role": "assistant", "content": chat_text}, "finish_reason": "stop"}
            ]})
        return httpx.Response(404, text=f"unexpected path {path}")

    return handler


def _inject(gateway: GenerativeModelGateway, handler) -> None:
    """Attach a MockTransport to every registered role provider."""
    transport = httpx.MockTransport(handler)
    for role in (ModelRole.TUTOR_WRITER, ModelRole.PRACTICE_GENERATOR):
        provider = gateway.provider_for(role)
        if provider is not None:
            provider._transport = transport


async def _configured(
    tmp_path, *, preset: str, api_key: str = _SECRET, base_url: str = "", model: str = ""
):
    store = InMemorySecretStore()
    gateway = GenerativeModelGateway(store)
    path = tmp_path / "gateway.json"
    service = GatewayConfigService(gateway, store, config_path=path)
    await service.apply_config(
        preset_id=preset, api_key=api_key, base_url=base_url, model=model
    )
    return store, gateway, service, path


def _write_inputs() -> dict:
    return dict(
        problem_view=PublicProblemView(
            problem_type="linear_equation", display_latex="x + 1 = 2"
        ),
        disclosure=DisclosedSolutionContext(assistance_level=0),
        policy=MIDDLE_POLICY,
        action=TutorAction(action="ASK_STUDENT", effective_assistance_level=0),
    )


# ------------------------------------------------- role binding (spec 1, 2)


async def test_writer_uses_tutor_writer_role(tmp_path):
    _, gateway, _, _ = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="my-model"
    )
    assert ModelRole.TUTOR_WRITER in gateway.configured_roles()
    assert ModelRole.PRACTICE_GENERATOR in gateway.configured_roles()
    assert gateway.provider_for(ModelRole.TUTOR_WRITER).provider_id == "custom"
    seen = []
    _inject(gateway, _route(chat_text="继续加油", seen=seen))
    writer_client = gateway.client_for(ModelRole.TUTOR_WRITER)
    assert writer_client is not None
    text = await writer_client.complete(
        prompt="题目：2x+3=7",
        system_prompt="你是老师",
        temperature=0.4,
        max_tokens=256,
        max_retries=0,
    )
    assert text == "继续加油"
    assert seen == ["/v1/chat/completions"]


async def test_practice_generator_uses_its_role(tmp_path):
    _, gateway, _, _ = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="my-model"
    )
    client = gateway.client_for(ModelRole.PRACTICE_GENERATOR)
    assert client is not None
    _inject(gateway, _route(chat_text="练习题"))
    text = await client.complete(prompt="生成一道一元一次方程题", max_retries=0)
    assert text == "练习题"


# ------------------------------------------------------ model resolution (3-5)


async def test_configured_model_preferred(tmp_path):
    """configured model wins — discovery must not even run."""
    _, gateway, service, _ = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="explicit-model"
    )

    async def forbidden(request: httpx.Request) -> httpx.Response:
        raise AssertionError("model discovery must not run when a model is configured")

    _inject(gateway, forbidden)
    result = await service.test_connection()
    assert result.status == "ok"
    assert result.resolved_model == "explicit-model"
    assert gateway.provider_for(ModelRole.TUTOR_WRITER).model == "explicit-model"


async def test_preset_default_model_preferred(tmp_path):
    default = PRESETS["deepseek"].default_model
    _, gateway, service, _ = await _configured(tmp_path, preset="deepseek")
    _inject(gateway, _route(models=[default, "other-model"]))
    result = await service.test_connection()
    assert result.status == "ok"
    assert result.resolved_model == default
    assert service.is_configured() is True


async def test_discovered_first_model_fallback(tmp_path):
    """preset default absent → sorted-first discovered model."""
    _, gateway, service, _ = await _configured(tmp_path, preset="deepseek")
    _inject(gateway, _route(models=["z-model", "a-model"]))
    result = await service.test_connection()
    assert result.status == "ok"
    assert result.resolved_model == "a-model"


# --------------------------------------------------- failure posture (6, 7)


async def test_models_error_is_not_swallowed(tmp_path):
    _, gateway, service, _ = await _configured(tmp_path, preset="deepseek")

    async def boom(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="model discovery upstream failure")

    _inject(gateway, boom)
    # the gateway itself raises — the error is never swallowed there
    with pytest.raises(GenerativeProviderError):
        await gateway.fetch_models("deepseek")
    # the service converts it into a redacted, non-key error result
    result = await service.discover_models()
    assert isinstance(result, GatewayConnectionResult)
    assert result.status == "error"
    assert "500" in result.message
    result2 = await service.test_connection()
    assert result2.status == "error"
    assert service.is_configured() is False
    assert isinstance(build_tutor_writer(gateway, _settings()), TemplateTutorWriter)


async def test_secret_missing_fails_closed(tmp_path):
    store, gateway, service, _ = await _configured(tmp_path, preset="deepseek")
    # the key vanishes from the store (revoked/evicted) — no value to leak
    await store.delete(secret_key_name("deepseek"))
    _inject(gateway, _route(models=[PRESETS["deepseek"].default_model]))
    result = await service.test_connection()
    assert result.status == "error"
    assert "deepseek" in result.message
    assert _SECRET not in result.message
    assert service.is_configured() is False
    assert isinstance(build_tutor_writer(gateway, _settings()), TemplateTutorWriter)


async def test_error_message_never_echoes_key_value(tmp_path):
    _, gateway, service, _ = await _configured(tmp_path, preset="deepseek")

    async def echo_key(request: httpx.Request) -> httpx.Response:
        # worst case: the remote endpoint echoes the Authorization header
        return httpx.Response(401, text=f"unauthorized {_SECRET}")

    _inject(gateway, echo_key)
    result = await service.test_connection()
    assert result.status == "error"
    assert _SECRET not in result.message
    assert "[REDACTED]" in result.message


# ------------------------------------------------------------ secret hygiene (8)


async def test_api_key_never_in_repr_or_persisted(tmp_path):
    leaky = "sk-leaky-789"
    _, gateway, service, path = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="m", api_key=leaky
    )
    provider = gateway.provider_for(ModelRole.TUTOR_WRITER)
    for obj in (service, gateway, provider, gateway.provider_for(ModelRole.PRACTICE_GENERATOR)):
        assert leaky not in repr(obj), type(obj).__name__
        assert leaky not in str(obj), type(obj).__name__
    assert leaky not in repr(service.current_config())
    assert leaky not in str(service.current_config())
    # the secret key NAME is a reference, not a secret — but even it must
    # not sit on the provider object (naive-impl trap: these would fail
    # if a provider ever stored the key or its name on itself).
    assert secret_key_name("custom") not in repr(provider)
    # persisted JSON is key-free
    assert leaky not in path.read_text(encoding="utf-8")


# ------------------------------------------------------------- call budget (9)


async def test_max_retries_zero_makes_exactly_one_request(tmp_path):
    _, gateway, _, _ = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="m"
    )
    calls = []

    async def fail(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503, text="busy")

    _inject(gateway, fail)
    client = gateway.client_for(ModelRole.TUTOR_WRITER)
    with pytest.raises(GenerativeProviderError):
        await client.complete(prompt="hi", max_retries=0)
    assert calls == ["/v1/chat/completions"]  # first attempt, zero retries


# -------------------------------------------------------------- writer wiring (10)


async def test_writer_provider_failure_templates_fallback(tmp_path):
    _, gateway, _, _ = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="m"
    )
    writer = build_tutor_writer(gateway, _settings(enabled=True))
    assert isinstance(writer, LLMTutorWriter)
    calls = []

    async def fail(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(500, text="provider down")

    _inject(gateway, fail)
    candidate = await writer.write(**_write_inputs())
    assert candidate.writer_version == TemplateTutorWriter.writer_version
    assert candidate.text  # deterministic template text
    assert calls == ["/v1/chat/completions"]  # A3: exactly one provider attempt


# ---------------------------------------------------------------- endpoints (11, 12)


async def test_custom_endpoint_works(tmp_path):
    _, gateway, _, _ = await _configured(
        tmp_path, preset="custom", base_url="https://custom.example/v1", model="cm"
    )
    urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=_CHAT_OK | {"choices": [
            {"message": {"role": "assistant", "content": "custom ok"}, "finish_reason": "stop"}
        ]})

    _inject(gateway, handler)
    text = await gateway.client_for(ModelRole.TUTOR_WRITER).complete(prompt="p", max_retries=0)
    assert text == "custom ok"
    assert urls == ["https://custom.example/v1/chat/completions"]


async def test_preset_endpoint_works(tmp_path):
    preset = PRESETS["openai"]
    _, gateway, service, _ = await _configured(tmp_path, preset="openai")
    _inject(gateway, _route(models=[preset.default_model]))
    result = await service.test_connection()
    assert result.status == "ok"
    urls = []

    async def handler(request: httpx.Request) -> httpx.Response:
        urls.append(str(request.url))
        return httpx.Response(200, json=_CHAT_OK | {"choices": [
            {"message": {"role": "assistant", "content": "openai ok"}, "finish_reason": "stop"}
        ]})

    _inject(gateway, handler)
    text = await gateway.client_for(ModelRole.TUTOR_WRITER).complete(prompt="p", max_retries=0)
    assert text == "openai ok"
    assert urls == [f"{preset.base_url}/chat/completions"]


# ---------------------------------------------------------- config validation (13)


async def test_preset_rejects_base_url_and_model(tmp_path):
    gateway = GenerativeModelGateway(InMemorySecretStore())
    service = GatewayConfigService(gateway, InMemorySecretStore())
    with pytest.raises(GenerativeConfigError):
        await service.apply_config(preset_id="openai", api_key=_SECRET, base_url="https://evil.example/v1")
    with pytest.raises(GenerativeConfigError):
        await service.apply_config(preset_id="openai", api_key=_SECRET, model="gpt-x")
    with pytest.raises(GenerativeConfigError):
        await service.apply_config(preset_id="unknown-vendor", api_key=_SECRET)
    with pytest.raises(GenerativeConfigError):
        await service.apply_config(preset_id="custom", api_key=_SECRET)  # needs base_url
    assert gateway.configured_roles() == []


# -------------------------------------------------------------- wiring + restore (14)


async def test_build_tutor_writer_selection(tmp_path):
    # disabled settings → template even with a fully configured gateway
    _, gateway, _, _ = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="m"
    )
    assert isinstance(build_tutor_writer(gateway, _settings(enabled=False)), TemplateTutorWriter)
    # enabled settings + unconfigured gateway → template (fail closed)
    empty = GenerativeModelGateway(InMemorySecretStore())
    assert isinstance(build_tutor_writer(empty, _settings(enabled=True)), TemplateTutorWriter)
    # enabled + configured + resolved model → LLMTutorWriter
    assert isinstance(build_tutor_writer(gateway, _settings(enabled=True)), LLMTutorWriter)
    # preset registered but model not yet resolved → template
    store = InMemorySecretStore()
    gw = GenerativeModelGateway(store)
    svc = GatewayConfigService(gw, store)
    await svc.apply_config(preset_id="deepseek", api_key=_SECRET)
    assert svc.is_configured() is False
    assert isinstance(build_tutor_writer(gw, _settings(enabled=True)), TemplateTutorWriter)


async def test_config_path_restore_reenables_writer(tmp_path):
    path = tmp_path / "gateway.json"
    store = InMemorySecretStore()
    gateway = GenerativeModelGateway(store)
    service = GatewayConfigService(gateway, store, config_path=path)
    await service.apply_config(preset_id="deepseek", api_key=_SECRET)
    assert service.is_configured() is False  # model not resolved yet
    _inject(gateway, _route(models=[PRESETS["deepseek"].default_model]))
    result = await service.test_connection()
    assert result.status == "ok"
    assert service.is_configured() is True
    assert PRESETS["deepseek"].default_model in path.read_text(encoding="utf-8")

    # rebuild a fresh service from the JSON — the key still resolves from
    # the SAME SecretStore at call time (the JSON never carries it).
    gateway2 = GenerativeModelGateway(store)
    service2 = GatewayConfigService(gateway2, store, config_path=path)
    assert set(gateway2.configured_roles()) == {
        ModelRole.TUTOR_WRITER,
        ModelRole.PRACTICE_GENERATOR,
    }
    assert service2.is_configured() is True
    assert isinstance(build_tutor_writer(gateway2, _settings(enabled=True)), LLMTutorWriter)
    seen = []
    _inject(gateway2, _route(chat_text="恢复完成", seen=seen))
    text = await gateway2.client_for(ModelRole.TUTOR_WRITER).complete(prompt="p", max_retries=0)
    assert text == "恢复完成"
    assert seen == ["/v1/chat/completions"]


# ----------------------------------------------------------- persistence (15)


async def test_persisted_config_never_contains_key_field(tmp_path):
    _, _, _, path = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="m", api_key=_SECRET
    )
    text = path.read_text(encoding="utf-8")
    assert "key" not in text  # no api_key field, no secret key name, no value
    assert _SECRET not in text
    data = json.loads(text)
    assert data["preset_id"] == "custom"
    assert data["model"] == "m"
    assert data["base_url"] == _BASE_URL
    assert data["roles"] == ["tutor_writer", "practice_generator"]
    assert data["config_version"] == 1
    assert (path.stat().st_mode & 0o777) == 0o600


# ------------------------------------------------------------------- extras


async def test_discover_models_success(tmp_path):
    _, gateway, service, _ = await _configured(tmp_path, preset="deepseek")
    _inject(gateway, _route(models=["b", "a"]))
    assert await service.discover_models() == ["a", "b"]  # sorted


async def test_apply_config_returns_nonsensitive_config(tmp_path):
    _, _, service, _ = await _configured(
        tmp_path, preset="custom", base_url=_BASE_URL, model="m", api_key=_SECRET
    )
    config = service.current_config()
    assert config == {
        "preset_id": "custom",
        "model": "m",
        "base_url": _BASE_URL,
        "roles": ["tutor_writer", "practice_generator"],
        "config_version": 1,
    }
    assert _SECRET not in json.dumps(config)


async def test_corrupt_config_file_fails_closed(tmp_path):
    path = tmp_path / "gateway.json"
    path.write_text("{not json", encoding="utf-8")
    gateway = GenerativeModelGateway(InMemorySecretStore())
    service = GatewayConfigService(gateway, InMemorySecretStore(), config_path=path)
    assert gateway.configured_roles() == []
    assert service.is_configured() is False
    result = await service.test_connection()
    assert result.status == "error"


async def test_restore_ignores_unknown_preset(tmp_path):
    path = tmp_path / "gateway.json"
    path.write_text(
        json.dumps(
            {
                "preset_id": "nope",
                "model": "x",
                "base_url": "http://x",
                "roles": ["tutor_writer"],
                "config_version": 1,
            }
        ),
        encoding="utf-8",
    )
    gateway = GenerativeModelGateway(InMemorySecretStore())
    GatewayConfigService(gateway, InMemorySecretStore(), config_path=path)
    assert gateway.configured_roles() == []


async def test_test_connection_without_configuration():
    service = GatewayConfigService(
        GenerativeModelGateway(InMemorySecretStore()), InMemorySecretStore()
    )
    result = await service.test_connection()
    assert result.status == "error"
    assert isinstance(await service.discover_models(), GatewayConnectionResult)
    assert service.is_configured() is False
    assert isinstance(build_tutor_writer(
        GenerativeModelGateway(InMemorySecretStore()), _settings(enabled=True)
    ), TemplateTutorWriter)
