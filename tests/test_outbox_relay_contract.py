"""Deterministic shutdown and bounded candidate fairness; no wall-clock backoff."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from mathtutor.application.outbox_relay import OutboxRelayService
from mathtutor.infrastructure import create_db_engine
from mathtutor.infrastructure.schema import domain_outbox, metadata, outbox_dispatch_ledger
from mathtutor.repositories.uow import MathTutorUow
from recording_dispatch_sink import RecordingSink

pytestmark = pytest.mark.asyncio
NOW = "2026-10-29T00:00:00+00:00"


@pytest_asyncio.fixture
async def uow(tmp_path):
    engine = create_db_engine(tmp_path / "contract.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield MathTutorUow(engine)
    await engine.dispose()


class Clock:
    value = NOW

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value = (datetime.fromisoformat(self.value) + timedelta(seconds=seconds)).isoformat()


async def seed(uow, count, *, start=0, gated=False, succeeded=False, created_at=NOW):
    rows = [dict(outbox_id=f"row-{i:06d}", aggregate_type="test", aggregate_id=f"event-{i}",
        aggregate_version=1, event_sequence=1, event_type="practice_offer_issued", audience="student",
        payload={"offer_id":f"synthetic-{i}"}, created_at=created_at) for i in range(start, start + count)]
    async with uow.transaction() as conn:
        await conn.execute(domain_outbox.insert(), rows)
        if gated or succeeded:
            await conn.execute(outbox_dispatch_ledger.insert(), [dict(
                outbox_id=r["outbox_id"], aggregate_type=r["aggregate_type"], aggregate_id=r["aggregate_id"],
                aggregate_version=1, event_sequence=1, event_type=r["event_type"], sink_id="prior",
                dispatched_at=NOW, attempts=1, last_error="retry later" if gated else None) for r in rows])


async def ledger(uow):
    async with uow.transaction() as conn:
        return (await conn.execute(select(outbox_dispatch_ledger).order_by(outbox_dispatch_ledger.c.outbox_id))).all()


class ObservedRelay(OutboxRelayService):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.idle = asyncio.Queue()
        self.batches = []

    async def process_batch(self, *args, **kwargs):
        result = await super().process_batch(*args, **kwargs)
        self.batches.append(result)
        return result

    async def _idle_wait(self):
        self.idle.put_nowait(self._wake_event.is_set())
        await super()._idle_wait()


@pytest.mark.parametrize("prefix", [400, 1250])
async def test_gated_prefix_larger_than_scan_budget_cannot_hide_healthy_tail(uow, prefix):
    await seed(uow, prefix, gated=True)
    await seed(uow, 1, start=prefix)
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, now_provider=Clock())
    rounds = (prefix + 1 + 399) // 400
    for _ in range(rounds):
        result = await relay.process_batch(limit=100)
        assert result["pending"] <= 400
    assert [e["outbox_id"] for e in sink.dispatched] == [f"row-{prefix:06d}"]
    rows = await ledger(uow)
    assert len(rows) == prefix + 1
    assert all(r.attempts == 1 for r in rows)
    assert sum(r.last_error is not None for r in rows) == prefix


async def test_sweep_watermark_revisits_due_retries_despite_continuous_new_events(uow):
    await seed(uow, 5, gated=True)
    await seed(uow, 6, start=5)
    clock = Clock()
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, now_provider=clock, max_scan_pages=2)
    assert (await relay.process_batch(limit=2))["skipped"] == 4
    clock.advance(10)
    # Each round appends more fresh work than it can dispatch. Without the
    # fixed sweep tail, the cursor could chase this stream forever.
    for round_no in range(6):
        await seed(uow, 3, start=100 + round_no * 3, created_at=clock())
        assert (await relay.process_batch(limit=2))["pending"] <= 4
        if any(e["outbox_id"] == "row-000000" for e in sink.dispatched):
            break
    else:
        pytest.fail("new arrivals starved an old due retry")
    assert next(r for r in await ledger(uow) if r.outbox_id == "row-000000").attempts == 2
    assert not any(int(e["outbox_id"].split("-")[1]) >= 100 for e in sink.dispatched)


async def test_restart_reconstructs_cursor_and_preserves_prior_receipts(uow):
    await seed(uow, 9, gated=True)
    await seed(uow, 2, start=9)
    await seed(uow, 1, start=11, succeeded=True)
    clock = Clock()
    relay = OutboxRelayService(uow, RecordingSink(), now_provider=clock, max_scan_pages=2)
    assert (await relay.process_batch(limit=2))["pending"] == 4
    sink = RecordingSink()
    restarted = OutboxRelayService(uow, sink, now_provider=clock, max_scan_pages=2)
    for _ in range(4):
        await restarted.process_batch(limit=2)
    assert {e["outbox_id"] for e in sink.dispatched} == {"row-000009", "row-000010"}
    clock.advance(10)
    for _ in range(10):
        await restarted.process_batch(limit=2)
    assert await restarted.pending_count() == 0
    rows = await ledger(uow)
    assert len(rows) == 12 and len({r.outbox_id for r in rows}) == 12
    assert next(r for r in rows if r.outbox_id == "row-000011").attempts == 1
    assert len(sink.dispatched) == 11


async def test_gated_batches_wait_for_external_wake_with_product_uow_notifications(uow):
    await seed(uow, 9, gated=True)
    relay = ObservedRelay(uow, RecordingSink(), now_provider=Clock(), batch_size=2,
        max_scan_pages=2, idle_seconds=30)
    uow.on_commit = relay.wake  # the real product wiring, including read commits
    relay.start()
    try:
        assert await asyncio.wait_for(relay.idle.get(), 1) is False
        assert relay.batches == [{"pending":4,"dispatched":0,"failed":0,"skipped":4}]
        await asyncio.sleep(0)
        assert relay.idle.empty()
        relay.wake()
        assert await asyncio.wait_for(relay.idle.get(), 1) is False
        assert len(relay.batches) == 2
        assert relay.batches[1]["skipped"] == 4
    finally:
        await relay.stop()
    assert all(r.attempts == 1 for r in await ledger(uow))


async def test_idle_stop_does_not_fetch_new_pending_work_and_restart_resumes(uow):
    sink = RecordingSink()
    relay = ObservedRelay(uow, sink, idle_seconds=30)
    relay.start()
    await asyncio.wait_for(relay.idle.get(), 1)
    await seed(uow, 3)
    await relay.stop()
    await relay.stop()  # idempotent
    assert sink.dispatched == [] and await ledger(uow) == []
    assert await relay.pending_count() == 3
    restarted = ObservedRelay(uow, sink, idle_seconds=30)
    restarted.start()
    await asyncio.wait_for(restarted.idle.get(), 1)  # after committed receipts
    await restarted.stop()
    assert len(sink.dispatched) == len(await ledger(uow)) == 3


async def test_stop_finishes_only_current_batch_not_the_whole_queue(uow):
    class GateSink(RecordingSink):
        def __init__(self):
            super().__init__()
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def dispatch(self, event):
            self.entered.set()
            await self.release.wait()
            await super().dispatch(event)

    await seed(uow, 3)
    sink = GateSink()
    relay = OutboxRelayService(uow, sink, batch_size=2)
    relay.start()
    await asyncio.wait_for(sink.entered.wait(), 1)
    stopping = asyncio.create_task(relay.stop())
    await relay._stop_event.wait()
    sink.release.set()
    await asyncio.wait_for(stopping, 1)
    assert len(sink.dispatched) == len(await ledger(uow)) == 2
    assert await relay.pending_count() == 1
    restarted = ObservedRelay(uow, sink, idle_seconds=30)
    restarted.start()
    await asyncio.wait_for(restarted.idle.get(), 1)
    await restarted.stop()
    rows = await ledger(uow)
    assert len(sink.dispatched) == len(rows) == 3
    assert all(r.attempts == 1 for r in rows)


async def test_timeout_cancels_cooperative_sink_and_leaves_work_for_restart(uow):
    class BlockedSink:
        def __init__(self):
            self.entered, self.cancelled = asyncio.Event(), asyncio.Event()

        async def dispatch(self, event):
            self.entered.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise

    await seed(uow, 1)
    sink = BlockedSink()
    relay = OutboxRelayService(uow, sink)
    relay.start()
    await asyncio.wait_for(sink.entered.wait(), 1)
    await asyncio.wait_for(relay.stop(timeout=0), 1)
    assert sink.cancelled.is_set() and not relay.is_running
    assert await ledger(uow) == [] and await relay.pending_count() == 1
    restarted = ObservedRelay(uow, RecordingSink(), idle_seconds=30)
    restarted.start()
    await asyncio.wait_for(restarted.idle.get(), 1)
    await restarted.stop()
    assert len(await ledger(uow)) == 1 and await restarted.pending_count() == 0


async def test_cancel_after_delivery_before_receipt_is_at_least_once_with_unique_ledger(uow):
    class IdempotentSink:
        def __init__(self):
            self.calls = 0
            self.effects = {}

        async def dispatch(self, event):
            self.calls += 1
            self.effects.setdefault(event["outbox_id"], dict(event))

    class ReceiptGateRelay(OutboxRelayService):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.receipt_written = asyncio.Event()

        async def _record_dispatch(self, *args, **kwargs):
            await super()._record_dispatch(*args, **kwargs)
            self.receipt_written.set()
            await asyncio.Event().wait()  # transaction has not committed

    await seed(uow, 1)
    sink = IdempotentSink()
    relay = ReceiptGateRelay(uow, sink)
    relay.start()
    await asyncio.wait_for(relay.receipt_written.wait(), 1)
    await asyncio.wait_for(relay.stop(timeout=0), 1)
    assert sink.calls == 1 and len(sink.effects) == 1
    assert await ledger(uow) == []
    restarted = ObservedRelay(uow, sink, idle_seconds=30)
    restarted.start()
    await asyncio.wait_for(restarted.idle.get(), 1)
    await restarted.stop()
    assert sink.calls == 2 and len(sink.effects) == 1
    rows = await ledger(uow)
    assert len(rows) == 1 and rows[0].attempts == 1 and rows[0].last_error is None
