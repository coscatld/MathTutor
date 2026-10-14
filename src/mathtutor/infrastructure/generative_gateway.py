"""Generative Model Gateway — the ONLY generative surface of MathTutor.

Design requirement: every generative call travels through ONE
OpenAI-compatible HTTP gateway. Domain/application layers never bind to a
vendor (no OpenAI/DeepSeek/Moonshot SDK import anywhere in domain/ or
application/); they address the gateway by ROLE
(``TUTOR_WRITER`` / ``PRACTICE_GENERATOR``) and receive plain text back.

User-facing configuration (desktop):

- ordinary users pick a provider PRESET + paste an API key — nothing else;
- only the ``custom`` preset additionally asks for base_url + model;
- the SYSTEM owns model discovery via ``GET {base_url}/models``
  (:meth:`GenerativeModelGateway.discover_models`), and resolves the
  concrete model automatically when none was configured.

Secret handling: providers never hold the key. A provider receives an
async resolver bound to the :class:`SecretStore`; the key is fetched at
call time and never written into config JSON or the business DB.

HTTP is plain ``httpx`` — no vendor SDK, no dependency on DeepTutor's
legacy LLMClient stack. The gateway is self-contained and testable with
the stdlib-free contract (a fake provider satisfies the same Protocol).
"""

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Awaitable, Callable, Protocol, Sequence

import httpx
from pydantic import BaseModel, ConfigDict, Field

from mathtutor.infrastructure.secret_store import (
    SecretStore,
    SecretStoreUnavailableError,
)



#: Set for one turn when the daily model budget is exhausted: every role then
#: looks unconfigured, so each consumer takes its existing template fallback.
from contextvars import ContextVar
model_calls_blocked: ContextVar[bool] = ContextVar("model_calls_blocked", default=False)

class ModelRole(str, Enum):
    """Business roles a generative model can serve (never a vendor name)."""

    TUTOR_WRITER = "tutor_writer"
    PRACTICE_GENERATOR = "practice_generator"


class GenerativeProviderError(RuntimeError):
    """Provider call failed after retries (transport / HTTP / malformed)."""

    def __init__(self, message: str, *, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


class GenerativeConfigError(RuntimeError):
    """Gateway/role misconfiguration (no provider registered, missing key)."""


class CompletionResult(BaseModel):
    """One completed generation with provenance."""

    model_config = ConfigDict(frozen=True)

    text: str
    provider_id: str
    model: str
    finish_reason: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    turn_result: dict | None = None
    tool_calls: tuple[dict, ...] = ()
    diagnostics: dict = Field(default_factory=dict)


class ProviderPreset(BaseModel):
    """A user-selectable provider preset (config data, not a vendor binding).

    The preset list is the desktop picker's data source. Business code
    NEVER references preset ids — only the gateway does.
    """

    model_config = ConfigDict(frozen=True)

    preset_id: str
    label: str
    base_url: str
    default_model: str
    custom: bool = False
    requires_api_key: bool = True
    editable_base_url: bool = True
    local: bool = False


PRESETS: dict[str, ProviderPreset] = {
    preset.preset_id: preset
    for preset in (
        ProviderPreset(
            preset_id="openai",
            label="OpenAI",
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini",
        ),
        ProviderPreset(
            preset_id="deepseek",
            label="DeepSeek",
            base_url="https://api.deepseek.com/v1",
            default_model="deepseek-chat",
        ),
        ProviderPreset(
            preset_id="moonshot",
            label="Moonshot (Kimi)",
            base_url="https://api.moonshot.cn/v1",
            default_model="moonshot-v1-8k",
        ),
        ProviderPreset(
            preset_id="custom",
            label="自定义 (OpenAI 兼容)",
            base_url="",
            default_model="",
            custom=True,
            editable_base_url=True,
        ),
        ProviderPreset(
            preset_id="ollama",
            label="Ollama",
            base_url="http://127.0.0.1:11434",
            default_model="",
            requires_api_key=False,
            editable_base_url=True,
            local=True,
        ),
    )
}

DEFAULT_TIMEOUT_SECONDS = 30.0


class GenerativeModelProvider(Protocol):
    """Minimal generative capability contract (async).

    ``complete`` takes OpenAI chat-message dicts (role/content) so any
    OpenAI-compatible endpoint fits without an adapter layer.
    """

    provider_id: str
    model: str

    async def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        max_retries: int = 0,
    ) -> CompletionResult: ...

    async def fetch_models(self) -> list[str]: ...

    def set_model(self, model: str) -> None: ...



