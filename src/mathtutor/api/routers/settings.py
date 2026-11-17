"""Desktop settings HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import (
    DesktopSettings,
    ModelTestResult,
    ProviderPreset,
    SettingsSaveResult,
    TestConnectionResult,
    TutorSettings,
)
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.schemas import (
    ConfigOperation,
    SettingsUpdate,
    TutorSettingsUpdate,
)
from mathtutor.infrastructure.gateway_config import (
    GatewayRevisionConflict,
    secret_key_name,
)
from mathtutor.infrastructure.generative_gateway import PRESETS, GenerativeConfigError
from mathtutor.infrastructure.secret_store import SecretStore
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


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


def _config_receipt(config: dict, service) -> dict:
    revision = int(config.get("revision", service.revision()))
    current = service.revision()
    return {
        "epoch": config.get("epoch"),
        "revision": revision,
        "current_revision": current,
        "accepted": revision == current,
        "persisted": bool(config.get("persisted", False)),
        "persistence_error": config.get("persistence_error"),
        **(
            {"operation_id": config["operation_id"]} if "operation_id" in config else {}
        ),
    }


def _probe_receipt(result, service) -> dict:
    current = service.revision()
    return {
        "epoch": result.epoch,
        "revision": result.revision,
        "current_revision": current,
        "operation_id": result.operation_id,
        "provider_id": result.provider_id,
        "accepted": result.accepted and current == result.revision,
        "persisted": result.persisted,
        "persistence_error": result.persistence_error,
    }


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


@router.get("/settings", response_model=DesktopSettings)
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
        "initial_assessment_required": bool(
            assessment_state
            and assessment_state["status"] in {"pending", "in_progress"}
        ),
        "preset_id": preset_id,
        "model": str(config.get("model") or ""),
        "base_url": str(config.get("base_url") or ""),
        "vision_mode": service.provider_profiles()
        .get(preset_id, {})
        .get("vision_mode", "auto"),
        "is_configured": await service.is_ready(),
        "onboarding_completed": service.onboarding_completed(),
        "key_masked": masked,
        "connection_status": service.connection_status(),
        "provider_configs": profiles,
        **_config_receipt(config, service),
    }


@router.get("/settings/presets", response_model=list[ProviderPreset])
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


@router.get("/settings/tutor", response_model=TutorSettings)
async def get_tutor_settings(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    return get_product_state().tutor_preferences.public_settings()


@router.put("/settings/tutor", response_model=TutorSettings)
async def put_tutor_settings(
    update: TutorSettingsUpdate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    try:
        result = state.tutor_preferences.update(
            update.personality, update.custom_instruction
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    state.refresh_model_writer()
    return result


@router.put("/settings", response_model=SettingsSaveResult)
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
            expected_revision=update.expected_revision,
            expected_epoch=update.expected_epoch,
            operation_id=update.operation_id,
        )
    except GatewayRevisionConflict as error:
        raise HTTPException(
            status_code=409, detail="模型配置已变化，请重新读取后再保存。"
        ) from error
    except GenerativeConfigError as error:
        raise HTTPException(
            status_code=422, detail="配置无效，请检查填写内容。"
        ) from error

    get_product_state().refresh_model_writer()

    assessment = get_product_state().initial_assessment
    if (
        assessment
        and not was_configured
        and update.api_key
        and await service.is_ready()
    ):
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
        "vision_mode": config.get("provider_configs", {})
        .get(str(config.get("preset_id") or ""), {})
        .get("vision_mode", "auto"),
        "model": str(config.get("model") or ""),
        "base_url": str(config.get("base_url") or ""),
        "key_masked": masked,
        "is_configured": await service.is_ready(),
        "onboarding_completed": service.onboarding_completed(),
        "connection_status": service.connection_status(),
        "initial_assessment_required": bool(
            assessment_state
            and assessment_state["status"] in {"pending", "in_progress"}
        ),
        **_config_receipt(config, service),
    }


@router.post("/settings/onboarding/skip")
async def skip_provider_onboarding(
    operation: ConfigOperation | None = None,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Remember the explicit choice to continue in template teaching mode."""
    service = _gateway_config_service()
    try:
        config = await service.mark_onboarding_completed(
            expected_revision=operation.revision if operation else None,
            expected_epoch=operation.epoch if operation else None,
            operation_id=operation.operation_id if operation else None,
        )
    except GatewayRevisionConflict as error:
        raise HTTPException(
            status_code=409, detail="模型配置已变化，请重新读取后再保存。"
        ) from error
    return {
        "ok": True,
        "onboarding_completed": True,
        **_config_receipt(config, service),
    }


