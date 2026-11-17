"""Quiesced restore and rollback orchestration for the product runtime."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from uuid import uuid4


async def _restore_io(function, *args):
    from mathtutor.infrastructure.owned_task import join_owned

    return await join_owned(asyncio.create_task(asyncio.to_thread(function, *args)))


async def _restore_backup_while_quiesced(
    state, backup_path: Path, recovery_key: str | None = None
) -> dict:
    """Keep one runtime-owned task through stop, every worker, and recovery."""
    return await state.run_restore(
        lambda: _perform_owned_restore(state, backup_path, recovery_key)
    )


def _restore_failed_closed(state, error: BaseException) -> dict:
    state.lifecycle_status = "FAILED"
    state._maintenance_active = True
    state.restore_status = "FAILED"
    state.restore_error = str(error)
    return {
        "ok": False,
        "recovery_required": True,
        "message": "恢复未完成，无法确认安全运行状态。应用保持维护状态，请保留数据库及现有恢复材料。",
    }


async def _remove_restore_image(state, path: Path) -> None:
    try:
        await _restore_io(lambda: path.unlink(missing_ok=True))
    except OSError as error:
        # A cleanup failure does not invalidate an already verified database.
        state.restore_cleanup_error = str(error)
    else:
        state.restore_recovery_path = None


async def _recover_refused_restore(
    state, rollback_path: Path | None, error: BaseException, message: str
) -> dict:
    """Only publish a new runtime after verified rollback/current-file safety."""
    from mathtutor.infrastructure.backup import BackupService

    if rollback_path is not None:
        try:
            rollback_error = await _rollback_failed_restore(
                rollback_path, state.db_path
            )
        except asyncio.CancelledError as rollback_error:
            _restore_failed_closed(state, rollback_error)
            raise
        if rollback_error:
            result = _restore_failed_closed(state, RuntimeError(rollback_error))
            if isinstance(error, asyncio.CancelledError):
                raise error
            return result
    else:
        try:
            integrity = await _restore_io(
                BackupService._verify_backup_file, state.db_path
            )
            if integrity != "ok":
                raise RuntimeError(f"original database integrity_check={integrity!r}")
        except (Exception, asyncio.CancelledError) as verify_error:
            result = _restore_failed_closed(state, verify_error)
            if isinstance(verify_error, asyncio.CancelledError) or isinstance(
                error, asyncio.CancelledError
            ):
                raise asyncio.CancelledError from verify_error
            return result
    try:
        _rebuild_after_restore(state)
    except Exception as rebuild_error:
        result = _restore_failed_closed(state, rebuild_error)
        if isinstance(error, asyncio.CancelledError):
            raise error from rebuild_error
        return result
    state.restore_status = "RECOVERED"
    if rollback_path is not None:
        await _remove_restore_image(state, rollback_path)
    if isinstance(error, asyncio.CancelledError):
        raise error
    return {"ok": False, "message": message}


async def _perform_owned_restore(
    state, backup_path: Path, recovery_key: str | None
) -> dict:
    from mathtutor.infrastructure import db_crypto
    from mathtutor.infrastructure.backup import BackupService
    from mathtutor.infrastructure.lifecycle_trace import trace
    from mathtutor.infrastructure.migrate import upgrade_db

    state.restore_status = "PREFLIGHT"
    try:
        # Restoring SQLite alone cannot roll back a simultaneous encryption
        # marker/journal transition. Finish that startup operation first.
        pending = await _restore_io(
            lambda: (
                db_crypto.state(state.db_path).get("pending")
                or db_crypto.conversion_path(state.db_path).exists()
            )
        )
    except Exception:
        state.restore_status = "REFUSED"
        return {
            "ok": False,
            "message": "无法确认加密转换状态，未开始恢复。请保留数据库与恢复材料，重新启动后检查。",
        }
    if pending:
        state.restore_status = "REFUSED"
        return {
            "ok": False,
            "message": "加密转换尚未完成，未开始恢复。请先重新启动应用完成加密转换，再恢复备份。",
        }
    state.restore_status = "STOPPING"
    try:
        await state.shutdown_runtime()
    except (Exception, asyncio.CancelledError) as error:
        result = _restore_failed_closed(state, error)
        result["message"] = "运行时未安全关闭，已取消恢复。应用保持维护状态。"
        if isinstance(error, asyncio.CancelledError):
            raise
        return result
    trace(id(state), "restore_replacement_begin")
    state.restore_status = "PROTECTING"
    rollback_path = state.db_path.with_name(
        f".{state.db_path.name}.pre-restore-{uuid4().hex}.rollback"
    )
    try:
        await _restore_io(shutil.copy2, state.db_path, rollback_path)
        integrity = await _restore_io(BackupService._verify_backup_file, rollback_path)
        if integrity != "ok":
            raise RuntimeError(f"protection image integrity_check={integrity!r}")
    except (Exception, asyncio.CancelledError) as error:
        # The live file has not been replaced. A partially copied protection
        # image is never advertised as a valid recovery point.
        try:
            return await _recover_refused_restore(
                state, None, error, f"无法创建恢复前保护副本，已取消恢复：{error}"
            )
        finally:
            if state.restore_status != "FAILED":
                await _remove_restore_image(state, rollback_path)
            elif rollback_path.exists():
                state.restore_partial_path = rollback_path
    state.restore_recovery_path = rollback_path
    phase = "恢复备份失败"
    try:
        state.restore_status = "REPLACING"
        await state.backup_service.restore_verified(
            backup_path, state.db_path, recovery_key=recovery_key
        )
        state.restore_status = "MIGRATING"
        phase = "恢复后迁移失败"
        # Migration owns blocking SQLite/file work too; it must reach a
        # terminal state before rollback can replace its target.
        await _restore_io(upgrade_db, state.db_path)
        phase = "插件访问权限重置失败"
        plugins = getattr(state, "community_plugins", None)
        if plugins is not None:
            await _restore_io(plugins.revoke_all_consents)
        phase = "恢复后运行时重建失败"
        _rebuild_after_restore(state)
    except (Exception, asyncio.CancelledError) as error:
        message = (
            "插件访问权限重置失败，已取消恢复。已恢复原数据库；请重新确认插件权限。"
            if phase == "插件访问权限重置失败"
            else f"{phase}：{error}；已自动恢复原数据库。"
        )
        return await _recover_refused_restore(state, rollback_path, error, message)
    state.restore_status = "RESTORED"
    await _remove_restore_image(state, rollback_path)
    return {
        "ok": True,
        "restart_required": True,
        "message": "备份已恢复，请重启应用以完成恢复。",
    }


async def _rollback_failed_restore(
    rollback_path: Path, target_path: Path
) -> str | None:
    """Retain the recovery point until copied target verification succeeds."""
    from mathtutor.infrastructure.backup import BackupService

    def rollback():
        if any(Path(f"{target_path}{suffix}").exists() for suffix in ("-wal", "-shm")):
            raise RuntimeError("Rollback refused: database sidecars remain")
        BackupService._copy_atomic(rollback_path, target_path)
        integrity = BackupService._verify_backup_file(target_path)
        if integrity != "ok":
            raise RuntimeError(f"rollback integrity_check={integrity!r}")

    try:
        await _restore_io(rollback)
    except Exception as error:
        return str(error)
    return None


def _rebuild_after_restore(state) -> None:
    from mathtutor.api.product_state import rebuild_product_state

    rebuild_product_state(state)
