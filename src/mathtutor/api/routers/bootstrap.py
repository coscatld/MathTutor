"""Desktop bootstrap HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import BootstrapPayload
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.readiness import (
    _gateway_check,
    _migrations_check,
    _retrieval_check,
    _secret_store_check,
    _sqlite_check,
    _storage_check,
)
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


def _as_step_status(value: str) -> str:
    """Map the readiness check vocabulary onto the bootstrap one.

    Readiness uses "error" (hard failures); the wire contract's
    BootstrapStep uses "blocked" — same severity, different name.
    """
    return {"error": "blocked"}.get(value, value)


async def _data_root_check(state) -> tuple[str, str]:
    """BLOCKED-level: the controlled data root must exist and accept a
    probe write (the document storage lives under it)."""
    root = state.document_storage.uploads_root().parent
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".bootstrap-probe"
        probe.write_bytes(b"probe")
        probe.unlink()
        return "ok", ""
    except Exception as error:
        return "error", f"数据目录不可写：{error}"


async def _curriculum_check(state) -> tuple[str, str]:
    """DEGRADED-level: the versioned curriculum catalog must answer. An
    empty (not-yet-published) catalog is still healthy."""
    try:
        versions = await state.curriculum.list_versions()
        if versions:
            return "ok", ""
        return "ok", "课程目录已就绪（尚未发布课程版本）"
    except Exception as error:
        return "degraded", f"课程目录不可用：{error}"


async def _outbox_check(state) -> tuple[str, str]:
    """DEGRADED-level: the resident relay loop must be running (SQLite
    mode), including the relay in ephemeral development databases."""
    relay = state.outbox_relay
    if relay is None:
        return "ok", "内存模式（开发/测试）"
    if relay.is_running:
        return "ok", ""
    return "degraded", "事件分发未运行（重启后自动恢复）"


async def _verifier_worker_check(state) -> tuple[str, str]:
    """BLOCKED-level in durable mode: math authority must be isolated."""
    health = getattr(state.verification_backend, "health", None)
    if health is None:
        return "ok", "进程内验证（仅开发/测试模式）"
    try:
        return ("ok", "") if await health() else ("error", "数学验证器未就绪。")
    except Exception:
        return "error", "数学验证器未就绪。"


async def run_bootstrap() -> None:
    """Run the boot sequence once and record it (startup hook).

    Each probe maps onto the wire-contract step vocabulary
    ("ok" | "degraded" | "blocked") and a friendly Chinese detail. A probe
    raising is recorded as that step's failure — never propagated (the app
    is already serving; the snapshot tells the shell what is wrong).
    """
    state = get_product_state()
    tracker = state.bootstrap_tracker
    for key, probe in (
        ("check_data_root", _data_root_check),
        ("database", _sqlite_check),
        ("migration", _migrations_check),
        ("verifier_worker", _verifier_worker_check),
        ("secret_store", _secret_store_check),
        ("document_storage", _storage_check),
        ("curriculum", _curriculum_check),
        ("retrieval", _retrieval_check),
        ("outbox", _outbox_check),
        ("model_gateway", _gateway_check),
    ):
        try:
            value, detail = await probe(state)
        except Exception:  # noqa: BLE001 - recorded as the step status
            value, detail = "error", "启动检查失败。"
        tracker.record(key, _as_step_status(value), detail or None)
    tracker.finish()


@router.get("/bootstrap", response_model=BootstrapPayload)
async def bootstrap(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """The recorded boot sequence (wire contract BootstrapPayload).

    Read-only: while booting, ``phase`` is the current step key; once the
    startup hook finishes it becomes "READY" and ``readiness``/``reason``
    reflect the final step statuses.
    """
    return get_product_state().bootstrap_tracker.snapshot()
