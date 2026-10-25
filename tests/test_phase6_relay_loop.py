"""Phase 6 second round — resident relay loop tests (spec 5.1 / 5.5 / 5.6).

Covers the loop lifecycle: start idempotency, wake + bounded idle polling,
graceful bounded shutdown (an app can never hang on stop), cancellation as
the crash proxy (rollback → no duplicate ledger rows, no duplicate public
effect after restart on the same DB), poison events never tight-looping
the resident loop, injected-clock backoff inside the loop, and loop
survival over transient DB errors.

Offline desktop semantics (spec 5.6): the sink is the local loopback
RecordingSink — no external broker is assumed anywhere in these
tests and none is added by the implementation.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from recording_dispatch_sink import RecordingSink

from mathtutor.application.outbox_relay import (
    OutboxRelayService,
)
from mathtutor.infrastructure.schema import outbox_dispatch_ledger
from mathtutor.repositories.uow import MathTutorUow, append_outbox_events

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture()
async def db(tmp_path):
    from mathtutor.infrastructure import create_db_engine
    from mathtutor.infrastructure.schema import metadata

    engine = create_db_engine(tmp_path / "relay.db")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield engine
    await engine.dispose()


class _FakeClock:
    """Injectable clock (ISO UTC): frozen until advanced."""

    def __init__(self, start: str) -> None:
        self.value = start

    def __call__(self) -> str:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value = (
            datetime.fromisoformat(self.value) + timedelta(seconds=seconds)
        ).isoformat()


def _event(aggregate_id: str, event_type: str = "practice_offer_issued") -> dict:
    return {
        "aggregate_type": "practice_offer",
        "aggregate_id": aggregate_id,
        "aggregate_version": 1,
        "event_sequence": 1,
        "event_type": event_type,
        "audience": "student",
        "payload": {"offer_id": f"o-{aggregate_id}", "parent_cycle_id": "c-1"},
    }


async def _insert_events(uow: MathTutorUow, events: list[dict]) -> None:
    async with uow.transaction() as conn:
        await append_outbox_events(conn, events)


async def _wait_until(predicate, timeout: float = 2.0) -> None:
    """Poll a predicate until true; raises asyncio.TimeoutError otherwise.

    ``predicate`` may return a plain value or a coroutine (async helper).
    """
    async with asyncio.timeout(timeout):
        while True:
            result = predicate()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                return
            await asyncio.sleep(0.01)


async def _ledger_count(uow: MathTutorUow) -> int:
    return len(await _ledger_rows(uow))


async def _ledger_count_eq(uow: MathTutorUow, expected: int) -> bool:
    """async predicate for _wait_until（await 不能出现在 lambda 里）。"""
    return await _ledger_count(uow) == expected


async def _ledger_rows(uow: MathTutorUow) -> list:
    async with uow.transaction() as conn:
        return (
            await conn.execute(
                select(outbox_dispatch_ledger).order_by(
                    outbox_dispatch_ledger.c.outbox_id
                )
            )
        ).all()


async def test_start_idempotent_loop_dispatches_committed_events(db):
    uow = MathTutorUow(db)
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, idle_seconds=0.02)
    relay.start()
    first_task = relay.task
    relay.start()  # 幂等：重复 start 不双跑
    assert relay.task is first_task
    assert relay.is_running

    await _insert_events(uow, [_event("e-1")])
    await _wait_until(lambda: len(sink.dispatched) == 1)
    await _wait_until(lambda: _ledger_count_eq(uow, 1))

    task = relay.task
    await relay.stop(timeout=2.0)
    assert not relay.is_running
    assert task is not None and task.done()
    # 只投递一次：无重复 public effect。
    assert [e["aggregate_id"] for e in sink.dispatched] == ["e-1"]
    assert len(await _ledger_rows(uow)) == 1


async def test_uncommitted_events_never_delivered(db):
    """回滚事务里的 outbox 行根本不存在 → 常驻 relay 永远看不到。"""
    uow = MathTutorUow(db)
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, idle_seconds=0.02)
    relay.start()
    try:
        async with uow.transaction() as conn:
            await append_outbox_events(conn, [_event("rolled-back")])
            raise RuntimeError("rollback proxy")  # 事务回滚，outbox 行消失
    except RuntimeError:
        pass
    await asyncio.sleep(0.1)  # 数个 idle 轮询周期
    assert sink.dispatched == []
    assert await relay.pending_count() == 0

    # 已提交的事件照常投递。
    await _insert_events(uow, [_event("committed")])
    await _wait_until(lambda: len(sink.dispatched) == 1)
    assert sink.dispatched[0]["aggregate_id"] == "committed"
    await relay.stop()


async def test_wake_drains_quickly_with_long_idle(db):
    """wake() 是加速器：idle=30s 也立即排空（轮询只是兜底）。"""
    uow = MathTutorUow(db)
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, idle_seconds=30.0)
    relay.start()
    await _insert_events(uow, [_event("w-1")])
    relay.wake()
    await _wait_until(lambda: len(sink.dispatched) == 1, timeout=1.0)
    await relay.stop()


async def test_idle_poll_picks_up_events_without_wake(db):
    """唤醒丢失也正确：最多 idle_seconds 后必然轮询。"""
    uow = MathTutorUow(db)
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, idle_seconds=0.05)
    relay.start()
    await _insert_events(uow, [_event("p-1")])  # 不调用 wake()
    await _wait_until(lambda: len(sink.dispatched) == 1, timeout=2.0)
    await relay.stop()


async def test_stop_graceful_drain_and_idempotent(db):
    """stop() 有界优雅关停：当前批次完成即退出；重复调用无害。"""
    uow = MathTutorUow(db)
    sink = RecordingSink()
    relay = OutboxRelayService(uow, sink, idle_seconds=0.02)
    relay.start()
    await _insert_events(
        uow, [_event(f"g-{i}", f"cycle_state_committed") for i in range(3)]
    )
    await _wait_until(lambda: len(sink.dispatched) == 3)
    await relay.stop(timeout=2.0)
    assert not relay.is_running
    assert len(await _ledger_rows(uow)) == 3
    await relay.stop()  # 幂等：已停止时立即返回


async def test_stop_force_cancels_blocked_sink_no_hang(db):
    """sink 永久阻塞时 stop() 强取消——"app 关不掉"不会发生。"""

    class _BlockingSink:
        def __init__(self) -> None:
            self.entered = asyncio.Event()

        async def dispatch(self, event: dict) -> None:
            self.entered.set()
            await asyncio.Event().wait()  # 永久阻塞

    uow = MathTutorUow(db)
    sink = _BlockingSink()
    relay = OutboxRelayService(uow, sink, idle_seconds=0.02)
    relay.start()
    await _insert_events(uow, [_event("b-1")])
    await sink.entered.wait()
    started = time.monotonic()
    await relay.stop(timeout=0.05)
    elapsed = time.monotonic() - started
    assert elapsed < 1.0, "stop() 必须强取消，绝不挂死"
    assert not relay.is_running


async def test_crash_cancel_mid_dispatch_then_restart_no_duplicate_effect(db):
    """asyncio 取消 = 崩溃代理（spec 5.5）：dispatch 进行中（ledger 提交前）
    崩溃 → 事务回滚 → 新实例同 DB 重启 → 无重复 ledger 行、无重复 public
    effect（只有 COMPLETE 的 dispatch 才构成 public effect）。"""

    class _GateSink:
        """进入即置位；只有放行后完成的 dispatch 才计入 public effect。"""

        def __init__(self) -> None:
            self.entered = asyncio.Event()
            self.completed: list[dict] = []
            self._gate = asyncio.Event()

        async def dispatch(self, event: dict) -> None:
            self.entered.set()
            await self._gate.wait()
            self.completed.append(dict(event))

    uow = MathTutorUow(db)
    gate = _GateSink()
    relay1 = OutboxRelayService(uow, gate, idle_seconds=0.02)
    relay1.start()
    await _insert_events(uow, [_event("crash-1")])
    await gate.entered.wait()  # dispatch 进行中，尚未完成

    task = relay1.task
    assert task is not None
    task.cancel()  # 崩溃代理：dispatch 中 + ledger 提交前
    with pytest.raises(asyncio.CancelledError):
        await task

    # 事务回滚：没有 ledger 行；被取消的 dispatch 不算 public effect。
    assert len(await _ledger_rows(uow)) == 0
    assert gate.completed == []

    # 新实例同 DB 重启：恰好投递一次。
    sink2 = RecordingSink()
    relay2 = OutboxRelayService(uow, sink2, sink_id="sink-r")
    result = await relay2.process_batch()
    assert result["dispatched"] == 1
    assert [e["aggregate_id"] for e in sink2.dispatched] == ["crash-1"]
    assert len(await _ledger_rows(uow)) == 1  # 无重复 ledger 行


async def test_crash_cancel_while_idle_then_restart_continues(db):
    """空闲时崩溃 → 重启继续排空，事件不丢不重。"""
    uow = MathTutorUow(db)
    sink1 = RecordingSink()
    relay1 = OutboxRelayService(uow, sink1, idle_seconds=0.02)
    relay1.start()
    await asyncio.sleep(0.05)  # 进入空闲等待
    task = relay1.task
    assert task is not None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sink1.dispatched == []

    await _insert_events(uow, [_event("after-crash")])
    sink2 = RecordingSink()
    relay2 = OutboxRelayService(uow, sink2, idle_seconds=0.02)
    relay2.start()
    await _wait_until(lambda: len(sink2.dispatched) == 1)
    assert sink2.dispatched[0]["aggregate_id"] == "after-crash"
    await relay2.stop()
    assert len(await _ledger_rows(uow)) == 1


class _SelectiveFailSink(RecordingSink):
    """只对指定 aggregate_id 抛错；计数所有调用。"""

    def __init__(self, poison_id: str) -> None:
        super().__init__()
        self._poison_id = poison_id
        self.calls = 0

    async def dispatch(self, event: dict) -> None:
        self.calls += 1
        if event["aggregate_id"] == self._poison_id:
            raise RuntimeError("poison")
        await super().dispatch(event)


async def test_poison_never_tight_loops_and_does_not_block_loop(db):
    """常驻循环中的 poison 事件：封顶停用后不再尝试（无 tight loop、无
    100% CPU），后续正常事件照常投递。"""
    uow = MathTutorUow(db)
    sink = _SelectiveFailSink("poison-1")
    relay = OutboxRelayService(
        uow, sink, idle_seconds=0.02, max_attempts=1
    )
    await _insert_events(uow, [_event("poison-1"), _event("ok-1")])
    relay.start()
    await _wait_until(lambda: len(sink.dispatched) == 1)
    await asyncio.sleep(0.15)  # 多个 idle 周期：poison 已停用，不再尝试
    assert sink.calls == 2  # poison 恰尝试 1 次 + 正常事件 1 次
    assert relay.is_running  # 循环健康，未被 poison 杀死
    await relay.stop()

    rows = await _ledger_rows(uow)
    by_id = {row.aggregate_id: row for row in rows}
    assert by_id["poison-1"].attempts == 1
    assert by_id["poison-1"].last_error.startswith("attempt limit exceeded")
    assert by_id["ok-1"].last_error is None


async def test_loop_backoff_uses_injected_clock(db):
    """循环内重试同样受派生 backoff 门约束：时钟冻结时不重试，推进到
    窗口后（>= BASE 之后）才发生第二次投递。"""

    class _FailOnceSink(RecordingSink):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        async def dispatch(self, event: dict) -> None:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("first attempt fails")
            await super().dispatch(event)

    uow = MathTutorUow(db)
    clock = _FakeClock("2026-08-20T00:00:00+00:00")
    sink = _FailOnceSink()
    relay = OutboxRelayService(
        uow, sink, idle_seconds=0.02, now_provider=clock
    )
    await _insert_events(uow, [_event("bk-1")])
    relay.start()
    await _wait_until(lambda: sink.calls == 1)  # 第一次失败
    await asyncio.sleep(0.1)  # 时钟冻结：多个真实 idle 周期也不重试
    assert sink.calls == 1
    assert sink.dispatched == []

    clock.advance(10.0)  # attempts=1 → 窗口 = BASE*2^1 = 10s
    await _wait_until(lambda: len(sink.dispatched) == 1, timeout=2.0)
    assert sink.calls == 2
    await relay.stop()


async def test_loop_survives_transient_db_error(db):
    """单批 DB 异常不杀循环：记录日志后按空闲节奏重试并恢复投递。"""

    class _FlakyUow:
        def __init__(self, uow: MathTutorUow, failures: int = 1) -> None:
            self._uow = uow
            self._remaining = failures

        def transaction(self):
            if self._remaining > 0:
                self._remaining -= 1

                @asynccontextmanager
                async def _boom():
                    raise RuntimeError("db temporarily unavailable")
                    yield  # pragma: no cover

                return _boom()
            return self._uow.transaction()

    uow = MathTutorUow(db)
    sink = RecordingSink()
    relay = OutboxRelayService(_FlakyUow(uow), sink, idle_seconds=0.02)
    await _insert_events(uow, [_event("t-1")])
    relay.start()
    await _wait_until(lambda: len(sink.dispatched) == 1, timeout=2.0)
    assert relay.is_running
    await relay.stop()
    assert len(await _ledger_rows(uow)) == 1
