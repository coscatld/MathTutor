"""Explicit owner-controlled declarative package lifecycle and local results."""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import Field

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.creator_api import require_local_creator_origin
from mathtutor.api.product_state import get_product_state
from mathtutor.extensions.community_plugins import Permission, builtin_plugin_packages, validate_package, package_hash
from mathtutor.extensions.registry import ExtensionError, StrictArguments
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter(prefix="/community/plugins")
mutating = [Depends(require_local_creator_origin)]


def service():
    result = getattr(get_product_state(), "community_plugins", None)
    if result is None:
        raise HTTPException(409, "社区插件运行时尚未初始化。")
    return result


def invoke(action):
    try:
        return action()
    except ExtensionError as exc:
        raise HTTPException(409, str(exc)) from None


class ImportInput(StrictArguments):
    package: dict


class EnableInput(StrictArguments):
    enabled: bool
    consent_permissions: list[Permission] = Field(default_factory=list, max_length=2)


class ConfigInput(StrictArguments):
    config: dict = Field(default_factory=dict)


@router.get("")
async def list_plugins(owner: StudentOwnerScope = Depends(require_student_owner)):
    return {"items": invoke(lambda: service().list_installed(owner.student_id))}


@router.get("/examples")
async def examples(owner: StudentOwnerScope = Depends(require_student_owner)):
    return {"items": builtin_plugin_packages()}


@router.post("/validate", dependencies=mutating)
async def validate_plugin(body: ImportInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    def check():
        normalized = validate_package(body.package).model_dump()
        return {"package": normalized, "package_hash": package_hash(normalized)}
    return invoke(check)


@router.post("", dependencies=mutating)
async def import_plugin(body: ImportInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        return invoke(lambda: service().import_package(owner.student_id, body.package))


@router.put("/{plugin_id}/enabled", dependencies=mutating)
async def enable_plugin(plugin_id: str, body: EnableInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        return invoke(lambda: service().set_enabled(owner.student_id, plugin_id,
            enabled=body.enabled, consent_permissions=body.consent_permissions))


@router.patch("/{plugin_id}/config", dependencies=mutating)
async def configure_plugin(plugin_id: str, body: ConfigInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        return invoke(lambda: service().configure(owner.student_id, plugin_id, body.config))


@router.delete("/{plugin_id}", dependencies=mutating)
async def uninstall_plugin(plugin_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        return invoke(lambda: service().uninstall(owner.student_id, plugin_id))


@router.post("/{plugin_id}/run", dependencies=mutating)
async def run_plugin(plugin_id: str, body: ConfigInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = get_product_state()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await service().run(owner.student_id, plugin_id, body.config)
        except ExtensionError as exc:
            raise HTTPException(409, str(exc)) from None


@router.get("/{plugin_id}/export")
async def export_plugin(plugin_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    package = invoke(lambda: service().export_package(owner.student_id, plugin_id))
    return Response(json.dumps(package, ensure_ascii=False, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{package["id"]}-{package["version"]}.plugin.json"'})
