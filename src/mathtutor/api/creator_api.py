"""Owner-authenticated catalog and explicit local directory grants; no code loading."""
import os
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.extensions import ExecutionContext, ExtensionError, StrictArguments
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter(prefix="/creator")


def require_local_creator_origin(request: Request):
    """Protect native dialogs and file grants from cross-site browser requests."""
    origin = request.headers.get("origin")
    if origin is None:  # authenticated non-browser clients have no Origin
        return
    try:
        parsed = urlsplit(origin)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                 and not parsed.username and not parsed.password and parsed.path in {"", "/"}
                 and not parsed.query and not parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(403, "目录授权只能从本地应用界面或认证客户端操作。")


@router.get("/catalog")
async def catalog(owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    result = state.extension_registry.catalog(ExecutionContext(owner_id=owner.student_id, conversation_id="catalog"))
    from mathtutor.skills.canvas_drawing import DRAW_SCENE_TOOL
    from mathtutor.application.tutor_runtime import VERIFY_MATH_TOOL
    result["skills"].insert(0, {"id": "mathtutor.canvas-drawing", "name": "交互画布作图",
        "description": "根据数学定义绘制函数和几何图形，实际场景由应用校验。", "kind": "teaching-skill",
        "version": "1.0.0", "source": "builtin", "enabled": True, "activation": "数学对话按需提供"})
    for definition, title in ((VERIFY_MATH_TOOL, "数学核验"), (DRAW_SCENE_TOOL, "交互画布")):
        function = definition["function"]
        result["tools"].insert(0, {"id": "mathtutor." + function["name"], "name": function["name"], "title": title,
            "description": function["description"], "source": "builtin", "active": True,
            "activation": "数学对话按需提供", "input_schema": function["parameters"]})
    result["workspaces"] = state.workspace_grants.list(owner.student_id)
    result["workspace_policy"] = {"persistent": False, "expires": "process-restart",
        "text_types": ["md", "txt", "json", "csv", "tsv"], "max_file_bytes": 65536}
    return result


@router.get("/workspaces")
async def workspaces(owner: StudentOwnerScope = Depends(require_student_owner)):
    return {"workspaces": get_product_state().workspace_grants.list(owner.student_id), "persistent": False}


class WorkspaceInput(StrictArguments):
    path: str = Field(min_length=1, max_length=4096)
    writable: bool = False


@router.post("/workspaces", dependencies=[Depends(require_local_creator_origin)])
async def grant_workspace(body: WorkspaceInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return state.workspace_grants.grant(owner.student_id, body.path, writable=body.writable)
        except ExtensionError as exc:
            raise HTTPException(422, str(exc)) from None


@router.delete("/workspaces/{workspace_id}", dependencies=[Depends(require_local_creator_origin)])
async def revoke_workspace(workspace_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return state.workspace_grants.revoke(owner.student_id, workspace_id)
        except ExtensionError as exc:
            raise HTTPException(404, str(exc)) from None


@router.post("/workspaces/pick", dependencies=[Depends(require_local_creator_origin)])
async def pick_workspace(owner: StudentOwnerScope = Depends(require_student_owner)):
    """Only an explicit UI POST opens a dialog. Picking does not grant access."""
    raw = os.environ.get("MATHTUTOR_ELECTRON_PICKER_URL", "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError:
        raise HTTPException(409, "原生目录选择器配置无效，请手动输入目录完整路径。") from None
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.username or parsed.password:
        raise HTTPException(409, "当前环境没有原生目录选择器，请手动输入目录完整路径。")
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, "/native-directory", "", ""))
    try:
        async with httpx.AsyncClient(timeout=55, trust_env=False) as client:
            response = await client.post(endpoint, json={"student_id": owner.student_id})
        response.raise_for_status()
        payload = response.json()
        path = payload.get("path")
        if path is None or payload.get("cancelled") is True:
            return {"path": None, "cancelled": True}
        if not isinstance(path, str) or not path or len(path) > 4096:
            raise ValueError("Invalid directory response")
        return {"path": path, "cancelled": False}
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        raise HTTPException(503, "目录选择未完成，可重试或手动输入路径。") from None
