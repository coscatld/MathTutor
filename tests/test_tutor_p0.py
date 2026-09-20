"""Public-command and durable request regressions over the real SQLite WS path.

No live model/key: deterministic verification and the existing template writer
exercise authorization, state commits, history, and replay independently of LLM.
"""
import asyncio
import json
import sqlite3
from contextlib import closing
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.api.math_tutor_ws import _canonical_envelope, _message_projection
from mathtutor.application.controller import USER_COMMANDS, _parse_envelope, student_allowed_inputs
from mathtutor.application.state_machine import CycleState
from mathtutor.security.allowlist import validate_client_envelope, SecurityViolationError
from mathtutor.security.settings import MathTutorSecuritySettings


@contextmanager
def client_at(db):
    reset_product_state()
    app = create_math_tutor_app(
        MathTutorSecuritySettings(environment="development", host="127.0.0.1"),
        auth_enabled=False, db_path=str(db),
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        reset_product_state()


def collect(ws):
    frames = []
    while True:
        frame = ws.receive_json()
        frames.append(frame)
        if frame["event_type"] == "turn_end":
            return frames


def envelope(command, key, payload=None, session="p0", **kwargs):
    return dict(protocol_version=2, request_id=key, idempotency_key=key,
                session_id=session, command=command, payload=payload or {}, **kwargs)


def send(ws, command, key, payload=None, **kwargs):
    ws.send_json(envelope(command, key, payload, **kwargs))
    return collect(ws)


def summary(client, session="p0"):
    response = client.get(f"/api/v2/math-tutor/sessions/{session}")
    assert response.status_code == 200
    return response.json()


def count(db, table):
    with closing(sqlite3.connect(db)) as conn, conn:
        return conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]


def test_advertised_inputs_are_public_commands():
    for state in CycleState:
        for name in student_allowed_inputs(state):
            assert name in USER_COMMANDS
            assert _parse_envelope(json.dumps({"protocol_version": 2, "command": name}))[0] == name
    for state in (CycleState.AWAITING_ATTEMPT, CycleState.AWAITING_RETRY):
        assert {"request_hint", "request_example", "request_explanation", "request_solution"} <= set(student_allowed_inputs(state))
        assert "solution_shown_permitted" not in student_allowed_inputs(state)


def test_legacy_alias_is_only_a_version_one_request():
    assert _parse_envelope(json.dumps({"command": "solution_shown_permitted"}))[0] == "request_solution"
    with pytest.raises(ValueError):
        _parse_envelope(json.dumps({"protocol_version": 2, "command": "solution_shown_permitted"}))
    for field in ("role", "tools", "system_prompt"):
        with pytest.raises(SecurityViolationError):
            validate_client_envelope({"command": "solution_shown_permitted", field: "forged"})


@pytest.mark.parametrize("text", ["2", "null", '["x"]', '"hello"'])
def test_plain_json_scalars_remain_chat_text(text):
    assert _canonical_envelope(text)["payload"]["text"] == text
    assert _message_projection(text)[0] == text


@pytest.mark.parametrize("wrong_first", [False, True])
def test_zero_hint_verified_solution_and_retry_actions(tmp_path, wrong_first):
    db = tmp_path / "p0.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        if wrong_first:
            send(ws, "submit_attempt", "wrong", {"answer": "3"})
            assert summary(client)["state"] == "awaiting_retry"
        assert "request_solution" in summary(client)["allowed_next_inputs"]
        result = send(ws, "request_solution", "solution")
        assert not [f for f in result if f["event_type"] == "turn_error"]
        actions = [f["payload"].get("action") for f in result]
        assert "SHOW_SOLUTION" in actions
        assert result[-2]["event_type"] == "assistant_complete"
        messages = [m for m in summary(client)["messages"] if m.get("turn_id") == "solution"]
        assert len(messages) == 1
        assert "2" in messages[0]["content"]
        assert messages[0]["status"] == "COMPLETED"
        assert messages[0]["action"] == "SHOW_SOLUTION"
        assert messages[0]["assistance_level"] == 5
        assert summary(client)["effective_assistance_level"] == 5
        ws.send_json(envelope("request_solution", "solution"))
        assert collect(ws) == result


def test_unverified_solution_is_one_persisted_failure_even_on_replay(tmp_path):
    db = tmp_path / "p0.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        first = send(ws, "request_solution", "unverified")
        assert first[-2]["event_type"] == "assistant_error"
        assert "SHOW_SOLUTION" not in json.dumps(first)
        assert send(ws, "request_solution", "unverified") == first
        messages = summary(client)["messages"]
        assert len(messages) == 2
        assert messages[-1]["role"] == "error"
        assert messages[-1]["turn_id"] == "unverified"
        assert "未知命令" not in messages[-1]["content"]


def test_unknown_attempt_commits_without_optional_evidence(tmp_path):
    db = tmp_path / "p0.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        first = send(ws, "submit_attempt", "unknown", {"answer": "我不确定"})
        assert not [f for f in first if f["event_type"] == "turn_error"]
        assert summary(client)["state"] == "awaiting_attempt_clarification"
        assert count(db, "attempt_assessments") == 1
        assert count(db, "mastery_evidence") == 0
        assert send(ws, "submit_attempt", "unknown", {"answer": "我不确定"}) == first
        assert count(db, "attempt_assessments") == 1


