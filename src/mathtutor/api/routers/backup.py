"""Desktop backup HTTP adapter."""

from __future__ import annotations

import asyncio
import fnmatch
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import (
    BackupActionResult,
    BackupRestoreResult,
    BackupsList,
    BackupVerifyResult,
)
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.schemas import BackupPathRequest
from mathtutor.application.restore_runtime import _restore_backup_while_quiesced
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()

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


@router.get("/backups", response_model=BackupsList)
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


@router.post("/backup", response_model=BackupActionResult)
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


@router.post("/backup/verify", response_model=BackupVerifyResult)
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


@router.post("/backup/restore", response_model=BackupRestoreResult)
async def restore_backup_endpoint(
    request: BackupPathRequest,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Hold admission until the owned restore reaches a known file/runtime state."""
    state = get_product_state()
    _require_backup_service(state)
    if state.db_path is None:
        raise HTTPException(status_code=409, detail="当前为内存模式，不支持恢复。")
    backup_path = _resolve_backup_path(state, request.path)
    # Acquisition itself is cancellation-safe; a rejected contender cannot
    # release the first restore's gate. Cancellation after acquisition joins
    # the complete owned operation before releasing either runtime's gate.
    async with state.maintenance(timeout=5.0) as acquired:
        if not acquired:
            return {
                "ok": False,
                "message": "当前仍有学习请求正在处理，未开始恢复，请稍后重试。",
            }
        return await _restore_backup_while_quiesced(
            state, backup_path, request.recovery_key
        )
