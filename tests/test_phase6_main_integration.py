"""MAIN INTEGRATION 3 (Phase 6 round 2): the desktop production surfaces.

- GET /bootstrap — the nine-step boot sequence recorded at startup (wire
  contract BootstrapPayload: readiness/phase/reason/steps);
- POST /model/test — five-way error classification with friendly copy,
  never raw provider detail or key material;
- GET /backups + POST /backup + /backup/verify + /backup/restore — the
  BackupService surfaces; restore runs the full stop → dispose → verified
  restore → rebuild orchestration and always reports restart_required;
  client backup names are strictly validated (traversal refused);
- GET /student-summary — read-only evidence projection without invented mastery;
- the UoW commit hook wakes the resident relay (wiring proof).
"""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import (
    BOOT_STEPS,
    BootstrapTracker,
    get_product_state,
    reset_product_state,
)
from mathtutor.infrastructure.gateway_config import (
    GatewayConfigService,
    classify_gateway_error,
)
from mathtutor.infrastructure.generative_gateway import (
    GenerativeProviderError,
)
from mathtutor.infrastructure.secret_store import InMemorySecretStore
from mathtutor.learning.skill_graph import SKILLS, FAMILY_SKILLS
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.security.settings import MathTutorSecuritySettings

pytestmark = pytest.mark.asyncio


def _client(db_file: Path | None = None) -> TestClient:
    settings = MathTutorSecuritySettings(environment="development", host="127.0.0.1")
    return TestClient(
        create_math_tutor_app(
            settings,
            auth_enabled=False,
            db_path=None if db_file is None else str(db_file),
        )
    )


def _collect(ws) -> list[dict]:
    events: list[dict] = []
    while True:
        frame = json.loads(ws.receive_text())
        events.append(frame)
        if frame.get("event_type") == "turn_end":
            break
    return events


def _submit_solved_problem(client, text: str, answer: str, session_id: str) -> None:
    with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        ws.send_text(
            json.dumps(
                {"command": "submit_problem", "payload": {"text": text}, "session_id": session_id}
            )
        )
        _collect(ws)
        ws.send_text(
            json.dumps(
                {"command": "submit_attempt", "payload": {"answer": answer}, "session_id": session_id}
            )
        )
        _collect(ws)


def _cycle_count(db_file: Path) -> int:
    with closing(sqlite3.connect(str(db_file))) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM tutoring_cycles").fetchone()[0])


# ---------------------------------------------------------------------------
# Bootstrap — nine-step sequence (wire contract shape + real probe results).
# ---------------------------------------------------------------------------


def test_bootstrap_tracker_snapshot_while_booting() -> None:
    """Before finish(), the snapshot reads BLOCKED/"正在启动" and the phase
    tracks the current step — the UI never sees a half-booted app as READY."""
    tracker = BootstrapTracker()
    tracker.record("check_data_root", "ok", None)
    snapshot = tracker.snapshot()
    assert snapshot["readiness"] == "BLOCKED"
    assert snapshot["phase"] == "check_data_root"
    assert "正在启动" in snapshot["reason"]
    assert snapshot["steps"][0]["key"] == "check_data_root"
    assert snapshot["steps"][0]["label"] == "数据目录"


def test_bootstrap_endpoint_in_memory_after_startup() -> None:
    """In-memory dev: boot finishes at startup; the gateway step degrades
    (no provider) — readiness DEGRADED, never BLOCKED."""
    reset_product_state()
    with _client() as client:
        body = client.get("/api/v2/math-tutor/desktop/bootstrap").json()
    assert body["phase"] == "READY"
    assert body["readiness"] == "DEGRADED"
    keys = [step["key"] for step in body["steps"]]
    assert keys == [key for key, _ in BOOT_STEPS], "the nine steps in boot order"
    for step in body["steps"]:
        assert set(step) == {"key", "label", "status", "detail"}
        assert step["status"] in {"ok", "degraded", "blocked"}
        assert isinstance(step["label"], str) and step["label"]
    gateway = next(s for s in body["steps"] if s["key"] == "model_gateway")
    assert gateway["status"] == "degraded"
    # No internals: details are friendly Chinese text.
    assert body["reason"] is not None and isinstance(body["reason"], str)
    reset_product_state()


