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

import asyncio
from copy import copy, deepcopy
from dataclasses import dataclass
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from mathtutor.infrastructure.generative_gateway import (
    GenerativeConfigError,
    GenerativeModelGateway,
    GenerativeModelProvider,
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
    "response_incomplete",
    "request_rejected",
    "quota_exceeded",
    "rate_limited",
    "provider_error",
]


def classify_gateway_error(message: str) -> ModelErrorKind:
    """Map a REDACTED provider error message onto the desktop error kinds.

    The patterns mirror the gateway's own error strings
    (``generative_gateway``): no key material can survive ``_redact``, and
    an unknown shape degrades to ``provider_error`` — never a guess
    that blames the user's credential.
    """
    lowered = message.lower()
    if "output truncated" in lowered or "empty content" in lowered:
        return "response_incomplete"
    if "http 402" in lowered or "insufficient_quota" in lowered:
        return "quota_exceeded"
    if "http 429" in lowered:
        return "rate_limited"
    if "http 400" in lowered or "http 422" in lowered:
        return "request_rejected"
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
    return "provider_error"


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
    epoch: str = ""
    revision: int = 0
    current_revision: int = 0
    operation_id: str = ""
    provider_id: str = ""
    accepted: bool = True
    persisted: bool = False
    persistence_error: str | None = None


class GatewayRevisionConflict(GenerativeConfigError):
    """The caller is attempting to replace a newer configuration."""


