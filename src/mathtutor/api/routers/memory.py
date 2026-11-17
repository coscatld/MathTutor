"""Desktop memory HTTP adapter."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import DesktopMemory
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.schemas import (
    MemoryConfirmation,
    MemoryCreate,
    MemoryUpdate,
    RetrievalToggle,
)
from mathtutor.application.public_projections import _project_memory
from mathtutor.domain.memory import MemoryConflictError, MemoryNotFoundError, MemoryType
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


def _memory_conflict_response(error: MemoryConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "code": "memory_conflict",
            "detail": "这条记忆已在其他位置更新。",
            "latest": _project_memory(error.latest),
        },
    )


def _require_memory(owner: StudentOwnerScope, memory_id: str) -> UUID:
    try:
        return UUID(memory_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="记忆不存在。") from error


@router.get("/memory", response_model=list[DesktopMemory])
async def list_memory(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[dict]:
    state = get_product_state()
    nodes = await state.personal_memory.list(owner.student_id)
    nodes = sorted(nodes, key=lambda n: n.updated_at, reverse=True)
    return [_project_memory(node) for node in nodes]


@router.post("/memory", response_model=DesktopMemory)
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


@router.put("/memory/{memory_id}", response_model=DesktopMemory)
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
            expected_updated_at=update.expected_updated_at,
        )
    except MemoryConflictError as error:
        return _memory_conflict_response(error)
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


@router.patch("/memory/{memory_id}/retrieval", response_model=DesktopMemory)
async def set_memory_retrieval(
    memory_id: str,
    toggle: RetrievalToggle,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    mem_uuid = _require_memory(owner, memory_id)
    state = get_product_state()
    try:
        node = await state.personal_memory.set_retrieval_enabled(
            owner.student_id,
            mem_uuid,
            toggle.enabled,
            expected_updated_at=toggle.expected_updated_at,
        )
    except MemoryConflictError as error:
        return _memory_conflict_response(error)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="记忆不存在。") from error
    return _project_memory(node)


@router.post("/memory/{memory_id}/confirm", response_model=DesktopMemory)
async def confirm_memory(
    memory_id: str,
    confirmation: MemoryConfirmation | None = None,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """MODEL_INFERRED → USER_CONFIRMED — the only legal migration."""
    mem_uuid = _require_memory(owner, memory_id)
    state = get_product_state()
    try:
        node = await state.personal_memory.confirm(
            owner.student_id,
            mem_uuid,
            expected_updated_at=confirmation.expected_updated_at
            if confirmation
            else None,
        )
    except MemoryConflictError as error:
        return _memory_conflict_response(error)
    except MemoryNotFoundError as error:
        raise HTTPException(status_code=404, detail="记忆不存在。") from error
    except ValueError as error:
        raise HTTPException(
            status_code=409, detail="只有 AI 推测的记忆可以确认。"
        ) from error
    return _project_memory(node)
