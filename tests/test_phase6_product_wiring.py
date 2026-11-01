"""MAIN INTEGRATION 2: Phase 6 components wired into the real product.

- the outbox relay is constructed over the product UoW and runs as a
  RESIDENT loop from app startup (round 2): it drains committed events
  exactly once (idempotent, restart-safe, domain_outbox untouched);
- the versioned curriculum catalog is available product-wide on both the
  SQLite and the in-memory state.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mathtutor.api.product_app import create_math_tutor_app
from mathtutor.api.product_state import (
    get_product_state,
    reset_product_state,
)
from mathtutor.security.settings import MathTutorSecuritySettings

pytestmark = pytest.mark.asyncio

_SESSION = "wire-1"


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


async def _outbox_count(state) -> int:
    import sqlalchemy as sa

    async with state.uow.transaction() as conn:
        return len((await conn.execute(sa.text("SELECT outbox_id FROM domain_outbox"))).all())


async def _ledger_count(state) -> int:
    import sqlalchemy as sa

    async with state.uow.transaction() as conn:
        return len(
            (await conn.execute(sa.text("SELECT outbox_id FROM outbox_dispatch_ledger"))).all()
        )


async def _wait_for_committed_receipts(state) -> None:
    """Assert eventual delivery while the resident loop is still admitted."""
    async with asyncio.timeout(3.0):
        while await state.outbox_relay.pending_count():
            await asyncio.sleep(0.01)
    assert await _ledger_count(state) == await _outbox_count(state)


async def _wait_for_barrier(event):
    await asyncio.wait_for(event.wait(), 3.0)


def _persisted_counts(path):
    """Read a stopped app without reopening its disposed engine/pool."""
    from mathtutor.infrastructure import db_crypto
    with closing(db_crypto.connect_db(path, readonly=True)) as conn:
        outbox = conn.execute("SELECT count(*) FROM domain_outbox").fetchone()[0]
        ledger = conn.execute("SELECT count(*) FROM outbox_dispatch_ledger").fetchone()[0]
        pending = conn.execute("SELECT count(*) FROM domain_outbox o LEFT JOIN outbox_dispatch_ledger l "
            "ON l.outbox_id=o.outbox_id WHERE l.outbox_id IS NULL OR l.last_error IS NOT NULL").fetchone()[0]
    return outbox, ledger, pending


async def test_resident_relay_drains_exactly_once_and_survives_restart(
    tmp_path: Path,
) -> None:
    """The live offer flow writes outbox events; the RESIDENT relay (started
    at app startup, stopped at shutdown) eventually delivers them — every
    outbox row lands in the ledger once, domain_outbox is untouched, and a
    fresh relay over the same db (restart) dispatches nothing again."""
    db_file = tmp_path / "math_tutor.db"
    reset_product_state()

    with _client(db_file) as client:
        state = get_product_state(db_file)
        assert state.outbox_relay is not None
        assert state.outbox_relay.is_running, "the resident loop starts at app startup"
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            ws.send_text(
                json.dumps(
                    {
                        "command": "submit_problem",
                        "payload": {"text": "2x + 3 = 7"},
                        "session_id": _SESSION,
                    }
                )
            )
            _collect(ws)
            ws.send_text(
                json.dumps(
                    {
                        "command": "submit_attempt",
                        "payload": {"answer": "2"},
                        "session_id": _SESSION,
                    }
                )
            )
            _collect(ws)

        # stop() only finishes its current batch. Establish completion while
        # the app is running instead of racing shutdown against the next poll.
        client.portal.call(_wait_for_committed_receipts, state)

    state = get_product_state(db_file)
    assert state.curriculum is not None
    # These receipts were confirmed before shutdown, not promised by stop().
    assert state.outbox_relay.is_running is False
    outbox_rows = await _outbox_count(state)
    assert outbox_rows >= 1, "the offer flow must have written outbox events"
    assert await state.outbox_relay.pending_count() == 0
    assert await _ledger_count(state) == outbox_rows

    # domain_outbox is append-only: relay dispatch never deletes/mutates.
    # Idempotent: a manual batch after the resident drain dispatches nothing.
    again = await state.outbox_relay.process_batch(limit=200)
    assert again["dispatched"] == 0
    await state.uow.engine.dispose()

    # Restart-safe: a fresh relay over the SAME db dispatches nothing.
    reset_product_state()
    state2 = get_product_state(db_file)
    after_restart = await state2.outbox_relay.process_batch(limit=200)
    assert after_restart["dispatched"] == 0
    assert await state2.outbox_relay.pending_count() == 0
    await state2.uow.engine.dispose()

    reset_product_state()


async def test_idle_shutdown_preserves_pending_then_resident_restart_delivers(
    tmp_path: Path, monkeypatch,
) -> None:
    """A barrier fixes commit → stop → next-fetch ordering in the real app."""
    from mathtutor.application.outbox_relay import OutboxRelayService
    from mathtutor.repositories.uow import append_outbox_events

    db_file = tmp_path / "pending.db"
    reset_product_state()
    entered, release = asyncio.Event(), asyncio.Event()
    original_idle = OutboxRelayService._idle_wait

    async def held_idle(relay):
        entered.set()
        await release.wait()
        await original_idle(relay)

    async def append_pending(state):
        async with state.uow.transaction() as conn:
            await append_outbox_events(conn, [dict(aggregate_type="test", aggregate_id=f"pending-{i}",
                aggregate_version=1, event_sequence=1, event_type="practice_offer_issued",
                audience="student", payload={"offer_id":f"synthetic-{i}"}) for i in range(3)])

    with monkeypatch.context() as patch:
        patch.setattr(OutboxRelayService, "_idle_wait", held_idle)
        with _client(db_file) as client:
            state = get_product_state(db_file)
            relay = state.outbox_relay
            client.portal.call(_wait_for_barrier, entered)
            baseline = client.portal.call(_outbox_count, state)
            assert client.portal.call(_ledger_count, state) == baseline
            original_stop = relay.stop

            async def release_after_stop(timeout=5.0):
                stopping = asyncio.create_task(original_stop(timeout=timeout))
                await relay._stop_event.wait()
                release.set()
                await stopping

            # The real application shutdown calls this wrapper, which releases
            # the pre-fetch barrier only after the original stop flag is set.
            relay.stop = release_after_stop
            client.portal.call(append_pending, state)
            assert client.portal.call(relay.pending_count) == 3
            assert client.portal.call(_ledger_count, state) == baseline
        assert not relay.is_running
        assert _persisted_counts(db_file) == (baseline + 3, baseline, 3)

    reset_product_state()
    with _client(db_file) as client:
        restarted = get_product_state(db_file)
        assert restarted.outbox_relay.is_running
        client.portal.call(_wait_for_committed_receipts, restarted)
        assert client.portal.call(_outbox_count, restarted) == baseline + 3
        assert client.portal.call(_ledger_count, restarted) == baseline + 3
    assert not restarted.outbox_relay.is_running
    assert _persisted_counts(db_file) == (baseline + 3, baseline + 3, 0)
    reset_product_state()


async def test_curriculum_catalog_wired_sqlite_and_in_memory(tmp_path: Path) -> None:
    """ProductState exposes a versioned curriculum catalog in BOTH modes."""
    from mathtutor.infrastructure.migrate import upgrade_db

    db_file = tmp_path / "math_tutor.db"
    upgrade_db(db_file)  # the app factory runs this; the test must too
    reset_product_state()
    state = get_product_state(db_file)

    version = await state.curriculum.create_version("v-mt-1", "初中代数 2026")
    node = await state.curriculum.add_node(
        version.version_id,
        code="LINEAR_EQUATION",
        kind="skill",
        title="一元一次方程",
        stage="middle",
        grade=7,
    )
    await state.curriculum.publish_version(version.version_id)
    graph = await state.curriculum.load_graph(version.version_id)
    assert len(graph.nodes) == 1
    assert graph.nodes[0].node_id == node.node_id
    # Published versions are immutable: writes are refused.
    with pytest.raises(Exception):
        await state.curriculum.add_node(
            version.version_id,
            code="QUADRATIC_EQUATION",
            kind="skill",
            title="一元二次方程",
        )

    reset_product_state()
    memory_state = get_product_state()
    assert memory_state.outbox_relay is None  # relay is SQLite-only
    version2 = await memory_state.curriculum.create_version("v-mt-2", "内存版课程")
    await memory_state.curriculum.publish_version(version2.version_id)
    assert len((await memory_state.curriculum.load_graph(version2.version_id)).nodes) == 0

    reset_product_state()