@router.delete("/settings/api-key", response_model=DesktopSettings)
async def delete_api_key(
    operation: ConfigOperation | None = None,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Remove the OS-stored credential and immediately fall back to templates."""
    service = _gateway_config_service()
    active = str(service.current_config().get("preset_id") or "")
    if active and not PRESETS[active].requires_api_key:
        raise HTTPException(status_code=422, detail="本地 Ollama 不使用 API Key。")
    try:
        config = await service.remove_api_key(
            expected_revision=operation.revision if operation else None,
            expected_epoch=operation.epoch if operation else None,
            operation_id=operation.operation_id if operation else None,
        )
    except GatewayRevisionConflict as error:
        raise HTTPException(
            status_code=409, detail="模型配置已变化，请重新读取后再保存。"
        ) from error
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
        **_config_receipt(config, service),
    }


@router.post("/settings/test-connection", response_model=TestConnectionResult)
async def test_connection(
    operation: ConfigOperation | None = None,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Legacy probe route with the same revision ownership as /model/test."""
    service = _gateway_config_service()
    result = await service.test_connection(
        expected_revision=operation.revision if operation else None,
        expected_epoch=operation.epoch if operation else None,
        operation_id=operation.operation_id if operation else None,
    )
    metadata = _probe_receipt(result, service)
    if not metadata["accepted"]:
        return {
            "status": "error",
            "message": "配置已变化，本次测试结果未应用。请测试当前配置。",
            "resolved_model": "",
            **metadata,
        }
    if result.status == "ok":
        get_product_state().refresh_model_writer()
        return {
            "status": "ok",
            "message": result.message or "连接成功，模型可正常调用。",
            "resolved_model": result.resolved_model,
            **metadata,
        }
    message = (
        "尚未配置模型提供商，请先保存 API Key。"
        if "no provider configured" in result.message
        else f"连接失败：{result.message}"
    )
    return {"status": "error", "message": message, "resolved_model": "", **metadata}


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


@router.post("/model/test", response_model=ModelTestResult)
async def test_model(
    operation: ConfigOperation | None = None,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Probe the configured provider (wire contract ModelTestResult).

    ``error_kind`` is the five-way classification; ``message`` is friendly
    copy by contract — the raw (redacted) provider message never leaves
    this router.
    """
    service = _gateway_config_service()
    result = await service.test_connection(
        expected_revision=operation.revision if operation else None,
        expected_epoch=operation.epoch if operation else None,
        operation_id=operation.operation_id if operation else None,
    )
    metadata = _probe_receipt(result, service)
    if not metadata["accepted"]:
        return {
            "ok": False,
            "error_kind": None,
            "message": "配置已变化，本次测试结果未应用。请测试当前配置。",
            "resolved_model": "",
            **metadata,
        }
    if result.status == "ok":
        get_product_state().refresh_model_writer()
        provider_id = result.provider_id
        return {
            "ok": True,
            "error_kind": None,
            "message": "已连接到本地 Ollama。"
            if provider_id == "ollama"
            else "连接成功，模型可正常调用。",
            "resolved_model": result.resolved_model,
            **metadata,
        }
    kind = result.error_kind or "provider_error"
    provider_id = result.provider_id
    message = _MODEL_TEST_MESSAGES.get(kind, "连接失败，请稍后重试。")
    if provider_id == "ollama" and kind == "network_unavailable":
        message = "Ollama 服务暂时不可用，请确认本地服务已启动。"
    return {
        "ok": False,
        "error_kind": kind,
        "message": message,
        **metadata,
    }