def test_bootstrap_endpoint_sqlite_steps_ok_but_gateway_degraded(tmp_path: Path) -> None:
    """Durable mode: database/migration/outbox steps ok (resident relay
    running), gateway degraded (no key) — readiness DEGRADED."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        body = client.get("/api/v2/math-tutor/desktop/bootstrap").json()
    assert body["phase"] == "READY"
    assert body["readiness"] == "DEGRADED"
    by_key = {step["key"]: step for step in body["steps"]}
    for key in ("check_data_root", "database", "migration", "document_storage",
                "curriculum", "retrieval", "outbox"):
        assert by_key[key]["status"] == "ok", f"{key}: {by_key[key]}"
    assert by_key["outbox"]["detail"] is None or "内存" not in by_key["outbox"]["detail"]
    assert by_key["model_gateway"]["status"] == "degraded"
    assert by_key["secret_store"]["status"] == "ok"
    reset_product_state()


# ---------------------------------------------------------------------------
# Model test — five-way classification, friendly copy, never raw internals.
# ---------------------------------------------------------------------------


class _StubProviderGateway:
    """Gateway stand-in for classification tests: resolve_model raises the
    exact error shapes the real providers produce."""

    def __init__(self, error: Exception) -> None:
        self._error = error
        self.register_calls: list[tuple] = []

    async def resolve_model(self, provider_id: str) -> str:
        raise self._error

    async def fetch_models(self, provider_id: str) -> list[str]:
        raise self._error

    def register_openai_compatible(self, *args, **kwargs) -> None:
        self.register_calls.append((args, kwargs))

    def provider_for(self, role):
        return None

    def configured_roles(self) -> list:
        return []


def _service_with_error(error: Exception) -> GatewayConfigService:
    service = GatewayConfigService(
        gateway=_StubProviderGateway(error),
        secret_store=InMemorySecretStore(),
    )
    service._provider_id = "test-provider"  # test-only injection
    return service


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("no provider configured", "gateway_disabled"),
        ("provider 'test' has no model resolved", "gateway_disabled"),
        ("provider 'test' model discovery HTTP 401: Unauthorized", "credential_invalid"),
        ("provider 'test' model discovery HTTP 403: Forbidden", "credential_invalid"),
        ("provider 'test' model discovery HTTP 404: Not Found", "model_unavailable"),
        (
            "provider 'test' model discovery transport error: ConnectTimeout",
            "network_unavailable",
        ),
        ("provider 'test' model discovery HTTP 500: boom", "provider_error"),
        ("provider 'test' malformed /models response", "provider_error"),
        ("provider output truncated before final content", "response_incomplete"),
        ("provider returned empty content", "response_incomplete"),
        ("HTTP 400: invalid parameters", "request_rejected"),
        ("HTTP 402: insufficient balance", "quota_exceeded"),
        ("HTTP 429: too many requests", "rate_limited"),
    ],
)
def test_classify_gateway_error(message: str, expected: str) -> None:
    assert classify_gateway_error(message) == expected


async def test_model_test_error_kind_credential_invalid() -> None:
    service = _service_with_error(
        GenerativeProviderError("provider 'test' model discovery HTTP 401: Unauthorized")
    )
    result = await service.test_connection()
    assert result.status == "error"
    assert result.error_kind == "credential_invalid"


async def test_model_test_error_kind_network_unavailable() -> None:
    service = _service_with_error(
        GenerativeProviderError("provider 'test' model discovery transport error: timeout")
    )
    result = await service.test_connection()
    assert result.error_kind == "network_unavailable"


async def test_model_test_error_kind_model_unavailable() -> None:
    service = _service_with_error(
        GenerativeProviderError("provider 'test' model discovery HTTP 404: Not Found")
    )
    result = await service.test_connection()
    assert result.error_kind == "model_unavailable"


async def test_model_test_error_kind_gateway_disabled_unconfigured() -> None:
    service = GatewayConfigService(
        gateway=_StubProviderGateway(GenerativeProviderError("unused")),
        secret_store=InMemorySecretStore(),
    )
    result = await service.test_connection()
    assert result.status == "error"
    assert result.error_kind == "gateway_disabled"


async def test_model_test_redacts_key_value_echoed_in_error() -> None:
    """An error message echoing the key VALUE is redacted before it reaches
    the classification and the wire — never the key itself."""
    secret = "sk-echo-me-123456"
    store = InMemorySecretStore()
    await store.put("generative.api_key.test-provider", secret)
    service = GatewayConfigService(
        gateway=_StubProviderGateway(
            GenerativeProviderError(f"provider 'test' HTTP 401: key {secret} rejected")
        ),
        secret_store=store,
    )
    service._provider_id = "test-provider"
    result = await service.test_connection()
    assert secret not in result.message
    assert "[REDACTED]" in result.message
    assert result.error_kind == "credential_invalid"


def test_model_test_endpoint_friendly_copy() -> None:
    """POST /model/test without a provider → ok False + gateway_disabled +
    fixed friendly copy (never raw provider text)."""
    reset_product_state()
    with _client() as client:
        body = client.post(
            "/api/v2/math-tutor/desktop/model/test", json={}
        ).json()
    assert body == {
        "ok": False,
        "error_kind": "gateway_disabled",
        "message": "尚未配置模型提供商，请先保存 API Key。",
    }
    reset_product_state()


# ---------------------------------------------------------------------------
# Backups — list/create/verify + strict client-path validation.
# ---------------------------------------------------------------------------


def test_backups_unsupported_in_memory_mode() -> None:
    reset_product_state()
    with _client() as client:
        assert client.get("/api/v2/math-tutor/desktop/backups").status_code == 409
        assert client.post("/api/v2/math-tutor/desktop/backup", json={}).status_code == 409
        assert (
            client.post(
                "/api/v2/math-tutor/desktop/backup/restore", json={"path": "x.backup-1.db"}
            ).status_code
            == 409
        )
    reset_product_state()


def test_backup_create_list_verify_flow(tmp_path: Path) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "main-int-backup")  # real data

        created = client.post("/api/v2/math-tutor/desktop/backup", json={})
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["ok"] is True
        record = payload["backup"]
        # Default naming: <db>.backup-<utc timestamp>.db (the service's glob).
        assert record["path"].startswith("math_tutor.db.backup-")
        assert record["path"].endswith(".db")
        assert record["integrity"] == "ok"
        assert len(record["sha256_prefix"]) == 12
        assert record["size_bytes"] > 0
        backup_name = record["path"]

        listing = client.get("/api/v2/math-tutor/desktop/backups").json()
        assert listing["backup_dir"] == "backups"
        assert listing["policy"] == {"retention_limit": 5, "mode": "manual"}
        assert [entry["path"] for entry in listing["backups"]] == [backup_name]
        listed = listing["backups"][0]
        assert listed["integrity"] == "ok"
        assert listed["sha256_prefix"] == record["sha256_prefix"]

        verified = client.post(
            "/api/v2/math-tutor/desktop/backup/verify", json={"path": backup_name}
        )
        assert verified.status_code == 200
        assert verified.json() == {"ok": True}

        # The backup file + sidecar manifest live in the controlled dir.
        backup_file = tmp_path / "backups" / backup_name
        assert backup_file.is_file()
        assert Path(f"{backup_file}.manifest.json").is_file()
    reset_product_state()


def test_backup_client_path_validation_refuses_traversal(tmp_path: Path) -> None:
    """A client can never address a file outside the backup directory:
    path separators, non-backup names, and unknown names are all refused."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        (tmp_path / "backups").mkdir(exist_ok=True)
        (tmp_path / "backups" / "real.backup-2026.db").write_bytes(b"not sqlite")
        victim = tmp_path / "victim.txt"
        victim.write_text("secret")

        for bad, status in (
            ("../victim.txt", 422),
            ("sub/../victim.txt", 422),
            ("/etc/passwd", 422),
            ("victim.txt", 422),
            ("evil.db", 422),
            ("real.backup-2026.db.evil", 422),
            ("missing.backup-2026.db", 404),
        ):
            response = client.post(
                "/api/v2/math-tutor/desktop/backup/restore", json={"path": bad}
            )
            assert response.status_code == status, f"{bad!r} → {response.status_code}"
            response = client.post(
                "/api/v2/math-tutor/desktop/backup/verify", json={"path": bad}
            )
            assert response.status_code == status, f"verify {bad!r} → {response.status_code}"
        assert victim.read_text() == "secret", "nothing outside the backup dir was touched"
    reset_product_state()