@dataclass(frozen=True)
class _ProbeSnapshot:
    revision: int
    operation_id: str
    provider_id: str
    model: str
    provider: GenerativeModelProvider | None
    bindings: tuple
    mutation: int


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
        self._revision = 0
        self._epoch = str(uuid4())
        self._persisted = False
        self._persistence_error: str | None = "persistence_unavailable" if config_path is None else None
        self._mutation_lock = asyncio.Lock()
        self._mutation_generation = 0
        if config_path is not None and config_path.is_file():
            self._restore(config_path)

    # ------------------------------------------------------------- helpers

    def _register(self, *, preset_id: str, base_url: str, model: str, vision_mode: str = "auto") -> None:
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
            self._gateway.provider_for(role).vision_mode = vision_mode

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

    def _persist(self, config: dict) -> bool:
        """Commit a non-secret JSON through a closed, fsynced sibling file.

        A write/fsync/replace failure keeps the previous JSON intact. This
        does not promise directory-entry durability across arbitrary power loss.
        Runtime registration remains usable when persistence is unavailable.
        """
        self._persisted = False
        if self._config_path is None:
            self._persistence_error = "persistence_unavailable"
            return False
        temporary: str | None = None
        try:
            payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
            fd, temporary = tempfile.mkstemp(
                dir=self._config_path.parent, prefix=f".{self._config_path.name}.", suffix=".tmp"
            )
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            # Close the temporary handle before replacing (also on Windows).
            os.replace(temporary, self._config_path)
            temporary = None
        except OSError:
            self._persistence_error = "config_write_failed"
            logger.warning("GatewayConfigService: runtime config active; JSON commit failed")
            return False
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    logger.warning("GatewayConfigService: temporary config cleanup failed")
        self._persisted = True
        self._persistence_error = None
        return True

    def revision(self) -> int:
        return self._revision

    def _advance_revision(self) -> None:
        self._revision += 1
        self._mutation_generation += 1
        self._config["revision"] = self._revision
        self._connection_status = "configured" if self._gateway.provider_for(ModelRole.TUTOR_WRITER) else "unconfigured"
        self._persisted = False

    def _check_revision(self, expected_revision: int | None, expected_epoch: str | None = None) -> None:
        if (expected_epoch is not None and expected_epoch != self._epoch) or (expected_revision is not None and expected_revision != self._revision):
            raise GatewayRevisionConflict("configuration revision changed")

    async def _capture_probe(self, operation_id: str | None) -> tuple[_ProbeSnapshot, str | None]:
        async with self._mutation_lock:
            provider = self._gateway.provider_for(ModelRole.TUTOR_WRITER)
            snapshot = _ProbeSnapshot(
                self._revision, operation_id or str(uuid4()), self._provider_id or "",
                str(self._config.get("model") or ""), copy(provider) if provider else None,
                tuple((role, self._gateway.provider_for(role)) for role in ALL_ROLES), self._mutation_generation,
            )
            secret = None
            if snapshot.provider_id:
                try:
                    secret = await self._secret_store.get(secret_key_name(snapshot.provider_id))
                except Exception:
                    pass
            # This short-lived copy must not resolve a later rotated key.
            # No credential is written to config, a result, a log, or a provider value field.
            if snapshot.provider is not None and hasattr(snapshot.provider, "_api_key_resolver"):
                async def captured_secret():
                    return secret
                snapshot.provider._api_key_resolver = captured_secret
            return snapshot, secret

    def _probe_current(self, snapshot: _ProbeSnapshot) -> bool:
        return (snapshot.mutation == self._mutation_generation and snapshot.revision == self._revision and snapshot.provider_id == (self._provider_id or "")
                and all(self._gateway.provider_for(role) is provider for role, provider in snapshot.bindings))

    def _probe_fields(self, snapshot: _ProbeSnapshot) -> dict:
        return {"epoch": self._epoch, "revision": snapshot.revision, "current_revision": self._revision,
                "operation_id": snapshot.operation_id, "provider_id": snapshot.provider_id,
                "accepted": self._probe_current(snapshot), "persisted": self._persisted,
                "persistence_error": self._persistence_error}

    def _restore(self, path: Path) -> None:
        """Re-register providers from a persisted JSON (never reads keys)."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # corrupt/unreadable → start unconfigured (fail closed)
        if not isinstance(data, dict):
            return
        try:
            self._revision = max(0, int(data.get("revision", 0)))
        except (TypeError, ValueError):
            self._revision = 0
        self._persisted = True
        self._persistence_error = None
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
                if raw.get("vision_mode") in {"enabled", "disabled"}:
                    profiles[str(profile_id)]["vision_mode"] = raw["vision_mode"]
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
        vision_mode = active_profile.get("vision_mode", "auto")
        if vision_mode != "auto":
            profiles[str(preset_id)]["vision_mode"] = vision_mode
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
        self._register(preset_id=str(preset_id), base_url=base_url, model=model, vision_mode=vision_mode)
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

    async def _error_result(self, message: str, snapshot: _ProbeSnapshot | None = None, secret: str | None = None) -> GatewayConnectionResult:
        """Redacted error result with the desktop error-kind classification.

        Classification runs on the REDACTED message only — the kind is a
        shape decision, never derived from a key value.
        """
        redacted = message.replace(secret, "[REDACTED]") if secret else await self._redact(message)
        if snapshot is None or self._probe_current(snapshot):
            self._connection_status = "failure"
        return GatewayConnectionResult(
            status="error",
            message=redacted,
            error_kind=classify_gateway_error(redacted),
            **(self._probe_fields(snapshot) if snapshot else {}),
        )

    # --------------------------------------------------------- public API

    async def apply_config(
        self,
        *,
        preset_id: str,
        api_key: str | None = None,
        base_url: str = "",
        model: str = "",
        vision_mode: Literal["auto", "enabled", "disabled"] | None = None,
        expected_revision: int | None = None,
        expected_epoch: str | None = None,
        operation_id: str | None = None,
    ) -> dict:
        """Apply a provider preset and bind every product role to it.

        - every provider accepts an explicit model; defaults apply only when
          the saved model is empty;
        - provider endpoints default to presets but are editable; Ollama stays loopback;
        - a non-empty ``api_key`` goes ONLY into the SecretStore;
        - the persisted JSON carries policy fields only — never the key.
        """
        async with self._mutation_lock:
            preset = PRESETS.get(preset_id)
            if preset is None:
                raise GenerativeConfigError(f"unknown provider preset {preset_id!r}")
            base_url = base_url.strip()
            model = model.strip()
            profiles = deepcopy(self._profiles())
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
                effective_base_url = base_url or str(prior.get("base_url") or "") or preset.base_url
            effective_model = model or preset.default_model
            if vision_mode is None:
                vision_mode = prior.get("vision_mode", "auto") if effective_model == prior.get("model") else "auto"
            if vision_mode not in {"auto", "enabled", "disabled"}:
                raise GenerativeConfigError("invalid vision mode")
            self._check_revision(expected_revision, expected_epoch)
            self._mutation_generation += 1
            self._connection_status = "configured" if self._provider_id else "unconfigured"
            if api_key and preset.requires_api_key:
                await self._secret_store.put(secret_key_name(preset_id), api_key)
            self._advance_revision()
            self._register(
                preset_id=preset_id,
                base_url=effective_base_url,
                model=effective_model,
                vision_mode=vision_mode,
            )
            self._provider_id = preset_id
            self._connection_status = "configured"
            profiles[preset_id] = {
                "model": effective_model,
                "base_url": effective_base_url,
            }
            if vision_mode != "auto":
                profiles[preset_id]["vision_mode"] = vision_mode
            self._config = {
                "preset_id": preset_id,
                "model": effective_model,
                "base_url": effective_base_url,
                "roles": [role.value for role in ALL_ROLES],
                "provider_configs": profiles,
                "onboarding_completed": True,
                "config_version": CONFIG_VERSION,
            }
            self._config["revision"] = self._revision
            self._persist(self._config)
            return {**self.current_config(), "operation_id": operation_id or str(uuid4())}

    async def discover_models(self) -> list[str] | GatewayConnectionResult:
        """Read models from a captured provider; stale errors cannot alter status."""
        snapshot, secret = await self._capture_probe(None)
        if snapshot.provider is None or not snapshot.provider_id:
            return await self._error_result("no provider configured", snapshot, secret)
        try:
            models = await snapshot.provider.fetch_models()
            if not self._probe_current(snapshot):
                return await self._error_result("configuration changed during discovery", snapshot, secret)
            return models
        except Exception as error:
            return await self._error_result(str(error), snapshot, secret)

    async def test_connection(self, *, expected_revision: int | None = None, expected_epoch: str | None = None, operation_id: str | None = None) -> GatewayConnectionResult:
        """Probe one isolated provider snapshot, publishing only to its revision."""
        snapshot, secret = await self._capture_probe(operation_id)
        if (expected_epoch is not None and expected_epoch != self._epoch) or (expected_revision is not None and expected_revision != snapshot.revision):
            return GatewayConnectionResult(status="error", message="configuration revision changed",
                                           **{**self._probe_fields(snapshot), "accepted": False})
        if snapshot.provider is None or not snapshot.provider_id:
            return await self._error_result("no provider configured", snapshot, secret)
        self._connection_status = "connecting"
        try:
            preset = PRESETS.get(snapshot.provider_id)
            if preset is not None and preset.local:
                models = await snapshot.provider.fetch_models()
                aliases = {name.removesuffix(":latest") for name in models}
                if snapshot.model and snapshot.model not in models and snapshot.model not in aliases:
                    return await self._error_result(f"provider 'ollama' model unavailable: {snapshot.model}", snapshot, secret)
            resolved = await self._gateway.resolve_model(snapshot.provider_id, provider=snapshot.provider, materialize=False)
            if not self._probe_current(snapshot):
                return GatewayConnectionResult(status="error", message="configuration revision changed", **self._probe_fields(snapshot))
            snapshot.provider.set_model(resolved)
            await self._gateway.probe_provider(snapshot.provider, [{"role": "user", "content": "只回复：连接成功"}])
        except TimeoutError:
            return await self._error_result("connection probe timeout", snapshot, secret)
        except Exception as error:
            return await self._error_result(str(error), snapshot, secret)
        if self._probe_current(snapshot):
            for _role, bound in snapshot.bindings:
                if bound is not None:
                    bound.set_model(resolved)
            if self._config.get("model", "") != resolved:
                self._config["model"] = resolved
                self._profiles().setdefault(snapshot.provider_id, {})["model"] = resolved
                self._persist(self._config)
            self._connection_status = "success"
        message = "已连接到本地 Ollama。" if preset is not None and preset.local else "模型已响应，配置可以使用。"
        return GatewayConnectionResult(status="ok", message=message, resolved_model=resolved, **self._probe_fields(snapshot))

    def current_config(self) -> dict:
        """Non-sensitive config snapshot (no key, no key name)."""
        return {**deepcopy(self._config), "epoch": self._epoch, "revision": self._revision, "persisted": self._persisted, "persistence_error": self._persistence_error}

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

    async def mark_onboarding_completed(self, *, expected_revision: int | None = None, expected_epoch: str | None = None, operation_id: str | None = None) -> dict:
        """Persist an explicit template-only choice with the same commit receipt."""
        async with self._mutation_lock:
            self._check_revision(expected_revision, expected_epoch)
            self._advance_revision()
            self._config["onboarding_completed"] = True
            self._config.setdefault("config_version", CONFIG_VERSION)
            self._persist(self._config)
            return {**self.current_config(), "operation_id": operation_id or str(uuid4())}

    async def remove_api_key(self, *, expected_revision: int | None = None, expected_epoch: str | None = None, operation_id: str | None = None) -> dict:
        """Invalidate in-flight probes before deleting a credential."""
        async with self._mutation_lock:
            self._check_revision(expected_revision, expected_epoch)
            self._mutation_generation += 1
            self._connection_status = "configured" if self._provider_id else "unconfigured"
            if self._provider_id is not None:
                await self._secret_store.delete(secret_key_name(self._provider_id))
            self._advance_revision()
            for role in ALL_ROLES:
                self._gateway.unregister(role)
            self._connection_status = "unconfigured"
            self._config["onboarding_completed"] = True
            self._config.setdefault("config_version", CONFIG_VERSION)
            self._persist(self._config)
            return {**self.current_config(), "operation_id": operation_id or str(uuid4())}

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
