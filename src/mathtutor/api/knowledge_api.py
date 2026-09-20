"""Owner-authenticated knowledge UI operations; no raw filesystem paths."""
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.knowledge_tools import Strict, KnowledgeTools, Save
from mathtutor.security.scopes import StudentOwnerScope
from mathtutor.infrastructure.knowledge_schema import drafts

router = APIRouter(prefix="/knowledge")


def state_for():
    state = get_product_state()
    if not getattr(state, "knowledge", None):
        raise HTTPException(409, "知识库需要持久数据库，请使用正式本地服务。")
    return state


async def invoke(owner, action):
    state = state_for()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await action(state, owner.student_id)
        except KnowledgeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except IntegrityError as exc:
            raise HTTPException(409, "同一内容或版本已存在，请刷新后重试。") from exc


class LibraryInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["personal", "course", "session"] = "personal"
    conversation_id: str = Field(default="", max_length=128)


class Toggle(Strict):
    enabled: bool


class ReviewPreferences(Strict):
    goal: str = Field(default="", max_length=240)
    style: Literal["default", "stepwise", "concise"] = "default"


@router.get("/stage-review")
async def stage_review(owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda s, o: s.stage_review.read(o))


@router.post("/stage-review")
async def request_review(owner: StudentOwnerScope = Depends(require_student_owner)):
    async def action(s, o):
        result = await s.stage_review.request(o)
        s.outbox_relay.wake()
        return result
    return await invoke(owner, action)


@router.put("/stage-review/preferences")
async def review_preferences(body: ReviewPreferences, owner: StudentOwnerScope = Depends(require_student_owner)):
    async def action(s, o):
        result = await s.stage_review.set_preferences(o, **body.model_dump())
        s.outbox_relay.wake()
        return result
    return await invoke(owner, action)


class MountInput(Strict):
    space_ids: list[str] = Field(default_factory=list, max_length=32)
    document_ids: list[str] = Field(default_factory=list, max_length=128)
    only_selected: bool = False
    mode: Literal["knowledge", "tutor"] = "knowledge"
    save_space_id: str = Field(default="", max_length=80)
    tool_mode: Literal["native", "structured"] = "native"
    hints_only: bool = False


class NoteInput(Strict):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=1024 * 1024)
    tags: list[str] = Field(default_factory=list, max_length=32)
    operation_id: str = Field(min_length=1, max_length=160)
    document_id: UUID | None = None
    expected_version: int | None = Field(default=None, ge=1)
    relative_path: str = Field(default="", max_length=512)


@router.get("/libraries")
async def libraries(owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda s, o: s.knowledge.list_spaces(o))


@router.post("/libraries")
async def create_library(body: LibraryInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda s, o: s.knowledge.create_space(o, **body.model_dump()))


@router.put("/libraries/{sid}/enabled")
async def enable_library(sid: str, body: Toggle, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda s, o: s.knowledge.set_enabled(o, sid, body.enabled))


@router.delete("/libraries/{sid}")
async def delete_library(sid: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda s, o: s.knowledge.delete_space(o, sid))


@router.get("/libraries/{sid}/notes")
async def notes(sid: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda s, o: s.knowledge.list_notes(o, sid))


