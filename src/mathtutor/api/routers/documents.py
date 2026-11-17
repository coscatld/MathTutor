"""Desktop documents HTTP adapter."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import DesktopDocument
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.schemas import (
    DocumentRename,
    DocumentScopeInput,
    RetrievalToggle,
)
from mathtutor.application.desktop_files import (
    LoopbackElectronPickTransport,
    NativeDesktopFilePicker,
    PickedFile,
    PickTransportUnavailableError,
)
from mathtutor.application.document_ingestion import DocumentBusyError
from mathtutor.application.public_projections import _project_document
from mathtutor.domain.documents import MAX_DOCUMENT_BYTES
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


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


async def _ingest(
    owner: StudentOwnerScope, picked: PickedFile, *, conversation_id: str = ""
) -> dict:
    state = get_product_state()
    from mathtutor.api.conversation_guard import require_active

    if conversation_id.strip():
        async with state.turn_requests.conversation(
            owner.student_id, conversation_id.strip()
        ):
            await require_active(state, owner.student_id, conversation_id.strip())
            doc = await state.documents.ingest(owner.student_id, picked)
            await state.conversations.attach_document(
                owner.student_id, conversation_id.strip(), doc.document_id
            )
    else:
        doc = await state.documents.ingest(owner.student_id, picked)
    return _project_document(doc)


@router.get("/documents", response_model=list[DesktopDocument])
async def list_documents(
    conversation_id: str = "",
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[dict]:
    state = get_product_state()
    docs = await state.documents.list_documents(owner.student_id)
    if conversation_id.strip():
        from mathtutor.api.conversation_guard import require_active

        await require_active(state, owner.student_id, conversation_id.strip())
        allowed = set(
            await state.conversations.document_ids(
                owner.student_id, conversation_id.strip()
            )
        )
        allowed.update(d.document_id for d in docs if d.is_global)
        docs = [doc for doc in docs if doc.document_id in allowed]
    docs = sorted(docs, key=lambda d: d.created_at, reverse=True)
    result = []
    for doc in docs:
        memberships = await state.conversations.conversation_ids_for_document(
            owner.student_id, doc.document_id
        )
        active_memberships = []
        for cid in memberships:
            row = await state.conversations.get(owner.student_id, cid)
            if row and not row.get("trashed_at") and not row.get("purged_at"):
                active_memberships.append(cid)
        if memberships and not active_memberships and not doc.is_global:
            continue
        memberships = active_memberships
        titles = {
            cid: (await state.conversations.get(owner.student_id, cid) or {}).get(
                "title", "未命名对话"
            )
            for cid in memberships
        }
        result.append(
            {
                "conversation_titles": titles,
                **_project_document(doc),
                "conversation_ids": memberships,
            }
        )
    return result


@router.patch("/documents/{document_id}/scope", response_model=DesktopDocument)
async def set_document_scope_setting(
    document_id: UUID,
    body: DocumentScopeInput,
    owner: StudentOwnerScope = Depends(require_student_owner),
):
    state = get_product_state()
    doc = await state.documents.get_document(owner.student_id, document_id)
    if doc is None:
        raise HTTPException(404, "资料不存在")
    updated = await state.document_repository.update_document(
        owner.student_id, doc.model_copy(update={"is_global": body.is_global})
    )
    if updated is None:
        raise HTTPException(404, "资料不存在")
    return _project_document(updated)


@router.get("/conversations/{conversation_id}/resources")
async def conversation_resources(
    conversation_id: str, owner: StudentOwnerScope = Depends(require_student_owner)
):
    from mathtutor.api.conversation_guard import require_active
    from mathtutor.application.conversation_resources import reference_state, resources

    await require_active(get_product_state(), owner.student_id, conversation_id)
    state = get_product_state()
    scope = await reference_state(state, owner.student_id, conversation_id)
    documents, images, messages = await resources(
        state, owner.student_id, conversation_id, scope=scope
    )
    candidates = {d["document_id"]: d for d in scope["available_documents"]}
    effective = set(scope["effective_document_ids"])
    return {
        "documents": [
            {
                **_project_document(d),
                "in_scope": str(d.document_id) in effective,
                "origin": candidates[str(d.document_id)]["origin"],
                "space_ids": candidates[str(d.document_id)]["space_ids"],
            }
            for d in documents
        ],
        "images": images,
        "message_count": len(messages),
        "scope": scope,
    }


@router.get("/conversations/{conversation_id}/export")
async def export_conversation_folder(
    conversation_id: str, owner: StudentOwnerScope = Depends(require_student_owner)
):
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

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="MathTutor-conversation.zip"'
        },
        background=BackgroundTask(stream.close),
    )


@router.post("/documents/import", response_model=DesktopDocument)
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


@router.get("/documents/{document_id}", response_model=DesktopDocument)
async def get_document(
    document_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state, doc_uuid = _require_document(owner, document_id)
    doc = await state.documents.get_document(owner.student_id, doc_uuid)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=404, detail="文档不存在。")
    return _project_document(doc)


@router.patch("/documents/{document_id}", response_model=DesktopDocument)
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
        await state.conversations.attach_document(
            owner.student_id, conversation_id, doc_uuid
        )
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
    return {
        "ok": await get_product_state().conversations.detach_document(
            owner.student_id, conversation_id, doc_uuid
        )
    }


@router.put("/documents/{document_id}", response_model=DesktopDocument)
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
            snapshot = await state.knowledge.snapshot(
                str(owner.student_id), str(doc_uuid)
            )
            if snapshot["provenance"].get("format") == "markdown":
                raise HTTPException(
                    409, "版本化 Markdown 请在知识库编辑；不使用旧重解析入口。"
                )
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


@router.patch("/documents/{document_id}/retrieval", response_model=DesktopDocument)
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