# ---------------------------------------------------------------------------
# Restore — stop → dispose → verified restore → rebuild, restart_required.
# ---------------------------------------------------------------------------


def test_restore_e2e_replaces_database_and_always_reports_restart(tmp_path: Path) -> None:
    """Full orchestration: back up after cycle A, create cycle B, restore —
    the database is back to A-only, the runtime is rebuilt, and the wire
    answer is {ok, restart_required: true, message}."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()

    with _client(db_file) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "main-int-a")  # cycle A
        created = client.post("/api/v2/math-tutor/desktop/backup", json={}).json()
        assert created["ok"] is True
        backup_name = created["backup"]["path"]
    assert _cycle_count(db_file) == 1
    reset_product_state()

    with _client(db_file) as client:
        _submit_solved_problem(client, "x + 1 = 2", "1", "main-int-b")  # cycle B
    assert _cycle_count(db_file) == 2
    reset_product_state()

    with _client(db_file) as client:
        plugin = client.get("/api/v2/math-tutor/desktop/community/plugins/examples").json()["items"][0]
        installed = client.post("/api/v2/math-tutor/desktop/community/plugins", json={"package": plugin})
        assert installed.status_code == 200
        path = f'/api/v2/math-tutor/desktop/community/plugins/{plugin["id"]}'
        configured = client.patch(path + "/config", json={"config": {"seed": 314}})
        assert configured.status_code == 200
        enabled = client.put(path + "/enabled", json={"enabled": True, "consent_permissions": plugin["required_permissions"]})
        assert enabled.status_code == 200 and enabled.json()["enabled"]
        restored = client.post(
            "/api/v2/math-tutor/desktop/backup/restore", json={"path": backup_name}
        )
        assert restored.status_code == 200, restored.text
        body = restored.json()
        assert body == {
            "ok": True,
            "restart_required": True,
            "message": "备份已恢复，请重启应用以完成恢复。",
        }
        # Installed local configuration is independent from the DB backup;
        # renewed data consent is required against the restored records.
        retained = client.get("/api/v2/math-tutor/desktop/community/plugins").json()["items"]
        assert len(retained) == 1 and retained[0]["plugin"]["id"] == plugin["id"]
        assert retained[0]["config"]["seed"] == 314
        assert retained[0]["enabled"] is False
        assert retained[0]["consented_permissions"] == []
    assert _cycle_count(db_file) == 1, "the restored db is back to cycle A only"

    # The rebuilt runtime serves the restored database.
    state = get_product_state(db_file)
    assert state.outbox_relay is not None
    assert state.db_path == db_file.resolve()
    reset_product_state()


def test_restore_plugin_consent_io_failure_rolls_back_database(tmp_path: Path, monkeypatch) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "plugin-restore-a")
        created = client.post("/api/v2/math-tutor/desktop/backup", json={}).json()
        _submit_solved_problem(client, "x + 1 = 2", "1", "plugin-restore-b")
        state = get_product_state()
        def refuse_reset():
            raise OSError("fixture disk failure")
        monkeypatch.setattr(state.community_plugins, "revoke_all_consents", refuse_reset)
        response = client.post("/api/v2/math-tutor/desktop/backup/restore", json={"path": created["backup"]["path"]})
        assert response.status_code == 200
        assert response.json()["ok"] is False
        assert "插件访问权限重置失败" in response.json()["message"]
        assert "fixture disk failure" not in response.text
        assert _cycle_count(db_file) == 2
        assert get_product_state() is not state
    reset_product_state()


def test_restore_refuses_corrupt_backup_and_keeps_db(tmp_path: Path) -> None:
    """A backup that fails verification is refused BEFORE the atomic copy —
    the current database stays intact and the runtime is rebuilt either way."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()

    with _client(db_file) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "main-int-c")
        created = client.post("/api/v2/math-tutor/desktop/backup", json={}).json()
        backup_name = created["backup"]["path"]
    assert _cycle_count(db_file) == 1

    # Corrupt the backup file in place (post-creation).
    backup_file = tmp_path / "backups" / backup_name
    backup_file.write_bytes(b"this is not a sqlite database")
    reset_product_state()

    with _client(db_file) as client:
        restored = client.post(
            "/api/v2/math-tutor/desktop/backup/restore", json={"path": backup_name}
        )
        assert restored.status_code == 200
        body = restored.json()
        assert body["ok"] is False
        assert "message" in body and body["message"]
    assert _cycle_count(db_file) == 1, "the current db was never replaced"

    # The runtime was rebuilt after the refused restore (fail-closed path).
    state = get_product_state(db_file)
    assert state.db_path == db_file.resolve()
    reset_product_state()


