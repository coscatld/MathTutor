"""Desktop embedding settings HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import EmbeddingSettings, EmbeddingTestResult
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.schemas import (
    EmbeddingSettingsUpdate,
    LocalEmbeddingDownloadRequest,
)
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


@router.get("/settings/embedding", response_model=EmbeddingSettings)
async def get_embedding_settings(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    await state.refresh_embedding_runtime()
    return await state.embedding_config.public_settings()


@router.put("/settings/embedding", response_model=EmbeddingSettings)
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


@router.delete("/settings/embedding/api-key", response_model=EmbeddingSettings)
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


@router.post("/settings/embedding/test", response_model=EmbeddingTestResult)
async def test_embedding_connection(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    # Failure is a normal, friendly result; it never crashes the settings UI.
    return await get_product_state().embedding_config.test_cloud()


@router.post(
    "/settings/embedding/local/download",
    status_code=202,
    response_model=EmbeddingSettings,
)
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


@router.delete("/settings/embedding/local/{model_id}", response_model=EmbeddingSettings)
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
