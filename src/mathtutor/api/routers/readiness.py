"""Desktop readiness HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import Readiness
from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.keychain_secret_store import KeychainSecretStore
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


def _check_value(checks: dict[str, str], key: str) -> str:
    return checks.get(key, "error")


_FALLBACK_REASONS: dict[str, str] = {
    "sqlite": "数据库不可用，应用无法正常工作。",
    "migrations": "数据库结构未迁移，请更新应用。",
    "storage": "文档存储目录不可写。",
    "secret_store": "系统凭据库不可用，API Key 无法保存。",
    "gateway": "未配置模型（缺少 API Key 或未选择提供商）。",
    "embedding": "向量索引未配置；文档仍可通过关键词检索使用。",
    "retrieval": "文档检索不可用。",
    "core": "核心辅导服务不可用。",
    "ui": "界面加载异常。",
}


def _overall(checks: dict[str, str]) -> str:
    if any(value == "error" for value in checks.values()):
        return "BLOCKED"
    if any(value == "degraded" for value in checks.values()):
        return "DEGRADED"
    return "READY"


def _state_engine(state):
    """The product database engine, when the store is SQLite-backed."""
    uow = getattr(state.store, "uow", None)
    if uow is None:
        return None
    return getattr(uow, "engine", None)


async def _sqlite_check(state) -> tuple[str, str]:
    """BLOCKED-level: the product database must answer."""
    engine = _state_engine(state)
    if engine is None:
        return "ok", "内存模式（开发/测试）"
    from mathtutor.infrastructure.db import check_db_health

    try:
        await check_db_health(engine)
        return "ok", ""
    except Exception as error:
        return "error", f"数据库打不开：{error}"


async def _migrations_check(state) -> tuple[str, str]:
    """BLOCKED-level: alembic head must be applied (runs at startup)."""
    engine = _state_engine(state)
    if engine is None:
        return "ok", "内存模式（开发/测试）"
    try:
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from mathtutor.infrastructure.migrate import alembic_config

        script = ScriptDirectory.from_config(alembic_config())
        head = script.get_current_head()
        async with engine.connect() as conn:
            current = await conn.run_sync(
                lambda sync: MigrationContext.configure(sync).get_current_revision()
            )
        current_str = str(current or "")
        if head and current_str == head:
            return "ok", ""
        return "error", f"数据库版本 {current_str or '未知'} ≠ 预期 {head or '未知'}"
    except Exception as error:
        return "error", f"迁移检查失败：{error}"


async def _storage_check(state) -> tuple[str, str]:
    """BLOCKED-level: controlled storage must accept a probe write."""
    root = state.document_storage.uploads_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".readiness-probe"
        probe.write_bytes(b"probe")
        probe.unlink()
        return "ok", ""
    except Exception as error:
        return "error", f"存储不可写：{error}"


async def _secret_store_check(state) -> tuple[str, str]:
    """DEGRADED-level: keys cannot be saved → generative surface only."""
    store = state.secret_store
    if isinstance(store, KeychainSecretStore):
        try:
            ok = store.available()
        except Exception:
            ok = False
        if not ok:
            return "degraded", (
                "系统凭据库不可用（macOS Keychain / Windows 凭据管理器 / secret-tool）"
            )
        return "ok", ""
    return "ok", "开发/测试内存凭据库"


async def _gateway_check(state) -> tuple[str, str]:
    """DEGRADED-level: unconfigured gateway → template writer still works."""
    if not await state.gateway_config.is_ready():
        if state.gateway_config.current_config().get("preset_id") == "ollama":
            return "degraded", "Ollama 已选择，但尚未选定本机模型（模板辅导仍可用）"
        return "degraded", "未配置模型提供商（可继续使用模板辅导与词汇检索）"
    roles = state.gateway.configured_roles()
    if not roles:
        return "degraded", "未配置模型提供商（可继续使用模板辅导与词汇检索）"
    provider = state.gateway.provider_for(roles[0])
    if provider is not None and provider.model:
        return "ok", ""
    return "degraded", "已配置提供商，但模型尚未解析（请测试连接）"


async def _embedding_check(state) -> tuple[str, str]:
    """DEGRADED-level: never BLOCKED — lexical retrieval always works."""
    try:
        status = state.embedding_runtime.status()
    except Exception as error:
        return "degraded", f"嵌入后端不可用：{error}"
    if status.available:
        return "ok", ""
    return "degraded", "向量索引未配置；文档仍可关键词检索"


async def _retrieval_check(state) -> tuple[str, str]:
    """DEGRADED-level: lexical retrieval is always available by construction."""
    return "ok", "词法检索可用"


async def _core_check(state) -> tuple[str, str]:
    try:
        if state.store is not None and state.capability is not None:
            return "ok", ""
    except Exception:
        pass
    return "error", "核心辅导服务未初始化"


async def _ui_check(state) -> tuple[str, str]:
    return "ok", "界面由桌面壳加载"


async def build_readiness() -> dict:
    """Aggregate per-check status into READY / DEGRADED / BLOCKED.

    ``checks`` maps each surface to "ok" | "degraded" | "error";
    ``reasons`` carries a HUMAN reason per non-ok check (live probe detail,
    falling back to static text). No internal values ever leave this router.
    """
    state = get_product_state()
    checks: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for name, probe in (
        ("core", _core_check),
        ("sqlite", _sqlite_check),
        ("migrations", _migrations_check),
        ("storage", _storage_check),
        ("secret_store", _secret_store_check),
        ("gateway", _gateway_check),
        ("embedding", _embedding_check),
        ("retrieval", _retrieval_check),
        ("ui", _ui_check),
    ):
        try:
            value, reason = await probe(state)
        except Exception:
            value, reason = "error", ""
        checks[name] = value
        if value != "ok":
            reasons[name] = reason or _FALLBACK_REASONS.get(name, "不可用")
    return {
        "status": _overall(checks),
        "checks": checks,
        "reasons": reasons,
    }


@router.get("/readiness", response_model=Readiness)
async def readiness(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    return await build_readiness()
