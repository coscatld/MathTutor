"""Desktop product bridge — settings, documents, memory, readiness, plus the
Phase 6 round-2 production surfaces (bootstrap, model test, backups,
student summary).

Router prefix: ``/api/v2/math-tutor/desktop`` (mounted by MAIN in
``product_app.py``; the app must ALSO pass the router the auth posture the
existing product routers use — every endpoint resolves the
``StudentOwnerScope`` via ``require_student_owner``).

This router is the ONLY surface that touches the desktop product shell:

- ``/settings`` — AI model configuration (presets, key, test-connection,
  model discovery). The API key goes ONLY into the SecretStore; responses
  never carry key material (masked tail is the documented exception);
- ``/documents`` — user documents: list/import/pick/reparse/delete/
  retrieval toggle. Only user-friendly projections are ever returned
  (no storage paths, chunk vectors, content hashes, parser tracebacks);
- ``/memory`` — personal memory KG: CRUD, retrieval toggle, MODEL_INFERRED
  confirm (the only legal source-type migration);
- ``/readiness`` — READY / DEGRADED / BLOCKED with per-check detail;
- ``/bootstrap`` — the nine-step boot sequence recorded at startup
  (read-only wire contract BootstrapPayload);
- ``/model/test`` — connectivity probe with the five error kinds;
- ``/backups`` + ``/backup`` + ``/backup/verify`` + ``/backup/restore`` —
  online backup inventory/create/verify/restore. Restore runs the full
  stop → dispose → verified restore → rebuild orchestration (spec 5.8)
  and ALWAYS reports ``restart_required: true`` on success; client backup
  names are strictly validated (traversal can never address a file);
- ``/student-summary`` — read-only mastery projection (never editable).

Security invariants:

- default deny: only the routes below exist on this router;
- every read/write is owner-scoped (the services enforce the same);
- no API key value ever appears in a response, an exception message, a
  log line, or a repr; the key is stored via ``KeychainSecretStore`` in
  desktop production (OS credential store), never in config JSON or the
  business DB;
- ``NativeDesktopFilePicker`` is the only document-entry path in desktop
  mode; it never scans user directories (see
  ``application/desktop_files.py``).
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
from pathlib import Path
import shutil
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.application.data_lifecycle import LifecycleUnavailableError
from mathtutor.application.desktop_files import (
    LoopbackElectronPickTransport,
    NativeDesktopFilePicker,
    PickTransportUnavailableError,
    PickedFile,
)
from mathtutor.application.document_ingestion import DocumentBusyError
from mathtutor.domain.documents import (
    MAX_DOCUMENT_BYTES,
)
from mathtutor.domain.memory import MemoryType, PersonalMemoryNode
from mathtutor.infrastructure.gateway_config import secret_key_name
from mathtutor.infrastructure.generative_gateway import (
    GenerativeConfigError,
    PRESETS,
)
from mathtutor.infrastructure.keychain_secret_store import KeychainSecretStore
from mathtutor.infrastructure.secret_store import SecretStore
from mathtutor.learning.skills import (
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
    SKILL_POLYNOMIAL_BASIC,
    SKILL_QUADRATIC_EQUATION,
    all_skill_ids,
)
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()

DESKTOP_ROUTER_PREFIX = "/api/v2/math-tutor/desktop"


# ---------------------------------------------------------------------------
# Settings — AI model configuration (GatewayConfigService is SUBAGENT A's
# module; this bridge only calls the fixed public contract).
# ---------------------------------------------------------------------------


from typing import Literal


class SettingsUpdate(BaseModel):
    preset_id: str
    api_key: str | None = None
    base_url: str = ""
    vision_mode: Literal["auto", "enabled", "disabled"] | None = None
    model: str = ""


class EmbeddingSettingsUpdate(BaseModel):
    enabled: bool = False
    provider: str = "local"
    local_model_id: str = "bge-small-zh-v1.5"
    cloud_base_url: str = ""
    cloud_api_key: str | None = Field(default=None, max_length=8192)
    cloud_model: str = ""


class LocalEmbeddingDownloadRequest(BaseModel):
    model_id: str = "bge-small-zh-v1.5"


class DocumentRename(BaseModel):
    filename: str = Field(min_length=1, max_length=255)


class TutorSettingsUpdate(BaseModel):
    personality: str = "patient"
    custom_instruction: str = Field(default="", max_length=1000)


def mask_secret(value: str) -> str:
    """Mask a secret for display: bullets + the last 4 characters.

    The full value must never reach the frontend; this masked tail is the
    documented exception (design: 设置 → AI 模型).
    """
    value = str(value or "")
    if not value:
        return ""
    tail = value[-4:] if len(value) >= 4 else value
    return f"••••••••{tail}"


def _desktop_secret_store() -> SecretStore:
    """The SecretStore backing the settings surface.

    Desktop production: the OS credential store (Keychain). Dev/test: the
    in-memory store. ``ProductState`` picks the store with the same
    decision (see ``product_state._default_secret_store``), so the settings
    surface and the gateway's key resolver share ONE instance — a key saved
    here is resolvable at generation time.
    """
    return get_product_state().secret_store


def _gateway_config_service():
    """Return the process-wide non-sensitive provider configuration service."""
    return get_product_state().gateway_config


def _friendly_config_error(preset_id: str, base_url: str, model: str) -> str | None:
    """Map user mistakes onto friendly Chinese messages (no internals)."""
    preset = PRESETS.get(preset_id)
    if preset is None:
        return "未知的模型提供商，请重新选择。"
    if preset.custom:
        if not base_url:
            return "自定义提供商需要填写 API 地址（Base URL）。"
        return None
    if preset.local:
        return None
    return None


@router.get("/settings")
async def get_settings(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Current non-sensitive configuration (never a key value)."""
    service = _gateway_config_service()
    config = service.current_config()
    preset_id = str(config.get("preset_id") or "")
    has_api_key = await service.has_api_key()
    masked: str | None = None
    if has_api_key and preset_id:
        try:
            stored = await _desktop_secret_store().get(secret_key_name(preset_id))
        except Exception:
            stored = None
        if stored:
            masked = mask_secret(stored)
    profiles: dict[str, dict] = {}
    for profile_id, profile in service.provider_profiles().items():
        has_profile_key = await service.has_api_key(profile_id)
        profile_masked = None
        if has_profile_key:
            try:
                stored = await _desktop_secret_store().get(secret_key_name(profile_id))
            except Exception:
                stored = None
            if stored:
                profile_masked = mask_secret(stored)
        profiles[profile_id] = {
            **profile,
            "has_api_key": has_profile_key,
            "key_masked": profile_masked,
        }
    assessment = get_product_state().initial_assessment
    assessment_state = await assessment.read(owner.student_id) if assessment else None
    return {
        "initial_assessment_required": bool(assessment_state and assessment_state["status"] in {"pending", "in_progress"}),
        "preset_id": preset_id,
        "model": str(config.get("model") or ""),
        "base_url": str(config.get("base_url") or ""),
        "vision_mode": service.provider_profiles().get(preset_id, {}).get("vision_mode", "auto"),
        "is_configured": await service.is_ready(),
        "onboarding_completed": service.onboarding_completed(),
        "key_masked": masked,
        "connection_status": service.connection_status(),
        "provider_configs": profiles,
    }


