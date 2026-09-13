from uuid import UUID
from mathtutor.api.product_state import reset_product_state
from test_phase5_e2e_offer_flow import _client, _send, _collect


def test_resume_preserves_cycle_and_feedback_never_completes_practice(tmp_path):
    reset_product_state()
    with _client(tmp_path / "resume.db") as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            _send(ws,"submit_problem",{"text":"2x+3=7"})
            _collect(ws)
            _send(ws,"submit_attempt",{"answer":"2"})
            _collect(ws)
            offer = client.get("/api/v2/math-tutor/offers").json()[0]
            _send(ws,"accept_practice_offer",{"offer_id":offer["offer_id"]})
            _collect(ws)
        accepted = client.get("/api/v2/math-tutor/offers").json()[0]
        assert accepted["display_status"] == "in_progress"
        assert accepted["result_summary"]["observations"] == 0
        assert client.post(f"/api/v2/math-tutor/offers/{offer['offer_id']}/feedback",json={"kind":"later"}).status_code == 409
        for _ in range(2):
            response = client.post(f"/api/v2/math-tutor/offers/{offer['offer_id']}/resume")
            assert response.status_code == 200
            assert response.json()["session_id"] == "e2e-1"
        assert client.get("/api/v2/math-tutor/sessions/e2e-1").json()["cycle_id"] == accepted["child_cycle_id"]
        assert client.get(f"/api/v2/math-tutor/cycles/{accepted['child_cycle_id']}").json()["session_id"] == "e2e-1"
    reset_product_state()
