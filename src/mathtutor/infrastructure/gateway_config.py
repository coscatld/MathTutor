"""Generative gateway configuration service — the desktop cutover surface (§6.4).

Product story: an ordinary user picks a provider and optionally overrides
its model. Cloud credentials live in the OS store; Ollama is keyless and
uses its native local API. Provider-specific model choices persist across
switches and restarts.

Security invariants enforced here (they also hold for the whole gateway):

- the API key enters ONLY the :class:`SecretStore` (key name
  ``generative.api_key.<preset_id>``); it never appears in the persisted
  config JSON, in repr/log output, or in error messages — provider binding
  references the key by NAME and the store resolves the value at call time;
- provider binding is per ROLE: ``TUTOR_WRITER`` and ``PRACTICE_GENERATOR``
  share ONE provider — one generative account serves the whole product
  (system policy: one provider per deployment);
- the LLM is never a math authority: this module only wires writers; it
  participates in no judging/verification/release logic.

:func:`build_tutor_writer` is the fail-closed factory the product uses in
``product_state._build_writer``: the deterministic template writer unless
the gateway is registered AND has a resolved model — a provider outage or a
missing secret can never break the teaching flow.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict

from mathtutor.infrastructure.generative_gateway import (
    GenerativeConfigError,
    GenerativeModelGateway,
    ModelRole,
    PRESETS,
)
from mathtutor.infrastructure.secret_store import SecretStore
from mathtutor.pedagogy.tutor_writer import (
    LLMTutorWriter,
    TemplateTutorWriter,
    TutorWriter,
)
from mathtutor.pedagogy.writer_settings import MathTutorWriterSettings

logger = logging.getLogger(__name__)

CONFIG_VERSION = 2

# One generative account serves every product role (system policy).
ALL_ROLES = (ModelRole.TUTOR_WRITER, ModelRole.PRACTICE_GENERATOR)


def secret_key_name(preset_id: str) -> str:
    """SecretStore key NAME for a preset (never the secret itself)."""
    return f"generative.api_key.{preset_id}"


#: Desktop wire contract: the five distinct failure kinds the settings UI
#: maps onto friendly copy. Never derived from a key VALUE — only from the
#: redacted error shape.
ModelErrorKind = Literal[
    "credential_invalid",
    "network_unavailable",
    "provider_unsupported",
    "model_unavailable",
    "gateway_disabled",
]


def classify_gateway_error(message: str) -> ModelErrorKind:
    """Map a REDACTED provider error message onto the desktop error kinds.

    The patterns mirror the gateway's own error strings
    (``generative_gateway``): no key material can survive ``_redact``, and
    an unknown shape degrades to ``provider_unsupported`` — never a guess
    that blames the user's credential.
    """
    lowered = message.lower()
    if "no provider configured" in lowered:
        return "gateway_disabled"
    if "has no model resolved" in lowered:
        return "gateway_disabled"
    if "http 401" in lowered or "http 403" in lowered:
        return "credential_invalid"
    if "invalid api key" in lowered or "incorrect api key" in lowered:
        return "credential_invalid"
    if "http 404" in lowered:
        return "model_unavailable"
    if "model unavailable" in lowered or "no models" in lowered:
        return "model_unavailable"
    if "transport error" in lowered or "timeout" in lowered:
        return "network_unavailable"
    return "provider_unsupported"


class GatewayConnectionResult(BaseModel):
    """Non-sensitive outcome of a connectivity/discovery probe.

    ``message`` is redacted: it must never carry an API key value.
    ``error_kind`` is the desktop wire contract's five-way classification
    (None on success) — the settings UI maps it onto distinct friendly copy.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["ok", "error"] = "error"
    message: str = ""
    resolved_model: str = ""
    error_kind: ModelErrorKind | None = None


