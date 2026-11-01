"""Temporary account stores and real HTTP/auth work; no developer credentials."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import multiprocessing
from pathlib import Path
import threading

import bcrypt
import httpx
import pytest
from fastapi.testclient import TestClient

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import reset_product_state
from mathtutor.security.auth import AuthSettings, LocalAuthProvider, load_auth_settings
from mathtutor.security.auth_store import AuthStoreError, AuthStoreBusy
from mathtutor.security.auth_runtime import AuthExecutor, AuthBusy, AuthAttemptBudget, AuthRateLimited
from mathtutor.security.settings import MathTutorSecuritySettings
from mathtutor.security.scopes import PrincipalScope


@contextmanager
def app_at(tmp_path, monkeypatch, *, enabled=True):
    monkeypatch.setenv("MATHTUTOR_DATA_ROOT", str(tmp_path))
    reset_product_state()
    app = create_math_tutor_app(MathTutorSecuritySettings(environment="test"),
        auth_enabled=enabled, auth_secret="s" * 64, db_path=str(tmp_path / "auth-test.db"))
    try:
        with TestClient(app) as client:
            yield app, client
    finally:
        reset_product_state()


def provider(tmp_path, **kwargs):
    return LocalAuthProvider(AuthSettings(enabled=True, secret="s" * 64, **kwargs), tmp_path)


def write_store(tmp_path, content):
    path = tmp_path / "user" / "auth_users.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def account_record(**changes):
    return {"id": "historical-owner-123", "hash": bcrypt.hashpw(b"valid-password", bcrypt.gensalt(rounds=4)).decode(),
            "role": "admin", "created_at": "", "disabled": False, "avatar": "", **changes}


@pytest.mark.parametrize("content", [b'{"alice":', b'[]', b'null', b'{}', b'"user"',
    b'{"alice":{}}', b'{"alice":{},"alice":{}}', b'\xff', b' ' * (256 * 1024 + 1),
    b'[' * 2000 + b'0' + b']' * 2000])
def test_invalid_existing_store_closes_registration_without_replacing_bytes(tmp_path, monkeypatch, content):
    path = write_store(tmp_path, content)
    with app_at(tmp_path, monkeypatch) as (_, client):
        for url in ("status", "is_first_user"):
            response = client.get(f"/api/v2/auth/{url}")
            assert response.status_code == 503
            assert response.json()["code"] == "auth_storage_recovery_required"
            assert response.json()["is_first_user"] is False
        response = client.post("/api/v2/auth/register", json={"username": "new-admin", "password": "safe-password"})
        assert response.status_code == 503 and response.json()["recovery_required"]
        assert path.read_bytes() == content
        assert not path.with_name("auth_initialized.json").exists()


@pytest.mark.parametrize("changes", [{"id": ""}, {"id": 17}, {"role": "super-admin"},
                                      {"hash": "broken"}, {"disabled": "false"}])
def test_invalid_record_structure_is_not_migrated(tmp_path, changes):
    content = json.dumps({"alice": account_record(**changes)}).encode()
    path = write_store(tmp_path, content)
    with pytest.raises(AuthStoreError):
        provider(tmp_path).register_first_user("new-admin", "safe-password")
    assert path.read_bytes() == content


@pytest.mark.parametrize("cost", [17, 31])
def test_out_of_budget_stored_hash_refuses_before_bcrypt_and_preserves_owner(tmp_path, monkeypatch, cost):
    record = account_record()
    record["hash"] = record["hash"][:4] + f"{cost:02}" + record["hash"][6:]
    content = json.dumps({"alice": record}).encode()
    path = write_store(tmp_path, content)
    def forbidden(*args):
        raise AssertionError("Out-of-budget bcrypt must not run")
    monkeypatch.setattr(bcrypt, "checkpw", forbidden)
    monkeypatch.setattr(bcrypt, "hashpw", forbidden)
    with app_at(tmp_path, monkeypatch) as (_, client):
        response = client.post("/api/v2/auth/login", json={"username": "alice", "password": "valid-password"})
        assert response.status_code == 503 and response.json()["recovery_required"]
        assert client.post("/api/v2/auth/register", json={"username": "bob", "password": "password"}).status_code == 503
    assert path.read_bytes() == content


def test_save_size_checked_before_publishing_marker_or_replacing_old_store(tmp_path):
    account = provider(tmp_path)
    too_large = {"alice": account_record(avatar="x" * (256 * 1024))}
    with account._store.transaction(), pytest.raises(AuthStoreError):
        account._store.save(too_large)
    assert not account._store_path.exists() and not account._store.marker.exists()
    old = json.dumps({"alice": account_record()}).encode()
    write_store(tmp_path, old)
    with account._store.transaction(), pytest.raises(AuthStoreError):
        account._store.save(too_large)
    assert account._store_path.read_bytes() == old and not account._store.marker.exists()


def test_permission_failure_is_recovery_not_first_install(tmp_path, monkeypatch):
    path = write_store(tmp_path, json.dumps({"alice": account_record()}).encode())
    original, contents = Path.open, path.read_bytes()
    with app_at(tmp_path, monkeypatch) as (_, client):
        def denied(self, *args, **kwargs):
            if self == path:
                raise PermissionError("synthetic filesystem permission denial")
            return original(self, *args, **kwargs)
        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", denied)
            assert client.get("/api/v2/auth/is_first_user").status_code == 503
            assert client.post("/api/v2/auth/register", json={"username": "new-admin", "password": "safe-password"}).status_code == 503
        assert path.read_bytes() == contents


def test_fresh_http_registration_once_real_bcrypt_jwt_and_stable_legacy_owner(tmp_path, monkeypatch):
    with app_at(tmp_path, monkeypatch) as (app, client):
        assert client.get("/api/v2/auth/is_first_user").json() == {"is_first_user": True}
        first = client.post("/api/v2/auth/register", json={"username": "alice", "password": "correct-password"})
        assert first.status_code == 201
        owner = first.json()["user_id"]
        assert client.post("/api/v2/auth/register", json={"username": "bob", "password": "other-password"}).status_code == 403
        assert client.post("/api/v2/auth/login", json={"username": "alice", "password": "bad-password"}).status_code == 401
        assert client.post("/api/v2/auth/login", json={"username": "alice", "password": "correct-password"}).json()["user_id"] == owner
        assert client.get("/api/v2/auth/status").json()["user_id"] == owner
        token = client.cookies.get("dt_token")
        assert app.state.math_tutor_auth.decode_token(token).user_id == owner
    assert LocalAuthProvider(AuthSettings(enabled=False), tmp_path).local_principal().user_id == owner
    store = tmp_path / "user" / "auth_users.json"
    old = store.read_bytes()
    store.with_name("auth_initialized.json").unlink()  # valid legacy storage
    assert provider(tmp_path).authenticate("alice", "correct-password").user_id == owner
    assert store.read_bytes() == old
    assert store.with_name("auth_initialized.json").exists()


def test_missing_initialized_store_never_bootstraps_or_reopens_registration(tmp_path):
    account = provider(tmp_path)
    account.register_first_user("alice", "correct-password")
    account._store_path.unlink()
    bootstrap = provider(tmp_path, bootstrap_username="bootstrap",
                         bootstrap_password_hash=account_record()["hash"])
    for instance in (account, bootstrap):
        with pytest.raises(AuthStoreError):
            instance.is_first_user()
        with pytest.raises(AuthStoreError):
            instance.register_first_user("bob", "another-password")
    assert not account._store_path.exists()


def test_bootstrap_initializes_only_missing_store_and_retains_owner(tmp_path):
    account = provider(tmp_path, bootstrap_username="bootstrap", bootstrap_password_hash=account_record()["hash"])
    assert not account.is_first_user()
    assert account.authenticate("bootstrap", "valid-password").user_id == "env-admin"
    account._store_path.write_bytes(b"[]")
    with pytest.raises(AuthStoreError):
        account.authenticate("bootstrap", "valid-password")
    assert account._store_path.read_bytes() == b"[]"


def test_auth_secret_is_serialized_and_existing_unreadable_secret_is_preserved(tmp_path, monkeypatch):
    for name in ("MATHTUTOR_AUTH_SECRET", "AUTH_SECRET", "DEEPTUTOR_AUTH_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MATHTUTOR_AUTH_ENABLED", "1")
    with ThreadPoolExecutor(max_workers=2) as threads:
        futures = [threads.submit(load_auth_settings, tmp_path) for _ in range(2)]
        first, second = [future.result(3) for future in futures]
    assert first.secret == second.secret and len(first.secret) >= 32
    path = tmp_path / "user" / "auth_secret"
    original, contents = Path.read_text, path.read_bytes()
    def denied(self, *args, **kwargs):
        if self == path:
            raise PermissionError("synthetic credential read denial")
        return original(self, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_text", denied)
        with pytest.raises(AuthStoreError):
            load_auth_settings(tmp_path)
    assert path.read_bytes() == contents


def test_failed_initial_publication_retains_closed_marker_and_cleans_temp_files(tmp_path, monkeypatch):
    import mathtutor.security.auth_store as storage
    account = provider(tmp_path)
    original = storage.os.replace
    def failed(source, destination):
        if Path(destination) == account._store_path:
            raise OSError("synthetic replace failure")
        return original(source, destination)
    monkeypatch.setattr(storage.os, "replace", failed)
    with pytest.raises(AuthStoreError):
        account.register_first_user("alice", "correct-password")
    assert account._store.marker.exists() and not account._store_path.exists()
    assert not list(account._store_path.parent.glob("*.tmp"))
    with pytest.raises(AuthStoreError):
        account.is_first_user()


def _register_process(root, name, start, results):
    account = provider(root)
    results.put(("ready", name))
    start.wait(5)
    try:
        user = account.register_first_user(name, "correct-password")
        results.put(("registered", user.user_id))
    except PermissionError:
        results.put(("closed", name))


def test_two_processes_register_exactly_one_administrator(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    start, results = ctx.Event(), ctx.Queue()
    workers = [ctx.Process(target=_register_process, args=(tmp_path, name, start, results)) for name in ("alice", "bob")]
    try:
        for worker in workers:
            worker.start()
        assert [results.get(timeout=10)[0] for _ in workers] == ["ready", "ready"]
        start.set()
        assert sorted(results.get(timeout=10)[0] for _ in workers) == ["closed", "registered"]
        for worker in workers:
            worker.join(5)
            assert worker.exitcode == 0
        users = provider(tmp_path)._load_users()
        assert len(users) == 1
        assert next(iter(users.values()))["id"].startswith("u_")
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(5)
        results.close()


@pytest.mark.asyncio
async def test_cancelled_auth_waiter_keeps_capacity_until_worker_finishes_and_shutdown_joins():
    executor = AuthExecutor(capacity=1)
    entered, release = threading.Event(), threading.Event()
    def slow():
        entered.set()
        assert release.wait(5)
        return "finished"
    task = asyncio.create_task(executor.run(slow))
    try:
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 2), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert executor.active == 1
        with pytest.raises(AuthBusy):
            await executor.run(lambda: None)
        closing = asyncio.create_task(executor.shutdown())
        await asyncio.sleep(0)
        assert not closing.done()
        closing.cancel()
        await asyncio.sleep(0)
        assert not closing.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert executor.active == 0
        with pytest.raises(AuthBusy):
            await executor.run(lambda: None)
    finally:
        release.set()
        await executor.shutdown()


def test_saturated_http_auth_does_not_block_health_or_exceed_worker_bound(tmp_path, monkeypatch):
    with app_at(tmp_path, monkeypatch) as (app, client):
        entered = [threading.Event(), threading.Event()]
        release = threading.Event()
        lock = threading.Lock()
        active, peak = 0, 0
        def slow(username, password):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            entered[int(username)].set()
            try:
                assert release.wait(10)
                return None
            finally:
                with lock:
                    active -= 1
        monkeypatch.setattr(app.state.math_tutor_auth, "authenticate", slow)
        with ThreadPoolExecutor(max_workers=2) as requests:
            futures = [requests.submit(client.post, "/api/v2/auth/login", json={"username": str(i), "password": "password"}) for i in range(2)]
            try:
                assert all(event.wait(2) for event in entered)
                assert client.get("/health").status_code == 200
                from test_tutor_p0 import send
                principal = PrincipalScope(user_id="auth-progress-student", username="learner", role="user")
                token = app.state.math_tutor_auth.create_token(principal)
                with client.websocket_connect(f"/api/v2/math-tutor/ws?token={token}") as ws:
                    frames = send(ws, "submit_problem", "while-auth-waits", {"text": "2x+3=7"})
                    assert any(frame["event_type"] == "assistant_complete" for frame in frames)
                response = client.post("/api/v2/auth/login", json={"username": "excess", "password": "password"})
                assert response.status_code == 503 and response.json()["code"] == "auth_busy"
                assert response.headers["retry-after"] == "1"
                assert peak == 2
            finally:
                release.set()
            assert all(future.result(3).status_code == 401 for future in futures)


def test_rate_limit_uses_peer_not_forwarded_headers_and_is_bounded(tmp_path, monkeypatch):
    with app_at(tmp_path, monkeypatch) as (app, client):
        app.state.math_tutor_auth_attempts = AuthAttemptBudget(per_peer=2, total=10)
        monkeypatch.setattr(app.state.math_tutor_auth, "authenticate", lambda *args: None)
        for i in range(2):
            assert client.post("/api/v2/auth/login", headers={"X-Forwarded-For": f"192.0.2.{i}"},
                               json={"username": "alice", "password": "password"}).status_code == 401
        limited = client.post("/api/v2/auth/login", headers={"X-Forwarded-For": "192.0.2.99"},
                              json={"username": "alice", "password": "password"})
        assert limited.status_code == 429 and limited.json()["code"] == "auth_rate_limited"
    clock = [0]
    budget = AuthAttemptBudget(per_peer=2, total=3, max_peers=2, clock=lambda: clock[0])
    for peer in ("a", "b", "c"):
        budget.admit(peer)
    assert len(budget._peers) == 2
    with pytest.raises(AuthRateLimited):
        budget.admit("d")
    clock[0] = 61
    budget.admit("d")


@pytest.mark.asyncio
async def test_cancelled_http_login_does_not_return_running_slot(tmp_path, monkeypatch):
    with app_at(tmp_path, monkeypatch) as (app, _):
        await app.state.math_tutor_auth_executor.shutdown()
        app.state.math_tutor_auth_executor = AuthExecutor(capacity=1)
        entered, release = threading.Event(), threading.Event()
        def slow(*args):
            entered.set()
            assert release.wait(5)
            return None
        monkeypatch.setattr(app.state.math_tutor_auth, "authenticate", slow)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver",
                                    headers={"X-MathTutor-Bridge": app.state.math_tutor_security.bridge_secret}) as client:
            task = asyncio.create_task(client.post("/api/v2/auth/login", json={"username": "alice", "password": "password"}))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert app.state.math_tutor_auth_executor.active == 1
                response = await client.post("/api/v2/auth/login", json={"username": "alice", "password": "password"})
                assert response.status_code == 503 and response.json()["code"] == "auth_busy"
                assert (await client.get("/health")).status_code == 200
            finally:
                release.set()


def test_auth_off_never_opens_registration_even_with_damaged_auth_store(tmp_path, monkeypatch):
    write_store(tmp_path, b"[]")
    with app_at(tmp_path, monkeypatch, enabled=False) as (_, client):
        assert client.get("/api/v2/auth/status").json()["authenticated"] is True
        assert client.get("/api/v2/auth/is_first_user").json()["is_first_user"] is False
        assert client.post("/api/v2/auth/register", json={"username": "alice", "password": "password"}).status_code == 400
