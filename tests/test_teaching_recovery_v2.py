"""Real WS/SQLite checkpoints: approved bytes survive crashes without replaying effects.

Only disposable test databases are modified. The abandoned-journal fixture
models process loss before final frame persistence; the stale-revision fixture
models an old checkpoint which no longer matches the current verified task.
"""
import json
import sqlite3
from contextlib import closing

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from mathtutor.pedagogy.tutor_writer import LLMTutorWriter
from test_tutor_p0 import client_at, send, summary, count
from test_teaching_v2 import terminal


class OneCallProvider:
    provider_id = "recovery-fixed-provider"
    model = "recovery-fixture"

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, **kwargs):
        self.calls += 1
        if self.calls != 1:
            raise AssertionError("Recovery must not make a second model call")
        return CompletionResult(text="先看等式两边：如果要去掉左边的常数，右边应该做什么？",
            provider_id=self.provider_id, model=self.model, finish_reason="stop",
            input_tokens=30, output_tokens=20)


def install_writer(provider):
    state = get_product_state()
    state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
    state.controller.writer = LLMTutorWriter(client=state.gateway.client_for(ModelRole.TUTOR_WRITER))
    return state


def context_row(db, cycle_id):
    with closing(sqlite3.connect(db)) as conn, conn:
        row = conn.execute("SELECT payload FROM teaching_contexts WHERE cycle_id=?", (cycle_id,)).fetchone()
        return json.loads(row[0])


def table_ids(db, table, column, cycle_id):
    # Table/column names are fixed test constants, never client-controlled SQL.
    with closing(sqlite3.connect(db)) as conn, conn:
        return [row[0] for row in conn.execute(f'SELECT "{column}" FROM "{table}" WHERE cycle_id=? ORDER BY "{column}"', (cycle_id,))]


def help_events(db, cycle_id):
    with closing(sqlite3.connect(db)) as conn, conn:
        return [json.loads(row[0]) for row in conn.execute("SELECT payload FROM learning_events ORDER BY event_seq")
                if json.loads(row[0]).get("cycle_id") == cycle_id and json.loads(row[0])["event_type"].startswith("help_")]


def inject_before_action_commit(state, db, cycle_id):
    original = state.store.commit_teaching_action
    seen = []
    async def fail_once(*args, **kwargs):
        if not seen:
            persisted = context_row(db, cycle_id)["pending_expression"]
            assert persisted["phase"] == "expression_approved"
            seen.append(persisted)
            raise RuntimeError("fixed crash after approved bytes, before action commit")
        return await original(*args, **kwargs)
    state.store.commit_teaching_action = fail_once
    return seen


def assert_exact_success(db, client, frames, cycle_id, saved, help_before, provider):
    result = terminal(frames)
    assert result["event_type"] == "assistant_complete"
    assert result["payload"]["final_text"] == saved["approved_utterance"]["text"]
    assert result["delivery_id"] == saved["action"]["action_id"]
    assert table_ids(db, "teaching_deliveries", "delivery_id", cycle_id) == [saved["action"]["action_id"]]
    assert table_ids(db, "tutor_actions", "action_id", cycle_id) == [saved["action"]["action_id"]]
    after = context_row(db, cycle_id)
    assert after["pending_expression"]["phase"] == "done"
    assert after["pending_expression"]["approved_utterance"] == saved["approved_utterance"]
    assert after["help_without_progress"] == 1
    assert help_events(db, cycle_id) == help_before
    assert provider.calls == 1 and count(db, "attempts") == 0
    messages = [row for row in summary(client)["messages"] if row.get("turn_id") == "hint"]
    assert len(messages) == 1 and messages[0]["status"] == "COMPLETED"
    return after


@pytest.mark.parametrize("journal_status", ["failed", "abandoned"])
def test_approved_expression_recovers_same_bytes_ids_and_single_effect_after_restart(tmp_path, journal_status):
    db = tmp_path / "approved.db"
    provider = OneCallProvider()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        cycle_id = summary(client)["cycle_id"]
        state = install_writer(provider)
        captured = inject_before_action_commit(state, db, cycle_id)
        failed = send(ws, "request_hint", "hint")
        assert terminal(failed)["event_type"] in {"assistant_error", "assistant_partial"}
        assert len(captured) == 1 and provider.calls == 1
        saved = captured[0]
        assert not table_ids(db, "tutor_actions", "action_id", cycle_id)
        assert summary(client)["state"] == "awaiting_attempt"
        assert context_row(db, cycle_id)["help_without_progress"] == 1
        help_before = help_events(db, cycle_id)
    if journal_status == "abandoned":
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute("UPDATE turn_requests SET status='RUNNING', frames=? WHERE request_id='hint'",
                         (json.dumps([failed[0]]),))
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        install_writer(provider)
        recovered = send(ws, "request_hint", "hint")
        after = assert_exact_success(db, client, recovered, cycle_id, saved, help_before, provider)
        # Completed replay is byte-identical and also has no second effects.
        assert send(ws, "request_hint", "hint") == recovered
        assert context_row(db, cycle_id) == after and provider.calls == 1


