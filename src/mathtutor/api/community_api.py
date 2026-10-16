"""Authenticated community metadata and explicitly requested package operations."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import Field

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.creator_api import require_local_creator_origin
from mathtutor.api.product_state import get_product_state
from mathtutor.application.community import CommunityError, CommunityService, MAX_SHARE_BYTES, Strict
from mathtutor.application.knowledge import KnowledgeError
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter(prefix="/community")


def service_for():
    state = get_product_state()
    return state, getattr(state, "community", None) or CommunityService(state)


async def invoke(owner, action):
    state, service = service_for()
    async with state.turn_requests.owner(owner.student_id):
        try:
            result = action(service)
            if hasattr(result, "__await__"):
                result = await result
            return result
        except KnowledgeError as exc:
            raise HTTPException(409, str(exc)) from None
        except ValueError:
            raise HTTPException(422, "社区资源内容无效，请检查文件、版本和权限说明。") from None


class FavoriteInput(Strict):
    favorite: bool


class SourceInput(Strict):
    name: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2048)


class ImportInput(Strict):
    version: str = Field(min_length=1, max_length=40)
    expected_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    operation_id: str | None = Field(default=None, min_length=1, max_length=128)


class PublishInput(Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    version: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=120)
    author: str = Field(min_length=1, max_length=200)
    license: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=32)
    grades: list[int] = Field(default_factory=list, max_length=12)
    readme: str = Field(default="", max_length=16000)
    changelog: str = Field(default="", max_length=12000)
    project_url: str | None = None
    issues_url: str | None = None
    discussions_url: str | None = None


@router.get("/catalog")
async def catalog(q: str = Query(default="", max_length=200), type: str | None = None, stage: str | None = None,
                  favorites_only: bool = False, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.catalog(owner.student_id, q=q, type=type, stage=stage, favorites_only=favorites_only))


@router.get("/resources/{resource_id}")
async def detail(resource_id: str, version: str | None = None, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.detail(owner.student_id, resource_id, version=version))


@router.put("/resources/{resource_id}/favorite", dependencies=[Depends(require_local_creator_origin)])
async def favorite(resource_id: str, body: FavoriteInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.favorite(owner.student_id, resource_id, body.favorite))


@router.post("/resources/{resource_id}/import", dependencies=[Depends(require_local_creator_origin)])
async def import_resource(resource_id: str, body: ImportInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.import_resource(owner.student_id, resource_id, **body.model_dump()))


@router.get("/resources/{resource_id}/export")
async def export_resource(resource_id: str, version: str | None = None, expected_sha256: str | None = None,
                          owner: StudentOwnerScope = Depends(require_student_owner)):
    data = await invoke(owner, lambda service: service.export_resource(owner.student_id, resource_id,
        version=version, expected_sha256=expected_sha256))
    return Response(data, media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="MathTutor-community-resource.json"', "X-Content-Type-Options": "nosniff"})


@router.get("/sources")
async def sources(owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.sources(owner.student_id))


@router.post("/sources", dependencies=[Depends(require_local_creator_origin)])
async def subscribe(body: SourceInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.subscribe(owner.student_id, body.name, body.url))


@router.post("/sources/import", dependencies=[Depends(require_local_creator_origin)])
async def import_source(file: UploadFile = File(...), owner: StudentOwnerScope = Depends(require_student_owner)):
    data = await file.read(MAX_SHARE_BYTES + 1)
    if len(data) > MAX_SHARE_BYTES:
        raise HTTPException(413, "分享资源文件最多 32 MiB。")
    return await invoke(owner, lambda service: service.import_source(owner.student_id, data))


@router.post("/import", dependencies=[Depends(require_local_creator_origin)])
async def import_file(file: UploadFile = File(...), operation_id: str | None = Form(default=None, min_length=1, max_length=128),
                      owner: StudentOwnerScope = Depends(require_student_owner)):
    data = await file.read(MAX_SHARE_BYTES + 1)
    if len(data) > MAX_SHARE_BYTES:
        raise HTTPException(413, "分享文件最多 32 MiB。")
    try:
        return await invoke(owner, lambda service: service.import_file(owner.student_id, data, file.filename or "", operation_id=operation_id))
    except HTTPException as exc:
        if isinstance(exc.detail, str):
            exc.detail = exc.detail.replace("JSON", "文件内容").replace("SHA256", "完整性").replace("Base64", "文件编码")
        raise


@router.post("/plugins/import", dependencies=[Depends(require_local_creator_origin)])
async def import_plugin_file(file: UploadFile = File(...), operation_id: str | None = Form(default=None, min_length=1, max_length=128),
                             owner: StudentOwnerScope = Depends(require_student_owner)):
    data = await file.read(MAX_SHARE_BYTES + 1)
    if len(data) > MAX_SHARE_BYTES:
        raise HTTPException(413, "插件文件最多 32 MiB。")
    async def action(service):
        try:
            service.validate_plugin_file(data, file.filename or "")
        except (KnowledgeError, ValueError):
            raise HTTPException(422, "请选择完整有效的 MathTutor 插件文件；题库和笔记请使用资料导入。") from None
        return await service.import_file(owner.student_id, data, file.filename or "", operation_id=operation_id)
    return await invoke(owner, action)


@router.post("/sources/{source_id}/refresh", dependencies=[Depends(require_local_creator_origin)])
async def refresh(source_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.refresh(owner.student_id, source_id))


@router.delete("/sources/{source_id}", dependencies=[Depends(require_local_creator_origin)])
async def remove_source(source_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.remove_source(owner.student_id, source_id))


@router.get("/history")
async def history(owner: StudentOwnerScope = Depends(require_student_owner)):
    return await invoke(owner, lambda service: service.history(owner.student_id))


@router.post("/libraries/{sid}/publish", dependencies=[Depends(require_local_creator_origin)])
async def publish_library(sid: str, body: PublishInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    data = await invoke(owner, lambda service: service.publish_library(owner.student_id, sid, body.model_dump()))
    return Response(data, media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="MathTutor-community-resource.json"', "X-Content-Type-Options": "nosniff"})


@router.delete("/state", dependencies=[Depends(require_local_creator_origin)])
async def delete_state(owner: StudentOwnerScope = Depends(require_student_owner)):
    # Personal libraries and installed plugins have separate explicit deletion
    # controls. Resetting directory preferences cannot silently delete either.
    return await invoke(owner, lambda service: service.delete_owner_data(owner.student_id))
