"""Real SQLite/WS evidence to profile, feedback, exclusion and deletion."""
from urllib.parse import quote
from mathtutor.api.product_state import reset_product_state
from test_phase5_e2e_offer_flow import _client, _send, _collect

PREFIX = "/api/v2/math-tutor/desktop"


def test_profile_feedback_exclusion_and_complete_delete(tmp_path):
    reset_product_state()
    with _client(tmp_path / "profile.db") as client:
        empty = client.get(PREFIX + "/student-summary").json()
        assert empty["coverage"]["observed_skills"] == 0
        assert all(s["mastery"] is None for s in empty["skills"])
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws, "submit_problem", {"text": "2x+3=7"})
            _collect(ws)
            _send(ws, "submit_attempt", {"answer": "2"})
            _collect(ws)
        profile = client.get(PREFIX + "/student-summary").json()
        assert profile["has_conversations"] and profile["has_independent_evidence"]
        assert profile["coverage"]["observed_skills"] > 0
        evidence = client.get(PREFIX + "/student-evidence").json()["items"]
        assert len(evidence) == 1
        assert evidence[0]["student_response"] == "2"
        assert evidence[0]["session_id"] == "e2e-1"
        assert "expected_roots" not in str(evidence) and "verification_log" not in str(evidence)
        offers = client.get("/api/v2/math-tutor/offers").json()
        offer_id = offers[0]["offer_id"]
        for _ in range(2):
            assert client.post(f"/api/v2/math-tutor/offers/{offer_id}/feedback", json={"kind":"later"}).status_code == 200
        later = client.get("/api/v2/math-tutor/offers").json()[0]
        assert later["display_status"] == "later"
        assert client.get(PREFIX + "/student-summary").json()["total_attempts"] == profile["total_attempts"]
        event_path = PREFIX + "/student-evidence/" + quote(evidence[0]["event_id"], safe="") + "/exclude"
        assert client.post(event_path).status_code == 200
        assert client.post(event_path).status_code == 200  # idempotent exclusion
        assert client.get(PREFIX + "/student-evidence").json()["items"][0]["excluded"]
        assert client.get("/api/v2/math-tutor/offers").json()[0]["status"] == "REVOKED"
        assert not client.get(PREFIX + "/student-summary").json()["has_independent_evidence"]
        assert client.post(PREFIX + "/student-evidence/not-owned/exclude").status_code == 404
        assert client.post(PREFIX + "/privacy/recompute-profile").status_code == 200
        assert client.post(PREFIX + "/privacy/educational-history").status_code == 200
        assert client.get(PREFIX + "/student-evidence").json()["items"] == []
        assert client.get(PREFIX + "/student-summary").json()["has_conversations"]
    reset_product_state()
    with _client(tmp_path / "profile.db") as client:
        assert client.get(PREFIX + "/student-evidence").json()["items"] == []
        assert client.get(PREFIX + "/student-summary").json()["coverage"]["observed_skills"] == 0
    reset_product_state()
