"""Desktop bridge tests: KeychainSecretStore, NativeDesktopFilePicker,
and the /api/v2/math-tutor/desktop router (settings/documents/memory/readiness).

Security invariants asserted here:

- the API key NEVER appears in any response (masked tail only) and lands
  ONLY in the SecretStore;
- the file picker contains NO directory-scanning code (static assertion);
- native picking unavailable → explicit error, never a silent fallback;
- document/memory projections never carry internal fields (storage refs,
  content hashes, parser tracebacks, chunk data);
- confirm is the only legal MODEL_INFERRED → USER_CONFIRMED migration;
- readiness: no API key → DEGRADED (not BLOCKED); fully configured → READY;
  broken database → BLOCKED.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from mathtutor import application  # noqa: F401  (module for source scan)
from mathtutor.api import desktop_api
from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import (
    get_product_state,
    reset_product_state,
)
from mathtutor.application.desktop_files import (
    InMemoryPickedFilePicker,
    LoopbackElectronPickTransport,
    NativeDesktopFilePicker,
    PickTransportUnavailableError,
    PickedFile,
)
from mathtutor.infrastructure.embedding_runtime import (
    EmbeddingRuntime,
    FakeEmbeddingBackend,
)
from mathtutor.infrastructure.generative_gateway import ModelRole
from mathtutor.infrastructure.keychain_secret_store import (
    KeychainSecretStore,
    KeychainSecretStoreError,
    KeychainUnavailableError,
    KeychainUnsupportedError,
    _win32_not_found_or_raise,
)
from mathtutor.security.settings import MathTutorSecuritySettings

pytestmark = pytest.mark.asyncio

SECRET = "sk-secret-value-1234"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _dev_settings() -> MathTutorSecuritySettings:
    return MathTutorSecuritySettings(environment="development", host="127.0.0.1")


def _app(**overrides) -> object:
    settings = _dev_settings()
    app = create_math_tutor_app(settings, auth_enabled=False, **overrides)
    app.include_router(
        desktop_api.router, prefix=desktop_api.DESKTOP_ROUTER_PREFIX
    )
    return app


def _client(**overrides) -> TestClient:
    return TestClient(_app(**overrides))


class FakeRunner:
    """Deterministic subprocess runner; records argv + stdin."""

    def __init__(
        self, exit_code: int = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.calls: list[tuple[list[str], bytes | None]] = []

    async def run(self, argv, *, stdin=None):
        self.calls.append((list(argv), stdin))
        return self.exit_code, self.stdout, self.stderr


def _keychain(monkeypatch, runner: FakeRunner) -> KeychainSecretStore:
    store = KeychainSecretStore(service="com.mathtutor.product", runner=runner.run)
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store.platform.system",
        lambda: "Darwin",
    )
    # These tests inject a fake subprocess runner and exercise the macOS
    # command contract on every host.  Do not require the real `security`
    # executable to be present when the suite runs on Windows/Linux.
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store._which",
        lambda command: command == "security",
    )
    return store


# ---------------------------------------------------------------------------
# KeychainSecretStore — fake subprocess runner, no real credential store.
# ---------------------------------------------------------------------------


async def test_keychain_put_pipes_secret_via_stdin_never_argv(monkeypatch) -> None:
    runner = FakeRunner()
    store = _keychain(monkeypatch, runner)
    await store.put("generative.api_key.openai", SECRET)

    assert len(runner.calls) == 1
    argv, stdin = runner.calls[0]
    assert argv == [
        "security",
        "add-generic-password",
        "-U",
        "-s",
        "com.mathtutor.product",
        "-a",
        "generative.api_key.openai",
        "-w",
    ]
    # macOS `security -w` prompts twice; the secret rides stdin twice.
    assert stdin == f"{SECRET}\n{SECRET}\n".encode("utf-8")
    # The secret must never appear in argv (ps/audit exposure).
    assert all(SECRET not in part for part in argv)


async def test_keychain_get_returns_value_and_not_found_none(monkeypatch) -> None:
    runner = FakeRunner(stdout=f"{SECRET}\n")
    store = _keychain(monkeypatch, runner)
    assert await store.get("k") == SECRET
    assert runner.calls[0][0][:2] == ["security", "find-generic-password"]

    runner = FakeRunner(exit_code=44)  # macOS: item not found
    store = _keychain(monkeypatch, runner)
    assert await store.get("missing") is None


async def test_keychain_fails_closed_on_unexpected_exit(monkeypatch) -> None:
    for op in ("put", "get", "delete"):
        runner = FakeRunner(exit_code=1, stderr="boom")
        store = _keychain(monkeypatch, runner)
        with pytest.raises(KeychainSecretStoreError):
            if op == "put":
                await store.put("k", "v")
            elif op == "get":
                await store.get("k")
            else:
                await store.delete("k")


async def test_keychain_delete_accepts_not_found(monkeypatch) -> None:
    runner = FakeRunner(exit_code=44)
    store = _keychain(monkeypatch, runner)
    await store.delete("already-gone")  # must not raise


# ---------------------------------------------------------------------------
# KeychainSecretStore — Windows Credential Manager (advapi32) via fake backend.
# The real advapi32 adapter is UNTESTED on a real Windows host; every branch
# here runs on macOS/Linux against an in-memory stand-in that emulates the
# documented CRED_TYPE_GENERIC / ERROR_NOT_FOUND (1168) semantics.
# ---------------------------------------------------------------------------


class FakeWin32Backend:
    """In-memory Credential Manager stand-in.

    Emulates the Win32CredBackend contract: ``cred_read`` returns None for a
    missing target (ERROR_NOT_FOUND 1168), ``cred_delete`` on a missing
    target succeeds (1168 semantics), and API failures raise
    KeychainSecretStoreError whose message never contains credential
    material (mirroring ``_default_win32_backend``).
    """

    def __init__(
        self,
        *,
        fail_write: bool = False,
        fail_read: bool = False,
        fail_delete: bool = False,
    ) -> None:
        self.records: dict[str, bytes] = {}
        self.fail_write = fail_write
        self.fail_read = fail_read
        self.fail_delete = fail_delete
        self.write_calls: list[tuple[str, bytes]] = []
        self.read_calls: list[str] = []
        self.delete_calls: list[str] = []

    async def cred_write(self, target: str, blob: bytes) -> None:
        self.write_calls.append((target, blob))
        if self.fail_write:
            raise KeychainSecretStoreError("CredWriteW failed (win32 error 5)")
        self.records[target] = blob

    async def cred_read(self, target: str) -> bytes | None:
        self.read_calls.append(target)
        if self.fail_read:
            raise KeychainSecretStoreError("CredReadW failed (win32 error 5)")
        return self.records.get(target)

    async def cred_delete(self, target: str) -> None:
        self.delete_calls.append(target)
        if self.fail_delete:
            raise KeychainSecretStoreError("CredDeleteW failed (win32 error 5)")
        self.records.pop(target, None)


def _windows_store(
    monkeypatch, backend: FakeWin32Backend | None = None
) -> tuple[KeychainSecretStore, FakeWin32Backend]:
    backend = backend if backend is not None else FakeWin32Backend()
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store.platform.system",
        lambda: "Windows",
    )
    # On non-Windows hosts the advapi32 probe is False; the injected fake
    # backend stands in for the whole adapter, so pretend the API is there.
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store._win32_api_available",
        lambda: True,
    )
    store = KeychainSecretStore(
        service="com.mathtutor.product", runner=FakeRunner().run, win32_backend=backend
    )
    return store, backend


async def test_keychain_windows_roundtrip_overwrite_delete(monkeypatch) -> None:
    backend = FakeWin32Backend()
    store, backend = _windows_store(monkeypatch, backend)

    await store.put("generative.api_key.openai", SECRET)
    # Target = service/key; the blob is the UTF-16-LE payload — the value
    # NEVER rides argv or any other channel than the CREDENTIALW blob.
    assert backend.write_calls == [
        ("com.mathtutor.product/generative.api_key.openai", SECRET.encode("utf-16-le"))
    ]
    assert await store.get("generative.api_key.openai") == SECRET
    assert backend.read_calls == ["com.mathtutor.product/generative.api_key.openai"]

    # put is overwrite-write.
    await store.put("generative.api_key.openai", "sk-replacement-9999")
    assert await store.get("generative.api_key.openai") == "sk-replacement-9999"

    # delete removes; a second delete (1168 semantics) must not raise.
    await store.delete("generative.api_key.openai")
    assert await store.get("generative.api_key.openai") is None
    await store.delete("generative.api_key.openai")
    assert backend.delete_calls == [
        "com.mathtutor.product/generative.api_key.openai",
        "com.mathtutor.product/generative.api_key.openai",
    ]


async def test_keychain_windows_get_missing_is_none(monkeypatch) -> None:
    store, backend = _windows_store(monkeypatch)
    assert await store.get("missing.key") is None
    assert backend.read_calls == ["com.mathtutor.product/missing.key"]


async def test_keychain_windows_api_failure_raises_fail_closed(monkeypatch) -> None:
    for name, kwargs, operation in (
        ("write", {"fail_write": True}, "put"),
        ("read", {"fail_read": True}, "get"),
        ("delete", {"fail_delete": True}, "delete"),
    ):
        store, _backend = _windows_store(monkeypatch, FakeWin32Backend(**kwargs))
        with pytest.raises(KeychainSecretStoreError):
            if operation == "put":
                await store.put("k", SECRET)
            elif operation == "get":
                await store.get("k")
            else:
                await store.delete("k")


async def test_keychain_windows_errors_never_contain_secret(monkeypatch) -> None:
    """Fail-closed errors carry the operation + numeric code only — never
    the secret value (the invariant: no key material in error messages)."""
    store, _backend = _windows_store(monkeypatch, FakeWin32Backend(fail_write=True))
    with pytest.raises(KeychainSecretStoreError) as excinfo:
        await store.put("k", SECRET)
    assert SECRET not in str(excinfo.value)
    assert "CredWriteW" in str(excinfo.value)


def test_win32_not_found_or_raise_semantics() -> None:
    # ERROR_NOT_FOUND (1168) → the documented not-found result.
    assert _win32_not_found_or_raise(1168, "CredReadW") is True
    assert _win32_not_found_or_raise(1168, "CredDeleteW") is True
    # Anything else fails closed, without credential material.
    for code in (5, 87, 1312):
        with pytest.raises(KeychainSecretStoreError) as excinfo:
            _win32_not_found_or_raise(code, "CredReadW")
        assert f"win32 error {code}" in str(excinfo.value)
        assert "secret" not in str(excinfo.value)
        assert SECRET not in str(excinfo.value)


def test_keychain_available_platform_matrix(monkeypatch) -> None:
    from mathtutor.infrastructure import keychain_secret_store as kss

    monkeypatch.setattr(kss.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(kss, "_which", lambda _cmd: True)
    assert KeychainSecretStore.available() is True
    monkeypatch.setattr(kss, "_which", lambda _cmd: False)
    assert KeychainSecretStore.available() is False

    monkeypatch.setattr(kss.platform, "system", lambda: "Linux")
    monkeypatch.setattr(kss, "_which", lambda _cmd: True)
    assert KeychainSecretStore.available() is True
    monkeypatch.setattr(kss, "_which", lambda _cmd: False)
    assert KeychainSecretStore.available() is False

    # Windows: available exactly when advapi32 can be probed.
    monkeypatch.setattr(kss.platform, "system", lambda: "Windows")
    monkeypatch.setattr(kss, "_win32_api_available", lambda: True)
    assert KeychainSecretStore.available() is True
    monkeypatch.setattr(kss, "_win32_api_available", lambda: False)
    assert KeychainSecretStore.available() is False

    # Unsupported platforms stay unavailable.
    monkeypatch.setattr(kss.platform, "system", lambda: "FreeBSD")
    assert KeychainSecretStore.available() is False


async def test_keychain_windows_check_supported_no_longer_raises(monkeypatch) -> None:
    """Windows is implemented (Credential Manager) — put/get/delete run
    instead of raising KeychainUnsupportedError."""
    probe = monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store._win32_api_available",
        lambda: True,
    )
    store, _backend = _windows_store(monkeypatch)
    await store.put("k", SECRET)  # must not raise
    assert await store.get("k") == SECRET
    await store.delete("k")


async def test_keychain_windows_unavailable_probe_fails_closed(monkeypatch) -> None:
    """advapi32 not loadable → KeychainUnavailableError, never a fallback."""
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store.platform.system",
        lambda: "Windows",
    )
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store._win32_api_available",
        lambda: False,
    )
    store = KeychainSecretStore(service="s", win32_backend=FakeWin32Backend())
    with pytest.raises(KeychainUnavailableError):
        await store.put("k", SECRET)
    with pytest.raises(KeychainUnavailableError):
        await store.get("k")


async def test_keychain_other_platform_still_unsupported(monkeypatch) -> None:
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store.platform.system",
        lambda: "FreeBSD",
    )
    store = KeychainSecretStore(service="s", runner=FakeRunner().run)
    with pytest.raises(KeychainUnsupportedError):
        await store.put("k", "v")


async def test_keychain_linux_uses_secret_tool(monkeypatch) -> None:
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store.platform.system",
        lambda: "Linux",
    )
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store._which",
        lambda _cmd: True,
    )
    runner = FakeRunner()
    store = KeychainSecretStore(runner=runner.run)
    await store.put("k", SECRET)
    assert runner.calls[0][0][0] == "secret-tool"
    assert runner.calls[0][1] == f"{SECRET}\n".encode("utf-8")

    runner = FakeRunner(stdout=f"{SECRET}\n")
    store = KeychainSecretStore(runner=runner.run)
    assert await store.get("k") == SECRET
    assert runner.calls[0][0][0] == "secret-tool"
    assert runner.calls[0][0][1] == "lookup"


async def test_keychain_available_probe(monkeypatch) -> None:
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store.platform.system",
        lambda: "Darwin",
    )
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store._which",
        lambda _cmd: True,
    )
    assert KeychainSecretStore.available() is True
    monkeypatch.setattr(
        "mathtutor.infrastructure.keychain_secret_store._which",
        lambda _cmd: False,
    )
    assert KeychainSecretStore.available() is False


# ---------------------------------------------------------------------------
# NativeDesktopFilePicker — explicit pick only, no scanning.
# ---------------------------------------------------------------------------


async def test_native_picker_cancel_returns_none() -> None:
    async def cancelled(_student_id: str) -> None:
        return None

    picker = NativeDesktopFilePicker(cancelled)
    assert await picker.pick_document_file("s") is None


async def test_native_picker_explicit_pick_returns_picked_file() -> None:
    async def transport(student_id: str):
        assert student_id == "student-a"
        return PickedFile(filename="notes.md", data=b"hello", mime_type="text/markdown")

    picker = NativeDesktopFilePicker(transport)
    picked = await picker.pick_document_file("student-a")
    assert picked is not None
    assert picked.filename == "notes.md"
    assert picked.data == b"hello"


async def test_native_picker_without_transport_is_unsupported() -> None:
    picker = NativeDesktopFilePicker()
    with pytest.raises(PickTransportUnavailableError):
        await picker.pick_document_file("student-a")


async def test_loopback_transport_unset_url_is_unsupported(monkeypatch) -> None:
    monkeypatch.delenv("MATHTUTOR_ELECTRON_PICKER_URL", raising=False)
    transport = LoopbackElectronPickTransport()
    assert transport.available() is False
    with pytest.raises(PickTransportUnavailableError):
        await transport.pick("student-a")


async def test_loopback_transport_happy_and_cancel() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "filename": "book.pdf",
            "mime_type": "application/pdf",
            "data_base64": base64.b64encode(b"%PDF-1.4 probe").decode(),
            "original_path": "/Users/probe/book.pdf",
        }
        if "cancel" in request.url.path:
            payload = {"cancelled": True}
        return httpx.Response(200, json=payload)

    transport = LoopbackElectronPickTransport(
        "http://127.0.0.1:38001", http=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    picked = await transport.pick("s")
    assert picked is not None
    assert picked.filename == "book.pdf"
    assert picked.data == b"%PDF-1.4 probe"

    cancel_transport = LoopbackElectronPickTransport(
        "http://127.0.0.1:38001",
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"cancelled": True}))),
    )
    assert await cancel_transport.pick("s") is None


async def test_loopback_transport_unreachable_is_unsupported() -> None:
    transport = LoopbackElectronPickTransport(
        "http://127.0.0.1:38002",
        timeout_seconds=0.05,
        http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503, json={}))),
    )
    with pytest.raises(PickTransportUnavailableError):
        await transport.pick("s")


def test_picker_source_never_scans_directories() -> None:
    """Static assertion: the picker contract contains no directory walk.

    The business layer must never enumerate user directories — the ONLY
    document entry path is an explicit native pick.
    """
    from mathtutor.application import desktop_files

    source = Path(desktop_files.__file__).read_text(encoding="utf-8")
    for forbidden in ("os.walk", "os.scandir", ".iterdir", "scandir(", "glob("):
        assert forbidden not in source, f"directory enumeration found: {forbidden}"

    api_source = Path(desktop_api.__file__).read_text(encoding="utf-8")
    for forbidden in ("os.walk", "os.scandir", ".iterdir", "glob("):
        assert forbidden not in api_source, f"directory enumeration found: {forbidden}"


# ---------------------------------------------------------------------------
# Settings bridge — masking, key only into the SecretStore.
# ---------------------------------------------------------------------------


def test_mask_secret_tail_only():
    assert desktop_api.mask_secret("sk-abcdef-1234") == "••••••••1234"
    assert desktop_api.mask_secret("ab") == "••••••••ab"
    assert desktop_api.mask_secret("") == ""


def test_desktop_production_secret_store_shared_with_gateway(monkeypatch) -> None:
    """Desktop production (MATHTUTOR_DESKTOP=1 + production env) constructs
    the OS credential store ONCE, on ProductState. The settings surface
    (``_desktop_secret_store``) and the gateway's key resolver read the SAME
    instance, so a key saved via PUT /settings is resolvable at generation
    time — a key in the Keychain is never visible to an InMemory-bound
    gateway (single-store wiring regression)."""
    monkeypatch.setenv("MATHTUTOR_DESKTOP", "1")
    monkeypatch.setenv("MATHTUTOR_ENVIRONMENT", "production")
    reset_product_state()
    try:
        state = get_product_state()
        assert isinstance(state.secret_store, KeychainSecretStore)
        # The gateway resolves keys through THIS store at call time.
        assert state.gateway._secret_store is state.secret_store
        # The settings surface resolves to the same instance.
        assert desktop_api._desktop_secret_store() is state.secret_store
    finally:
        reset_product_state()


def test_default_secret_store_is_in_memory(monkeypatch) -> None:
    """Without the desktop env (dev/test/CI) the store stays in-memory."""
    monkeypatch.delenv("MATHTUTOR_DESKTOP", raising=False)
    monkeypatch.delenv("MATHTUTOR_ENVIRONMENT", raising=False)
    reset_product_state()
    try:
        state = get_product_state()
        from mathtutor.infrastructure.secret_store import (
            InMemorySecretStore,
        )

        assert isinstance(state.secret_store, InMemorySecretStore)
    finally:
        reset_product_state()


async def test_put_settings_never_returns_key_and_stores_it() -> None:
    reset_product_state()
    with _client() as client:
        response = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "openai", "api_key": SECRET},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert "api_key" not in body
        assert SECRET not in response.text
        assert body["key_masked"] == desktop_api.mask_secret(SECRET)
        assert body["key_masked"].endswith("1234")
        assert body["preset_id"] == "openai"
        assert body["is_configured"] is True
        assert body["onboarding_completed"] is True

        # The key landed ONLY in the SecretStore.
        state = get_product_state()
        stored = await state.secret_store.get("generative.api_key.openai")
        assert stored == SECRET


async def test_configured_provider_handles_normal_chat_before_math_parser() -> None:
    reset_product_state()
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, json={
            "choices": [{
                "message": {"role": "assistant", "content": "你好，同学！"},
                "finish_reason": "stop",
            }]
        })

    with _client() as client:
        saved = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={
                "preset_id": "custom",
                "api_key": SECRET,
                "base_url": "https://provider.example/v1",
                "model": "chat-model",
            },
        )
        assert saved.status_code == 200
        provider = get_product_state().gateway.provider_for(ModelRole.TUTOR_WRITER)
        assert provider is not None
        provider._transport = httpx.MockTransport(handler)
        with client.websocket_connect("/api/v2/math-tutor/ws") as websocket:
            websocket.send_text(json.dumps({
                "command": "send_message",
                "payload": {"text": "你好"},
                "session_id": "provider-chat",
            }, ensure_ascii=False))
            frames = []
            while True:
                frame = json.loads(websocket.receive_text())
                frames.append(frame)
                if frame["event_type"] == "turn_end":
                    break
        assert seen == ["/v1/chat/completions"]
        chat = next(frame for frame in frames if frame["event_type"] == "tutor_message")
        assert chat["payload"]["student_message"] == "你好，同学！"
        assert "题目有歧义" not in json.dumps(frames, ensure_ascii=False)


async def test_get_settings_has_no_key_material() -> None:
    reset_product_state()
    with _client() as client:
        response = client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings")
        assert response.status_code == 200
        assert set(response.json().keys()) == {
            "vision_mode",
            "preset_id",
            "model",
            "base_url",
            "is_configured",
            "onboarding_completed",
            "initial_assessment_required",
            "key_masked",
            "connection_status",
            "provider_configs",
        }
        assert "api_key" not in response.text
        assert SECRET not in response.text


async def test_embedding_settings_default_off_and_cloud_empty_key_degrades() -> None:
    reset_product_state()
    with _client() as client:
        prefix = desktop_api.DESKTOP_ROUTER_PREFIX
        initial = client.get(f"{prefix}/settings/embedding")
        assert initial.status_code == 200
        assert initial.json()["enabled"] is False
        assert initial.json()["status"] == "disabled"

        updated = client.put(
            f"{prefix}/settings/embedding",
            json={
                "enabled": True,
                "provider": "cloud",
                "local_model_id": "bge-small-zh-v1.5",
                "cloud_base_url": "https://embedding.example/v1",
                "cloud_model": "embedding-zh",
            },
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["status"] == "incomplete"
        assert get_product_state().embedding_runtime.backend() is None


async def test_embedding_api_key_is_masked_and_only_in_secret_store() -> None:
    reset_product_state()
    with _client() as client:
        prefix = desktop_api.DESKTOP_ROUTER_PREFIX
        response = client.put(
            f"{prefix}/settings/embedding",
            json={
                "enabled": True,
                "provider": "cloud",
                "local_model_id": "bge-small-zh-v1.5",
                "cloud_base_url": "https://embedding.example/v1",
                "cloud_model": "embedding-zh",
                "cloud_api_key": SECRET,
            },
        )
        assert response.status_code == 200, response.text
        assert SECRET not in response.text
        assert response.json()["cloud_key_masked"].endswith("1234")
        assert await get_product_state().secret_store.get("embedding.api_key") == SECRET


async def test_skip_onboarding_persists_template_mode_across_restart(tmp_path) -> None:
    db_path = tmp_path / "math_tutor.db"
    reset_product_state()
    with _client(db_path=str(db_path)) as client:
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings/onboarding/skip"
        )
        assert response.status_code == 200
        assert response.json()["onboarding_completed"] is True

    reset_product_state()
    with _client(db_path=str(db_path)) as client:
        settings = client.get(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings"
        ).json()
        assert settings["onboarding_completed"] is True
        assert settings["is_configured"] is False


async def test_remove_api_key_falls_back_without_deleting_learning_data() -> None:
    reset_product_state()
    with _client() as client:
        saved = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "openai", "api_key": SECRET},
        )
        assert saved.status_code == 200
        removed = client.delete(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings/api-key"
        )
        assert removed.status_code == 200
        assert removed.json()["is_configured"] is False
        assert removed.json()["onboarding_completed"] is True
        assert removed.json()["key_masked"] is None
        assert await get_product_state().secret_store.get(
            "generative.api_key.openai"
        ) is None


async def test_settings_custom_preset_requires_base_url() -> None:
    reset_product_state()
    with _client() as client:
        response = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "custom", "api_key": SECRET},
        )
        assert response.status_code == 422
        assert "Base URL" in response.json()["detail"]


async def test_settings_accepts_preset_base_url_overrides() -> None:
    reset_product_state()
    with _client() as client:
        response = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "openai", "api_key": SECRET, "base_url": "https://proxy.example/v1"},
        )
        assert response.status_code == 200
        assert response.json()["base_url"] == "https://proxy.example/v1"


async def test_settings_unknown_preset_rejected() -> None:
    reset_product_state()
    with _client() as client:
        response = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "nope", "api_key": SECRET},
        )
        assert response.status_code == 422


async def test_model_discovery_success(monkeypatch) -> None:
    reset_product_state()

    async def fake_fetch_models(self):
        return ["gpt-4o-mini", "gpt-4o"]

    monkeypatch.setattr(
        "mathtutor.infrastructure.generative_gateway.OpenAICompatibleProvider.fetch_models",
        fake_fetch_models,
    )
    with _client() as client:
        put = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "openai", "api_key": SECRET},
        )
        assert put.status_code == 200
        response = client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings/models")
        assert response.status_code == 200
        # The gateway sorts discovered ids; the fake bypasses that, so the
        # endpoint returns the fake's order unchanged.
        assert response.json() == ["gpt-4o-mini", "gpt-4o"]


async def test_model_discovery_without_provider_is_409() -> None:
    reset_product_state()
    with _client() as client:
        response = client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings/models")
        assert response.status_code == 409


async def test_connection_error_never_leaks_key(monkeypatch) -> None:
    reset_product_state()

    async def broken_fetch_models(self):
        raise RuntimeError(f"transport refused secret {SECRET}")

    monkeypatch.setattr(
        "mathtutor.infrastructure.generative_gateway.OpenAICompatibleProvider.fetch_models",
        broken_fetch_models,
    )
    with _client() as client:
        put = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "openai", "api_key": SECRET},
        )
        assert put.status_code == 200
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings/test-connection"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert SECRET not in response.text  # redacted by the gateway


async def test_connection_success_resolves_model(monkeypatch) -> None:
    reset_product_state()

    async def fake_fetch_models(self):
        return ["gpt-4o-mini", "gpt-4o"]

    monkeypatch.setattr(
        "mathtutor.infrastructure.generative_gateway.OpenAICompatibleProvider.fetch_models",
        fake_fetch_models,
    )
    async def fake_complete(self, *args, **kwargs):
        return None
    monkeypatch.setattr(
        "mathtutor.infrastructure.generative_gateway.GenerativeModelGateway.complete",
        fake_complete,
    )
    with _client() as client:
        put = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={"preset_id": "openai", "api_key": SECRET},
        )
        assert put.status_code == 200
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings/test-connection"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["resolved_model"] == "gpt-4o-mini"  # preset default wins


async def test_presets_listing() -> None:
    reset_product_state()
    with _client() as client:
        response = client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings/presets")
        assert response.status_code == 200
        ids = [p["preset_id"] for p in response.json()]
        assert ids == ["openai", "deepseek", "moonshot", "custom", "ollama"]
        custom = next(p for p in response.json() if p["preset_id"] == "custom")
        assert custom["custom"] is True
        ollama = next(p for p in response.json() if p["preset_id"] == "ollama")
        assert ollama["requires_api_key"] is False
        assert ollama["local"] is True


async def test_ollama_settings_require_no_key_and_offline_error_is_specific(monkeypatch) -> None:
    reset_product_state()

    async def offline(self):
        raise RuntimeError("provider 'ollama' transport error: connection refused")

    monkeypatch.setattr(
        "mathtutor.infrastructure.generative_gateway.OllamaProviderAdapter.fetch_models",
        offline,
    )
    with _client() as client:
        saved = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/settings",
            json={
                "preset_id": "ollama",
                "base_url": "http://127.0.0.1:11434",
                "model": "qwen3",
            },
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["key_masked"] is None
        assert saved.json()["is_configured"] is True
        tested = client.post(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/model/test")
        assert tested.status_code == 200
        assert tested.json()["ok"] is False
        assert tested.json()["message"] == "Ollama 服务暂时不可用，请确认本地服务已启动。"


# ---------------------------------------------------------------------------
# Documents bridge — projections, toggles, friendly errors.
# ---------------------------------------------------------------------------


def test_document_import_and_projection() -> None:
    reset_product_state()
    with _client() as client:
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/import",
            files={"file": ("notes.md", "# 我的笔记\n\n二次方程内容。".encode("utf-8"), "text/markdown")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["filename"] == "notes.md"
        assert body["status"] == "ready"
        assert "storage_ref" not in body
        assert "content_hash" not in body
        assert "parse_error" not in body
        assert "document_id" in body
        assert body["retrieval_enabled"] is True

        listing = client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents")
        assert listing.status_code == 200
        assert len(listing.json()) == 1
        assert all("storage_ref" not in d and "content_hash" not in d for d in listing.json())


def test_document_membership_is_scoped_to_one_conversation() -> None:
    reset_product_state()
    with _client() as client:
        for conversation_id in ("conversation-a", "conversation-b"):
            created = client.post(
                "/api/v2/math-tutor/sessions",
                json={"conversation_id": conversation_id},
            )
            assert created.status_code == 201
        imported = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/import?conversation_id=conversation-a",
            files={"file": ("notes.txt", b"quadratic formula and discriminant", "text/plain")},
        )
        assert imported.status_code == 200
        document_id = imported.json()["document_id"]
        assert [item["document_id"] for item in client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents?conversation_id=conversation-a").json()] == [document_id]
        assert client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents?conversation_id=conversation-b").json() == []
        attached = client.post(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/conversations/conversation-b/documents/{document_id}")
        assert attached.status_code == 200
        assert [item["document_id"] for item in client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents?conversation_id=conversation-b").json()] == [document_id]


def test_document_rejected_type_is_friendly() -> None:
    reset_product_state()
    with _client() as client:
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/import",
            files={"file": ("evil.exe", b"MZ", "application/octet-stream")},
        )
        assert response.status_code == 422
        assert "不支持的文件类型" in response.json()["detail"]


def test_blank_pdf_import_is_not_ready() -> None:
    from io import BytesIO

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buffer = BytesIO()
    writer.write(buffer)

    reset_product_state()
    with _client() as client:
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/import",
            files={
                "file": (
                    "scan.pdf",
                    buffer.getvalue(),
                    "application/pdf",
                )
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "needs_ocr"
        assert body["retrieval_enabled"] is False
        assert body["chunk_count"] == 0
        assert body["page_count"] == 1
        assert body["error"]
        assert "已就绪" not in body["error"]
        assert "storage_ref" not in body
        assert "parse_error" not in body


def test_document_parse_failure_shows_friendly_error_only() -> None:
    reset_product_state()
    with _client() as client:
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/import",
            files={"file": ("broken.pdf", b"this is not a pdf at all", "application/pdf")},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "failed"
        assert body["error"] is not None and "无法解析此 PDF" in body["error"]
        # Internal detail never leaves the API.
        assert "parse_error" not in body
        assert "Traceback" not in response.text
        assert "storage_ref" not in body


def test_document_retrieval_toggle_and_delete() -> None:
    reset_product_state()
    with _client() as client:
        imported = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/import",
            files={"file": ("notes.md", "内容".encode("utf-8"), "text/markdown")},
        ).json()
        doc_id = imported["document_id"]
        prefix = f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents"

        toggled = client.patch(
            f"{prefix}/{doc_id}/retrieval", json={"enabled": False}
        )
        assert toggled.status_code == 200
        assert toggled.json()["retrieval_enabled"] is False

        deleted = client.delete(f"{prefix}/{doc_id}")
        assert deleted.status_code == 200
        assert client.get(f"{prefix}/{doc_id}").status_code == 404


def test_document_pick_cancelled_and_unsupported(monkeypatch) -> None:
    reset_product_state()

    monkeypatch.setattr(
        desktop_api.__name__ + "._document_picker",
        lambda: NativeDesktopFilePicker(InMemoryPickedFilePicker().pick_document_file),
    )
    with _client() as client:
        response = client.post(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/pick")
        assert response.status_code == 200
        assert response.json() == {"status": "cancelled"}

    monkeypatch.setattr(
        desktop_api.__name__ + "._document_picker",
        lambda: NativeDesktopFilePicker(),
    )
    with _client() as client:
        response = client.post(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/pick")
        assert response.status_code == 501
        assert "不支持原生文件选择" in response.json()["detail"]


def test_document_pick_imports_explicit_pick(monkeypatch) -> None:
    reset_product_state()
    picker = InMemoryPickedFilePicker()
    picker.enqueue(
        PickedFile(filename="picked.md", data=b"picked content", mime_type="text/markdown")
    )
    monkeypatch.setattr(
        desktop_api.__name__ + "._document_picker",
        lambda: NativeDesktopFilePicker(picker.pick_document_file),
    )
    with _client() as client:
        response = client.post(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/pick")
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "imported"
        assert response.json()["document"]["filename"] == "picked.md"


def test_document_reparse_put() -> None:
    reset_product_state()
    with _client() as client:
        imported = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/import",
            files={"file": ("notes.md", "# 二次方程\n\nax^2+bx+c=0".encode("utf-8"), "text/markdown")},
        ).json()
        doc_id = imported["document_id"]
        response = client.put(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/documents/{doc_id}"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "ready"


# ---------------------------------------------------------------------------
# Memory bridge — CRUD, retrieval toggle, MODEL_INFERRED confirm.
# ---------------------------------------------------------------------------


def test_memory_crud_and_toggles() -> None:
    reset_product_state()
    with _client() as client:
        prefix = f"{desktop_api.DESKTOP_ROUTER_PREFIX}/memory"
        created = client.post(
            prefix,
            json={
                "memory_type": "learning_preference",
                "subject": "我",
                "predicate": "喜欢",
                "object_json": {"style": "先讲概念再做题"},
            },
        )
        assert created.status_code == 200, created.text
        node = created.json()
        assert node["source_type"] == "USER_EXPLICIT"
        assert node["memory_type"] == "learning_preference"
        assert "student_id" not in node

        memory_id = node["memory_id"]
        listing = client.get(prefix)
        assert len(listing.json()) == 1

        updated = client.put(
            f"{prefix}/{memory_id}",
            json={"predicate": "偏好", "object_json": {"style": "分步讲解"}},
        )
        assert updated.status_code == 200
        assert updated.json()["predicate"] == "偏好"

        toggled = client.patch(f"{prefix}/{memory_id}/retrieval", json={"enabled": False})
        assert toggled.status_code == 200
        assert toggled.json()["retrieval_enabled"] is False

        deleted = client.delete(f"{prefix}/{memory_id}")
        assert deleted.status_code == 200
        assert client.get(prefix).json() == []


def test_memory_rejects_forbidden_authoritative_types() -> None:
    reset_product_state()
    with _client() as client:
        response = client.post(
            f"{desktop_api.DESKTOP_ROUTER_PREFIX}/memory",
            json={
                "memory_type": "mastery",
                "subject": "我",
                "predicate": "掌握",
                "object_json": {"skill": "quadratic"},
            },
        )
        assert response.status_code == 422


def test_memory_model_inferred_confirm_is_only_migration() -> None:
    reset_product_state()
    state = get_product_state()
    # Seed a MODEL_INFERRED memory the way the future inference pipeline would
    # (the auth-disabled dev identity, see scopes.DEV_STUDENT_ID).
    import asyncio

    async def seed():
        return await state.personal_memory.add_inference(
            "local-admin",
            subject="学生",
            predicate="偏好",
            object_json={"hint_style": "scaffolded"},
            confidence=0.6,
        )

    node = asyncio.run(seed())
    memory_id = str(node.memory_id)
    with _client() as client:
        prefix = f"{desktop_api.DESKTOP_ROUTER_PREFIX}/memory"
        # USER_EXPLICIT memory cannot be "confirmed" (409).
        explicit = client.post(
            prefix,
            json={"memory_type": "user_note", "subject": "我", "predicate": "备注", "object_json": {}},
        ).json()
        refused = client.post(f"{prefix}/{explicit['memory_id']}/confirm")
        assert refused.status_code == 409

        confirmed = client.post(f"{prefix}/{memory_id}/confirm")
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["source_type"] == "USER_CONFIRMED"

        # Idempotent second confirm.
        again = client.post(f"{prefix}/{memory_id}/confirm")
        assert again.status_code == 200
        assert again.json()["source_type"] == "USER_CONFIRMED"


# ---------------------------------------------------------------------------
# Readiness — DEGRADED without key, READY configured, BLOCKED on broken db.
# ---------------------------------------------------------------------------


def test_readiness_without_key_is_degraded() -> None:
    reset_product_state()
    with _client() as client:
        response = client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/readiness")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "DEGRADED"
        assert body["checks"]["embedding"] == "degraded"
        assert body["checks"]["gateway"] == "degraded"
        assert body["checks"]["sqlite"] == "ok"


def test_readiness_ready_when_fully_configured(monkeypatch) -> None:
    reset_product_state()

    async def fake_fetch_models(self):
        return ["gpt-4o-mini", "gpt-4o"]

    monkeypatch.setattr(
        "mathtutor.infrastructure.generative_gateway.OpenAICompatibleProvider.fetch_models",
        fake_fetch_models,
    )
    async def fake_complete(self, *args, **kwargs):
        return None
    monkeypatch.setattr(
        "mathtutor.infrastructure.generative_gateway.GenerativeModelGateway.complete",
        fake_complete,
    )
    with _client() as client:
        prefix = desktop_api.DESKTOP_ROUTER_PREFIX
        put = client.put(f"{prefix}/settings", json={"preset_id": "openai", "api_key": SECRET})
        assert put.status_code == 200
        ok = client.post(f"{prefix}/settings/test-connection")
        assert ok.status_code == 200 and ok.json()["status"] == "ok"
        # Provision an embedding backend (vector surface is optional).
        state = get_product_state()
        state.embedding_runtime = EmbeddingRuntime(FakeEmbeddingBackend())
        body = client.get(f"{prefix}/readiness").json()
        assert body["status"] == "READY", body
        assert body["checks"]["gateway"] == "ok"
        assert body["checks"]["embedding"] == "ok"


def test_readiness_blocked_when_db_broken(monkeypatch, tmp_path: Path) -> None:
    reset_product_state()

    async def broken_health(*args, **kwargs):
        raise RuntimeError("unable to open database file")

    monkeypatch.setattr(
        "mathtutor.infrastructure.db.check_db_health", broken_health
    )
    db_file = tmp_path / "math_tutor.db"
    try:
        with _client(db_path=str(db_file)) as client:
            body = client.get(f"{desktop_api.DESKTOP_ROUTER_PREFIX}/readiness").json()
            assert body["status"] == "BLOCKED", body
            assert body["checks"]["sqlite"] == "error"
            assert "数据库打不开" in body["reasons"]["sqlite"]
    finally:
        # The app factory left a SQLite-backed singleton — restore the
        # in-memory default so later tests (which call store.reset()) work.
        reset_product_state()
