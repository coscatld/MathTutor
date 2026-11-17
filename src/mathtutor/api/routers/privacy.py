"""Desktop privacy HTTP adapter."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import (
    EducationalHistoryResult,
    PurgeDocumentsResult,
    PurgeMemoryResult,
    RebuildIndexesResult,
    StudentExport,
)
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.schemas import EncryptionUpdate
from mathtutor.application.data_lifecycle import LifecycleUnavailableError
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


def _encryption_status(state) -> dict:
    from mathtutor.infrastructure import db_crypto

    if state.db_path is None:
        return {
            "available": False,
            "mode": "plaintext",
            "pending": None,
            "reason": "当前为内存模式",
        }
    current = db_crypto.state(Path(state.db_path))
    available = db_crypto.available()
    return {
        **current,
        "available": available,
        "backups_encrypted": available,
        "reason": "" if available else "当前环境缺少 SQLCipher 或系统密钥存储",
    }


@router.get("/privacy/encryption")
async def get_encryption(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Database encryption mode, any pending change, and whether backups are encrypted."""
    return _encryption_status(get_product_state())


@router.put("/privacy/encryption")
async def put_encryption(
    update: EncryptionUpdate, owner: StudentOwnerScope = Depends(require_student_owner)
) -> dict:
    """Record the wanted mode; the conversion runs at the next start."""
    from mathtutor.infrastructure import db_crypto

    state = get_product_state()
    if state.db_path is None:
        raise HTTPException(status_code=409, detail="当前为内存模式，不支持加密。")
    try:
        await asyncio.to_thread(
            db_crypto.request_change, Path(state.db_path), update.enabled
        )
    except db_crypto.EncryptionUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    status = _encryption_status(state)
    return {**status, "restart_required": bool(status["pending"])}


@router.post("/privacy/encryption/recovery-key")
async def reveal_recovery_key(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """The backup key, shown only on an explicit request so it can be kept safe."""
    from mathtutor.infrastructure import db_crypto

    try:
        key = await asyncio.to_thread(db_crypto.backup_key)
    except db_crypto.EncryptionUnavailable as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    if not key:
        raise HTTPException(
            status_code=409, detail="当前环境不加密备份，没有恢复密钥。"
        )
    return {"recovery_key": key}


async def _export_student_summary(state, student_id: str) -> dict:
    """Use the same v2 evidence contract as the application export path."""
    from mathtutor.application.data_export import export_evidence_summary

    return await export_evidence_summary(
        student_id, uow=state.uow, student_state=getattr(state, "student_state", None)
    )


@router.post("/privacy/purge-documents", response_model=PurgeDocumentsResult)
async def purge_documents(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Delete ALL of the student's documents: live rows soft-deleted,
    chunk facts hard-deleted, derived vectors/index rows removed, every
    controlled storage file deleted. Never touches other students."""
    state = get_product_state()
    summary = await state.data_lifecycle.purge_user_documents(str(owner.student_id))
    return {"ok": True, **summary}


@router.post("/privacy/purge-memory", response_model=PurgeMemoryResult)
async def purge_memory(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Soft-delete ALL live personal-memory nodes of the student
    (status-quo node semantics — no trash, immediately invisible)."""
    state = get_product_state()
    summary = await state.data_lifecycle.purge_personal_memory(str(owner.student_id))
    return {"ok": True, **summary}


@router.post("/privacy/educational-history", response_model=EducationalHistoryResult)
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
            result = await state.data_lifecycle.delete_educational_history(
                str(owner.student_id)
            )
    except LifecycleUnavailableError as error:
        raise HTTPException(
            status_code=409, detail="当前环境不支持删除教育历史（需要本地数据库）。"
        ) from error
    return {"ok": True, **result}


@router.post("/privacy/rebuild-indexes", response_model=RebuildIndexesResult)
async def rebuild_indexes(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Rebuild the DERIVED embedding indexes from the chunk FACTS
    (invariant E — never re-imports user files). Without a provisioned
    embedding backend every document is honestly marked ``unavailable``."""
    state = get_product_state()
    results = await state.data_lifecycle.rebuild_derived_indexes(str(owner.student_id))
    if all(
        value.get("status") in {"rebuilt", "no_chunks"} for value in results.values()
    ):
        state.embedding_config.mark_reindexed()
    return {"ok": True, "documents": results}


@router.get("/privacy/export", response_model=StudentExport)
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
