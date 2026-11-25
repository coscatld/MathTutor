"""Real SQLite/API contracts for bounded diagnostic and delayed learning episodes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from uuid import uuid4
from urllib.parse import quote

import pytest

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.application.learning_loop import LearningLoopService
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.migrate import alembic_config, upgrade_db
from mathtutor.learning.diagnostic_probes import format_answer
from mathtutor.learning.review_items import get_probe
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from test_phase5_e2e_offer_flow import _client
from test_phase5_e2e_offer_flow import _collect, _send

BASE = "/api/v2/math-tutor/desktop"
PREFIX = BASE + "/learning-loop"
DOMAIN = "fraction_addition"


@pytest.fixture(autouse=True)
def isolated_state():
    reset_product_state()
    yield
    reset_product_state()


def episode(response, domain=DOMAIN):
    assert response.status_code == 200, response.text
    return next(row["episode"] for row in response.json()["domains"] if row["domain"] == domain)


def body(state, **kwargs):
    return {"domain": state["domain"], "episode_id": state["episode_id"],
            "probe_id": state["question"]["probe_id"], "request_id": str(uuid4()), **kwargs}


def correct(state):
    return format_answer(get_probe(state["question"]["probe_id"]).answer)


def submit(client, state, answer=None):
    return episode(client.post(PREFIX + "/answer", json=body(state, answer=correct(state) if answer is None else answer)), state["domain"])


def practice(client, state):
    while state["phase"] == "diagnose":
        previous = state
        state = submit(client, state)
        assert state["diagnostic"]["answered"] <= 3
        if state["phase"] == "diagnose":
            assert state["feedback"] == {"kind": "recorded", "probe_id": previous["question"]["probe_id"], "statement": previous["question"]["statement"]}
    assert state["phase"] == "practice"
    return state


def stored(path, domain=DOMAIN):
    with closing(sqlite3.connect(path)) as conn:
        return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM learning_loop_episodes WHERE domain=?", (domain,))]


def tutor_problem(client, statement, answer=None, help_requested=False):
    session = str(uuid4())
    with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        _send(ws, "submit_problem", {"text": statement}, session)
        _collect(ws)
        if help_requested:
            _send(ws, "request_hint", {}, session)
            _collect(ws)
            _send(ws, "request_solution", {}, session)
            _collect(ws)
        if answer is not None:
            _send(ws, "submit_attempt", {"answer": answer}, session)
            _collect(ws)


def replace_saved(path, domain, payload):
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("UPDATE learning_loop_episodes SET payload=? WHERE domain=?", (json.dumps(payload), domain))


def test_regular_equation_error_to_assisted_correction_to_new_independent_agenda(tmp_path):
    path = tmp_path / "tutor.db"
    domain = "linear_equation"
    with _client(path) as client:
        tutor_problem(client, "2x+3=7", "2x=10")
        observed = client.get(BASE + "/student-summary").json()["review_observations"][0]
        assert (observed["category"], observed["reason"], observed["mode"]) == ("calculation", "constant", "independent")
        assert observed["next_problem"] == "3x-4=11"
        tutor_problem(client, "2x+3=7", "x=2", help_requested=True)
        assert episode(client.get(PREFIX), domain) is None
        assisted = client.get(BASE + "/student-evidence").json()["items"][0]
        assert assisted["correctness"] == "correct" and assisted["evidence_kind"] == "post_solution"
        tutor_problem(client, observed["next_problem"], "x=5")
        saved = stored(path, domain)[0]
        start = datetime.fromisoformat(saved["anchor_at"])
        assert saved["source_event_id"] and saved["source_cycle_id"] and saved["evidence"]["independent_practice"] == 1
        assert episode(client.get(PREFIX), domain)["source_cycle_id"] == saved["source_cycle_id"]
        ids, families = set(), []
        for day in (1, 3, 7):
            now = start + timedelta(days=day)
            get_product_state().learning_loop.clock = lambda: now
            state = episode(client.post(PREFIX + "/start", json={"domain": domain}), domain)
            assert state["phase"] == "review" and "answer" not in state["question"]
            ids.add(state["question"]["statement"])
            state = submit(client, state, "x=" + correct(state))
            assert state["phase"] == "transfer"
            ids.add(state["question"]["statement"])
            families.append(state["question"]["relation"])
            command = body(state, answer=correct(state))
            state = episode(client.post(PREFIX + "/answer", json=command), domain)
            assert episode(client.post(PREFIX + "/answer", json=command), domain) == state
        assert families == ["unknown_on_right", "variable_both_sides", "distribute"]
        assert len(ids) == 6 and "2x+3=7" not in ids
        assert state["phase"] == "complete" and state["evidence"] == {
            "independent_practice": 1, "delayed_review": 3, "structural_transfer": 3}
        assert [row["day"] for row in state["schedule"]["checkpoints"] if row["completed_at"]] == [1, 3, 7]
    reset_product_state()
    with _client(path) as client:
        assert episode(client.get(PREFIX), domain)["phase"] == "complete"


def test_overdue_rounds_never_stack_and_assisted_transfer_cannot_advance(tmp_path):
    path = tmp_path / "late.db"
    day_zero = datetime(2026, 8, 1, tzinfo=timezone.utc)
    now = [day_zero]
    with _client(path) as client:
        get_product_state().learning_loop.clock = lambda: now[0]
        state = submit(client, practice(client, episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))))
        now[0] += timedelta(days=20)
        state = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
        state = submit(client, state)
        assert state["evidence"]["delayed_review"] == 1
        helped = episode(client.post(PREFIX + "/help", json=body(state)))
        request = body(helped, answer=correct(helped))
        state = episode(client.post(PREFIX + "/answer", json=request))
        assert state["evidence"]["structural_transfer"] == 0 and state["phase"] == "practice"
        assert not state["feedback"]["independent"] and state["question"]["purpose"] == "transfer"
        state = submit(client, state)
        assert not state["can_start"] and state["due_at"] == (now[0] + timedelta(days=1)).isoformat()
        assert state["schedule"]["anchor_at"] == day_zero.isoformat()
        for day in (21, 22, 23):
            now[0] = day_zero + timedelta(days=day)
            state = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
            state = submit(client, submit(client, state))
            if day < 23:
                assert state["due_at"] == (now[0] + timedelta(days=1)).isoformat()
                assert not episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))["can_start"]
        assert state["evidence"]["delayed_review"] == state["evidence"]["structural_transfer"] == 3
        assert [row["completed_at"] for row in state["schedule"]["checkpoints"]] == [
            (day_zero + timedelta(days=day)).isoformat() for day in (21, 22, 23)]


def test_linear_agenda_respects_tutoring_exposure_exclusions_and_old_events(tmp_path):
    domain = "linear_equation"
    path = tmp_path / "owner.db"
    with _client(path) as client:
        tutor_problem(client, "2x+3=7", "x=2")
        saved = stored(path, domain)[0]
        anchor = datetime.fromisoformat(saved["anchor_at"])
        # An older installation may contain the independent event and no episode row.
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("DELETE FROM learning_loop_episodes WHERE domain=?", (domain,))
        assert episode(client.get(PREFIX), domain)["episode_id"] == saved["episode_id"]
        get_product_state().learning_loop.clock = lambda: anchor + timedelta(days=1)
        state = episode(client.post(PREFIX + "/start", json={"domain": domain}), domain)
        tutor_problem(client, state["question"]["statement"], help_requested=True)
        result = submit(client, state)
        assert result["evidence"]["delayed_review"] == 0 and not result["feedback"]["independent"]
        assert result["feedback"]["seen_in_tutoring"] and result["question"]["probe_id"] != state["question"]["probe_id"]
        excluded = client.post(BASE + "/student-evidence/" + quote(saved["source_event_id"], safe="") + "/exclude")
        assert excluded.status_code == 200
        retired = episode(client.get(PREFIX), domain)
        assert retired["schedule"] is None and retired["phase"] == "exhausted"
        assert retired["evidence"]["independent_practice"] == 0
        tutor_problem(client, "4x-7=9", "x=4")
        fresh = episode(client.get(PREFIX), domain)
        assert fresh["episode_id"] != saved["episode_id"] and fresh["schedule"]["anchor_at"]
        assert set(stored(path, domain)[0]["served_ids"]) >= {state["question"]["probe_id"]}


def test_v1_completed_history_resumes_only_unobserved_day_seven(tmp_path):
    path = tmp_path / "v1.db"
    origin = datetime(2026, 7, 1, tzinfo=timezone.utc)
    now = [origin]
    with _client(path) as client:
        get_product_state().learning_loop.clock = lambda: now[0]
        state = submit(client, practice(client, episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))))
        old = stored(path)[0]
        for key in ("schedule_version", "checkpoints", "anchor_at"):
            del old[key]
        old.update(phase="complete", review_round=2, due_at=None, current_probe=None)
        for i, day in enumerate((1, 4)):
            for phase in ("review", "transfer"):
                probe_id = f"{DOMAIN}:{phase}:{i+2:02}"
                old["served_ids"].append(probe_id)
                old["attempts"].append({"phase": phase, "probe_id": probe_id, "answer": str(get_probe(probe_id).answer),
                    "independent": True, "correctness": "correct", "occurred_at": (origin + timedelta(days=day)).isoformat()})
        old["evidence"].update(delayed_review=2, structural_transfer=2)
        replace_saved(path, DOMAIN, old)
        state = episode(client.get(PREFIX))
        assert state["phase"] == "waiting" and state["review_round"] == 2
        assert state["schedule"]["checkpoints"][1]["from_legacy"]
        assert state["schedule"]["checkpoints"][1]["completed_at"] == (origin + timedelta(days=4)).isoformat()
        assert state["due_at"] == (origin + timedelta(days=7)).isoformat()
        now[0] += timedelta(days=7)
        state = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
        state = submit(client, submit(client, state))
        assert state["phase"] == "complete" and state["evidence"]["structural_transfer"] == 3


@pytest.mark.parametrize("domain", [DOMAIN, "signed_subtraction"])
def test_real_clock_gated_path_has_three_anchored_and_distinct_structural_checks(tmp_path, domain):
    path = tmp_path / "loop.db"
    now = [datetime(2026, 11, 11, 9, tzinfo=timezone.utc)]
    with _client(path) as client:
        get_product_state().learning_loop.clock = lambda: now[0]
        state = episode(client.post(PREFIX + "/start", json={"domain": domain}), domain)
        assert "answer" not in state["question"] and "predictions" not in state["question"]
        state = practice(client, state)
        state = submit(client, state)
        assert state["phase"] == "waiting" and not state["can_start"]
        assert state["evidence"] == {"independent_practice": 1, "delayed_review": 0, "structural_transfer": 0}
        structures = []
        anchor = now[0]
        for review_round, day in enumerate((1, 3, 7), 1):
            delay = (anchor + timedelta(days=day) - now[0]).days
            assert state["schedule"]["anchor_at"] == anchor.isoformat()
            assert state["due_at"] == (anchor + timedelta(days=day)).isoformat()
            now[0] += timedelta(days=delay) - timedelta(microseconds=1)
            before = episode(client.post(PREFIX + "/start", json={"domain": domain}), domain)
            assert before["phase"] == "waiting" and not before["can_start"]
            now[0] += timedelta(microseconds=1)
            due_read = episode(client.get(PREFIX), domain)
            assert due_read["phase"] == "waiting" and due_read["can_start"]
            state = episode(client.post(PREFIX + "/start", json={"domain": domain}), domain)
            assert state["phase"] == "review"
            state = submit(client, state)
            assert state["phase"] == "transfer" and state["question"]["relation"] != "new_instance"
            structures.append(state["question"]["relation"])
            state = submit(client, state)
            assert state["review_round"] == review_round
        assert len(set(structures)) == 3
        assert state["phase"] == "complete" and state["question"] is None
        assert state["evidence"] == {"independent_practice": 1, "delayed_review": 3, "structural_transfer": 3}
        assert episode(client.post(PREFIX + "/start", json={"domain": domain}), domain) == state
        assert client.get(BASE + "/student-summary").json()["total_attempts"] == 0
        saved = stored(path, domain)[0]
        assert len(saved["served_ids"]) == len(set(saved["served_ids"]))
        assert len(saved["diagnosis"]) <= 3


def test_unknown_help_repeat_restart_and_owner_are_separate(tmp_path):
    path = tmp_path / "loop.db"
    with _client(path) as client:
        initial = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
        unknown = submit(client, initial, "x + 1")
        assert unknown["question"] == initial["question"] and unknown["diagnostic"]["answered"] == 0
        assert unknown["feedback"]["kind"] == "unknown" and "answer" not in unknown["feedback"]
        initial_help = body(unknown)
        helped = episode(client.post(PREFIX + "/help", json=initial_help))
        assert helped["phase"] == "practice" and helped["diagnostic"]["status"] == "uncertain"
        assert helped["feedback"]["answer"] == correct(initial)
        assert helped["question"]["probe_id"] != initial["question"]["probe_id"]
        practice_help = body(helped)
        helped = episode(client.post(PREFIX + "/help", json=practice_help))
        assert helped["phase"] == "practice"
        after_helped_correct = submit(client, helped)
        assert after_helped_correct["phase"] == "practice"
        assert not after_helped_correct["feedback"]["independent"]
        assert after_helped_correct["evidence"]["independent_practice"] == 0
        assert episode(client.post(PREFIX + "/help", json=practice_help)) == after_helped_correct
        saved = stored(path)[0]
        client.app.dependency_overrides[require_student_owner] = lambda: StudentOwnerScope(
            principal=PrincipalScope(user_id="other", username="other", role="student"), student_id="other")
        try:
            assert episode(client.get(PREFIX)) is None
            assert client.post(PREFIX + "/help", json=practice_help).status_code == 409
            other = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
            assert other["episode_id"] != saved["episode_id"]
            assert client.post(PREFIX + "/help", json=practice_help).status_code == 409
        finally:
            client.app.dependency_overrides.clear()
        assert episode(client.get(PREFIX)) == after_helped_correct
    reset_product_state()
    with _client(path) as client:
        assert episode(client.get(PREFIX)) == after_helped_correct
        assert episode(client.post(PREFIX + "/start", json={"domain": DOMAIN})) == after_helped_correct


def test_duplicates_concurrent_answers_and_stale_items_never_recount(tmp_path):
    path = tmp_path / "loop.db"
    with _client(path) as client:
        state = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
        request = body(state, answer=correct(state))
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: client.post(PREFIX + "/answer", json=request), range(2)))
        states = [episode(response) for response in responses]
        assert states[0] == states[1]
        assert len(stored(path)[0]["attempts"]) == 1
        assert client.post(PREFIX + "/answer", json={**request, "answer": "999"}).status_code == 409
        assert client.post(PREFIX + "/answer", json={**request, "request_id": str(uuid4())}).status_code == 409
        assert client.post(PREFIX + "/answer", json={**request, "occurred_at": "2099-01-01"}).status_code == 422
        assert client.post(PREFIX + "/answer", json={**request, "independent": True}).status_code == 422
        assert len(stored(path)[0]["attempts"]) == 1


def test_late_review_unknown_and_backwards_clock_do_not_manufacture_success(tmp_path):
    path = tmp_path / "loop.db"
    now = [datetime(2026, 11, 11, tzinfo=timezone.utc)]
    with _client(path) as client:
        service = get_product_state().learning_loop
        service.clock = lambda: now[0]
        state = practice(client, episode(client.post(PREFIX + "/start", json={"domain": DOMAIN})))
        state = submit(client, state)
        now[0] += timedelta(days=50)
        assert episode(client.get(PREFIX))["evidence"]["delayed_review"] == 0
        state = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
        now[0] -= timedelta(seconds=1)
        assert client.post(PREFIX + "/answer", json=body(state, answer=correct(state))).status_code == 409
        now[0] += timedelta(seconds=1)
        state = submit(client, state, "not a number")
        assert state["phase"] == "review" and state["evidence"]["delayed_review"] == 0
        state = submit(client, state, "999")
        assert state["phase"] == "practice" and state["evidence"]["delayed_review"] == 0
        assert state["diagnostic"]["status"] == "uncertain"


def test_export_whitelist_and_forgetting_delete_only_current_owner(tmp_path):
    path = tmp_path / "loop.db"
    with _client(path) as client:
        state = practice(client, episode(client.post(PREFIX + "/start", json={"domain": DOMAIN})))
        stale = body(state, answer=correct(state))
        export = client.get(BASE + "/privacy/export")
        assert export.status_code == 200, export.text
        rows = export.json()["student_summary"]["learning_loop"]
        assert rows[0]["domain"] == DOMAIN and rows[0]["phase"] == "practice"
        assert all(key not in json.dumps(rows) for key in ("fingerprint", "answer", "predictions", "request_id", "payload"))
        owner = StudentOwnerScope(principal=PrincipalScope(user_id="other", username="other", role="student"), student_id="other")
        client.app.dependency_overrides[require_student_owner] = lambda: owner
        other = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
        client.app.dependency_overrides.clear()
        assert client.post(BASE + "/privacy/educational-history").status_code == 200
        assert episode(client.get(PREFIX)) is None
        assert client.post(PREFIX + "/answer", json=stale).status_code == 409
        assert client.get(BASE + "/privacy/export").json()["student_summary"]["learning_loop"] == []
        client.app.dependency_overrides[require_student_owner] = lambda: owner
        try:
            assert episode(client.get(PREFIX)) == other
        finally:
            client.app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("after_write", [False, True])
async def test_cancelled_before_commit_keeps_question_and_no_evidence(tmp_path, after_write):
    path = tmp_path / "loop.db"
    upgrade_db(str(path))
    engine = create_db_engine(path)
    service = LearningLoopService(engine)
    sid = str(uuid4())
    try:
        data = await service.start(sid, DOMAIN)
        state = data["domains"][0]["episode"]
        entered = asyncio.Event()
        original_save = service._save
        async def blocked(*args):
            if after_write:
                await original_save(*args)
            entered.set()
            await asyncio.Event().wait()
            if not after_write:
                await original_save(*args)
        service._save = blocked
        task = asyncio.create_task(service.submit(sid, **body(state, answer=correct(state))))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        unchanged = await service.read(sid)
        assert unchanged["domains"][0]["episode"] == state
        assert stored(path)[0]["attempts"] == []
    finally:
        await engine.dispose()


def test_upgrade_real_024_adds_loop_without_losing_rows_and_is_idempotent(tmp_path):
    from alembic import command
    path = tmp_path / "loop.db"
    command.upgrade(alembic_config(str(path)), "024")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DROP TABLE IF EXISTS learning_loop_episodes")
        conn.execute("CREATE TABLE migration_sentinel(value TEXT)")
        conn.execute("INSERT INTO migration_sentinel VALUES ('kept')")
    upgrade_db(str(path))
    upgrade_db(str(path))
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("028",)]
        assert conn.execute("SELECT value FROM migration_sentinel").fetchall() == [("kept",)]
        assert conn.execute("SELECT count(*) FROM learning_loop_episodes").fetchone()[0] == 0


def test_incompatible_catalog_is_readable_exportable_and_never_reinterpreted(tmp_path):
    path = tmp_path / "loop.db"
    with _client(path) as client:
        state = episode(client.post(PREFIX + "/start", json={"domain": DOMAIN}))
        old = stored(path)[0]
        old.update(probe_policy="old-removed-catalog", current_probe="removed:old:item")
        old["diagnosis"] = [{"probe_id": "removed:old:item", "answer": "42", "independent": True}]
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.execute("UPDATE learning_loop_episodes SET payload=?", (json.dumps(old),))
        public = episode(client.get(PREFIX))
        assert public["phase"] == "exhausted" and public["question"] is None
        assert public["diagnostic"]["status"] == "uncertain"
        assert client.get(BASE + "/privacy/export").status_code == 200
        assert client.post(PREFIX + "/start", json={"domain": DOMAIN}).status_code == 409
        assert client.post(PREFIX + "/answer", json=body(state, answer="42")).status_code == 409
        assert stored(path)[0] == old


def test_invalid_preexisting_loop_table_aborts_migration_without_stamping_head(tmp_path):
    from alembic import command
    path = tmp_path / "loop.db"
    command.upgrade(alembic_config(str(path)), "024")
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute("DROP TABLE learning_loop_episodes")
        conn.execute("CREATE TABLE learning_loop_episodes(student_id TEXT, payload TEXT)")
        conn.execute("INSERT INTO learning_loop_episodes VALUES ('sentinel', 'kept')")
    with pytest.raises(RuntimeError, match="migration contract"):
        upgrade_db(str(path))
    with closing(sqlite3.connect(path)) as conn:
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("024",)]
        assert conn.execute("SELECT * FROM learning_loop_episodes").fetchall() == [("sentinel", "kept")]
