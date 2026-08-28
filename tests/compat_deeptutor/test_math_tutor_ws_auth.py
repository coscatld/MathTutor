"""MathTutor product WebSocket: same identity boundary as HTTP (Phase 0 §16, §28).

- no token → rejected (auth enabled)
- invalid token → rejected
- valid student token → tutoring session works
- student A token + student B session id → isolated (B's cycle unreachable)
- envelope smuggling (identity/capability/tools) → rejected
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import get_product_state
from mathtutor.security.settings import MathTutorSecuritySettings

pytestmark = pytest.mark.asyncio

_ALICE_ID = "550e8400-e29b-41d4-a716-446655440000"
_BOB_ID = "660e8400-e29b-41d4-a716-446655440000"


@pytest.fixture()
def auth_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable DeepTutor auth with a strong test secret."""
    import deeptutor.api.routers.auth as auth_router
    import deeptutor.services.auth as auth_service

    monkeypatch.setattr(auth_service, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_service, "AUTH_SECRET", "phase0-test-secret-" + "x" * 48)
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)


def _token(user_id: str, username: str, role: str = "user") -> str:
    from deeptutor.services import auth as auth_service

    return auth_service.create_token(username, role=role, user_id=user_id)


def _client() -> TestClient:
    settings = MathTutorSecuritySettings(environment="development", host="127.0.0.1")
    app = create_math_tutor_app(
        settings, auth_enabled=True, auth_secret="phase0-test-secret-" + "x" * 48
    )
    return TestClient(app)


def _envelope(command: str, payload: dict, session_id: str = "") -> str:
    body: dict = {"command": command, "payload": payload}
    if session_id:
        body["session_id"] = session_id
    return json.dumps(body, ensure_ascii=False)


def _collect(ws) -> list[dict]:
    """Read frames until the server's turn_end marker (student schema)."""
    events: list[dict] = []
    while True:
        frame = json.loads(ws.receive_text())
        events.append(frame)
        if frame.get("event_type") == "turn_end":
            break
    return events


class TestWebSocketAuthentication:
    def test_no_token_rejected(self, auth_on) -> None:
        with _client() as client:
            with pytest.raises(Exception):
                with client.websocket_connect("/api/v2/math-tutor/ws"):
                    pass

    def test_invalid_token_rejected(self, auth_on) -> None:
        with _client() as client:
            with pytest.raises(Exception):
                with client.websocket_connect(
                    "/api/v2/math-tutor/ws?token=not-a-valid-token"
                ):
                    pass

    def test_valid_student_token_accepted(self, auth_on) -> None:
        token = _token(_ALICE_ID, "alice")
        with _client() as client:
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={token}"
            ) as ws:
                ws.send_text(_envelope("submit_problem", {"text": "2x + 3 = 7"}, session_id="s-alice"))
                events = _collect(ws)
        contents = _student_messages(events)
        assert any("已解析并验证" in c for c in contents)

    def test_full_turn_over_authenticated_ws(self, auth_on) -> None:
        token = _token(_ALICE_ID, "alice")
        get_product_state().reset()
        with _client() as client:
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={token}"
            ) as ws:
                ws.send_text(_envelope("submit_problem", {"text": "2x + 3 = 7"}, session_id="s1"))
                events = _collect(ws)
            state = _last_state(events)
            assert state.get("cycle_state") == "awaiting_attempt"
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={token}"
            ) as ws:
                ws.send_text(_envelope("submit_attempt", {"answer": "2"}, session_id="s1"))
                events = _collect(ws)
            # Phase 5 E2E (§7.5): a correct attempt is diagnosed "correct"
            # and the cycle is advanced server-side to a practice offer.
            committed = [
                e
                for e in events
                if e.get("event_type") == "tutor_action_committed"
            ]
            last = committed[-1]
            assert last.get("payload", {}).get("action") == "practice_offered"
            assert last.get("cycle_state") == "practice_offered"
            # Public projection only: offer id + labels ride in the
            # allowlisted extra; no internal field may ever leak.
            extra = last.get("extra", {})
            assert extra.get("offer_id")
            assert extra.get("expires_at")
            assert "verified_solution" not in extra
            assert "attestation_payload" not in extra


class TestOwnerIsolation:
    async def test_student_a_session_invisible_to_student_b(self, auth_on) -> None:
        """A's session id is a client namespace — B's same string resolves to
        B's own (fresh) cycle, so A's data is unreachable (§17, §28)."""
        get_product_state().reset()
        alice_token = _token(_ALICE_ID, "alice")
        bob_token = _token(_BOB_ID, "bob")
        with _client() as client:
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={alice_token}"
            ) as ws:
                ws.send_text(_envelope("submit_problem", {"text": "2x + 3 = 7"}, session_id="shared-name"))
                _collect(ws)

            # Bob uses the same session-name string: his own store entry is a
            # fresh cycle, so submit_attempt is an invalid transition there.
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={bob_token}"
            ) as ws:
                ws.send_text(_envelope("submit_attempt", {"answer": "2"}, session_id="shared-name"))
                events = _collect(ws)
        errors = [e for e in events if e.get("event_type") == "turn_error"]
        assert errors, "B 必须在 A 的会话命名空间中碰壁（自己的新 cycle 无法直接判题）"

        # A's session is untouched.
        alice_sessions = await get_product_state().store.iter_for_student(_ALICE_ID)
        bob_sessions = await get_product_state().store.iter_for_student(_BOB_ID)
        assert [sid for sid, _ in alice_sessions] == ["shared-name"]
        assert [sid for sid, _ in bob_sessions] == ["shared-name"]
        alice_session = dict(alice_sessions)["shared-name"]
        assert alice_session.state.value == "awaiting_attempt"