@router.post("/libraries/{sid}/notes")
async def save_note(sid: str, body: NoteInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    path = PurePosixPath(body.relative_path.replace("\\", "/"))
    if body.relative_path and (path.is_absolute() or ".." in path.parts or any(p.startswith(".") for p in path.parts)
                               or path.suffix.lower() != ".md"):
        raise HTTPException(422, "仅导入明确选择的 Markdown 文件；隐藏目录、插件和越界路径不会导入。")
    return await invoke(owner, lambda s, o: s.knowledge.save_markdown(o, sid,
        title=body.title, body=body.body, tags=body.tags, operation_id=body.operation_id,
        document_id=str(body.document_id) if body.document_id else None, expected_version=body.expected_version,
        provenance={"origin": "user", "relative_path": body.relative_path}))


@router.post("/libraries/{sid}/imports")
async def import_file(sid: str, file: UploadFile = File(...), owner: StudentOwnerScope = Depends(require_student_owner)):
    from mathtutor.application.desktop_files import PickedFile
    from mathtutor.domain.documents import MAX_DOCUMENT_BYTES
    data = await file.read(MAX_DOCUMENT_BYTES + 1)
    if len(data) > MAX_DOCUMENT_BYTES:
        raise HTTPException(413, "文件超过导入大小限制。")
    async def action(state, oid):
        await state.knowledge.require_space(oid, sid, enabled=True)
        generation = await state.knowledge.generation(oid)
        picked = PickedFile(filename=file.filename or "document", mime_type=file.content_type or "", data=data)
        try:
            doc = await state.documents.ingest(oid, picked)
        except ValueError as exc:
            raise KnowledgeError(str(exc)) from exc
        row = await state.knowledge.attach(oid, sid, str(doc.document_id), expected_generation=generation)
        return {"document_id": str(doc.document_id), "version": row["version"], "status": doc.status}
    return await invoke(owner, action)


@router.get("/libraries/{sid}/export")
async def export_library(sid: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    data = await invoke(owner, lambda s, o: s.knowledge.export(o, sid))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": 'attachment; filename="knowledge.zip"'})


@router.get("/conversations/{cid}")
async def mount_state(cid: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    async def action(s, o):
        if not await s.conversations.get(o, cid):
            return {"space_ids": [], "document_ids": [], "only_selected": False, "mode": "tutor", "available_documents": []}
        await s.knowledge.require_conversation(o, cid)
        config = await s.knowledge.configuration(o, cid)
        ids = await s.knowledge.scope(o, cid, configuration={**config, "only_selected": False})
        eligible = []
        for did in ids:
            doc = await s.documents.get_document(o, did)
            if doc:
                eligible.append({"document_id": str(did), "title": doc.filename, "enabled": doc.is_retrievable()})
        return {**config, "available_documents": eligible}
    return await invoke(owner, action)


@router.put("/conversations/{cid}")
async def mount(cid: str, body: MountInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda s, o: s.knowledge.configure(o, cid, **body.model_dump()))


@router.get("/sources/{did}")
async def source(did: UUID, conversation: str = "", version: int | None = Query(None, ge=1),
                 start: int = Query(0, ge=0), end: int | None = Query(None, ge=1),
                 owner: StudentOwnerScope = Depends(require_student_owner)):
    async def action(s, o):
        if conversation:
            if version is None or end is None:
                raise KnowledgeError("引用须指定版本及区间。")
            return await s.knowledge.read_source(o, conversation, str(did), version, start, end)
        row = await s.knowledge.snapshot(o, str(did), version)
        return {**row, "backlinks": await s.knowledge.backlinks(o, str(did))}
    return await invoke(owner, action)


@router.get("/drafts")
async def list_drafts(owner: StudentOwnerScope = Depends(require_student_owner)):
    async def action(s, o):
        generation = await s.knowledge.generation(o)
        async with s.knowledge.engine.connect() as db:
            return list((await db.execute(select(drafts.c.payload).where(drafts.c.student_id == o,
                drafts.c.generation == generation).limit(30))).scalars())
    return await invoke(owner, action)


class DraftSave(Strict):
    space_id: str = Field(min_length=1, max_length=80)


@router.post("/drafts/{draft_id}/save")
async def save_draft(draft_id: str, body: DraftSave, owner: StudentOwnerScope = Depends(require_student_owner)):
    async def action(s, o):
        generation = await s.knowledge.generation(o)
        async with s.knowledge.engine.connect() as db:
            payload = (await db.execute(select(drafts.c.payload).where(drafts.c.student_id == o,
                drafts.c.draft_id == draft_id, drafts.c.generation == generation))).scalar_one_or_none()
        if not payload:
            raise KnowledgeError("草稿已失效。")
        executor = KnowledgeTools(s, o, payload["conversation_id"], generation=generation,
            save_space=body.space_id, allow_save=True)
        return await executor._dispatch("save_note", Save(draft_id=draft_id))
    return await invoke(owner, action)
