"""Turn traces persist across restarts, carry no text and leave with the conversation."""
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

from mathtutor.api.product_state import get_product_state
from mathtutor.repositories.turn_trace_repository import ALERT_MIN_TURNS, health
from test_tutor_p0 import client_at, send

DIAG = "/api/v2/math-tutor/desktop/diagnostics/turns"
ROOT = Path(__file__).resolve().parents[1]


def rows(db):
    with closing(sqlite3.connect(db)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM turn_traces ORDER BY created_at")]


def test_each_turn_leaves_a_text_free_trace_that_survives_restart(tmp_path):
    db = tmp_path / "trace.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        send(ws, "request_solution", "early")
        send(ws, "submit_attempt", "answer", {"answer": "x=7/3"})
    stored = rows(db)
    assert [r["turn_id"] for r in stored] == ["problem", "early", "answer"]
    early = next(r for r in stored if r["turn_id"] == "early")
    assert (early["command"], early["error_code"]) == ("request_solution", "HINT_REQUIRED")
    assert "incorrect" in json.loads(stored[-1]["actions"])
    assert not any("7/3" in json.dumps(r, ensure_ascii=False) or "2x+3=7" in json.dumps(r) for r in stored)
    with client_at(db) as client:
        report = client.get(DIAG).json()
        assert report["health"]["turns"] == 3 and report["health"]["alerts"] == []
        assert [t["turn_id"] for t in client.get(DIAG, params={"status": "COMPLETED"}).json()["turns"]] == ["answer", "problem"]
        assert all("student_id" not in t for t in report["turns"])


def test_formula_checks_are_counted_in_the_trace(tmp_path):
    class WrongChat:
        async def respond(self, text, **kwargs):
            return "先算 $3+4=8$。"

    db = tmp_path / "trace.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().controller.chat_responder = WrongChat()
        send(ws, "send_message", "chat", {"text": "3 加 4 等于几？"})
    details = json.loads(rows(db)[-1]["details"])
    assert details["formulas"] == {"verified": 0, "unchecked": 0, "refuted": 1}


def test_purging_a_conversation_removes_its_traces(tmp_path):
    db = tmp_path / "trace.db"
    with client_at(db) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        assert rows(db)
        assert client.delete("/api/v2/math-tutor/sessions/p0").status_code == 200
        assert rows(db), "moving to trash keeps the conversation and its traces"
        assert client.delete("/api/v2/math-tutor/trash/p0").status_code == 200
    assert rows(db) == []


def test_health_alerts_only_on_a_real_sample():
    failing = [{"status": "FAILED", "finish_reason": "PROVIDER_ERROR", "latency_ms": 10,
                "input_tokens": 1, "output_tokens": 1, "details": {}}]
    assert health(failing * (ALERT_MIN_TURNS - 1))["alerts"] == []
    report = health(failing * ALERT_MIN_TURNS)
    assert report["failed_rate"] == 1.0 and report["alerts"][0].startswith("failed_rate")


def test_replay_reproduces_a_recorded_turn_from_a_read_only_copy(tmp_path):
    db = tmp_path / "trace.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        send(ws, "request_hint", "hint")
        send(ws, "submit_attempt", "answer", {"answer": "x=2"})
    before = db.read_bytes()
    result = subprocess.run([sys.executable, "scripts/replay_turn.py", "--db", str(db), "--conversation", "p0",
                             "--turn", "answer"], cwd=ROOT, capture_output=True, text=True,
                            env={**os.environ, "PYTHONPATH": str(ROOT / "src")}, timeout=300)
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout[result.stdout.index("{"):])
    assert report["target_reproduced"] and [t["command"] for t in report["turns"]] == [
        "submit_problem", "request_hint", "submit_attempt"]
    assert db.read_bytes() == before
