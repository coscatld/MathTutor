"""Frozen recommendation reasons and erasure, including accepted exercises."""
import json
import sqlite3
from urllib.parse import quote

import pytest

from mathtutor.api.product_state import reset_product_state
from test_phase5_e2e_offer_flow import _client, _send, _collect

PREFIX = "/api/v2/math-tutor/desktop"


@pytest.mark.parametrize("operation", ["exclude", "delete"])
def test_basis_is_frozen_and_erased_without_losing_accepted_exercise(tmp_path, operation):
    db = tmp_path / "basis.db"
    reset_product_state()
    with _client(db) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_problem", {"text": "2x+3=7"})
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": "2"})
            _collect(ws)
            original = client.get("/api/v2/math-tutor/offers").json()[0]
            assert original["basis"]["policy_version"] == "mt-recommendation-basis-v1"
            evidence_id = original["evidence_ids"][0]
            assert original["basis"]["target_revision"]
            assert original["basis"]["target_skill_ids"]
            _send(ws, "accept_practice_offer", {"offer_id": original["offer_id"]})
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": "9999"})
            _collect(ws)
        latest = next(o for o in client.get("/api/v2/math-tutor/offers").json() if o["offer_id"] == original["offer_id"])
        assert latest["basis"] == original["basis"]
        assert latest["reason"] == original["reason"]
        child = latest["child_cycle_id"]
    reset_product_state()
    with _client(db) as client:
        restored = next(o for o in client.get("/api/v2/math-tutor/offers").json() if o["offer_id"] == original["offer_id"])
        assert restored["basis"] == original["basis"]
        endpoint = (PREFIX + "/student-evidence/" + quote(evidence_id, safe="") + "/exclude"
                    if operation == "exclude" else PREFIX + "/privacy/educational-history")
        assert client.post(endpoint).status_code == 200
    reset_product_state()
    with _client(db) as client:
        restored = next(o for o in client.get("/api/v2/math-tutor/offers").json() if o["offer_id"] == original["offer_id"])
        assert restored["status"] == "ACCEPTED"
        assert restored["child_cycle_id"] == child
        assert restored["basis"] is None and restored["evidence_ids"] == []
        assert restored["history_cutoff_seq"] is None
        assert "不可用" in restored["reason"]
        assert client.post(f"/api/v2/math-tutor/offers/{original['offer_id']}/resume").status_code == 200
    with sqlite3.connect(db) as conn:
        payload = json.loads(conn.execute("SELECT payload FROM practice_recommendations WHERE offer_id=?", (original["offer_id"],)).fetchone()[0])
        assert payload["basis"] is None and payload["decision_reason"] == ""
        assert evidence_id not in json.dumps(payload)
    reset_product_state()


def test_legacy_recommendation_does_not_backfill_reason_from_current_history(tmp_path):
    db = tmp_path / "legacy.db"
    reset_product_state()
    with _client(db) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_problem", {"text": "2x+3=7"})
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": "2"})
            _collect(ws)
    with sqlite3.connect(db) as conn:
        row = conn.execute("SELECT recommendation_id,payload FROM practice_recommendations").fetchone()
        payload = json.loads(row[1])
        payload.pop("basis")
        conn.execute("UPDATE practice_recommendations SET payload=? WHERE recommendation_id=?", (json.dumps(payload), row[0]))
    reset_product_state()
    with _client(db) as client:
        offer = client.get("/api/v2/math-tutor/offers").json()[0]
        assert offer["basis"] is None and offer["evidence_ids"] == []
        assert "不可用" in offer["reason"]
    reset_product_state()
