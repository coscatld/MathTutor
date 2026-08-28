"""Generative gateway configuration service — the desktop cutover surface (§6.4).

Product story: an ordinary user picks a provider PRESET and pastes an API
key — nothing else. Only the ``custom`` preset additionally accepts
``base_url`` + ``model``. The SYSTEM owns model discovery (``GET /models``)
and resolves the concrete model when none was configured.

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

CONFIG_VERSION = 1

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
        if config_path is not None and config_path.is_file():
            self._restore(config_path)

    # ------------------------------------------------------------- helpers

    def _register(self, *, preset_id: str, base_url: str, model: str) -> None:
        """Bind BOTH product roles to one provider (system policy)."""
        for role in ALL_ROLES:
            self._gateway.register_openai_compatible(
                role,
                provider_id=preset_id,
                base_url=base_url,
                model=model,
                secret_key=secret_key_name(preset_id),
            )

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
        preset_id = data.get("preset_id")
        preset = PRESETS.get(preset_id)
        if preset is None:
            return  # unknown preset → ignore the file (fail closed)
        base_url = str(data.get("base_url") or "") or preset.base_url
        if not preset.custom and base_url != preset.base_url:
            # Preset endpoints are fixed by policy; never trust an override.
            base_url = preset.base_url
        model = str(data.get("model") or "")
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
        for role in roles:
            self._gateway.register_openai_compatible(
                role,
                provider_id=preset_id,
                base_url=base_url,
                model=model,
                secret_key=secret_key_name(preset_id),
            )
        self._provider_id = preset_id
        self._config = {
            "preset_id": preset_id,
            "model": model,
            "base_url": base_url,
            "roles": [role.value for role in roles],
            "config_version": int(data.get("config_version") or CONFIG_VERSION),
        }

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

        - ordinary presets are fixed: a non-empty ``base_url``/``model`` is
          rejected (only the ``custom`` preset accepts them);
        - ``custom`` requires ``base_url`` (model optional → discovery);
        - a non-empty ``api_key`` goes ONLY into the SecretStore;
        - the persisted JSON carries policy fields only — never the key.
        """
        preset = PRESETS.get(preset_id)
        if preset is None:
            raise GenerativeConfigError(f"unknown provider preset {preset_id!r}")
        if preset.custom:
            if not base_url:
                raise GenerativeConfigError(
                    "the 'custom' preset requires base_url"
                )
            effective_base_url = base_url
            effective_model = model
        else:
            if base_url or model:
                raise GenerativeConfigError(
                    f"preset {preset_id!r} is fixed: base_url/model are only "
                    "configurable through the 'custom' preset"
                )
            effective_base_url = preset.base_url
            effective_model = ""
        if api_key:
            await self._secret_store.put(secret_key_name(preset_id), api_key)
        self._register(
            preset_id=preset_id,
            base_url=effective_base_url,
            model=effective_model,
        )
        self._provider_id = preset_id
        self._config = {
            "preset_id": preset_id,
            "model": effective_model,
            "base_url": effective_base_url,
            "roles": [role.value for role in ALL_ROLES],
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
        try:
            resolved = await self._gateway.resolve_model(provider_id)
        except Exception as error:
            return await self._error_result(str(error))
        if self._config.get("model", "") != resolved:
            self._register(
                preset_id=provider_id,
                base_url=self._config.get("base_url", ""),
                model=resolved,
            )
            self._config["model"] = resolved
            self._persist(self._config)
        return GatewayConnectionResult(status="ok", resolved_model=resolved)

    def current_config(self) -> dict:
        """Non-sensitive config snapshot (no key, no key name)."""
        return dict(self._config)

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
