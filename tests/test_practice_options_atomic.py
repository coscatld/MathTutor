"""Choice exposure is committed with acceptance before it becomes public."""
import json
import sqlite3
from contextlib import closing
from uuid import UUID

import pytest

from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.learning.knowledge_tracing.events import evidence_category
from mathtutor.security.scopes import DEV_STUDENT_ID
from test_phase5_e2e_offer_flow import _client, _collect, _send
from test_practice_response_modes import OFFERS, SESSION, answer_for, begin_transfer


@pytest.fixture(autouse=True)
def isolated_state():
    reset_product_state()
    yield
    reset_product_state()


def test_legacy_choice_accept_exposure_failure_rolls_back_and_retry_stays_diagnostic(tmp_path):
    path = tmp_path / "atomic-options.db"
    with _client(path) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            offer = begin_transfer(client, ws)
            answer = answer_for(client, offer)
            # Invitations created before response-mode fields retain choices.
            with closing(sqlite3.connect(path)) as db:
                payload = json.loads(db.execute("SELECT payload FROM practice_recommendations WHERE offer_id=?",
                    (offer["offer_id"],)).fetchone()[0])
                payload.pop("response_mode")
                payload.pop("observation_kind")
                db.execute("UPDATE practice_recommendations SET payload=? WHERE offer_id=?",
                    (json.dumps(payload), offer["offer_id"]))
                db.commit()
            state = get_product_state()
            before = client.get(SESSION).json()
            original = state.student_state.append_event
            failed = []

            async def fail_exposure(event, *, conn=None):
                if event.event_type == "options_exposed":
                    assert conn is not None, "exposure must use acceptance's transaction"
                    failed.append(event)
                    raise RuntimeError("synthetic exposure write failure")
                return await original(event, conn=conn)

            state.student_state.append_event = fail_exposure
            try:
                _send(ws, "accept_practice_offer", {"offer_id": offer["offer_id"]})
                assert any(f["event_type"] == "turn_error" for f in _collect(ws))
            finally:
                state.student_state.append_event = original
            assert len(failed) == 1
            saved = client.get(SESSION).json()
            assert saved["cycle_id"] == offer["parent_cycle_id"] == before["cycle_id"]
            assert saved["problem_context"] == before["problem_context"]
            assert next(o for o in client.get(OFFERS).json() if o["offer_id"] == offer["offer_id"])["status"] == "ACTIVE"

            async def rollback_state():
                return (await state.store.load_child_cycle_for_offer(DEV_STUDENT_ID, UUID(offer["offer_id"])),
                    await state.store.teaching.load(DEV_STUDENT_ID, failed[0].cycle_id),
                    await state.student_state.events(DEV_STUDENT_ID))

            child, context, events = client.portal.call(rollback_state)
            assert child is None and context is None
            assert not any(e.event_type == "options_exposed" for e in events)

            _send(ws, "accept_practice_offer", {"offer_id": offer["offer_id"]})
            assert not any(f["event_type"] == "turn_error" for f in _collect(ws))
            accepted = client.get(SESSION).json()
            assert accepted["problem_context"]["choices"]
            assert accepted["problem_context"]["options_exposed"]
            revision = accepted["problem_revision"]
            # A fresh cycle for the same canonical task cannot regain an
            # independent-transfer label by typing the now-exposed answer.
            _send(ws, "submit_problem", {"text": accepted["problem_context"]["display_text"]},
                session_id="reopened-after-exposure")
            assert not any(f["event_type"] == "turn_error" for f in _collect(ws))
            reopened = client.get("/api/v2/math-tutor/sessions/reopened-after-exposure").json()
            assert reopened["problem_revision"] == revision
            _send(ws, "submit_attempt", {"answer": answer}, session_id="reopened-after-exposure")
            assert not any(f["event_type"] == "turn_error" for f in _collect(ws))

        async def evidence():
            return (await state.student_state.events(DEV_STUDENT_ID),
                await state.student_state.presentation(DEV_STUDENT_ID, reopened["cycle_id"]))

        events, presentation = client.portal.call(evidence)
        assert sum(e.event_type == "options_exposed" and e.problem_revision == revision for e in events) == 1
        assessment = next(e for e in reversed(events) if e.event_type == "attempt_assessed")
        assert assessment.cycle_id == reopened["cycle_id"]
        assert assessment.correctness == "correct"
        assert assessment.options_exposed and assessment.response_format == "single_choice"
        assert evidence_category(assessment) == "diagnostic"
        assert not assessment.independent_target
        assert presentation["prediction_label"] is None