def test_action_committed_before_emit_recovers_only_approved_output(tmp_path):
    db = tmp_path / "committed.db"
    provider = OneCallProvider()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        cycle_id = summary(client)["cycle_id"]
        state = install_writer(provider)
        original = state.controller._emit
        captured = []
        async def fail_before_emit(*args, **kwargs):
            if not captured:
                saved = context_row(db, cycle_id)["pending_expression"]
                assert saved["phase"] == "action_committed"
                assert table_ids(db, "tutor_actions", "action_id", cycle_id) == [saved["action"]["action_id"]]
                captured.append(saved)
                raise RuntimeError("fixed crash after action commit, before stream emit")
            return await original(*args, **kwargs)
        state.controller._emit = fail_before_emit
        failed = send(ws, "request_hint", "hint")
        assert terminal(failed)["event_type"] in {"assistant_error", "assistant_partial"}
        saved = captured[0]
        before_version = summary(client)["state_version"]
        help_before = help_events(db, cycle_id)
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        install_writer(provider)
        recovered = send(ws, "request_hint", "hint")
        assert_exact_success(db, client, recovered, cycle_id, saved, help_before, provider)
        assert summary(client)["state_version"] == before_version


@pytest.mark.parametrize("change", ["cycle", "revision"])
def test_old_checkpoint_cannot_resume_after_cycle_or_revision_changes(tmp_path, change):
    db = tmp_path / "stale.db"
    provider = OneCallProvider()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        old_cycle = summary(client)["cycle_id"]
        state = install_writer(provider)
        saved = inject_before_action_commit(state, db, old_cycle)
        send(ws, "request_hint", "hint")
        assert saved and provider.calls == 1
        if change == "cycle":
            # This fixture isolates expression replay, not the independently
            # tested semantic interpreter's call on a new free-form question.
            state.controller.semantic_interpreter = None
            send(ws, "send_message", "next", {"text": "换一道题，3x+2=11"})
            assert summary(client)["cycle_id"] != old_cycle
        stable = summary(client)
        actions = count(db, "tutor_actions")
        helps = help_events(db, old_cycle)
    if change == "revision":
        with closing(sqlite3.connect(db)) as conn, conn:
            context = context_row(db, old_cycle)
            context["pending_expression"]["problem_revision"] = "superseded-test-revision"
            conn.execute("UPDATE teaching_contexts SET payload=? WHERE cycle_id=?", (json.dumps(context), old_cycle))
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        install_writer(provider)
        rejected = send(ws, "request_hint", "hint")
        assert terminal(rejected)["event_type"] != "assistant_complete"
        assert saved[0]["approved_utterance"]["text"] not in json.dumps(rejected, ensure_ascii=False)
        assert summary(client)["cycle_id"] == stable["cycle_id"]
        assert count(db, "tutor_actions") == actions and count(db, "attempts") == 0
        assert help_events(db, old_cycle) == helps and provider.calls == 1


def test_focus_changed_while_model_runs_discards_old_expression_before_delivery(tmp_path):
    db = tmp_path / "focus-race.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        send(ws, "submit_problem", "p", {"text": "2x+3=7"})
        old_cycle = summary(client)["cycle_id"]
        with closing(sqlite3.connect(db)) as conn, conn:
            owner = conn.execute("SELECT student_id FROM tutoring_cycles WHERE cycle_id=?", (old_cycle,)).fetchone()[0]
        changed = []
        class FocusChangingProvider(OneCallProvider):
            async def complete(self, messages, **kwargs):
                result = await super().complete(messages, **kwargs)
                # Another runtime action changes the persisted focus during
                # model latency, before the writer's candidate returns.
                next_session = await get_product_state().store.start_new_cycle(owner, "p0")
                changed.append(str(next_session.cycle.cycle_id))
                return result
        provider = FocusChangingProvider()
        install_writer(provider)
        rejected = send(ws, "request_hint", "old-expression")
        assert changed and changed[0] != old_cycle
        assert summary(client)["cycle_id"] == changed[0]
        assert terminal(rejected)["event_type"] == "assistant_error"
        assert "如果要去掉左边的常数" not in json.dumps(rejected, ensure_ascii=False)
        assert count(db, "teaching_deliveries") == count(db, "tutor_actions") == count(db, "attempts") == 0
        assert not help_events(db, old_cycle) and not help_events(db, changed[0])
        assert context_row(db, old_cycle)["pending_expression"]["phase"] == "planned"
        assert provider.calls == 1