def test_hint_replay_survives_restart_and_stale_expected_version(tmp_path):
    db = tmp_path / "p0.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        request = envelope("request_hint", "hint", expected_cycle_version=summary(client)["state_version"])
        ws.send_json(request)
        first = collect(ws)
        before = summary(client)
        ws.send_json(request)
        assert collect(ws) == first
        assert summary(client) == before
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        ws.send_json(request)
        assert collect(ws) == first
        assert summary(client) == before
        delta = next(f for f in first if f["event_type"] == "assistant_delta")
        saved = next(m for m in before["messages"] if m.get("turn_id") == "hint")
        assert delta["payload"]["message_id"] == saved["message_id"]
        assert count(db, "turn_requests") == 2


def test_request_id_conflict_does_not_mutate_original_result(tmp_path):
    db = tmp_path / "p0.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        send(ws, "request_hint", "same")
        before = summary(client)
        conflict = send(ws, "request_solution", "same")
        assert conflict[-2]["payload"]["error_code"] == "REQUEST_ID_CONFLICT"
        assert summary(client) == before


def test_two_sockets_replay_one_hint_result(tmp_path):
    db = tmp_path / "p0.db"
    with client_at(db) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as one, client.websocket_connect("/api/v2/math-tutor/ws") as two:
            send(one, "submit_problem", "problem", {"text": "2x+3=7"})
            request = envelope("request_hint", "concurrent", expected_cycle_version=summary(client)["state_version"])
            one.send_json(request)
            two.send_json(request)
            assert collect(one) == collect(two)
            assert summary(client)["effective_assistance_level"] == 1
            assert len(summary(client)["messages"]) == 4
            assert count(db, "turn_requests") == 2


def test_error_after_approved_content_updates_one_history_result(tmp_path):
    db = tmp_path / "p0.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        async def emit_then_fail(request, stream):
            await stream.content("已完成第一步。", source="test", metadata={"event_type": "tutor_message"})
            await stream.error("暂时无法完成下一步。", source="test")
        get_product_state().controller.run = emit_then_fail
        result = send(ws, "send_message", "partial-error", {"text": "你好"})
        assert result[-2]["event_type"] == "assistant_partial"
        messages = summary(client)["messages"]
        assert len(messages) == 2
        assert messages[-1]["content"] == "已完成第一步。\n\n暂时无法完成下一步。"
        assert messages[-1]["content"] == result[-2]["payload"]["final_text"]
        assert messages[-1]["status"] == "PARTIAL"


def test_same_attempt_request_key_in_two_conversations_is_owner_scoped(tmp_path):
    db = tmp_path / "p0.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        for session in ("a", "b"):
            send(ws, "submit_problem", "problem", {"text": "2x+3=7"}, session=session)
            result = send(ws, "submit_attempt", "answer", {"answer": "2"}, session=session)
            assert not [f for f in result if f["event_type"] == "turn_error"]
        assert count(db, "attempt_assessments") == 2
        assert count(db, "mastery_evidence") == 2


def test_abandoned_claim_is_not_executed_again(tmp_path):
    db = tmp_path / "p0.db"
    request = envelope("request_hint", "abandoned")
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        send(ws, "request_hint", "abandoned")
        before = summary(client)["state_version"]
    # Simulate a process lost after commit but before recording the terminal.
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute("UPDATE turn_requests SET status='RUNNING', frames='[]' WHERE request_id='abandoned'")
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        ws.send_json(request)
        result = collect(ws)
        assert result[-2]["payload"]["error_code"] == "REQUEST_INTERRUPTED"
        assert summary(client)["state_version"] == before
        assert len([m for m in summary(client)["messages"] if m.get("turn_id") == "abandoned"]) == 1
        message = next(m for m in summary(client)["messages"] if m.get("turn_id") == "abandoned")
        assert message["role"] == "tutor" and message["status"] == "PARTIAL"


def test_010_database_upgrade_keeps_conversation_history(tmp_path):
    from alembic import command
    from mathtutor.infrastructure.migrate import alembic_config, upgrade_db
    db = tmp_path / "upgrade.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        before = summary(client)["messages"]
    # Disposable fixture only: simulate an installed pre-journal schema.
    command.downgrade(alembic_config(str(db)), "010")
    upgrade_db(str(db))
    with client_at(db) as client:
        assert summary(client)["messages"] == before
    with closing(sqlite3.connect(db)) as conn, conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "023"


@pytest.mark.asyncio
async def test_journal_owner_isolation_and_concurrent_claim():
    from mathtutor.repositories.turn_repository import TurnRequestRepository
    repo = TurnRequestRepository()
    async def claim(owner):
        async with repo.conversation(owner, "c"):
            return await repo.claim(owner, "c", "r", "hash")
    claims = await asyncio.gather(claim("one"), claim("one"), claim("two"))
    assert [created for created, _ in claims] == [True, False, True]
    await repo.record("one", "c", "r", [{"only": "one"}], finished=True)
    _, other = await repo.claim("two", "c", "r", "hash")
    assert other["frames"] == []
