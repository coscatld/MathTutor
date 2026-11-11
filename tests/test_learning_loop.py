"""Real SQLite/API contracts for bounded diagnostic and delayed learning episodes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from uuid import uuid4

import pytest

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state, reset_product_state
from mathtutor.application.learning_loop import LearningLoopService
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.migrate import alembic_config, upgrade_db
from mathtutor.learning.diagnostic_probes import format_answer, get_probe
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from test_phase5_e2e_offer_flow import _client

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


@pytest.mark.parametrize("domain", [DOMAIN, "signed_subtraction"])
def test_real_clock_gated_path_has_two_delayed_and_structural_checks(tmp_path, domain):
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
        for review_round, delay in ((1, 1), (2, 3)):
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
            state = submit(client, state)
            assert state["review_round"] == review_round
        assert state["phase"] == "complete" and state["question"] is None
        assert state["evidence"] == {"independent_practice": 1, "delayed_review": 2, "structural_transfer": 2}
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
        assert conn.execute("SELECT version_num FROM alembic_version").fetchall() == [("025",)]
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