@router.get("/settings/presets")
async def list_presets(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[dict]:
    """User-selectable provider presets (label + custom flag only)."""
    return [
        {
            "preset_id": preset.preset_id,
            "label": preset.label,
            "custom": preset.custom,
            "default_model": preset.default_model,
            "base_url": preset.base_url,
            "requires_api_key": preset.requires_api_key,
            "editable_base_url": preset.editable_base_url,
            "local": preset.local,
        }
        for preset in PRESETS.values()
    ]


@router.get("/settings/tutor")
async def get_tutor_settings(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    return get_product_state().tutor_preferences.public_settings()


@router.put("/settings/tutor")
async def put_tutor_settings(
    update: TutorSettingsUpdate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    try:
        result = state.tutor_preferences.update(update.personality, update.custom_instruction)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    state.refresh_model_writer()
    return result


@router.put("/settings")
async def put_settings(
    update: SettingsUpdate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Apply a provider preset; the API key goes ONLY into the SecretStore."""
    friendly = _friendly_config_error(update.preset_id, update.base_url, update.model)
    if friendly is not None:
        raise HTTPException(status_code=422, detail=friendly)
    service = _gateway_config_service()
    was_configured = await service.is_ready()
    try:
        config = await service.apply_config(
            preset_id=update.preset_id,
            api_key=update.api_key or None,
            base_url=update.base_url,
            vision_mode=update.vision_mode,
            model=update.model,
        )
    except GenerativeConfigError as error:
        raise HTTPException(status_code=422, detail="配置无效，请检查填写内容。") from error

    get_product_state().refresh_model_writer()

    assessment = get_product_state().initial_assessment
    if assessment and not was_configured and update.api_key and await service.is_ready():
        async with get_product_state().turn_requests.owner(owner.student_id):
            await assessment.ensure(owner.student_id)
    assessment_state = await assessment.read(owner.student_id) if assessment else None

    # Masked tail only — the response never carries the key value.
    store = _desktop_secret_store()
    masked: str | None = None
    if update.api_key:
        masked = mask_secret(update.api_key)
    else:
        try:
            stored = await store.get(secret_key_name(update.preset_id))
        except Exception:
            stored = None
        if stored:
            masked = mask_secret(stored)
    return {
        "preset_id": str(config.get("preset_id") or ""),
        "vision_mode": service.provider_profiles().get(str(config.get("preset_id") or ""), {}).get("vision_mode", "auto"),
        "model": str(config.get("model") or ""),
        "base_url": str(config.get("base_url") or ""),
        "key_masked": masked,
        "is_configured": await service.is_ready(),
        "onboarding_completed": service.onboarding_completed(),
        "connection_status": service.connection_status(),
        "initial_assessment_required": bool(assessment_state and assessment_state["status"] in {"pending", "in_progress"}),
    }


@router.post("/settings/onboarding/skip")
async def skip_provider_onboarding(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Remember the explicit choice to continue in template teaching mode."""
    service = _gateway_config_service()
    service.mark_onboarding_completed()
    return {"ok": True, "onboarding_completed": True}


@router.delete("/settings/api-key")
async def delete_api_key(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Remove the OS-stored credential and immediately fall back to templates."""
    service = _gateway_config_service()
    active = str(service.current_config().get("preset_id") or "")
    if active and not PRESETS[active].requires_api_key:
        raise HTTPException(status_code=422, detail="本地 Ollama 不使用 API Key。")
    try:
        config = await service.remove_api_key()
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="系统凭据库暂时无法删除 API Key，请稍后再试。",
        ) from error
    get_product_state().refresh_model_writer()
    return {
        "preset_id": str(config.get("preset_id") or ""),
        "model": str(config.get("model") or ""),
        "base_url": str(config.get("base_url") or ""),
        "is_configured": False,
        "onboarding_completed": True,
        "key_masked": None,
        "connection_status": service.connection_status(),
    }


# ---------------------------------------------------------------------------
# Settings — opt-in document Embedding. Deliberately separate from the
# generative-model key/configuration above.
# ---------------------------------------------------------------------------


@router.get("/settings/embedding")
async def get_embedding_settings(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    await state.refresh_embedding_runtime()
    return await state.embedding_config.public_settings()


@router.put("/settings/embedding")
async def put_embedding_settings(
    update: EmbeddingSettingsUpdate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    try:
        return await state.embedding_config.update(
            enabled=update.enabled,
            provider=update.provider,
            local_model_id=update.local_model_id,
            cloud_base_url=update.cloud_base_url,
            cloud_model=update.cloud_model,
            cloud_api_key=update.cloud_api_key or None,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="Embedding 设置暂时无法保存，请稍后重试。",
        ) from error


@router.delete("/settings/embedding/api-key")
async def delete_embedding_api_key(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    try:
        return await get_product_state().embedding_config.remove_cloud_key()
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="系统凭据库暂时无法删除 Embedding API Key。",
        ) from error


@router.post("/settings/embedding/test")
async def test_embedding_connection(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    # Failure is a normal, friendly result; it never crashes the settings UI.
    return await get_product_state().embedding_config.test_cloud()


@router.post("/settings/embedding/local/download", status_code=202)
async def download_local_embedding_model(
    request: LocalEmbeddingDownloadRequest,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    try:
        return await get_product_state().embedding_config.start_download(
            request.model_id
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/settings/embedding/local/{model_id}")
async def delete_local_embedding_model(
    model_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    try:
        return await get_product_state().embedding_config.delete_local_model(model_id)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/settings/test-connection")
async def test_connection(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Probe the configured provider; ``message`` never carries a key."""
    service = _gateway_config_service()
    result = await service.test_connection()
    if result.status == "ok":
        get_product_state().refresh_model_writer()
        message = result.message or "连接成功，模型可正常调用。"
        return {
            "status": "ok",
            "message": message,
            "resolved_model": result.resolved_model,
        }
    if "no provider configured" in result.message:
        message = "尚未配置模型提供商，请先保存 API Key。"
    else:
        message = f"连接失败：{result.message}"
    return {"status": "error", "message": message, "resolved_model": ""}


@router.get("/settings/models")
async def list_models(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[str]:
    """System-side model discovery (sorted model ids)."""
    from mathtutor.infrastructure.gateway_config import (
        GatewayConnectionResult,
    )

    service = _gateway_config_service()
    result = await service.discover_models()
    if isinstance(result, GatewayConnectionResult):
        if "no provider configured" in result.message:
            raise HTTPException(
                status_code=409, detail="尚未配置模型提供商，请先保存 API Key。"
            )
        provider_id = str(service.current_config().get("preset_id") or "")
        raise HTTPException(
            status_code=502,
            detail=(
                "Ollama 服务暂时不可用，请确认本地服务已启动。"
                if provider_id == "ollama"
                else "模型发现失败，请检查连接与 API Key。"
            ),
        )
    return list(result)


# ---------------------------------------------------------------------------
# Readiness — READY / DEGRADED / BLOCKED with per-check detail.
# ---------------------------------------------------------------------------


def _check_value(checks: dict[str, str], key: str) -> str:
    return checks.get(key, "error")


# Static fallback text per check — the live probe reason wins when present.
_FALLBACK_REASONS: dict[str, str] = {
    "sqlite": "数据库不可用，应用无法正常工作。",
    "migrations": "数据库结构未迁移，请更新应用。",
    "storage": "文档存储目录不可写。",
    "secret_store": "系统凭据库不可用，API Key 无法保存。",
    "gateway": "未配置模型（缺少 API Key 或未选择提供商）。",
    "embedding": "向量索引未配置；文档仍可通过关键词检索使用。",
    "retrieval": "文档检索不可用。",
    "core": "核心辅导服务不可用。",
    "ui": "界面加载异常。",
}


def _overall(checks: dict[str, str]) -> str:
    if any(value == "error" for value in checks.values()):
        return "BLOCKED"
    if any(value == "degraded" for value in checks.values()):
        return "DEGRADED"
    return "READY"


def _state_engine(state):
    """The product database engine, when the store is SQLite-backed."""
    uow = getattr(state.store, "uow", None)
    if uow is None:
        return None
    return getattr(uow, "engine", None)


async def _sqlite_check(state) -> tuple[str, str]:
    """BLOCKED-level: the product database must answer."""
    engine = _state_engine(state)
    if engine is None:
        return "ok", "内存模式（开发/测试）"
    from mathtutor.infrastructure.db import check_db_health

    try:
        await check_db_health(engine)
        return "ok", ""
    except Exception as error:
        return "error", f"数据库打不开：{error}"


async def _migrations_check(state) -> tuple[str, str]:
    """BLOCKED-level: alembic head must be applied (runs at startup)."""
    engine = _state_engine(state)
    if engine is None:
        return "ok", "内存模式（开发/测试）"
    try:
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import create_engine

        from mathtutor.infrastructure.migrate import alembic_config

        db_path = engine.url.database
        script = ScriptDirectory.from_config(alembic_config(db_path))
        head = script.get_current_head()
        from mathtutor.infrastructure import db_crypto
        sync_engine = create_engine(f"sqlite:///{db_path}", creator=lambda: db_crypto.connect_db(db_path))
        try:
            with sync_engine.connect() as conn:
                current = MigrationContext.configure(conn).get_current_revision()
        finally:
            sync_engine.dispose()
        current_str = str(current or "")
        if head and current_str == head:
            return "ok", ""
        return "error", f"数据库版本 {current_str or '未知'} ≠ 预期 {head or '未知'}"
    except Exception as error:
        return "error", f"迁移检查失败：{error}"


async def _storage_check(state) -> tuple[str, str]:
    """BLOCKED-level: controlled storage must accept a probe write."""
    root = state.document_storage.uploads_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".readiness-probe"
        probe.write_bytes(b"probe")
        probe.unlink()
        return "ok", ""
    except Exception as error:
        return "error", f"存储不可写：{error}"


async def _secret_store_check(state) -> tuple[str, str]:
    """DEGRADED-level: keys cannot be saved → generative surface only."""
    store = state.secret_store
    if isinstance(store, KeychainSecretStore):
        try:
            ok = store.available()
        except Exception:
            ok = False
        if not ok:
            return "degraded", (
                "系统凭据库不可用（macOS Keychain / Windows 凭据管理器 / secret-tool）"
            )
        return "ok", ""
    return "ok", "开发/测试内存凭据库"


async def _gateway_check(state) -> tuple[str, str]:
    """DEGRADED-level: unconfigured gateway → template writer still works."""
    if not await state.gateway_config.is_ready():
        if state.gateway_config.current_config().get("preset_id") == "ollama":
            return "degraded", "Ollama 已选择，但尚未选定本机模型（模板辅导仍可用）"
        return "degraded", "未配置模型提供商（可继续使用模板辅导与词汇检索）"
    roles = state.gateway.configured_roles()
    if not roles:
        return "degraded", "未配置模型提供商（可继续使用模板辅导与词汇检索）"
    provider = state.gateway.provider_for(roles[0])
    if provider is not None and provider.model:
        return "ok", ""
    return "degraded", "已配置提供商，但模型尚未解析（请测试连接）"


async def _embedding_check(state) -> tuple[str, str]:
    """DEGRADED-level: never BLOCKED — lexical retrieval always works."""
    try:
        status = state.embedding_runtime.status()
    except Exception as error:
        return "degraded", f"嵌入后端不可用：{error}"
    if status.available:
        return "ok", ""
    return "degraded", "向量索引未配置；文档仍可关键词检索"


async def _retrieval_check(state) -> tuple[str, str]:
    """DEGRADED-level: lexical retrieval is always available by construction."""
    return "ok", "词法检索可用"


async def _core_check(state) -> tuple[str, str]:
    try:
        if state.store is not None and state.capability is not None:
            return "ok", ""
    except Exception:
        pass
    return "error", "核心辅导服务未初始化"


async def _ui_check(state) -> tuple[str, str]:
    return "ok", "界面由桌面壳加载"


async def build_readiness() -> dict:
    """Aggregate per-check status into READY / DEGRADED / BLOCKED.

    ``checks`` maps each surface to "ok" | "degraded" | "error";
    ``reasons`` carries a HUMAN reason per non-ok check (live probe detail,
    falling back to static text). No internal values ever leave this router.
    """
    state = get_product_state()
    checks: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for name, probe in (
        ("core", _core_check),
        ("sqlite", _sqlite_check),
        ("migrations", _migrations_check),
        ("storage", _storage_check),
        ("secret_store", _secret_store_check),
        ("gateway", _gateway_check),
        ("embedding", _embedding_check),
        ("retrieval", _retrieval_check),
        ("ui", _ui_check),
    ):
        try:
            value, reason = await probe(state)
        except Exception:
            value, reason = "error", ""
        checks[name] = value
        if value != "ok":
            reasons[name] = reason or _FALLBACK_REASONS.get(name, "不可用")
    return {
        "status": _overall(checks),
        "checks": checks,
        "reasons": reasons,
    }


@router.get("/readiness")
async def readiness(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    return await build_readiness()


# ---------------------------------------------------------------------------
# Bootstrap — the nine-step startup sequence (Phase 6 round 2, MAIN wiring).
# ---------------------------------------------------------------------------


def _as_step_status(value: str) -> str:
    """Map the readiness check vocabulary onto the bootstrap one.

    Readiness uses "error" (hard failures); the wire contract's
    BootstrapStep uses "blocked" — same severity, different name.
    """
    return {"error": "blocked"}.get(value, value)


async def _data_root_check(state) -> tuple[str, str]:
    """BLOCKED-level: the controlled data root must exist and accept a
    probe write (the document storage lives under it)."""
    root = state.document_storage.uploads_root().parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".bootstrap-probe"
        probe.write_bytes(b"probe")
        probe.unlink()
        return "ok", ""
    except Exception as error:
        return "error", f"数据目录不可写：{error}"


async def _curriculum_check(state) -> tuple[str, str]:
    """DEGRADED-level: the versioned curriculum catalog must answer. An
    empty (not-yet-published) catalog is still healthy."""
    try:
        versions = await state.curriculum.list_versions()
        if versions:
            return "ok", ""
        return "ok", "课程目录已就绪（尚未发布课程版本）"
    except Exception as error:
        return "degraded", f"课程目录不可用：{error}"


async def _outbox_check(state) -> tuple[str, str]:
    """DEGRADED-level: the resident relay loop must be running (SQLite
    mode); in-memory mode has no relay by design (development)."""
    relay = state.outbox_relay
    if relay is None:
        return "ok", "内存模式（开发/测试）"
    if relay.is_running:
        return "ok", ""
    return "degraded", "事件分发未运行（重启后自动恢复）"


async def _verifier_worker_check(state) -> tuple[str, str]:
    """BLOCKED-level in durable mode: math authority must be isolated."""
    health = getattr(state.verification_backend, "health", None)
    if health is None:
        return "ok", "进程内验证（仅开发/测试模式）"
    try:
        return ("ok", "") if await health() else ("error", "数学验证器未就绪。")
    except Exception:
        return "error", "数学验证器未就绪。"


async def run_bootstrap() -> None:
    """Run the boot sequence once and record it (startup hook).

    Each probe maps onto the wire-contract step vocabulary
    ("ok" | "degraded" | "blocked") and a friendly Chinese detail. A probe
    raising is recorded as that step's failure — never propagated (the app
    is already serving; the snapshot tells the shell what is wrong).
    """
    state = get_product_state()
    tracker = state.bootstrap_tracker
    for key, probe in (
        ("check_data_root", _data_root_check),
        ("database", _sqlite_check),
        ("migration", _migrations_check),
        ("verifier_worker", _verifier_worker_check),
        ("secret_store", _secret_store_check),
        ("document_storage", _storage_check),
        ("curriculum", _curriculum_check),
        ("retrieval", _retrieval_check),
        ("outbox", _outbox_check),
        ("model_gateway", _gateway_check),
    ):
        try:
            value, detail = await probe(state)
        except Exception:  # noqa: BLE001 - recorded as the step status
            value, detail = "error", "启动检查失败。"
        tracker.record(key, _as_step_status(value), detail or None)
    tracker.finish()


@router.get("/bootstrap")
async def bootstrap(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """The recorded boot sequence (wire contract BootstrapPayload).

    Read-only: while booting, ``phase`` is the current step key; once the
    startup hook finishes it becomes "READY" and ``readiness``/``reason``
    reflect the final step statuses.
    """
    return get_product_state().bootstrap_tracker.snapshot()


# ---------------------------------------------------------------------------
# Model connection test — five distinct failure kinds, friendly copy.
# ---------------------------------------------------------------------------


#: Friendly Chinese messages per error kind — never raw HTTP detail,
#: headers, or key material (the gateway's message is redacted upstream).
_MODEL_TEST_MESSAGES: dict[str, str] = {
    "response_incomplete": "服务已响应，但回答为空或被截断，请重试。",
    "request_rejected": "服务拒绝了请求参数，请检查模型名称与接口兼容性。",
    "quota_exceeded": "服务账户余额或配额不足，请到服务商控制台检查。",
    "rate_limited": "请求受到限流，请稍后重试。",
    "provider_error": "模型服务调用失败，请稍后重试；这不代表服务商不受支持。",
    "credential_invalid": "API 密钥无效或已失效，请重新粘贴完整密钥。",
    "network_unavailable": "无法连接网络，请检查电脑的网络或代理设置。",
    "provider_unsupported": "暂不支持此服务商，请更换服务商或使用自定义服务地址。",
    "model_unavailable": "所选模型不可用，请更换模型名称或服务商。",
    "gateway_disabled": "尚未配置模型提供商，请先保存 API Key。",
}


@router.post("/model/test")
async def test_model(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Probe the configured provider (wire contract ModelTestResult).

    ``error_kind`` is the five-way classification; ``message`` is friendly
    copy by contract — the raw (redacted) provider message never leaves
    this router.
    """
    service = _gateway_config_service()
    result = await service.test_connection()
    if result.status == "ok":
        get_product_state().refresh_model_writer()
        provider_id = str(service.current_config().get("preset_id") or "")
        return {
            "ok": True,
            "error_kind": None,
            "message": "已连接到本地 Ollama。" if provider_id == "ollama" else "连接成功，模型可正常调用。",
            "resolved_model": result.resolved_model,
        }
    kind = result.error_kind or "provider_error"
    provider_id = str(service.current_config().get("preset_id") or "")
    message = _MODEL_TEST_MESSAGES.get(kind, "连接失败，请稍后重试。")
    if provider_id == "ollama" and kind == "network_unavailable":
        message = "Ollama 服务暂时不可用，请确认本地服务已启动。"
    return {
        "ok": False,
        "error_kind": kind,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Backups — list / create / verify / restore (BackupService + restore
# orchestration; wire contract BackupRecord & friends).
# ---------------------------------------------------------------------------


class BackupPathRequest(BaseModel):
    """Client-supplied backup name (a bare file NAME — never a path)."""

    path: str
    #: Only needed when the key store no longer holds the backup key.
    recovery_key: str | None = Field(default=None, max_length=128)


#: The service's own backup naming pattern (mirrors backup._BACKUP_FILE_GLOB).
_BACKUP_NAME_GLOB = "*.backup-*.db"


def _require_backup_service(state):
    """SQLite-only surface: in-memory mode has no file to back up."""
    if state.backup_service is None:
        raise HTTPException(status_code=409, detail="当前为内存模式，不支持备份。")
    return state.backup_service


def _backup_directory(state) -> Path:
    """The controlled backup directory (data_dir/backups)."""
    return Path(state.backup_policy.backup_dir).resolve()


def _resolve_backup_path(state, client_path: str) -> Path:
    """Strict client-path validation — a traversal can never address an
    arbitrary file.

    The client only ever sees bare file NAMES (BackupRecord.path). Here the
    name must be exactly one path component, match the backup naming
    pattern, resolve INSIDE the backup directory, and exist — anything else
    is refused with 404/422.
    """
    if not client_path or Path(client_path).name != client_path:
        raise HTTPException(status_code=422, detail="备份文件名无效。")
    if not fnmatch.fnmatch(client_path, _BACKUP_NAME_GLOB):
        raise HTTPException(status_code=422, detail="备份文件名无效。")
    directory = _backup_directory(state)
    directory.mkdir(parents=True, exist_ok=True)
    candidate = (directory / client_path).resolve()
    if candidate.parent != directory:
        raise HTTPException(status_code=422, detail="备份文件名无效。")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="备份不存在。")
    return candidate


def _project_backup_entry(entry) -> dict:
    """Wire-contract BackupRecord from a BackupEntry — file NAME only, no
    sensitive paths; integrity is the service's own verdict."""
    manifest = entry.manifest
    size = entry.backup_path.stat().st_size if entry.backup_path.is_file() else 0
    if entry.status == "ok" and manifest is not None:
        integrity, sha_prefix = "ok", manifest.sha256[:12]
    else:
        integrity, sha_prefix = "unknown", ""
    return {
        "path": entry.backup_path.name,
        "created_at": entry.created_at,
        "size_bytes": size,
        "integrity": integrity,
        "sha256_prefix": sha_prefix,
    }


def _project_manifest(manifest) -> dict:
    """Wire-contract BackupRecord from a freshly created BackupManifest."""
    return {
        "path": Path(manifest.backup_path).name,
        "created_at": manifest.created_at,
        "size_bytes": manifest.size_bytes,
        "integrity": "ok",
        "sha256_prefix": manifest.sha256[:12],
    }


@router.get("/backups")
async def list_backups_endpoint(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Backup inventory (wire contract BackupsList). Newest first; the
    service's own statuses annotate corrupt/orphan entries — listing never
    deletes anything."""
    from mathtutor.infrastructure.backup import BackupService

    state = get_product_state()
    _require_backup_service(state)
    directory = _backup_directory(state)
    entries = BackupService.list_backups(directory)
    return {
        "backups": [_project_backup_entry(entry) for entry in entries],
        "backup_dir": directory.name,
        "policy": {
            "retention_limit": state.backup_policy.retention_limit,
            "mode": state.backup_policy.mode,
        },
    }


@router.post("/backup")
async def create_backup_endpoint(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Take one online backup now (VACUUM INTO + manifest) and apply the
    retention limit. Failures return a friendly message — never internals."""
    from mathtutor.infrastructure.backup import (
        BackupError,
    )

    state = get_product_state()
    _require_backup_service(state)
    directory = _backup_directory(state)
    try:
        manifest = await state.backup_service.create_backup(backup_dir=directory)
        try:
            await state.backup_service.run_retention(
                directory, state.backup_policy.retention_limit
            )
        except Exception:  # pragma: no cover - retention is best-effort
            pass
    except BackupError as error:
        return {"ok": False, "message": str(error)}
    return {"ok": True, "backup": _project_manifest(manifest)}


class EncryptionUpdate(BaseModel):
    enabled: bool


def _encryption_status(state) -> dict:
    from mathtutor.infrastructure import db_crypto
    if state.db_path is None:
        return {"available": False, "mode": "plaintext", "pending": None, "reason": "当前为内存模式"}
    current = db_crypto.state(Path(state.db_path))
    available = db_crypto.available()
    return {**current, "available": available, "backups_encrypted": available,
            "reason": "" if available else "当前环境缺少 SQLCipher 或系统密钥存储"}


@router.get("/privacy/encryption")
async def get_encryption(owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    """Database encryption mode, any pending change, and whether backups are encrypted."""
    return _encryption_status(get_product_state())


@router.put("/privacy/encryption")
async def put_encryption(update: EncryptionUpdate, owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    """Record the wanted mode; the conversion runs at the next start."""
    from mathtutor.infrastructure import db_crypto
    state = get_product_state()
    if state.db_path is None:
        raise HTTPException(status_code=409, detail="当前为内存模式，不支持加密。")
    try:
        await asyncio.to_thread(db_crypto.request_change, Path(state.db_path), update.enabled)
    except db_crypto.EncryptionUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    status = _encryption_status(state)
    return {**status, "restart_required": bool(status["pending"])}


@router.post("/privacy/encryption/recovery-key")
async def reveal_recovery_key(owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    """The backup key, shown only on an explicit request so it can be kept safe."""
    from mathtutor.infrastructure import db_crypto
    try:
        key = await asyncio.to_thread(db_crypto.backup_key)
    except db_crypto.EncryptionUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not key:
        raise HTTPException(status_code=409, detail="当前环境不加密备份，没有恢复密钥。")
    return {"recovery_key": key}


@router.post("/backup/verify")
async def verify_backup_endpoint(
    request: BackupPathRequest,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Re-verify one backup (manifest sha256 + size + integrity_check)."""
    from mathtutor.infrastructure.backup import BackupService

    state = get_product_state()
    _require_backup_service(state)
    backup_path = _resolve_backup_path(state, request.path)

    manifest = None
    for entry in BackupService.list_backups(_backup_directory(state)):
        if entry.backup_path == backup_path:
            manifest = entry.manifest
            break
    if manifest is None:
        return {"ok": False, "message": "备份缺少校验记录，无法验证。"}
    ok, detail = await asyncio.to_thread(
        BackupService.verify_backup, backup_path, manifest, request.recovery_key
    )
    if ok:
        return {"ok": True}
    return {"ok": False, "message": f"备份校验未通过：{detail}"}


@router.post("/backup/restore")
async def restore_backup_endpoint(
    request: BackupPathRequest,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Verified restore with the full stop→dispose→restore→rebuild
    orchestration (spec 5.8). Wire contract: success ALWAYS returns
    ``restart_required: true`` — the desktop shell prompts a restart.

    Fail-closed: a refused restore leaves the current database untouched
    (the service validates before the atomic copy); the runtime is rebuilt
    in both outcomes so the app keeps serving.
    """
    state = get_product_state()
    _require_backup_service(state)
    if state.db_path is None:
        raise HTTPException(status_code=409, detail="当前为内存模式，不支持恢复。")
    backup_path = _resolve_backup_path(state, request.path)

    # The ASGI maintenance middleware has counted this restore request. Close
    # admission, drain every other HTTP/WebSocket request, and hold the gate
    # through shutdown, target precheck, replacement, migration and rollback.
    if not await state.begin_maintenance(timeout=5.0):
        return {
            "ok": False,
            "message": "当前仍有学习请求正在处理，未开始恢复，请稍后重试。",
        }
    try:
        return await _restore_backup_while_quiesced(state, backup_path, request.recovery_key)
    finally:
        await state.end_maintenance()


async def _restore_backup_while_quiesced(state, backup_path: Path, recovery_key: str | None = None) -> dict:
    """Perform restore while the ProductState request gate is exclusively held."""
    from mathtutor.api.product_state import (
        get_product_state,
        reset_product_state,
    )
    from mathtutor.infrastructure.backup import BackupError
    from mathtutor.infrastructure.migrate import upgrade_db

    # 1) stop the write runtime (relay loop + backup scheduler), checkpoint
    #    the WAL and dispose every engine — ProductState.shutdown_runtime
    #    guarantees no live connection and no active -wal/-shm remains.
    try:
        await state.shutdown_runtime()
    except Exception:
        return {"ok": False, "message": "运行时未安全关闭，已取消恢复。"}
    from mathtutor.infrastructure.lifecycle_trace import trace
    trace(id(state), "restore_replacement_begin")
    # Preserve the exact checkpointed live database until BOTH replacement
    # and forward migration have succeeded.  ``restore_verified`` provides an
    # atomic file replacement, but migration is a later failure boundary; a
    # private same-directory rollback image closes that gap.
    rollback_path = state.db_path.with_name(
        f".{state.db_path.name}.pre-restore-{uuid4().hex}.rollback"
    )
    try:
        await asyncio.to_thread(shutil.copy2, state.db_path, rollback_path)
    except OSError as error:
        _rebuild_after_restore(state)
        return {
            "ok": False,
            "message": f"无法创建恢复前保护副本，已取消恢复：{error}",
        }
    # 2) verified restore (sha256 + integrity + alembic compatibility +
    #    active-wal/shm refusal + atomic copy + post-copy re-check).
    try:
        await state.backup_service.restore_verified(backup_path, state.db_path, recovery_key=recovery_key)
    except BackupError as error:
        rollback_error = await _rollback_failed_restore(
            rollback_path, state.db_path
        )
        _rebuild_after_restore(state)
        if rollback_error:
            return {
                "ok": False,
                "message": f"{error}；原数据库自动回滚失败：{rollback_error}",
            }
        return {"ok": False, "message": str(error)}
    # 3) rebuild the product runtime over the restored file and bring its
    #    schema forward (idempotent — an older backup migrates to head).
    try:
        upgrade_db(state.db_path)
    except Exception as error:  # noqa: BLE001 - surface as a failed restore
        rollback_error = await _rollback_failed_restore(
            rollback_path, state.db_path
        )
        _rebuild_after_restore(state)
        if rollback_error:
            return {
                "ok": False,
                "message": f"恢复后迁移失败：{error}；原数据库自动回滚失败：{rollback_error}",
            }
        return {
            "ok": False,
            "message": f"恢复后迁移失败：{error}；已自动恢复原数据库。",
        }
    # Community settings live outside the SQLite-only backup. A restored
    # learning database requires a fresh consent before plugins read it.
    try:
        plugins = getattr(state, "community_plugins", None)
        if plugins is not None:
            plugins.revoke_all_consents()
    except Exception:
        rollback_error = await _rollback_failed_restore(rollback_path, state.db_path)
        _rebuild_after_restore(state)
        return {"ok": False, "message": "插件访问权限重置失败，已取消恢复。" +
                ("原数据库自动回滚失败，请使用保护副本恢复。" if rollback_error else "已恢复原数据库；请重新确认插件权限。")}
    rollback_path.unlink(missing_ok=True)
    reset_product_state()
    get_product_state(state.db_path)
    return {
        "ok": True,
        "restart_required": True,
        "message": "备份已恢复，请重启应用以完成恢复。",
    }


async def _rollback_failed_restore(
    rollback_path: Path, target_path: Path
) -> str | None:
    """Atomically put the checkpointed pre-restore DB back in place.

    Alembic/SQLite may have created sidecars before raising.  With the runtime
    already stopped, removing those derived files and replacing the main DB is
    safe.  The rollback image is retained if replacement itself fails so an
    operator still has a recoverable copy.
    """
    from mathtutor.infrastructure.backup import BackupService

    try:
        if any(Path(f"{target_path}{suffix}").exists() for suffix in ("-wal", "-shm")):
            raise RuntimeError("Rollback refused: database sidecars remain")
        await asyncio.to_thread(os.replace, rollback_path, target_path)
        integrity = await asyncio.to_thread(
            BackupService._verify_backup_file, target_path
        )
        if integrity != "ok":
            raise RuntimeError(f"rollback integrity_check={integrity!r}")
    except Exception as error:  # noqa: BLE001 - returned as fail-closed detail
        return str(error)
    return None


def _rebuild_after_restore(state) -> None:
    """Rebuild the product singleton after a refused restore (fail-closed:
    the current database file was never replaced, but its engines were
    disposed — the runtime must be reconstructed either way)."""
    from mathtutor.api.product_state import (
        get_product_state,
        reset_product_state,
    )

    reset_product_state()
    if state.db_path is not None:
        get_product_state(state.db_path)


# ---------------------------------------------------------------------------
# Student summary — read-only mastery projection (wire contract
# StudentSummary). Never editable here; mastery is a projection only.
# ---------------------------------------------------------------------------


#: Display metadata for the stable MVP skill ids (friendly label, grade
#: band). Read-only UI copy — the authoritative curriculum stays elsewhere.
_SKILL_DISPLAY: dict[str, tuple[str, str]] = {
    SKILL_ARITHMETIC: ("四则运算", "小学"),
    SKILL_POLYNOMIAL_BASIC: ("整式运算", "初中"),
    SKILL_LINEAR_EQUATION: ("一元一次方程", "初中"),
    SKILL_QUADRATIC_EQUATION: ("一元二次方程", "初中"),
}


async def _student_projection(
    state, student_id: str
) -> tuple[dict | None, int, set[str]]:
    """(projection, total_attempts, observed_skill_ids) from the SQLite
    education tables; all empty in in-memory mode (no persisted student)."""
    if state.uow is None:
        return None, 0, set()
    from sqlalchemy import func, select

    from mathtutor.infrastructure.schema import attempts
    from mathtutor.repositories import sqlite_education

    async with state.uow.transaction() as conn:
        projection = await sqlite_education.load_student_projection(conn, student_id)
        total = await conn.execute(
            select(func.count())
            .select_from(attempts)
            .where(attempts.c.student_id == student_id)
        )
        evidence = await sqlite_education.load_evidence_for_student(conn, student_id)
        return (
            projection,
            int(total.scalar() or 0),
            {item.skill_id for item in evidence},
        )


class CostSettingsUpdate(BaseModel):
    input_price_per_mtok: float | None = None
    output_price_per_mtok: float | None = None
    currency: str = "CNY"
    daily_budget: float | None = None
    daily_token_budget: int | None = None


@router.get("/settings/cost")
async def get_cost_settings(owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    """Prices, budget and today's usage. Costs exist only where prices are set."""
    state = get_product_state()
    policy = getattr(state, "cost_policy", None)
    if policy is None:
        raise HTTPException(status_code=503, detail="成本设置不可用")
    start, end = policy.utc_day_bounds()
    if getattr(state, "turn_traces", None) is None:
        aggregate = {"tokens": 0, "cost": 0, "turns": 0}
    else:
        aggregate = await state.turn_traces.usage_for_day(str(owner.student_id), start=start, end=end)
    usage = policy.usage_from_aggregate(aggregate, date=start)
    return {**policy.current().model_dump(), "today": usage, "over_budget": policy.over_budget(usage)}


@router.put("/settings/cost")
async def put_cost_settings(update: CostSettingsUpdate, owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    policy = getattr(get_product_state(), "cost_policy", None)
    if policy is None:
        raise HTTPException(status_code=503, detail="成本设置不可用")
    try:
        policy.update(update.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await get_cost_settings(owner)


class LearnerUpdate(BaseModel):
    stage: str | None = None
    grade: int | None = None


def _learner_service(state):
    service = getattr(state, "learner_settings", None)
    if service is None:
        from mathtutor.infrastructure.learner_settings import LearnerSettingsService
        service = state.learner_settings = LearnerSettingsService(None)
    return service


@router.get("/settings/learner")
async def get_learner_settings(owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    """The learner's stage and grade; the question bank defaults to this stage."""
    return _learner_service(get_product_state()).public()


@router.put("/settings/learner")
async def put_learner_settings(update: LearnerUpdate, owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    try:
        return _learner_service(get_product_state()).update(update.stage, update.grade)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


_QUESTION_BANK = None


def _question_bank():
    """One shared bank: the catalog and its verified problems are static content."""
    global _QUESTION_BANK
    if _QUESTION_BANK is None:
        from mathtutor.question_bank.service import QuestionBankService
        _QUESTION_BANK = QuestionBankService()
    return _QUESTION_BANK


@router.get("/exercise-bank")
async def get_question_bank(stage: str | None = None, owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    """Catalog tree for one stage (default: the learner's stage; none set → all stages)."""
    from mathtutor.question_bank.service import STAGES
    if stage is not None and stage not in STAGES:
        raise HTTPException(status_code=422, detail="学段只能是 primary、middle 或 high")
    chosen = stage or _learner_service(get_product_state()).current().stage
    return await asyncio.to_thread(_question_bank().tree, chosen)


@router.get("/exercise-bank/points/{code}")
async def get_question_bank_point(code: str, owner: StudentOwnerScope = Depends(require_student_owner)) -> dict:
    detail = await _question_bank().point(code)
    if detail is None:
        raise HTTPException(status_code=404, detail="没有这个知识点")
    return detail


@router.get("/diagnostics/turns")
async def turn_diagnostics(
    status: str | None = None,
    limit: int = 200,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Persisted turn health and recent turns: structure only, no text."""
    from mathtutor.repositories.turn_trace_repository import health
    state = get_product_state()
    traces = getattr(state, "turn_traces", None)
    if traces is None:
        return {"health": {"turns": 0, "alerts": []}, "turns": []}
    limit = max(1, min(limit, 1000))
    rows = await traces.recent(str(owner.student_id), limit=limit)
    shown = [row for row in rows if not status or row["status"] == status]
    return {"health": health(rows), "turns": [{k: v for k, v in row.items() if k != "student_id"} for row in shown]}


@router.get("/student-summary")
async def student_summary(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Read-only evidence observations; probabilities remain internal."""
    from mathtutor.application.learning_profile import profile_projection
    from mathtutor.application.evidence_projection import public_evidence
    state = get_product_state()
    history = await state.student_state.events(str(owner.student_id)) if state.student_state else []
    conversations = await state.conversations.list(owner.student_id)
    result = profile_projection(history, has_conversations=bool(conversations),
        model_status=state.student_state.dkt_mode if state.student_state else "not_trained")
    result["evidence_summary"] = public_evidence(history)
    return result


# ---------------------------------------------------------------------------
# Documents — explicit user pick / import, projections only.
# ---------------------------------------------------------------------------


def _project_document(doc) -> dict:
    """User-facing document projection — never storage/internal fields."""
    friendly_error = None
    if doc.status == "needs_ocr":
        friendly_error = (
            doc.parse_warning
            or "未提取到文字层，可能是扫描件。当前版本不支持 OCR，无法用于检索。"
        )
    elif doc.status == "failed":
        resource_errors = {
            "PARSE_PAGE_LIMIT": "资料页数超过处理上限，请拆分后重试。",
            "PARSE_TEXT_LIMIT": "资料文字量超过处理上限，请拆分后重试。",
            "PARSE_BLOCK_LIMIT": "资料内容数量超过处理上限，请拆分后重试。",
            "PARSE_ASSET_LIMIT": "资料图片数量或总大小超过处理上限，请拆分后重试。",
            "PARSE_TIMEOUT": "资料处理用时过长，请拆分资料后重试。",
            "PARSE_CANCELLED": "资料处理已取消，可以重新解析。",
            "PARSE_BUSY": "资料处理任务较多，请稍后重新解析。",
            "PARSE_CLOSED": "资料处理服务已关闭，请重新打开应用后重试。",
        }
        if getattr(doc, "classification", "") in resource_errors:
            friendly_error = resource_errors[doc.classification]
        elif Path(doc.filename).suffix.lower() == ".pdf":
            friendly_error = "无法解析此 PDF，请确认它是文本型 PDF（非扫描图片）。"
        else:
            friendly_error = "无法解析此文件，请确认内容是纯文本格式。"
    warning = doc.parse_warning or None
    return {
        "document_id": str(doc.document_id),
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "status": doc.status,
        "retrieval_enabled": doc.retrieval_enabled,
        "is_global": doc.is_global,
        "size_bytes": doc.size_bytes,
        "page_count": doc.page_count,
        "chunk_count": doc.chunk_count,
        "image_count": doc.image_count,
        "empty_page_count": doc.empty_page_count,
        "parse_warning": warning,
        "created_at": doc.created_at.isoformat(),
        "error": friendly_error,
    }


def _document_picker() -> NativeDesktopFilePicker:
    """The desktop picker; explicit-pick only, no directory scanning."""
    return NativeDesktopFilePicker(LoopbackElectronPickTransport())


def _validate_or_422(picked: PickedFile) -> None:
    from mathtutor.application.document_ingestion import (
        DocumentValidationError,
        validate_import,
    )

    try:
        validate_import(picked.filename, picked.mime_type, len(picked.data))
    except DocumentValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


async def _ingest(owner: StudentOwnerScope, picked: PickedFile, *, conversation_id: str = "") -> dict:
    state = get_product_state()
    from mathtutor.api.conversation_guard import require_active
    if conversation_id.strip():
        async with state.turn_requests.conversation(owner.student_id, conversation_id.strip()):
            await require_active(state, owner.student_id, conversation_id.strip())
            doc = await state.documents.ingest(owner.student_id, picked)
            await state.conversations.attach_document(owner.student_id, conversation_id.strip(), doc.document_id)
    else:
        doc = await state.documents.ingest(owner.student_id, picked)
    return _project_document(doc)


@router.get("/documents")
async def list_documents(
    conversation_id: str = "",
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[dict]:
    state = get_product_state()
    docs = await state.documents.list_documents(owner.student_id)
    if conversation_id.strip():
        from mathtutor.api.conversation_guard import require_active
        await require_active(state, owner.student_id, conversation_id.strip())
        allowed = set(await state.conversations.document_ids(owner.student_id, conversation_id.strip()))
        allowed.update(d.document_id for d in docs if d.is_global)
        docs = [doc for doc in docs if doc.document_id in allowed]
    docs = sorted(docs, key=lambda d: d.created_at, reverse=True)
    result = []
    for doc in docs:
        memberships = await state.conversations.conversation_ids_for_document(owner.student_id, doc.document_id)
        active_memberships = []
        for cid in memberships:
            row = await state.conversations.get(owner.student_id, cid)
            if row and not row.get("trashed_at") and not row.get("purged_at"):
                active_memberships.append(cid)
        if memberships and not active_memberships and not doc.is_global:
            continue
        memberships = active_memberships
        titles = {cid: (await state.conversations.get(owner.student_id, cid) or {}).get("title", "未命名对话") for cid in memberships}
        result.append({
            "conversation_titles": titles,
            **_project_document(doc),
            "conversation_ids": memberships,
        })
    return result


class DocumentScopeInput(BaseModel):
    is_global: bool


@router.patch("/documents/{document_id}/scope")
async def set_document_scope_setting(document_id: UUID, body: DocumentScopeInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    doc = await state.documents.get_document(owner.student_id, document_id)
    if doc is None:
        raise HTTPException(404, "资料不存在")
    updated = await state.document_repository.update_document(owner.student_id, doc.model_copy(update={"is_global": body.is_global}))
    if updated is None:
        raise HTTPException(404, "资料不存在")
    return _project_document(updated)


@router.get("/conversations/{conversation_id}/resources")
async def conversation_resources(conversation_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    from mathtutor.application.conversation_resources import resources, reference_state
    from mathtutor.api.conversation_guard import require_active
    await require_active(get_product_state(), owner.student_id, conversation_id)
    state = get_product_state()
    scope = await reference_state(state, owner.student_id, conversation_id)
    documents, images, messages = await resources(state, owner.student_id, conversation_id, scope=scope)
    candidates = {d["document_id"]: d for d in scope["available_documents"]}
    effective = set(scope["effective_document_ids"])
    return {"documents": [{**_project_document(d), "in_scope": str(d.document_id) in effective,
                          "origin": candidates[str(d.document_id)]["origin"],
                          "space_ids": candidates[str(d.document_id)]["space_ids"]} for d in documents],
            "images": images, "message_count": len(messages), "scope": scope}


@router.get("/conversations/{conversation_id}/export")
async def export_conversation_folder(conversation_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    from fastapi.responses import StreamingResponse
    from starlette.background import BackgroundTask
    from mathtutor.application.conversation_resources import export_folder
    state = get_product_state()
    from mathtutor.api.conversation_guard import require_active
    if not await require_active(state, owner.student_id, conversation_id):
        raise HTTPException(404, "对话不存在")
    try:
        stream = await export_folder(state, owner.student_id, conversation_id)
    except ValueError as error:
        raise HTTPException(413, "资料夹过大或包含无法导出的文件。") from error
    def chunks():
        try:
            while data := stream.read(65536):
                yield data
        finally:
            stream.close()
    return StreamingResponse(chunks(), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="MathTutor-conversation.zip"'},
        background=BackgroundTask(stream.close))


@router.post("/documents/import")
async def import_document(
    file: UploadFile = File(...),
    conversation_id: str = "",
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Import one explicitly uploaded file (browser fallback / Electron)."""
    from mathtutor.api.upload_limits import read_upload_limited

    data = await read_upload_limited(file, MAX_DOCUMENT_BYTES)
    picked = PickedFile(
        filename=file.filename or "unnamed",
        mime_type=file.content_type or "",
        data=data,
        original_path="",
    )
    _validate_or_422(picked)
    return await _ingest(owner, picked, conversation_id=conversation_id)


@router.post("/documents/pick")
async def pick_document(
    conversation_id: str = "",
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Ask the desktop shell for ONE explicit user-picked file, then import.

    Returns ``{"status": "cancelled"}`` when the user closes the dialog.
    The shell is unreachable → explicit 501 (never a silent scan).
    """
    try:
        picked = await _document_picker().pick_document_file(owner.student_id)
    except PickTransportUnavailableError as error:
        raise HTTPException(
            status_code=501,
            detail="此环境不支持原生文件选择（桌面壳未运行）。",
        ) from error
    if picked is None:
        return {"status": "cancelled"}
    _validate_or_422(picked)
    document = await _ingest(owner, picked, conversation_id=conversation_id)
    return {"status": "imported", "document": document}


def _require_document(owner: StudentOwnerScope, document_id: str):
    state = get_product_state()
    try:
        doc_uuid = UUID(document_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="文档不存在。") from error
    return state, doc_uuid


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state, doc_uuid = _require_document(owner, document_id)
    doc = await state.documents.get_document(owner.student_id, doc_uuid)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    return _project_document(doc)


@router.patch("/documents/{document_id}")
async def rename_document(
    document_id: str,
    update: DocumentRename,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state, doc_uuid = _require_document(owner, document_id)
    doc = await state.document_repository.get_document(owner.student_id, doc_uuid)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    if getattr(state, "knowledge", None):
        snapshot = await state.knowledge.snapshot(str(owner.student_id), str(doc_uuid))
        if snapshot["provenance"].get("format") == "markdown":
            raise HTTPException(409, "版本化 Markdown 请在知识库编辑标题并确认新版本。")
    from mathtutor.infrastructure.document_storage import sanitize_filename

    safe_name = sanitize_filename(update.filename.strip())
    if not safe_name:
        raise HTTPException(status_code=422, detail="资料名称不能为空。")
    renamed = await state.document_repository.update_document(
        owner.student_id, doc.model_copy(update={"filename": safe_name})
    )
    if renamed is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    return _project_document(renamed)


@router.post("/conversations/{conversation_id}/documents/{document_id}")
async def attach_conversation_document(
    conversation_id: str,
    document_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state, doc_uuid = _require_document(owner, document_id)
    if await state.document_repository.get_document(owner.student_id, doc_uuid) is None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    from mathtutor.api.conversation_guard import require_active
    async with state.turn_requests.conversation(owner.student_id, conversation_id):
        await require_active(state, owner.student_id, conversation_id)
        await state.conversations.attach_document(owner.student_id, conversation_id, doc_uuid)
    return {"ok": True}


@router.delete("/conversations/{conversation_id}/documents/{document_id}")
async def detach_conversation_document(
    conversation_id: str,
    document_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    try:
        doc_uuid = UUID(document_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="文档不存在。") from error
    return {"ok": await get_product_state().conversations.detach_document(owner.student_id, conversation_id, doc_uuid)}


@router.put("/documents/{document_id}")
async def reparse_document(
    document_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Re-run parse + chunk on the stored bytes (same pipeline as import)."""
    state, doc_uuid = _require_document(owner, document_id)
    doc = await state.documents.get_document(owner.student_id, doc_uuid)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    try:
        if getattr(state, "knowledge", None):
            snapshot = await state.knowledge.snapshot(str(owner.student_id), str(doc_uuid))
            if snapshot["provenance"].get("format") == "markdown":
                raise HTTPException(409, "版本化 Markdown 请在知识库编辑；不使用旧重解析入口。")
            await state.knowledge.bump(str(owner.student_id))
        doc = await state.documents.reparse(owner.student_id, doc_uuid)
    except DocumentBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail="文档不存在。") from error
    return _project_document(doc)


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Delete one document through the lifecycle service: soft delete the
    row + remove the storage file (status-quo semantics) AND make the
    content cleanup real — chunk facts and derived vector/index rows go in
    the same breath (Phase 6 round 2, SUBAGENT D)."""
    state, doc_uuid = _require_document(owner, document_id)
    deleted = await state.data_lifecycle.delete_document(
        str(owner.student_id), doc_uuid
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="文档不存在。")
    return {"deleted": True}


class RetrievalToggle(BaseModel):
    enabled: bool


@router.patch("/documents/{document_id}/retrieval")
async def set_document_retrieval(
    document_id: str,
    toggle: RetrievalToggle,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state, doc_uuid = _require_document(owner, document_id)
    try:
        doc = await state.documents.set_retrieval_enabled(
            owner.student_id, doc_uuid, toggle.enabled
        )
        if getattr(state, "knowledge", None):
            await state.knowledge.bump(str(owner.student_id))
    except ValueError as error:
        raise HTTPException(status_code=404, detail="文档不存在。") from error
    return _project_document(doc)


# ---------------------------------------------------------------------------
# Memory — personal memory KG CRUD + the only legal confirm migration.
# ---------------------------------------------------------------------------


def _project_memory(node: PersonalMemoryNode) -> dict:
    return {
        "memory_id": str(node.memory_id),
        "memory_type": node.memory_type,
        "subject": node.subject,
        "predicate": node.predicate,
        "object_json": node.object_json,
        "source_type": node.source_type,
        "confidence": node.confidence,
        "retrieval_enabled": node.retrieval_enabled,
        "created_at": node.created_at.isoformat(),
        "updated_at": node.updated_at.isoformat(),
    }


class MemoryCreate(BaseModel):
    memory_type: str
    subject: str
    predicate: str
    object_json: dict = Field(default_factory=dict)
    confidence: float | None = None


class MemoryUpdate(BaseModel):
    object_json: dict | None = None
    predicate: str | None = None
    confidence: float | None = None


def _require_memory(owner: StudentOwnerScope, memory_id: str) -> UUID:
    try:
        return UUID(memory_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="记忆不存在。") from error


@router.get("/memory")
async def list_memory(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[dict]:
    state = get_product_state()
    nodes = await state.personal_memory.list(owner.student_id)
    nodes = sorted(nodes, key=lambda n: n.updated_at, reverse=True)
    return [_project_memory(node) for node in nodes]


@router.post("/memory")
async def create_memory(
    create: MemoryCreate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    if create.memory_type not in MemoryType.__args__:
        raise HTTPException(status_code=422, detail="未知的记忆类别。")
    if not create.subject.strip() or not create.predicate.strip():
        raise HTTPException(status_code=422, detail="请填写记忆内容（主题与描述）。")
    state = get_product_state()
    try:
        node = await state.personal_memory.add_explicit(
            owner.student_id,
            memory_type=create.memory_type,
            subject=create.subject.strip(),
            predicate=create.predicate.strip(),
            object_json=create.object_json,
            confidence=create.confidence if create.confidence is not None else 0.9,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return _project_memory(node)


@router.put("/memory/{memory_id}")
async def update_memory(
    memory_id: str,
    update: MemoryUpdate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    mem_uuid = _require_memory(owner, memory_id)
    state = get_product_state()
    try:
        node = await state.personal_memory.update(
            owner.student_id,
            mem_uuid,
            object_json=update.object_json,
            predicate=update.predicate.strip() if update.predicate else None,
            confidence=update.confidence,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail="记忆不存在。") from error
    return _project_memory(node)


@router.delete("/memory/{memory_id}")
async def delete_memory(
    memory_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    mem_uuid = _require_memory(owner, memory_id)
    state = get_product_state()
    deleted = await state.data_lifecycle.delete_personal_memory(
        str(owner.student_id), mem_uuid
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="记忆不存在。")
    return {"deleted": True}


@router.patch("/memory/{memory_id}/retrieval")
async def set_memory_retrieval(
    memory_id: str,
    toggle: RetrievalToggle,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    mem_uuid = _require_memory(owner, memory_id)
    state = get_product_state()
    try:
        node = await state.personal_memory.set_retrieval_enabled(
            owner.student_id, mem_uuid, toggle.enabled
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail="记忆不存在。") from error
    return _project_memory(node)


@router.post("/memory/{memory_id}/confirm")
async def confirm_memory(
    memory_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """MODEL_INFERRED → USER_CONFIRMED — the only legal migration."""
    mem_uuid = _require_memory(owner, memory_id)
    state = get_product_state()
    try:
        node = await state.personal_memory.confirm(owner.student_id, mem_uuid)
    except ValueError as error:
        raise HTTPException(
            status_code=409, detail="只有 AI 推测的记忆可以确认。"
        ) from error
    return _project_memory(node)


# ---------------------------------------------------------------------------
# Privacy — data lifecycle (Phase 6 round 2, SUBAGENT D).
#
# Five data classes, four surfaces: USER_CONTROLLED data (documents/memory)
# is deletable per item (existing endpoints above now route through the
# lifecycle service) or purgeable wholesale; AUTHORITY_EDUCATIONAL results
# are deletable ONLY via /privacy/educational-history (facts deleted, the
# StudentState projection REPLAYED — invariant B, never a hand-written
# mastery reset); DERIVED indexes rebuild from chunk facts (invariant E);
# the export carries ONLY whitelisted user-comprehensible projections.
# ---------------------------------------------------------------------------


async def _export_student_summary(state, student_id: str) -> dict:
    """Use the same v2 evidence contract as the application export path."""
    from mathtutor.application.data_export import export_evidence_summary
    return await export_evidence_summary(student_id, uow=state.uow,
                                          student_state=getattr(state, "student_state", None))


@router.post("/privacy/purge-documents")
async def purge_documents(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Delete ALL of the student's documents: live rows soft-deleted,
    chunk facts hard-deleted, derived vectors/index rows removed, every
    controlled storage file deleted. Never touches other students."""
    state = get_product_state()
    summary = await state.data_lifecycle.purge_user_documents(
        str(owner.student_id)
    )
    return {"ok": True, **summary}


@router.post("/privacy/purge-memory")
async def purge_memory(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Soft-delete ALL live personal-memory nodes of the student
    (status-quo node semantics — no trash, immediately invisible)."""
    state = get_product_state()
    summary = await state.data_lifecycle.purge_personal_memory(
        str(owner.student_id)
    )
    return {"ok": True, **summary}


@router.post("/privacy/educational-history")
async def delete_educational_history(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Delete the student's educational RESULT facts (attempts,
    assessments, evidence, observations, attempt-linked verification logs)
    inside one short transaction, then REPLAY the StudentState projection
    from the remaining evidence (invariant B — mastery is never zeroed by
    hand; whatever the replay yields IS the new state). The session
    skeleton (cycles/transitions/problem submissions/tutor actions/offers)
    is kept. Destructive — the UI confirms twice before calling. Never
    routes through the memory CRUD surface."""
    state = get_product_state()
    try:
        async with state.turn_requests.owner(owner.student_id):
            result = await state.data_lifecycle.delete_educational_history(str(owner.student_id))
    except LifecycleUnavailableError as error:
        raise HTTPException(
            status_code=409, detail="当前环境不支持删除教育历史（需要本地数据库）。"
        ) from error
    return {"ok": True, **result}


@router.post("/privacy/rebuild-indexes")
async def rebuild_indexes(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Rebuild the DERIVED embedding indexes from the chunk FACTS
    (invariant E — never re-imports user files). Without a provisioned
    embedding backend every document is honestly marked ``unavailable``."""
    state = get_product_state()
    results = await state.data_lifecycle.rebuild_derived_indexes(
        str(owner.student_id)
    )
    if all(
        value.get("status") in {"rebuilt", "no_chunks"}
        for value in results.values()
    ):
        state.embedding_config.mark_reindexed()
    return {"ok": True, "documents": results}


@router.get("/privacy/export")
async def export_student_data(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Whitelist-only export of the student's OWN, user-comprehensible
    data (document projections, memory projections, student summary).
    Secret/attestation/trace/reasoning/payload/path/hash fields CANNOT
    appear — the export fails closed if any unexpected field shows up."""
    state = get_product_state()
    try:
        from mathtutor.application.data_export import (
            ExportValidationError,
            build_student_export,
        )

        return await build_student_export(
            student_id=str(owner.student_id),
            documents=state.documents,
            memory=state.personal_memory,
            uow=state.uow,
            student_summary_loader=lambda sid: _export_student_summary(state, sid),
        )
    except ExportValidationError as error:
        raise HTTPException(
            status_code=500,
            detail="导出校验失败（出现白名单外字段）——已拒绝导出。",
        ) from error


__all__ = [
    "DESKTOP_ROUTER_PREFIX",
    "build_readiness",
    "mask_secret",
    "router",
    "run_bootstrap",
]