async def _no_lines():
    return
    yield  # pragma: no cover - makes this an async generator

class OpenAICompatibleProvider:
    """httpx implementation of the chat-completions + models contract.

    - POST ``{base_url}/chat/completions`` — bearer key resolved at call
      time through ``api_key_resolver`` (bound to the SecretStore);
    - GET ``{base_url}/models`` — model discovery, the system's job;
    - ``max_retries`` counts ADDITIONAL attempts after the first (matches
      the LLMTutorWriter convention: ``max_retries=0`` → exactly one call);
    - failures raise :class:`GenerativeProviderError` — never swallow.
      (Pedagogy callers convert that into their deterministic fallback.)
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key_resolver: Callable[[], Awaitable[str | None]],
        provider_id: str = "custom",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise GenerativeConfigError("base_url is required for a provider")
        # ``model`` MAY be empty: the gateway then resolves it via model
        # discovery (preset default → first discovered). ``complete``
        # fails closed until a model is resolved.
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key_resolver = api_key_resolver
        self.provider_id = provider_id
        self._timeout = httpx.Timeout(timeout_seconds)
        # Injectable transport (httpx.MockTransport in tests); None → real HTTP.
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model

    async def _key(self) -> str:
        key = await self._api_key_resolver()
        if not key:
            raise SecretStoreUnavailableError(
                f"API key for provider {self.provider_id!r} is not configured"
            )
        return key

    async def supports_vision(self) -> bool:
        from mathtutor.infrastructure.vision import openai_vision_model
        return openai_vision_model(self.provider_id, self.model)

    supports_native_tools = True

    async def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        max_retries: int = 0,
        tools: Sequence[dict] | None = None,
    ) -> CompletionResult:
        if not self._model:
            raise GenerativeConfigError(
                f"provider {self.provider_id!r} has no model resolved — "
                "run gateway.resolve_model() (model discovery) first"
            )
        payload: dict = {
            "model": self._model,
            "messages": list(messages),
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools is not None:
            payload["tools"] = list(tools)
        if self.provider_id == "moonshot" and self._model in {"kimi-k2.5", "kimi-k2.6"}:
            payload.pop("temperature", None)
            payload["thinking"] = {"type": "disabled"}
        if self.provider_id == "deepseek":
            # The bounded tutoring/tool budget is for visible content. A default
            # reasoning mode can consume it entirely before delivering any text.
            payload["thinking"] = {"type": "disabled"}
        if self.provider_id == "deepseek" and any(
            isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"])
            for m in messages
        ):
            import json
            if len(json.dumps(payload).encode("utf-8")) > 48 * 1024 * 1024:
                raise GenerativeConfigError("图片编码后的请求超过 DeepSeek 48 MiB 限制，请减少图片数量或压缩图片。")
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                return await self._post_chat(payload)
            except GenerativeProviderError as error:
                last_error = error
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise GenerativeProviderError(
            f"provider {self.provider_id!r} failed after {max_retries + 1} attempt(s): {last_error}",
            diagnostics=getattr(last_error, "diagnostics", None),
        ) from last_error

    async def complete_streaming(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        on_delta=None,
    ) -> CompletionResult:
        """Server-sent-events variant of ``complete`` with the same result.

        ``on_delta(text_so_far)`` is awaited as content arrives; the caller
        decides what (if anything) may be shown. Tools are not streamed.
        """
        if not self._model:
            raise GenerativeConfigError(f"provider {self.provider_id!r} has no model resolved")
        payload: dict = {"model": self._model, "messages": list(messages), "temperature": temperature,
                         "stream": True, "stream_options": {"include_usage": True}}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if self.provider_id in {"deepseek"} or (self.provider_id == "moonshot" and self._model in {"kimi-k2.5", "kimi-k2.6"}):
            payload["thinking"] = {"type": "disabled"}
            if self.provider_id == "moonshot":
                payload.pop("temperature", None)
        headers = {"Authorization": f"Bearer {await self._key()}", "Content-Type": "application/json"}
        text, finish_reason, usage = "", "", {}
        import json as _json
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self._base_url}/chat/completions", json=payload, headers=headers) as response:
                    if response.status_code == 400:
                        # Some compatible servers reject stream options: answer without streaming.
                        await response.aread()
                        result = await self.complete(messages, temperature=temperature, max_tokens=max_tokens)
                        if on_delta is not None:
                            await on_delta(result.text)
                        return result
                    if response.status_code != 200:
                        detail = (await response.aread())[:300]
                        raise GenerativeProviderError(f"provider {self.provider_id!r} HTTP {response.status_code}: {detail!r}")
                    if "text/event-stream" not in response.headers.get("content-type", ""):
                        # The server ignored stream=true and sent one JSON body.
                        body = _json.loads(await response.aread())
                        message = body["choices"][0]["message"]
                        text = message.get("content") or ""
                        finish_reason = body["choices"][0].get("finish_reason") or ""
                        usage = body.get("usage") or {}
                        if on_delta is not None and text:
                            await on_delta(text)
                        response_kind = "json"
                    else:
                        response_kind = "sse"
                    async for line in (response.aiter_lines() if response_kind == "sse" else _no_lines()):
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = _json.loads(data)
                        except ValueError:
                            raise GenerativeProviderError(f"provider {self.provider_id!r} malformed stream chunk") from None
                        usage = chunk.get("usage") or usage
                        for choice in chunk.get("choices") or ():
                            delta = (choice.get("delta") or {}).get("content") or ""
                            finish_reason = choice.get("finish_reason") or finish_reason
                            if delta:
                                text += delta
                                if on_delta is not None:
                                    await on_delta(text)
        except httpx.HTTPError as error:
            raise GenerativeProviderError(f"provider {self.provider_id!r} transport error: {error}") from error
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise GenerativeProviderError(f"provider {self.provider_id!r} malformed response") from error
        if not text.strip():
            raise GenerativeProviderError(f"provider {self.provider_id!r} returned empty content")
        return CompletionResult(text=text, provider_id=self.provider_id, model=self._model, finish_reason=finish_reason,
                                input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens"),
                                diagnostics={"streamed": True, "finish_reason": finish_reason,
                                             "usage": {k: usage[k] for k in ("prompt_tokens", "completion_tokens") if k in usage}})

    async def probe_connection(self, messages: Sequence[dict]) -> CompletionResult:
        """A bounded connectivity probe, independent of teaching-turn policy."""
        payload = {"model": self._model, "messages": list(messages), "temperature": 0, "max_tokens": 128}
        if self.provider_id == "deepseek":
            payload["thinking"] = {"type": "disabled"}
        if self.provider_id == "moonshot" and self._model in {"kimi-k2.5", "kimi-k2.6"}:
            payload.pop("temperature", None)
            payload["thinking"] = {"type": "disabled"}
        return await self._post_chat(payload)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def _post_chat(self, payload: dict) -> CompletionResult:
        headers = {
            "Authorization": f"Bearer {await self._key()}",
            "Content-Type": "application/json",
        }
        try:
            async with self._client() as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
        except httpx.HTTPError as error:
            raise GenerativeProviderError(
                f"provider {self.provider_id!r} transport error: {error}"
            ) from error
        if response.status_code != 200:
            detail = response.text[:300]
            raise GenerativeProviderError(
                f"provider {self.provider_id!r} HTTP {response.status_code}: {detail}"
            )
        try:
            data = response.json()
            message = data["choices"][0]["message"]
            text = message.get("content") or ""
            tool_calls = message.get("tool_calls") or []
            if not isinstance(tool_calls, list) or len(tool_calls) > 8 or any(not isinstance(c, dict) for c in tool_calls):
                raise ValueError("invalid tool calls")
            finish_reason = data["choices"][0].get("finish_reason") or ""
        except (KeyError, IndexError, ValueError) as error:
            raise GenerativeProviderError(
                f"provider {self.provider_id!r} malformed response: {response.text[:300]!r}"
            ) from error
        # Retain only bounded response metadata, never hidden reasoning or keys.
        usage = data.get("usage") or {}
        diagnostics = {
            "http_status": response.status_code, "server_model": data.get("model"),
            "finish_reason": finish_reason, "content_chars": len(text) if isinstance(text, str) else None,
            "reasoning_chars": len(message.get("reasoning_content") or ""),
            "tool_calls_count": len(tool_calls), "request_max_tokens": payload.get("max_tokens"),
            "request_thinking": payload.get("thinking"),
            "usage": {key: usage[key] for key in ("prompt_tokens", "completion_tokens", "total_tokens",
                      "completion_tokens_details") if key in usage},
        }
        if finish_reason in {"length", "max_tokens"} and (not isinstance(text, str) or not text.strip()):
            raise GenerativeProviderError(f"provider {self.provider_id!r} output truncated before final content",
                                          diagnostics=diagnostics)
        if not isinstance(text, str) or (not text.strip() and not tool_calls):
            raise GenerativeProviderError(
                f"provider {self.provider_id!r} returned empty content", diagnostics=diagnostics
            )
        return CompletionResult(
            text=text,
            provider_id=self.provider_id,
            model=self._model,
            finish_reason=finish_reason,
            input_tokens=(data.get("usage") or {}).get("prompt_tokens"),
            output_tokens=(data.get("usage") or {}).get("completion_tokens"),
            tool_calls=tuple(tool_calls),
            diagnostics=diagnostics,
        )

    async def fetch_models(self) -> list[str]:
        headers = {"Authorization": f"Bearer {await self._key()}"}
        try:
            async with self._client() as client:
                response = await client.get(f"{self._base_url}/models", headers=headers)
        except httpx.HTTPError as error:
            raise GenerativeProviderError(
                f"provider {self.provider_id!r} model discovery transport error: {error}"
            ) from error
        if response.status_code != 200:
            raise GenerativeProviderError(
                f"provider {self.provider_id!r} model discovery HTTP "
                f"{response.status_code}: {response.text[:300]}"
            )
        try:
            entries = response.json()["data"]
            return sorted(str(entry["id"]) for entry in entries)
        except (KeyError, TypeError, ValueError) as error:
            raise GenerativeProviderError(
                f"provider {self.provider_id!r} malformed /models response"
            ) from error


class OllamaProviderAdapter:
    """Native Ollama adapter.

    Ollama is intentionally not disguised as a credentialed cloud provider:
    it uses ``/api/tags`` for the machine's installed models and
    ``/api/chat`` for generation, and never asks the SecretStore for a key.
    """

    provider_id = "ollama"

    def __init__(
        self,
        *,
        base_url: str,
        model: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url:
            raise GenerativeConfigError("base_url is required for Ollama")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = httpx.Timeout(timeout_seconds)
        self._transport = transport

    @property
    def model(self) -> str:
        return self._model

    def set_model(self, model: str) -> None:
        self._model = model

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def fetch_models(self) -> list[str]:
        try:
            async with self._client() as client:
                response = await client.get(f"{self._base_url}/api/tags")
        except httpx.HTTPError as error:
            raise GenerativeProviderError(
                f"provider 'ollama' transport error: {error}"
            ) from error
        if response.status_code != 200:
            raise GenerativeProviderError(
                f"provider 'ollama' HTTP {response.status_code}: {response.text[:300]}"
            )
        try:
            entries = response.json()["models"]
            names = {
                str(entry.get("name") or entry.get("model") or "").strip()
                for entry in entries
                if isinstance(entry, dict)
            }
        except (KeyError, TypeError, ValueError) as error:
            raise GenerativeProviderError("provider 'ollama' malformed /api/tags response") from error
        return sorted(name for name in names if name)

    async def supports_vision(self) -> bool:
        try:
            async with self._client() as client:
                response = await client.post(f"{self._base_url}/api/show", json={"model": self.model}, timeout=5)
                return response.status_code == 200 and "vision" in response.json().get("capabilities", [])
        except (httpx.HTTPError, ValueError, TypeError):
            return False

    async def complete(
        self,
        messages: Sequence[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        max_retries: int = 0,
    ) -> CompletionResult:
        if not self._model:
            raise GenerativeConfigError(
                "provider 'ollama' has no model resolved — select an installed model"
            )
        options: dict[str, int | float] = {"temperature": temperature}
        from mathtutor.infrastructure.vision import ollama_messages
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        payload = {
            "model": self._model,
            "messages": ollama_messages(messages),
            "stream": False,
            "options": options,
        }
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                async with self._client() as client:
                    response = await client.post(f"{self._base_url}/api/chat", json=payload)
                if response.status_code != 200:
                    raise GenerativeProviderError(
                        f"provider 'ollama' HTTP {response.status_code}: {response.text[:300]}"
                    )
                data = response.json()
                text = data["message"]["content"]
                if not isinstance(text, str) or not text.strip():
                    raise GenerativeProviderError("provider 'ollama' returned empty content")
                return CompletionResult(
                    text=text,
                    provider_id=self.provider_id,
                    model=self._model,
                    finish_reason=str(data.get("done_reason") or ""),
                    input_tokens=data.get("prompt_eval_count"),
                    output_tokens=data.get("eval_count"),
                )
            except (httpx.HTTPError, KeyError, TypeError, ValueError, GenerativeProviderError) as error:
                last_error = error
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
        if isinstance(last_error, GenerativeProviderError):
            raise last_error
        raise GenerativeProviderError(f"provider 'ollama' transport error: {last_error}")


class GatewayRoleClient:
    """Adapter to the legacy ``LLMClient`` calling convention.

    ``LLMTutorWriter`` calls ``client.complete(prompt=..., system_prompt=...,
    temperature=..., max_tokens=..., max_retries=...)`` and expects a plain
    string back. This class makes a gateway role look exactly like that —
    so wiring the gateway into pedagogy is injection-only, no writer edits.
    """

    def __init__(self, gateway: "GenerativeModelGateway", role: ModelRole) -> None:
        self._gateway = gateway
        self._role = role

    async def complete_result(
        self, *, prompt: str, system_prompt: str = "", temperature: float = 0.4,
        max_tokens: int | None = None, max_retries: int = 0,
    ) -> CompletionResult:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return await self._gateway.complete(self._role, messages, temperature=temperature,
            max_tokens=max_tokens, max_retries=max_retries)

    async def complete(self, **kwargs) -> str:
        """Compatibility adapter for non-tutor consumers; TutorWriter uses complete_result."""
        return (await self.complete_result(**kwargs)).text


class GenerativeModelGateway:
    """Role→provider registry + the only generative entry point.

    Providers are registered per ROLE (one role → one provider). Every
    call site resolves through this gateway; nothing outside
    ``infrastructure/`` ever imports a vendor SDK or a preset id.
    """

    def __init__(self, secret_store: SecretStore | None = None) -> None:
        self._secret_store = secret_store
        self._by_role: dict[ModelRole, GenerativeModelProvider] = {}
        self._by_id: dict[str, GenerativeModelProvider] = {}

    # ------------------------------------------------------- registration

    def register_provider(
        self,
        role: ModelRole,
        provider: GenerativeModelProvider,
    ) -> None:
        """Bind a role to a provider (overwrites any previous binding)."""
        self._by_role[role] = provider
        self._by_id[provider.provider_id] = provider

    def register_openai_compatible(
        self,
        role: ModelRole,
        *,
        provider_id: str,
        base_url: str,
        model: str,
        secret_key: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> OpenAICompatibleProvider:
        """Configure a role from the desktop settings surface.

        ``secret_key`` is the SecretStore key NAME — the value stays in the
        store (OS credential store in the shipped desktop app).
        """
        store = self._secret_store
        if store is None:
            raise GenerativeConfigError(
                "gateway has no SecretStore — API keys cannot be resolved"
            )

        async def resolve_key() -> str | None:
            return await store.get(secret_key)

        provider = OpenAICompatibleProvider(
            base_url=base_url,
            model=model,
            api_key_resolver=resolve_key,
            provider_id=provider_id,
            timeout_seconds=timeout_seconds,
        )
        self.register_provider(role, provider)
        return provider

    def register_ollama(
        self,
        role: ModelRole,
        *,
        base_url: str,
        model: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> OllamaProviderAdapter:
        provider = OllamaProviderAdapter(
            base_url=base_url,
            model=model,
            timeout_seconds=timeout_seconds,
        )
        self.register_provider(role, provider)
        return provider

    def unregister(self, role: ModelRole) -> None:
        self._by_role.pop(role, None)

    # ------------------------------------------------------------- queries

    def provider_for(self, role: ModelRole) -> GenerativeModelProvider | None:
        if model_calls_blocked.get():
            return None
        return self._by_role.get(role)

    def client_for(self, role: ModelRole) -> GatewayRoleClient | None:
        if role not in self._by_role:
            return None
        return GatewayRoleClient(self, role)

    def configured_roles(self) -> list[ModelRole]:
        return list(self._by_role)

    # ----------------------------------------------------------- generation

    async def complete(
        self,
        role: ModelRole,
        messages: Sequence[dict],
        *,
        temperature: float = 0.4,
        max_tokens: int | None = None,
        max_retries: int = 0,
        connection_probe: bool = False,
        tool_executor=None,
        structured_tools: bool = False,
    ) -> CompletionResult:
        provider = None if model_calls_blocked.get() else self._by_role.get(role)
        if provider is None:
            raise GenerativeConfigError(f"no generative provider for role {role.value!r}")
        if connection_probe:
            probe = getattr(provider, "probe_connection", None)
            result = await asyncio.wait_for(
                probe(messages) if probe else provider.complete(messages, temperature=0, max_tokens=128, max_retries=0),
                timeout=30,
            )
            if result.finish_reason in {"length", "max_tokens"}:
                raise GenerativeProviderError("connection probe output truncated")
            return result
        if any(isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"]) for m in messages):
            from mathtutor.infrastructure.vision import supports_vision, VISION_UNSUPPORTED
            if not await supports_vision(provider):
                raise GenerativeConfigError(VISION_UNSUPPORTED)
        if role == ModelRole.TUTOR_WRITER:
            if tool_executor is not None:
                from mathtutor.application.tutor_runtime import complete_tools
                return await complete_tools(provider, messages, executor=tool_executor,
                    structured=structured_tools, temperature=temperature, max_tokens=max_tokens)
            from mathtutor.application.tutor_runtime import complete_tutor
            return await complete_tutor(provider, messages, temperature=temperature, max_tokens=max_tokens, max_retries=max_retries)
        from mathtutor.application.tutor_runtime import complete_auxiliary
        return await complete_auxiliary(provider, messages, temperature=temperature,
            max_tokens=max_tokens, max_retries=max_retries)

    # ---------------------------------------------------------- discovery

    async def fetch_models(self, provider_id: str) -> list[str]:
        """System-side model discovery (GET /models) — never a user chore."""
        provider = self._by_id.get(provider_id)
        if provider is None:
            raise GenerativeConfigError(f"unknown provider id {provider_id!r}")
        return await provider.fetch_models()

    async def resolve_model(self, provider_id: str) -> str:
        """Concrete model for a provider: configured → preset default →
        first discovered. Raises when nothing is discoverable."""
        provider = self._by_id.get(provider_id)
        if provider is None:
            raise GenerativeConfigError(f"unknown provider id {provider_id!r}")
        if provider.model:
            return provider.model
        preset = PRESETS.get(provider_id)
        models = await provider.fetch_models()
        if preset and preset.default_model in models:
            resolved = preset.default_model
        elif models:
            resolved = models[0]
        else:
            raise GenerativeConfigError(
                f"provider {provider_id!r} exposes no models and none is configured"
            )
        # Materialize the discovery result on every role binding without
        # rebuilding providers (preserves transports, timeouts and clients).
        for bound in self._by_role.values():
            if bound.provider_id == provider_id:
                bound.set_model(resolved)
        return resolved


__all__ = [
    "CompletionResult",
    "DEFAULT_TIMEOUT_SECONDS",
    "GenerativeConfigError",
    "GenerativeModelGateway",
    "GenerativeModelProvider",
    "GenerativeProviderError",
    "GatewayRoleClient",
    "ModelRole",
    "OpenAICompatibleProvider",
    "OllamaProviderAdapter",
    "PRESETS",
    "ProviderPreset",
]
