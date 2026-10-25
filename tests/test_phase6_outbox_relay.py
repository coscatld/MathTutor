"""Phase 6 — outbox relay tests (spec §11.4 + 第二轮 spec 5.3).

Covers: only committed outbox rows are dispatched (ledger written in the
same transaction, domain_outbox never modified), idempotency + restart
resume (a new instance on the same db never re-dispatches; the ledger's
aggregate 4-tuple unique key is DB-enforced), and failure isolation
(attempts increment, last_error recorded, one bad sink never blocks the
rest of the batch).

Second round (spec 5.3): bounded exponential backoff DERIVED from the
existing ledger columns (dispatched_at + attempts — no new column):
next eligible retry = dispatched_at + min(MAX, BASE * 2**attempts). The
gate is deterministic via an injected clock; a poison event is parked at
the attempt cap ("attempt limit exceeded") and never selected again.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from recording_dispatch_sink import RecordingSink

from mathtutor.application.outbox_relay import (
    LoggingDispatchSink,
    OutboxRelayService,
)
from mathtutor.infrastructure.schema import (
    domain_outbox,
    outbox_dispatch_ledger,
)
from mathtutor.repositories.uow import MathTutorUow, append_outbox_events

pytestmark = pytest.mark.asyncio


async def test_production_logging_sink_does_not_retain_event_payloads(monkeypatch):
    """A long-lived production sink retains only its scalar counter."""
    import gc
    import weakref

    from mathtutor.application import outbox_relay

    # Test log capture is itself a recorder; bypass it for this volume probe.
    monkeypatch.setattr(outbox_relay.logger, "info", lambda *args: None)
    sink = LoggingDispatchSink()

    class Payload(dict):
        pass

    payload = Payload(answer="private student answer", reasoning="private reasoning")
    reference = weakref.ref(payload)
    event = _event(payload=payload)
    for _ in range(100_000):
        await sink.dispatch(event)
    del payload, event
    gc.collect()

    assert sink.dispatched_count == 100_000
    assert vars(sink) == {"dispatched_count": 100_000}
    assert reference() is None


async def test_production_logging_sink_emits_only_whitelisted_summary(caplog):
    import logging

    sink = LoggingDispatchSink()
    event = _event(payload={
        "offer_id": "o-safe",
        "answer": "secret-answer",
        "reasoning": "secret-reasoning",
        "attestation_hash": "secret-attestation",
    })
    with caplog.at_level(logging.INFO, logger="mathtutor.application.outbox_relay"):
        await sink.dispatch(event)
        await sink.dispatch(_event(event_type="unknown", payload={"offer_id": "unknown-secret"}))
    assert "o-safe" in caplog.text
    assert "secret" not in caplog.text
    assert sink.dispatched_count == 2


@pytest_asyncio.fixture()
async def db(tmp_path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "relay.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _FakeClock:
    """Injectable clock: ``now_provider=lambda: clock.value``."""

    def __init__(self, start: str) -> None:
        self.value = start

    def __call__(self) -> str:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = _add_seconds(self.value, seconds)


def _add_seconds(iso: str, seconds: float) -> str:
    return (datetime.fromisoformat(iso) + timedelta(seconds=seconds)).isoformat()


async def _insert_events(uow: MathTutorUow, events: list[dict]) -> None:
    async with uow.transaction() as conn:
        await append_outbox_events(conn, events)


async def _outbox_rows(db) -> list[dict]:
    async with db.connect() as conn:
        rows = (
            await conn.execute(
                select(domain_outbox).order_by(domain_outbox.c.outbox_id)
            )
        ).all()
    return [dict(row._mapping) for row in rows]


def _event(**overrides) -> dict:
    base = {
        "aggregate_type": "practice_offer",
        "aggregate_id": "p-x",
        "aggregate_version": 1,
        "event_sequence": 1,
        "event_type": "practice_offer_issued",
        "audience": "student",
        "payload": {"offer_id": "o-x", "parent_cycle_id": "c-x"},
    }
    base.update(overrides)
    return base


async def test_dispatches_committed_rows_ledger_same_tx_outbox_untouched(db):
    uow = MathTutorUow(db)
    events = [
        {
            "aggregate_type": "exercise_release",
            "aggregate_id": "r-1",
            "aggregate_version": 1,
            "event_sequence": 1,
            "event_type": "exercise_release_issued",
            "audience": "internal",
            "payload": {"exercise_id": "e-1", "status": "released", "source_type": "BANK"},
        },
        {
            "aggregate_type": "attempt",
            "aggregate_id": "a-1",
            "aggregate_version": 1,
            "event_sequence": 1,
            "event_type": "attempt_assessed",
            "audience": "student",
            "payload": {"correctness": "correct"},
        },
    ]
    await _insert_events(uow, events)
    before = await _outbox_rows(db)

    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, sink_id="sink-1")
    result = await relay.process_batch(limit=10)
    assert result == {"pending": 2, "dispatched": 2, "failed": 0, "skipped": 0}
    # 批次内顺序按 outbox_id 决胜（同 created_at），只断言集合。
    assert sorted(e["event_type"] for e in sink.dispatched) == [
        "attempt_assessed",
        "exercise_release_issued",
    ]

    # Ledger rows are written in the SAME transaction as the batch commit.
    async with uow.transaction() as conn:
        ledger = (
            await conn.execute(
                select(outbox_dispatch_ledger).order_by(outbox_dispatch_ledger.c.outbox_id)
            )
        ).all()
    assert len(ledger) == 2
    assert all(
        row.attempts == 1 and row.sink_id == "sink-1" and row.last_error is None
        for row in ledger
    )
    # domain_outbox rows are never modified by the relay.
    assert await _outbox_rows(db) == before
    # The sink's summary is a whitelisted projection, never the raw payload.
    summary = sink.summarize(events[0])
    assert summary["payload_summary"] == {
        "exercise_id": "e-1",
        "status": "released",
        "source_type": "BANK",
    }


async def test_idempotent_replay_restart_resume_and_ledger_constraint(db):
    uow = MathTutorUow(db)
    await _insert_events(
        uow,
        [
            {
                "aggregate_type": "practice_offer",
                "aggregate_id": "p-1",
                "aggregate_version": 1,
                "event_sequence": 1,
                "event_type": "practice_offer_issued",
                "audience": "student",
                "payload": {"offer_id": "o-1", "parent_cycle_id": "c-1"},
            }
        ],
    )
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, sink_id="sink-a")
    await relay.process_batch()
    assert len(sink.dispatched) == 1
    # Replaying the same batch must not re-dispatch.
    await relay.process_batch()
    assert len(sink.dispatched) == 1

    # A NEW instance on the same db resumes from the ledger watermark.
    sink2 = RecordingSink()
    relay2 = OutboxRelayService(uow, sink2, sink_id="sink-b")
    result2 = await relay2.process_batch()
    assert result2 == {"pending": 0, "dispatched": 0, "failed": 0, "skipped": 0}
    assert len(sink2.dispatched) == 0

    # The ledger's aggregate 4-tuple unique key is enforced by the DB: a
    # replayed event with a DIFFERENT outbox_id cannot be ledgered twice.
    async with uow.transaction() as conn:
        await conn.execute(
            domain_outbox.insert().values(
                outbox_id="outbox-replay-2",
                aggregate_type="practice_offer",
                aggregate_id="p-1",
                aggregate_version=1,
                event_sequence=2,
                event_type="practice_offer_issued",
                audience="student",
                payload={"offer_id": "o-1"},
                created_at=_now(),
            )
        )
    with pytest.raises(Exception, match="UNIQUE"):
        async with uow.transaction() as conn:
            await conn.execute(
                outbox_dispatch_ledger.insert().values(
                    outbox_id="outbox-replay-2",
                    aggregate_type="practice_offer",
                    aggregate_id="p-1",
                    aggregate_version=1,
                    event_sequence=1,  # same 4-tuple as the already-dispatched event
                    event_type="practice_offer_issued",
                    sink_id="sink-x",
                    dispatched_at=_now(),
                    attempts=1,
                    last_error=None,
                )
            )


class _FlakySink(RecordingSink):
    """Fails the first ``fail_count`` dispatch calls, then behaves normally."""

    def __init__(self, fail_count: int) -> None:
        super().__init__()
        self._remaining_failures = fail_count

    async def dispatch(self, event: dict) -> None:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise RuntimeError("sink temporarily down")
        await super().dispatch(event)


async def test_failure_records_attempts_retries_and_does_not_block(db):
    """失败事件记录 attempts/last_error 且不阻断批次；重试受派生 backoff
    时间门约束（注入时钟确定性推进；spec 5.3）。"""
    uow = MathTutorUow(db)
    clock = _FakeClock("2026-08-20T00:00:00+00:00")
    await _insert_events(
        uow,
        [
            {
                "aggregate_type": "attempt",
                "aggregate_id": "a-1",
                "aggregate_version": 1,
                "event_sequence": 1,
                "event_type": "attempt_assessed",
                "audience": "student",
                "payload": {"correctness": "incorrect"},
            },
            {
                "aggregate_type": "practice_offer",
                "aggregate_id": "p-2",
                "aggregate_version": 1,
                "event_sequence": 1,
                "event_type": "practice_offer_issued",
                "audience": "student",
                "payload": {"offer_id": "o-2", "parent_cycle_id": "c-2"},
            },
        ],
    )
    sink = _FlakySink(fail_count=1)  # 第一个事件失败，第二个成功
    relay = OutboxRelayService(uow, sink, sink_id="sink-f", now_provider=clock)
    result = await relay.process_batch()
    assert result["failed"] == 1
    assert result["dispatched"] == 1
    assert result["skipped"] == 0

    async with uow.transaction() as conn:
        rows = (
            await conn.execute(
                select(outbox_dispatch_ledger).order_by(outbox_dispatch_ledger.c.outbox_id)
            )
        ).all()
    failed_rows = [row for row in rows if row.last_error is not None]
    ok_rows = [row for row in rows if row.last_error is None]
    assert len(failed_rows) == 1 and len(ok_rows) == 1
    assert failed_rows[0].attempts == 1
    assert "sink temporarily down" in failed_rows[0].last_error
    failed_event_type = failed_rows[0].event_type

    # 时间门：attempts=1 → 下一次重试窗口 = dispatched_at + BASE*2^1 = +10s。
    # 未到窗口 → 跳过（计入 skipped），事件不被重试。
    clock.advance(9.0)
    gated = await relay.process_batch()
    assert gated == {"pending": 1, "dispatched": 0, "failed": 0, "skipped": 1}

    # 窗口打开 → 重试成功，attempts 递增，last_error 清空。
    clock.advance(1.0)
    result2 = await relay.process_batch()
    assert result2 == {"pending": 1, "dispatched": 1, "failed": 0, "skipped": 0}
    async with uow.transaction() as conn:
        row = (
            await conn.execute(
                select(outbox_dispatch_ledger).where(
                    outbox_dispatch_ledger.c.event_type == failed_event_type
                )
            )
        ).first()
    assert row.attempts == 2
    assert row.last_error is None
    assert len(sink.dispatched) == 2
    # 第三次无待派发。
    assert (await relay.process_batch())["pending"] == 0


class _AlwaysFailSink(RecordingSink):
    """Poison sink: every dispatch raises."""

    async def dispatch(self, event: dict) -> None:
        raise RuntimeError("poison sink")


class _PoisonSink(RecordingSink):
    """只对指定 aggregate_id 抛错（poison），其余正常投递。"""

    def __init__(self, poison_id: str) -> None:
        super().__init__()
        self._poison_id = poison_id

    async def dispatch(self, event: dict) -> None:
        if event["aggregate_id"] == self._poison_id:
            raise RuntimeError("poison sink")
        await super().dispatch(event)


async def test_poison_event_backoff_parks_at_attempt_limit_and_never_blocks(db):
    """Poison 事件：backoff 递增重试 → 达到 max_attempts 后记
    "attempt limit exceeded" 并永久停用；同批正常事件照常投递。"""
    uow = MathTutorUow(db)
    clock = _FakeClock("2026-08-20T00:00:00+00:00")
    poison = _event(
        aggregate_type="attempt", aggregate_id="poison-1", event_type="attempt_assessed",
        payload={"correctness": "incorrect"},
    )
    normal = _event(aggregate_type="practice_offer", aggregate_id="p-ok")
    await _insert_events(uow, [poison, normal])

    sink = _PoisonSink("poison-1")  # 只有 poison 失败，正常事件照常投递
    relay = OutboxRelayService(
        uow, sink, sink_id="sink-p", now_provider=clock, max_attempts=3
    )

    # 第一批：poison 失败（attempts=1），正常事件照常 dispatch。
    result = await relay.process_batch()
    assert result["failed"] == 1
    assert result["dispatched"] == 1
    assert sorted(e["aggregate_id"] for e in sink.dispatched) == ["p-ok"]

    async def _ledger_poison():
        async with uow.transaction() as conn:
            return (
                await conn.execute(
                    select(outbox_dispatch_ledger).where(
                        outbox_dispatch_ledger.c.aggregate_id == "poison-1"
                    )
                )
            ).first()

    row = await _ledger_poison()
    assert row.attempts == 1
    assert row.last_error == "poison sink"

    # 第二次：窗口 = +BASE*2^1 = +10s。
    clock.advance(10.0)
    result = await relay.process_batch()
    assert result == {"pending": 1, "dispatched": 0, "failed": 1, "skipped": 0}
    row = await _ledger_poison()
    assert row.attempts == 2
    assert row.last_error == "poison sink"

    # 第三次：窗口 = +BASE*2^2 = +20s；失败后 attempts=3 达到封顶 → 停用。
    clock.advance(20.0)
    result = await relay.process_batch()
    assert result["failed"] == 1
    row = await _ledger_poison()
    assert row.attempts == 3
    assert row.last_error.startswith("attempt limit exceeded: poison sink")

    # 任意长时间之后也不再选择：不会 tight loop、不阻塞、attempts 不再增长。
    clock.advance(3600.0)
    result = await relay.process_batch()
    assert result == {"pending": 0, "dispatched": 0, "failed": 0, "skipped": 0}
    row = await _ledger_poison()
    assert row.attempts == 3

    # lag 指标仍计入停用事件；真正可投递数为 0。
    assert await relay.pending_count() == 1
    assert await relay.eligible_count() == 0


async def test_eligible_count_vs_pending_count_semantics(db):
    """pending_count = lag 指标（总未成功数）；eligible_count = 下一批真正
    会尝试的数量（backoff 未到 + attempt 封顶的不计入）。"""
    uow = MathTutorUow(db)
    clock = _FakeClock("2026-08-20T00:00:00+00:00")
    await _insert_events(uow, [_event(aggregate_id="f-1")])
    relay = OutboxRelayService(
        uow, _AlwaysFailSink(), sink_id="sink-e", now_provider=clock
    )
    await relay.process_batch()  # 失败 → attempts=1，backoff +10s
    assert await relay.pending_count() == 1
    assert await relay.eligible_count() == 0  # backoff 未到

    clock.advance(10.0)
    assert await relay.eligible_count() == 1  # 窗口打开

    await _insert_events(uow, [_event(aggregate_id="f-2")])
    assert await relay.pending_count() == 2
    assert await relay.eligible_count() == 2  # 新事件立即 eligible


async def test_unparseable_dispatched_at_fails_open(db):
    """ledger 时间戳不可解析时 FAIL-OPEN（立即重试）：at-least-once 语义
    容忍重复投递，绝不让事件卡死。"""
    uow = MathTutorUow(db)
    clock = _FakeClock("2026-08-20T00:00:00+00:00")
    await _insert_events(uow, [_event(aggregate_id="u-1")])
    relay = OutboxRelayService(
        uow, _AlwaysFailSink(), sink_id="sink-u", now_provider=clock
    )
    await relay.process_batch()
    async with uow.transaction() as conn:
        await conn.execute(
            outbox_dispatch_ledger.update().values(dispatched_at="garbage-not-iso")
        )
    # 时钟未推进，但时间戳不可解析 → fail-open，立即再试一次。
    result = await relay.process_batch()
    assert result["failed"] == 1


async def test_invalid_now_provider_raises(db):
    """now_provider 契约是 ISO UTC 串；坏了要 fail-loud，绝不静默误判。"""
    uow = MathTutorUow(db)
    await _insert_events(uow, [_event(aggregate_id="n-1")])
    relay = OutboxRelayService(uow, RecordingSink())
    with pytest.raises(ValueError):
        await relay.process_batch(now_provider=lambda: "not-a-time")
