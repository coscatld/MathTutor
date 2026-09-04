"""Permanent hard gates for the standalone runtime/auth boundary."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from mathtutor.api.event_stream import MathTutorEventStream
from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import reset_product_state
from mathtutor.application.controller import (
    MathTutorController,
    MathTutorRequest,
)
from mathtutor.security.auth import (
    AuthSettings,
    LocalAuthProvider,
    load_auth_settings,
)
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from mathtutor.security.settings import MathTutorSecuritySettings

_REPO = Path(__file__).resolve().parents[1]
_SOURCE = _REPO / "src" / "mathtutor"
_EXTERNAL_PREFIXES = ("deeptutor",)


def test_explicit_db_path_wins_over_inherited_data_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mathtutor.standalone import (
        resolve_standalone_data_root,
        resolve_standalone_db_path,
    )

    inherited = tmp_path / "normal-user-data"
    isolated_db = tmp_path / "release-smoke" / "isolated.db"
    monkeypatch.setenv("MATHTUTOR_DATA_ROOT", str(inherited))
    monkeypatch.setenv("MATHTUTOR_DB_PATH", str(isolated_db))

    assert resolve_standalone_data_root() == isolated_db.parent.resolve()
    assert resolve_standalone_db_path() == isolated_db.resolve()


def _external_imports(path: Path) -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for source in path.rglob("*.py"):
        relative = source.relative_to(path)
        if relative.parts[0] in {"tests", "legacy"}:
            continue
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                names = (node.module,)
            elif isinstance(node, ast.Import):
                names = tuple(alias.name for alias in node.names)
            else:
                names = ()
            for name in names:
                if name.startswith(_EXTERNAL_PREFIXES):
                    found.append((str(relative), node.lineno, name))
    return found


def test_production_source_has_zero_external_deeptutor_imports() -> None:
    assert _external_imports(_SOURCE) == []


def test_controller_is_not_a_capability_or_runtime_subclass() -> None:
    assert MathTutorController.__bases__ == (object,)
    controller_source = (_SOURCE / "application" / "controller.py").read_text(encoding="utf-8")
    for forbidden in ("BaseCapability", "UnifiedContext", "StreamBus", "ChatOrchestrator", "CapabilityRegistry"):
        assert forbidden not in controller_source


@pytest.mark.asyncio
async def test_controller_accepts_trusted_request_and_typed_sink() -> None:
    owner = StudentOwnerScope(
        principal=PrincipalScope(user_id="u1", username="alice", role="user"),
        student_id="u1",
    )
    stream = MathTutorEventStream()
    await MathTutorController().run(
        MathTutorRequest(session_id="standalone", user_message="2x=4", owner=owner),
        stream,
    )
    await stream.close()
    events = [event async for event in stream.subscribe()]
    assert events
    assert {event.type.value for event in events} <= {"content", "error"}


def test_auth_environment_alias_precedence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "1")
    monkeypatch.setenv("DEEPTUTOR_AUTH_ENABLED", "1")
    monkeypatch.setenv("MATHTUTOR_AUTH_ENABLED", "0")
    assert load_auth_settings(tmp_path).enabled is False
    monkeypatch.delenv("MATHTUTOR_AUTH_ENABLED")
    assert load_auth_settings(tmp_path).enabled is True


def test_local_auth_register_login_and_jwt(tmp_path: Path) -> None:
    provider = LocalAuthProvider(
        AuthSettings(enabled=True, secret="s" * 64), tmp_path
    )
    assert provider.is_first_user()
    principal = provider.register_first_user("alice", "correct-horse")
    assert principal.role == "admin"
    assert provider.authenticate("alice", "wrong-password") is None
    assert provider.authenticate("alice", "correct-horse") == principal
    assert provider.decode_token(provider.create_token(principal)) == principal
    with pytest.raises(PermissionError):
        provider.register_first_user("bob", "another-password")


def test_production_auth_on_register_login_and_ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reset_product_state()
    secret = "production-auth-secret-" + "x" * 48
    monkeypatch.setenv("MATHTUTOR_DATA_ROOT", str(tmp_path))
    app = create_math_tutor_app(
        MathTutorSecuritySettings(environment="production", host="127.0.0.1"),
        auth_enabled=True,
        auth_secret=secret,
        db_path=str(tmp_path / "math_tutor.db"),
    )
    with TestClient(app) as client:
        registration = client.post(
            "/api/v2/auth/register",
            json={"username": "alice", "password": "correct-horse"},
        )
        assert registration.status_code == 201
        login = client.post(
            "/api/v2/auth/login",
            json={"username": "alice", "password": "correct-horse"},
        )
        assert login.status_code == 200
        assert client.get("/api/v2/auth/profile").status_code == 200
        with client.websocket_connect("/api/v2/math-tutor/ws") as websocket:
            websocket.send_text(json.dumps({"command": "submit_problem", "payload": {"text": "2x=4"}}))
            frames = []
            while True:
                frame = json.loads(websocket.receive_text())
                frames.append(frame)
                if frame.get("event_type") == "turn_end":
                    break
        assert any(frame.get("event_type") == "tutor_action_committed" for frame in frames)
    reset_product_state()


def test_isolated_source_only_factory_has_zero_external_runtime_modules(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    shutil.copytree(
        _SOURCE,
        stage / "mathtutor",
        ignore=shutil.ignore_patterns("tests", "legacy", "capabilities", "__pycache__", "*.pyc"),
    )
    data_root = tmp_path / "data"
    probe = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(stage)!r})
from mathtutor.standalone import create_standalone_app
app = create_standalone_app(Path({str(data_root)!r}))
bad = sorted(name for name in sys.modules if name == 'deeptutor' or name.startswith('deeptutor.'))
assert app.title == 'MathTutor Student Product'
assert not bad, bad
for name in ('ChatOrchestrator', 'CapabilityRegistry'):
    assert not any(name.lower() in module.lower() for module in sys.modules)
"""
    environment = {
        "MATHTUTOR_ENVIRONMENT": "development",
        "MATHTUTOR_AUTH_ENABLED": "false",
        "MATHTUTOR_DATA_ROOT": str(data_root),
        "PATH": os.environ.get("PATH", ""),
    }
    # CPython's Windows socket/overlapped initialization requires the system
    # directory variables even in this intentionally minimal environment.
    # Preserve only those OS runtime values; Python isolation is still
    # enforced by `-I` and the staged source path above.
    if os.name == "nt":
        for name in ("SystemRoot", "WINDIR"):
            if value := os.environ.get(name):
                environment[name] = value
    completed = subprocess.run(
        [sys.executable, "-I", "-c", probe],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