class TestEnvelopeSmugglingOverWs:
    @pytest.mark.parametrize(
        "smuggled",
        [
            {"student_id": _BOB_ID},
            {"user_id": "admin"},
            {"role": "admin"},
            {"capability": "deep_research"},
            {"active_capability": "math_animator"},
            {"tools": ["code_execution"]},
            {"enabled_tools": ["shell"]},
            {"plugin": "execute"},
            {"subagent": "research"},
        ],
    )
    def test_identity_and_tool_smuggling_rejected(self, auth_on, smuggled: dict) -> None:
        token = _token(_ALICE_ID, "alice")
        body = {"command": "submit_problem", "payload": {"text": "2x=4"}, **smuggled}
        with _client() as client:
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={token}"
            ) as ws:
                ws.send_text(json.dumps(body))
                events = _collect(ws)
        errors = [e for e in events if e.get("event_type") == "turn_error"]
        assert errors and any("forbidden" in e.get("payload", {}).get("error", "") for e in errors)


class TestInternalFieldsNeverReachStudentWs:
    def test_every_frame_is_clean_student_schema(self, auth_on) -> None:
        """Phase 3 acceptance 5 (E2E): EVERY websocket frame must pass the
        forbidden-field detector — solver traces/model internals have no
        path onto the student wire."""
        from mathtutor.pedagogy.events import assert_no_forbidden_fields

        token = _token(_ALICE_ID, "alice")
        get_product_state().reset()
        all_frames: list[dict] = []
        with _client() as client:
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={token}"
            ) as ws:
                for message in (
                    _envelope("submit_problem", {"text": "2x + 3 = 7"}, session_id="s-clean"),
                    _envelope("request_hint", {}, session_id="s-clean"),
                    _envelope("submit_attempt", {"answer": "2"}, session_id="s-clean"),
                ):
                    ws.send_text(message)
                    while True:
                        frame = json.loads(ws.receive_text())
                        all_frames.append(frame)
                        assert_no_forbidden_fields(frame)
                        assert frame.get("audience") == "student"
                        if frame.get("event_type") == "turn_end":
                            break
        assert any(
            f.get("event_type") == "tutor_action_committed" for f in all_frames
        )
        assert all(f.get("audience") == "student" for f in all_frames)


class TestHttpReadEndpointsAuth:
    def test_unauthenticated_http_rejected(self, auth_on) -> None:
        with _client() as client:
            assert client.get("/api/v2/math-tutor/sessions").status_code == 401

    def test_authenticated_http_reads_own_sessions(self, auth_on) -> None:
        get_product_state().reset()
        token = _token(_ALICE_ID, "alice")
        with _client() as client:
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={token}"
            ) as ws:
                ws.send_text(_envelope("submit_problem", {"text": "2x + 3 = 7"}, session_id="s-alice"))
                _collect(ws)
            response = client.get(
                "/api/v2/math-tutor/sessions",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            sessions = response.json()
            assert [s["client_session_id"] for s in sessions] == ["s-alice"]

    def test_student_a_cannot_read_student_b_session(self, auth_on) -> None:
        get_product_state().reset()
        alice_token = _token(_ALICE_ID, "alice")
        bob_token = _token(_BOB_ID, "bob")
        with _client() as client:
            with client.websocket_connect(
                f"/api/v2/math-tutor/ws?token={alice_token}"
            ) as ws:
                ws.send_text(_envelope("submit_problem", {"text": "2x + 3 = 7"}, session_id="s-alice"))
                _collect(ws)
            response = client.get(
                "/api/v2/math-tutor/sessions/s-alice",
                headers={"Authorization": f"Bearer {bob_token}"},
            )
            assert response.status_code == 404
            response = client.get(
                "/api/v2/math-tutor/sessions/s-alice",
                headers={"Authorization": f"Bearer {alice_token}"},
            )
            assert response.status_code == 200


def _last_state(events: list[dict]) -> dict:
    """Latest student-schema action frame (Phase 3E wire shape)."""
    states = [
        e
        for e in events
        if e.get("event_type") == "tutor_action_committed" and e.get("cycle_state")
    ]
    return states[-1] if states else {}


def _student_messages(events: list[dict]) -> list[str]:
    return [
        e.get("payload", {}).get("student_message", "")
        for e in events
        if e.get("event_type") == "tutor_action_committed"
    ]