def test_restore_migration_failure_atomically_rolls_back_live_db(
    tmp_path: Path, monkeypatch
) -> None:
    """A failure after replacement must restore the exact pre-restore bytes.

    Capture the endpoint's protected snapshot hash at copy time; this avoids
    comparing against a pre-checkpoint WAL representation of the same DB.
    """
    from mathtutor.api import desktop_api
    from mathtutor.infrastructure import migrate

    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "rollback-a")
        backup_name = client.post(
            "/api/v2/math-tutor/desktop/backup", json={}
        ).json()["backup"]["path"]
    reset_product_state()
    with _client(db_file) as client:
        _submit_solved_problem(client, "x + 1 = 2", "1", "rollback-b")
    assert _cycle_count(db_file) == 2
    reset_product_state()

    captured: dict[str, str] = {}
    real_copy2 = desktop_api.shutil.copy2

    def capture_protected_snapshot(src, dst, *args, **kwargs):
        result = real_copy2(src, dst, *args, **kwargs)
        if ".pre-restore-" in Path(dst).name:
            captured["sha256"] = hashlib.sha256(Path(dst).read_bytes()).hexdigest()
        return result

    def fail_migration(_db_path=None):
        raise RuntimeError("injected migration failure")

    with _client(db_file) as client:
        monkeypatch.setattr(desktop_api.shutil, "copy2", capture_protected_snapshot)
        monkeypatch.setattr(migrate, "upgrade_db", fail_migration)
        response = client.post(
            "/api/v2/math-tutor/desktop/backup/restore",
            json={"path": backup_name},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is False
        assert "已自动恢复原数据库" in body["message"]

    assert _cycle_count(db_file) == 2
    assert captured["sha256"] == hashlib.sha256(db_file.read_bytes()).hexdigest()
    assert not list(tmp_path.glob(".math_tutor.db.pre-restore-*.rollback"))
    reset_product_state()


async def test_maintenance_gate_drains_and_rejects_new_requests() -> None:
    from mathtutor.api.product_state import ProductState

    state = ProductState()
    assert await state.admit_request() is True  # restore request
    assert await state.admit_request() is True  # already-running request
    acquiring = asyncio.create_task(state.begin_maintenance(timeout=1.0))
    await asyncio.sleep(0)
    assert acquiring.done() is False
    await state.release_request()
    assert await acquiring is True
    assert await state.admit_request() is False
    await state.end_maintenance()
    assert await state.admit_request() is True
    await state.release_request()
    await state.release_request()


def test_restore_maintenance_middleware_rejects_concurrent_http(
    tmp_path: Path, monkeypatch
) -> None:
    """Once restore owns the gate, a concurrent request gets 503 and cannot
    reopen SQLite between dispose, sidecar precheck and atomic replacement."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    entered_shutdown = threading.Event()
    allow_shutdown = threading.Event()

    with _client(db_file) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "gate-a")
        backup_name = client.post(
            "/api/v2/math-tutor/desktop/backup", json={}
        ).json()["backup"]["path"]
        state = get_product_state(db_file)
        real_shutdown = state.shutdown_runtime

        async def paused_shutdown():
            entered_shutdown.set()
            await asyncio.to_thread(allow_shutdown.wait, 2.0)
            await real_shutdown()

        monkeypatch.setattr(state, "shutdown_runtime", paused_shutdown)
        with ThreadPoolExecutor(max_workers=1) as pool:
            restoring = pool.submit(
                client.post,
                "/api/v2/math-tutor/desktop/backup/restore",
                json={"path": backup_name},
            )
            assert entered_shutdown.wait(2.0)
            blocked = client.get("/health")
            assert blocked.status_code == 503
            assert blocked.headers["retry-after"] == "1"
            allow_shutdown.set()
            restored = restoring.result(timeout=10.0)
        assert restored.status_code == 200
        assert restored.json()["ok"] is True

    assert not Path(f"{db_file}-wal").exists()
    assert not Path(f"{db_file}-shm").exists()
    reset_product_state()


# ---------------------------------------------------------------------------
# Student summary — read-only projection (never editable, stable shape).
# ---------------------------------------------------------------------------


def test_student_summary_empty_in_memory() -> None:
    reset_product_state()
    with _client() as client:
        body = client.get("/api/v2/math-tutor/desktop/student-summary").json()
    assert body["total_attempts"] == 0
    assert body["active_misconceptions"] == 0
    assert {skill["code"] for skill in body["skills"]} == set(SKILLS)
    for skill in body["skills"]:
        assert skill["label"] == SKILLS[skill["code"]].label
        assert skill["mastery"] is None
        assert skill["grade_band"] is None
        assert skill["evidence_summary"] == {
            "independent": 0, "assisted": 0, "post_solution": 0,
            "diagnostic": 0, "ungradable": 0,
        }
    reset_product_state()


def test_student_summary_reports_evidence_without_fabricated_mastery(tmp_path: Path) -> None:
    """One independent multiskill item is not several independent successes
    or proof of mastery. The profile retains its item-level evidence."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_file) as client:
        _submit_solved_problem(client, "2x + 3 = 7", "2", "main-int-sum")
        body = client.get("/api/v2/math-tutor/desktop/student-summary").json()
    assert body["total_attempts"] == 1
    assert body["active_misconceptions"] == 0
    skills = {skill["code"]: skill for skill in body["skills"]}
    assert set(skills) == set(SKILLS)
    assert all(skill["mastery"] is None for skill in skills.values())
    assert body["evidence_summary"]["independent"] == 1
    for code, skill in skills.items():
        assert skill["evidence_summary"] == {
            "independent": 0, "assisted": 0, "post_solution": 0,
            "diagnostic": 0, "ungradable": 0,
        }
        assert skill["joint_task_evidence"] == int(code in FAMILY_SKILLS["linear"])
    # Read-only: the endpoint has no body and accepts no writes.
    reset_product_state()


# ---------------------------------------------------------------------------
# Relay wake wiring — the UoW commit hook (best-effort accelerator).
# ---------------------------------------------------------------------------


async def test_uow_commit_hook_semantics(tmp_path: Path) -> None:
    import sqlalchemy as sa

    from mathtutor.infrastructure.db import create_db_engine

    engine = create_db_engine(tmp_path / "hook.db")
    fired: list[int] = []
    uow = MathTutorUow(engine, on_commit=lambda: fired.append(1))

    async with uow.transaction() as conn:
        await conn.execute(sa.text("SELECT 1"))
    assert fired == [1], "clean commit fires the callback"

    try:
        async with uow.transaction() as conn:
            await conn.execute(sa.text("SELECT 1"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert fired == [1], "rollback never fires the callback"
    await engine.dispose()


def test_product_state_wires_relay_wake(tmp_path: Path) -> None:
    from mathtutor.infrastructure.migrate import upgrade_db

    db_file = tmp_path / "math_tutor.db"
    upgrade_db(db_file)
    reset_product_state()
    state = get_product_state(db_file)
    assert state.outbox_relay is not None
    assert state.uow.on_commit is not None, "the product UoW wakes the relay"
    assert state.backup_service is not None
    assert state.backup_policy is not None
    assert state.backup_policy.mode == "manual"
    assert state.backup_policy.retention_limit == 5
    assert state.backup_policy.backup_dir == (db_file.parent / "backups").resolve()
    assert state.backup_scheduler is not None
    assert state.db_path == db_file.resolve()
    reset_product_state()
