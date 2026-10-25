"""Transport rejection precedes HTTP bodies and WebSocket business effects."""
from __future__ import annotations

import pytest

from mathtutor.api.local_boundary import LocalBoundaryMiddleware
from mathtutor.security.settings import MathTutorSecuritySettings

ORIGIN = "http://127.0.0.1:34821"
HOST = "127.0.0.1:46519"
SECRET = "fresh-per-launch-" + "s" * 48


async def exercise(*, kind="http", origin=ORIGIN, host=HOST, secret=None, csrf=None, method="POST", extra=()):
    effects = []
    reads = []
    messages = []

    async def business(scope, receive, send):
        effects.append("owner/session/delete/model")
        if kind == "websocket":
            await send({"type": "websocket.accept"})
        else:
            await receive()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

    async def receive():
        reads.append(True)
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(message)

    headers = [(b"host", host.encode())]
    for name, value in [("origin", origin), ("x-mathtutor-bridge", secret), ("x-mathtutor-csrf", csrf)]:
        if value is not None:
            headers.append((name.encode(), value.encode()))
    headers.extend(extra)
    app = LocalBoundaryMiddleware(business, MathTutorSecuritySettings(
        allowed_hosts=(HOST,), allowed_origins=(ORIGIN,), bridge_secret=SECRET))
    await app({"type": kind, "headers": headers, "method": method}, receive, send)
    return messages, effects, reads


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://127.0.0.1:34822",
    "http://localhost:34821", "https://127.0.0.1:34821", "http://127.0.0.1.evil.example:34821", ORIGIN + "/"])
@pytest.mark.parametrize("kind", ["http", "websocket"])
async def test_invalid_origin_rejected_even_with_secret_before_business(kind, origin):
    messages, effects, reads = await exercise(kind=kind, origin=origin, secret=SECRET, csrf="1")
    assert effects == reads == []
    assert messages[0].get("status", messages[0].get("code")) == (403 if kind == "http" else 1008)
    assert not any(message["type"] == "websocket.accept" for message in messages)


@pytest.mark.parametrize("kind", ["http", "websocket"])
@pytest.mark.parametrize("secret", [None, "", "wrong"])
async def test_no_origin_requires_explicit_native_credential(kind, secret):
    messages, effects, reads = await exercise(kind=kind, origin=None, secret=secret, csrf="1")
    assert not effects and not reads
    assert messages[0]["type"] != "websocket.accept"


@pytest.mark.parametrize("host", ["evil.example", "localhost:46519", "127.0.0.1:46520", "127.0.0.1", HOST + ".evil.example"])
async def test_host_requires_exact_backend_authority(host):
    messages, effects, reads = await exercise(host=host, secret=SECRET)
    assert messages[0]["status"] == 403 and not effects and not reads


async def test_simple_post_cannot_mutate_but_csrf_and_bridge_paths_work():
    assert (await exercise())[0][0]["status"] == 403
    assert (await exercise(csrf="1"))[1]
    assert (await exercise(origin=None, secret=SECRET))[1]
    assert (await exercise(method="GET"))[1]
    assert (await exercise(kind="websocket"))[0][0]["type"] == "websocket.accept"
    assert (await exercise(kind="websocket", origin=None, secret=SECRET))[1]


@pytest.mark.parametrize("header", [b"origin", b"host", b"x-mathtutor-bridge", b"x-mathtutor-csrf"])
async def test_duplicate_security_headers_fail_closed(header):
    kwargs = {"secret": SECRET, "csrf": "1"}
    value = {b"origin": ORIGIN, b"host": HOST, b"x-mathtutor-bridge": SECRET, b"x-mathtutor-csrf": "1"}[header]
    messages, effects, reads = await exercise(extra=[(header, value.encode())], **kwargs)
    assert messages[0]["status"] == 403 and not effects and not reads


def test_runtime_defaults_do_not_allow_test_host_or_native_anonymous(monkeypatch):
    monkeypatch.delenv("MATHTUTOR_ALLOWED_HOSTS")
    monkeypatch.delenv("MATHTUTOR_BRIDGE_SECRET")
    settings = MathTutorSecuritySettings()
    assert "testserver" not in settings.allowed_hosts and settings.bridge_secret == ""


def test_bridge_secret_is_not_in_settings_repr_or_serialization():
    settings = MathTutorSecuritySettings(bridge_secret=SECRET)
    assert SECRET not in repr(settings)
    assert SECRET not in settings.model_dump_json()


@pytest.mark.parametrize("kwargs", [
    {"allowed_hosts": ("*.localhost:8001",)}, {"allowed_hosts": ("user@127.0.0.1:8001",)},
    {"allowed_origins": ("null",)}, {"allowed_origins": (ORIGIN + "/path",)},
])
def test_ambiguous_transport_configuration_is_rejected(kwargs):
    with pytest.raises(ValueError):
        MathTutorSecuritySettings(**kwargs)


def test_installed_product_gate_rejects_before_conversation_creation_and_purge(monkeypatch):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from mathtutor.api.product_app import create_math_tutor_app

    settings = MathTutorSecuritySettings(allowed_hosts=("testserver",), allowed_origins=(ORIGIN,), bridge_secret=SECRET)
    app = create_math_tutor_app(settings, auth_enabled=False)
    client = TestClient(app, headers={"X-MathTutor-Bridge": ""})
    native = {"X-MathTutor-Bridge": SECRET}
    before = client.get("/api/v2/math-tutor/sessions", headers=native).json()
    for origin in ["https://evil.example", "null", ORIGIN + "0"]:
        headers = {"Origin": origin, "X-MathTutor-Bridge": SECRET}
        assert client.post("/api/v2/math-tutor/sessions", json={"conversation_id": "rejected"}, headers=headers).status_code == 403
        assert client.post("/api/v2/math-tutor/desktop/privacy/purge-memory", headers=headers).status_code == 403
        with pytest.raises(WebSocketDisconnect) as refused:
            with client.websocket_connect("/api/v2/math-tutor/ws", headers=headers):
                pytest.fail("untrusted WebSocket accepted")
        assert refused.value.code == 1008
    assert client.get("/api/v2/math-tutor/sessions", headers=native).json() == before
