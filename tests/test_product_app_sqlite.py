"""Product app over durable SQLite: WS turn persists, "restart" resumes
(Phase 1B end-to-end through the Phase 0 product shell)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import (
    get_product_state,
    reset_product_state,
)
from mathtutor.security.settings import MathTutorSecuritySettings

pytestmark = pytest.mark.asyncio


def _client(db_file: Path) -> TestClient:
    settings = MathTutorSecuritySettings(environment="development", host="127.0.0.1")
    return TestClient(create_math_tutor_app(settings, auth_enabled=False, db_path=str(db_file)))


def _collect(ws) -> list[dict]:
    events: list[dict] = []
    while True:
        frame = json.loads(ws.receive_text())
        events.append(frame)
        if frame.get("event_type") == "turn_end":
            break
    return events


def _last_state(events: list[dict]) -> dict:
    states = [
        e
        for e in events
        if e.get("event_type") == "tutor_action_committed" and e.get("cycle_state")
    ]
    return states[-1] if states else {}


async def test_ws_turn_durable_across_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()

    with _client(db_file) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "command": "submit_problem",
                        "payload": {"text": "2x + 3 = 7"},
                        "session_id": "durable-1",
                    }
                )
            )
            events = _collect(ws)
        assert _last_state(events).get("cycle_state") == "awaiting_attempt"

    # Simulated restart: drop the process-local singleton, rebuild the app
    # over the SAME database file.
    reset_product_state()
    with _client(db_file) as client:
        response = client.get("/api/v2/math-tutor/sessions")
        assert response.status_code == 200
        sessions = response.json()
        assert len(sessions) == 1
        assert sessions[0]["client_session_id"] == "durable-1"
        assert sessions[0]["state"] == "awaiting_attempt"
        assert sessions[0]["state_version"] == 3
        assert sessions[0]["title"] == "2x + 3 = 7"
        restored = client.get("/api/v2/math-tutor/sessions/durable-1").json()
        assert [message["role"] for message in restored["messages"]] == ["student", "tutor"]
        assert restored["messages"][0]["content"] == "2x + 3 = 7"

    reset_product_state()


async def test_first_chat_message_persists_one_conversation_across_restart(tmp_path: Path) -> None:
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()

    with _client(db_file) as client:
        assert client.get("/api/v2/math-tutor/sessions").json() == []
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            ws.send_text(json.dumps({
                "command": "send_message",
                "payload": {"text": "你好"},
                "session_id": "draft-becomes-one",
            }, ensure_ascii=False))
            events = _collect(ws)
        assert any(event["event_type"] == "tutor_message" for event in events)
        assert all("题目有歧义" not in str(event) for event in events)
        sessions = client.get("/api/v2/math-tutor/sessions").json()
        assert len(sessions) == 1
        assert sessions[0]["title"] == "你好"

    reset_product_state()
    with _client(db_file) as client:
        sessions = client.get("/api/v2/math-tutor/sessions").json()
        assert [item["conversation_id"] for item in sessions] == ["draft-becomes-one"]
        restored = client.get("/api/v2/math-tutor/sessions/draft-becomes-one").json()
        assert [message["role"] for message in restored["messages"]] == ["student", "tutor"]

    reset_product_state()

async def test_ws_attempt_after_restart(tmp_path: Path) -> None:
    """Continue the SAME cycle after a restart: submit_attempt resumes from
    the persisted version (no CAS drift)."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()

    with _client(db_file) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "command": "submit_problem",
                        "payload": {"text": "2x + 3 = 7"},
                        "session_id": "durable-2",
                    }
                )
            )
            _collect(ws)

    reset_product_state()
    with _client(db_file) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "command": "submit_attempt",
                        "payload": {"answer": "2"},
                        "session_id": "durable-2",
                    }
                )
            )
            events = _collect(ws)
        state = _last_state(events)
        # An offer is independently durable; it does not overwrite SOLVED.
        assert state.get("cycle_state") == "solved"
        assert state.get("payload", {}).get("action") == "practice_offered"
        assert state.get("extra", {}).get("offer_id")
        offers = client.get("/api/v2/math-tutor/offers").json()
        assert len(offers) == 1
        assert offers[0]["status"] == "ACTIVE"
        assert offers[0]["offer_id"] == state["extra"]["offer_id"]
        assert offers[0]["parent_cycle_id"]
        restored = client.get("/api/v2/math-tutor/sessions/durable-2").json()
        assert restored["state"] == "solved"
        assert restored["active_offer"]["offer_id"] == offers[0]["offer_id"]

    reset_product_state()