class GatewayConfigService:
    """Configure gateway providers and restore them across restarts.

    Construction auto-restores a persisted (non-sensitive) config JSON when
    ``config_path`` exists: roles are re-registered with the SAME secret key
    NAME; the key value is resolved from the SecretStore at call time.
    """

    def __init__(
        self,
        gateway: GenerativeModelGateway,
        secret_store: SecretStore,
        config_path: Path | None = None,
    ) -> None:
        self._gateway = gateway
        self._secret_store = secret_store
        self._config_path = config_path
        self._provider_id: str | None = None
        self._config: dict = {}
        self._connection_status = "unconfigured"
        if config_path is not None and config_path.is_file():
            self._restore(config_path)

    # ------------------------------------------------------------- helpers

    def _register(self, *, preset_id: str, base_url: str, model: str) -> None:
        """Bind BOTH product roles to one provider (system policy)."""
        preset = PRESETS[preset_id]
        for role in ALL_ROLES:
            if preset.local:
                self._gateway.register_ollama(
                    role, base_url=base_url, model=model
                )
            else:
                self._gateway.register_openai_compatible(
                    role,
                    provider_id=preset_id,
                    base_url=base_url,
                    model=model,
                    secret_key=secret_key_name(preset_id),
                )

    @staticmethod
    def _valid_ollama_url(value: str) -> bool:
        parsed = urlparse(value)
        return (
            parsed.scheme in {"http", "https"}
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            and not parsed.username
            and not parsed.password
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )

    def _profiles(self) -> dict[str, dict[str, str]]:
        profiles = self._config.get("provider_configs")
        if not isinstance(profiles, dict):
            profiles = {}
            self._config["provider_configs"] = profiles
        return profiles

    def _persist(self, config: dict) -> None:
        """Best-effort write of the NON-sensitive config (0600 when possible).

        Never called with a key value in ``config``. A persistence failure
        is not fatal: registration is the source of truth for this process.
        """
        if self._config_path is None:
            return
        payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
        try:
            fd = os.open(
                self._config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
        except OSError:
            try:
                self._config_path.write_text(payload, encoding="utf-8")
            except OSError:
                logger.warning(
                    "GatewayConfigService: config persistence failed (best-effort)",
                    exc_info=True,
                )
            return
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
        except OSError:
            logger.warning(
                "GatewayConfigService: config persistence failed (best-effort)",
                exc_info=True,
            )

    def _restore(self, path: Path) -> None:
        """Re-register providers from a persisted JSON (never reads keys)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # corrupt/unreadable → start unconfigured (fail closed)
        if not isinstance(data, dict):
            return
        onboarding_completed = bool(data.get("onboarding_completed", False))
        preset_id = data.get("preset_id")
        preset = PRESETS.get(preset_id)
        if preset is None:
            # A user may explicitly finish onboarding in template-only mode.
            # This marker is non-sensitive and must survive restarts even
            # though there is intentionally no provider to register.
            if onboarding_completed:
                self._config = {
                    "onboarding_completed": True,
                    "config_version": int(
                        data.get("config_version") or CONFIG_VERSION
                    ),
                }
            return  # unknown preset → ignore the file (fail closed)
        raw_profiles = data.get("provider_configs")
        profiles: dict[str, dict[str, str]] = {}
        if isinstance(raw_profiles, dict):
            for profile_id, raw in raw_profiles.items():
                profile_preset = PRESETS.get(str(profile_id))
                if profile_preset is None or not isinstance(raw, dict):
                    continue
                profile_base = str(raw.get("base_url") or "") or profile_preset.base_url
                if not profile_preset.editable_base_url:
                    profile_base = profile_preset.base_url
                if profile_preset.local and not self._valid_ollama_url(profile_base):
                    profile_base = profile_preset.base_url
                profiles[str(profile_id)] = {
                    "base_url": profile_base,
                    "model": str(raw.get("model") or "") or profile_preset.default_model,
                }
        # Version-1 migration: promote the former single active config into
        # the new provider profile map without changing the user's selection.
        active_profile = profiles.get(str(preset_id), {})
        base_url = str(active_profile.get("base_url") or data.get("base_url") or "") or preset.base_url
        if not preset.editable_base_url:
            base_url = preset.base_url
        if preset.local and not self._valid_ollama_url(base_url):
            base_url = preset.base_url
        model = str(active_profile.get("model") or data.get("model") or "") or preset.default_model
        profiles[str(preset_id)] = {"base_url": base_url, "model": model}
        role_names = data.get("roles")
        if isinstance(role_names, list) and role_names:
            roles: list[ModelRole] = []
            for name in role_names:
                try:
                    roles.append(ModelRole(name))
                except ValueError:
                    continue
        else:
            roles = list(ALL_ROLES)
        if not roles:
            return
        self._register(preset_id=str(preset_id), base_url=base_url, model=model)
        self._provider_id = preset_id
        self._connection_status = "configured"
        self._config = {
            "preset_id": preset_id,
            "model": model,
            "base_url": base_url,
            "roles": [role.value for role in roles],
            "provider_configs": profiles,
            # Existing provider configs predate this field. Treat them as a
            # completed first run so upgrades never show onboarding again.
            "onboarding_completed": True,
            "config_version": CONFIG_VERSION,
        }
        if int(data.get("config_version") or 1) < CONFIG_VERSION:
            self._persist(self._config)

    async def _redact(self, message: str) -> str:
        """Strip any stored secret VALUE from an error message (defense in
        depth: e.g. a remote endpoint echoing the Authorization header)."""
        provider_id = self._provider_id
        if not provider_id or not message:
            return message
        try:
            secret = await self._secret_store.get(secret_key_name(provider_id))
        except Exception:
            return message
        if secret:
            message = message.replace(secret, "[REDACTED]")
        return message

    async def _error_result(self, message: str) -> GatewayConnectionResult:
        """Redacted error result with the desktop error-kind classification.

        Classification runs on the REDACTED message only — the kind is a
        shape decision, never derived from a key value.
        """
        redacted = await self._redact(message)
        self._connection_status = "failure"
        return GatewayConnectionResult(
            status="error",
            message=redacted,
            error_kind=classify_gateway_error(redacted),
        )

    # --------------------------------------------------------- public API

    async def apply_config(
        self,
        *,
        preset_id: str,
        api_key: str | None = None,
        base_url: str = "",
        model: str = "",
    ) -> dict:
        """Apply a provider preset and bind every product role to it.

        - every provider accepts an explicit model; defaults apply only when
          the saved model is empty;
        - only custom/Ollama endpoints are editable; Ollama stays loopback;
        - a non-empty ``api_key`` goes ONLY into the SecretStore;
        - the persisted JSON carries policy fields only — never the key.
        """
        preset = PRESETS.get(preset_id)
        if preset is None:
            raise GenerativeConfigError(f"unknown provider preset {preset_id!r}")
        base_url = base_url.strip()
        model = model.strip()
        profiles = self._profiles()
        prior = profiles.get(preset_id, {})
        if preset.custom:
            if not base_url:
                raise GenerativeConfigError(
                    "the 'custom' preset requires base_url"
                )
            effective_base_url = base_url
        elif preset.local:
            effective_base_url = base_url or str(prior.get("base_url") or "") or preset.base_url
            if not self._valid_ollama_url(effective_base_url):
                raise GenerativeConfigError("Ollama base_url must be a loopback HTTP URL")
        else:
            if base_url and base_url != preset.base_url:
                raise GenerativeConfigError(
                    f"preset {preset_id!r} has a fixed base_url"
                )
            effective_base_url = preset.base_url
        effective_model = model or preset.default_model
        if api_key and preset.requires_api_key:
            await self._secret_store.put(secret_key_name(preset_id), api_key)
        self._register(
            preset_id=preset_id,
            base_url=effective_base_url,
            model=effective_model,
        )
        self._provider_id = preset_id
        self._connection_status = "configured"
        profiles[preset_id] = {
            "model": effective_model,
            "base_url": effective_base_url,
        }
        self._config = {
            "preset_id": preset_id,
            "model": effective_model,
            "base_url": effective_base_url,
            "roles": [role.value for role in ALL_ROLES],
            "provider_configs": profiles,
            "onboarding_completed": True,
            "config_version": CONFIG_VERSION,
        }
        self._persist(self._config)
        return dict(self._config)

    async def discover_models(self) -> list[str] | GatewayConnectionResult:
        """System-side model discovery; never a user chore.

        Success → sorted model ids. Failure → a ``GatewayConnectionResult``
        with status "error" whose message is redacted (never a key value).
        The underlying provider error is NOT swallowed at the gateway level:
        ``gateway.fetch_models`` still raises for direct callers.
        """
        provider_id = self._provider_id
        if provider_id is None:
            return await self._error_result("no provider configured")
        try:
            return await self._gateway.fetch_models(provider_id)
        except Exception as error:
            return await self._error_result(str(error))

    async def test_connection(self) -> GatewayConnectionResult:
        """Resolve the concrete model and report connectivity.

        On success the resolved model is materialized on the registered
        providers (the system's model-resolution job) and persisted — so a
        restart can restore a fully-configured gateway without discovery.
        """
        provider_id = self._provider_id
        if provider_id is None:
            return await self._error_result("no provider configured")
        self._connection_status = "connecting"
        try:
            preset = PRESETS.get(provider_id)
            if preset is not None and preset.local:
                models = await self._gateway.fetch_models(provider_id)
                configured = str(self._config.get("model") or "")
                model_aliases = {name.removesuffix(":latest") for name in models}
                if configured and configured not in models and configured not in model_aliases:
                    return await self._error_result(
                        f"provider 'ollama' model unavailable: {configured}"
                    )
            resolved = await self._gateway.resolve_model(provider_id)
        except Exception as error:
            return await self._error_result(str(error))
        if self._config.get("model", "") != resolved:
            self._config["model"] = resolved
            self._profiles().setdefault(provider_id, {})["model"] = resolved
            self._persist(self._config)
        try:
            await self._gateway.complete(
                ModelRole.TUTOR_WRITER,
                [{"role": "user", "content": "只回复：连接成功"}],
                temperature=0,
                max_tokens=12,
                max_retries=0,
            )
        except Exception as error:
            return await self._error_result(str(error))
        self._connection_status = "success"
        preset = PRESETS.get(provider_id)
        message = "已连接到本地 Ollama。" if preset is not None and preset.local else "模型已响应，配置可以使用。"
        return GatewayConnectionResult(status="ok", message=message, resolved_model=resolved)

    def current_config(self) -> dict:
        """Non-sensitive config snapshot (no key, no key name)."""
        return dict(self._config)

    def provider_profiles(self) -> dict[str, dict[str, str]]:
        """All saved non-sensitive provider profiles for UI switching."""
        return {
            key: dict(value)
            for key, value in self._profiles().items()
            if key in PRESETS and isinstance(value, dict)
        }

    def connection_status(self) -> str:
        return self._connection_status

    async def has_api_key(self, preset_id: str | None = None) -> bool:
        """Return only whether a provider credential exists."""
        provider_id = preset_id or self._provider_id
        if provider_id is None:
            return False
        preset = PRESETS.get(provider_id)
        if preset is not None and not preset.requires_api_key:
            return False
        try:
            return bool(
                await self._secret_store.get(secret_key_name(provider_id))
            )
        except Exception:
            return False

    def onboarding_completed(self) -> bool:
        """Whether first-run provider onboarding was configured or skipped."""
        return bool(self._config.get("onboarding_completed", False))

    def mark_onboarding_completed(self) -> dict:
        """Persist an explicit template-only onboarding choice."""
        self._config["onboarding_completed"] = True
        self._config.setdefault("config_version", CONFIG_VERSION)
        self._persist(self._config)
        return self.current_config()

    async def remove_api_key(self) -> dict:
        """Delete the current credential and leave template mode usable."""
        if self._provider_id is not None:
            await self._secret_store.delete(secret_key_name(self._provider_id))
        for role in ALL_ROLES:
            self._gateway.unregister(role)
        self._connection_status = "unconfigured"
        self._config["onboarding_completed"] = True
        self._config.setdefault("config_version", CONFIG_VERSION)
        self._persist(self._config)
        return self.current_config()

    async def is_ready(self) -> bool:
        provider = self._gateway.provider_for(ModelRole.TUTOR_WRITER)
        if provider is None or not provider.model or self._provider_id is None:
            return False
        preset = PRESETS[self._provider_id]
        return not preset.requires_api_key or await self.has_api_key()

    def is_configured(self) -> bool:
        """True when the writer role has a provider with a usable model."""
        provider = self._gateway.provider_for(ModelRole.TUTOR_WRITER)
        if provider is None:
            return False
        return bool(provider.model)


def build_tutor_writer(
    gateway: GenerativeModelGateway,
    settings: MathTutorWriterSettings,
) -> TutorWriter:
    """Fail-closed writer factory for ``product_state._build_writer``.

    Order of checks (any failure → deterministic template writer):

    1. ``settings.enabled`` false → template;
    2. no TUTOR_WRITER provider registered → template;
    3. provider model not resolved → template;
    4. any unexpected exception → template.
    """
    try:
        if not settings.enabled:
            return TemplateTutorWriter()
        provider = gateway.provider_for(ModelRole.TUTOR_WRITER)
        if provider is None or not provider.model:
            return TemplateTutorWriter()
        client = gateway.client_for(ModelRole.TUTOR_WRITER)
        return LLMTutorWriter(client=client, settings=settings)
    except Exception:
        logger.warning(
            "build_tutor_writer: gateway unusable — template writer", exc_info=True
        )
        return TemplateTutorWriter()


__all__ = [
    "ALL_ROLES",
    "CONFIG_VERSION",
    "GatewayConfigService",
    "GatewayConnectionResult",
    "ModelErrorKind",
    "build_tutor_writer",
    "classify_gateway_error",
    "secret_key_name",
]
