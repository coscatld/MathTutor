"""Outbox relay — the transactional-outbox consumer (Phase 6, spec §11.4).

The outbox (``domain_outbox``) is written INSIDE the same transaction as
the domain commit (attempt/evidence/state/release/offer). The relay reads
COMMITTED rows and hands each to a :class:`DispatchSink`.

Guarantees:

- Only committed rows are ever dispatched — the relay never reads a row
  the originating transaction rolled back (the outbox row simply does not
  exist).
- Idempotent: every dispatch is recorded in ``outbox_dispatch_ledger`` in
  a short transaction after dispatch; the ledger's unique key
  ``(aggregate_type, aggregate_id, aggregate_version, event_sequence)``
  (mirroring the outbox's own key) makes a replayed event impossible to
  acquire duplicate ledger records. A crash after delivery can redeliver;
  consumers must be idempotent, and restart uses the durable ledger watermark.
- Failure isolation: a failing sink records ``attempts``/``last_error`` in
  the ledger and does NOT block subsequent events; failed events are
  retried by a later batch (their ledger row still has ``last_error``).
- The relay NEVER deletes or modifies ``domain_outbox`` rows and never
  touches any domain state.

Phase 6 second round — resident runtime:

- :meth:`OutboxRelayService.start` / :meth:`OutboxRelayService.stop` /
  :meth:`OutboxRelayService.wake` run the relay as a resident asyncio
  loop (spec 5.1): drain → idle-wait (event + bounded poll) → wake on new
  events → graceful bounded shutdown. All loop state is per-process; a
  fresh service instance on the same DB is naturally safe (ledger
  idempotency).
- Bounded exponential backoff (spec 5.3) is DERIVED from existing ledger
  columns — no schema change: next eligible retry =
  ``dispatched_at + min(RETRY_MAX_SECONDS, RETRY_BASE_SECONDS * 2**attempts)``.
  A row whose retry window has not opened is skipped this batch and
  re-examined later. After ``max_attempts`` failed attempts the row is
  permanently parked (``last_error`` prefixed with ``attempt limit
  exceeded``) and never selected again — a poison event can neither
  tight-loop nor block later events.
- Offline desktop semantics (spec 5.6): the sink is the local
  :class:`LoggingDispatchSink` (or a future local event projection) —
  loopback-only, no external broker assumptions, no new dependencies.

Logging discipline: :class:`LoggingDispatchSink` logs a per-event-type
WHITELISTED summary (never the raw payload — no attestation/answer/reasoning
bytes may reach logs; see the Phase 6 observability rules).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol

from sqlalchemy import and_, or_, select

from mathtutor.infrastructure.schema import (
    domain_outbox,
    outbox_dispatch_ledger,
)

logger = logging.getLogger(__name__)

#: Per-event-type payload summary whitelist. Event types not listed here are
#: logged with NO payload keys at all. Never add sensitive fields
#: (attestation hashes, answers, reasoning, full documents) to this list.
_PAYLOAD_SUMMARY_WHITELIST: dict[str, tuple[str, ...]] = {
    "exercise_release_issued": ("exercise_id", "status", "source_type"),
    "practice_offer_issued": ("offer_id", "parent_cycle_id", "expires_at"),
    "practice_offer_accepted": ("child_cycle_id",),
    "attempt_assessed": ("correctness",),
    "cycle_state_committed": ("from_state", "to_state", "trigger_command"),
    "transition_committed": ("from_state", "to_state", "trigger_command"),
    "tutor_action_committed": ("from_state", "to_state", "cycle_state"),
}

#: Maximum recorded error length (a sink error is data, not a trace dump).
_MAX_ERROR_LEN = 200

# ------------------------------------------------- retry backoff constants
# All injectable per-service-instance (constructor args) for deterministic
# tests; these are the production defaults.

#: Backoff base: the first retry of a failed event waits
#: ``BASE * 2**attempts`` seconds from its last ``dispatched_at``
#: (attempts=1 → 10s, attempts=2 → 20s, ...).
RETRY_BASE_SECONDS: float = 5.0
#: Backoff ceiling (300s = 5min).
RETRY_MAX_SECONDS: float = 300.0
#: After this many failed attempts the event is parked permanently
#: (last_error = "attempt limit exceeded: ...") and never selected again.
MAX_ATTEMPTS: int = 20

#: Default resident-loop batch size.
DEFAULT_BATCH_SIZE: int = 100
#: Default idle poll interval (seconds) when the queue is drained.
DEFAULT_IDLE_SECONDS: float = 1.0
#: Candidate SELECT window = batch limit × this factor, so that rows whose
#: backoff has not opened yet can never starve younger eligible rows at the
#: tail of the queue (the time gate is applied per row in Python).
_CANDIDATE_WINDOW_FACTOR = 4


class DispatchSink(Protocol):
    """Consumer of one outbox event. Implementations must be idempotent-safe
    (the relay guarantees at-least-once delivery)."""

    async def dispatch(self, event: dict[str, Any]) -> None: ...


class LoggingDispatchSink:
    """Whitelisted-summary sink: logs event_type + aggregate keys only.

    ``payload`` is summarized through :data:`_PAYLOAD_SUMMARY_WHITELIST` —
    unknown event types contribute ZERO payload keys. Only a dispatch count
    is retained; event payloads are released after the call. Tests that need
    event history must explicitly inject a recording sink.

    This is the offline-desktop loopback sink: local logging now, local
    event projection later. There is NO external broker anywhere in the
    delivery path.
    """

    def __init__(self) -> None:
        self.dispatched_count = 0

    def summarize(self, event: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key in (
            "event_type",
            "aggregate_type",
            "aggregate_id",
            "aggregate_version",
            "event_sequence",
            "audience",
        ):
            if key in event:
                summary[key] = event[key]
        payload = event.get("payload")
        allowed = _PAYLOAD_SUMMARY_WHITELIST.get(event.get("event_type", ""), ())
        if isinstance(payload, dict) and allowed:
            summary["payload_summary"] = {
                key: payload[key] for key in allowed if key in payload
            }
        return summary

    async def dispatch(self, event: dict[str, Any]) -> None:
        summary = self.summarize(event)
        logger.info("outbox dispatch: %s", json.dumps(summary, ensure_ascii=False))
        self.dispatched_count += 1


class OutboxRelayService:
    """Relay over the product UoW: read committed outbox → sink → ledger.

    Short transactions read candidates and record individual receipts.
    Dispatch runs outside database transactions, allowing sinks to commit
    projections without holding SQLite's writer lock across external work.
    A crash after delivery can cause at-least-once redelivery, not loss.

    Resident mode (spec 5.1): :meth:`start` spawns the drain loop;
    :meth:`wake` accelerates a drain after new events were appended;
    :meth:`stop` performs a bounded graceful shutdown (current batch
    finishes; force-cancel after the timeout — an app can never hang on
    shutdown). All loop state lives in this instance; restarting with a
    NEW instance on the same DB is idempotent via the ledger.
    """

    def __init__(
        self,
        uow: Any,
        sink: DispatchSink | None = None,
        *,
        sink_id: str = "default",
        batch_size: int = DEFAULT_BATCH_SIZE,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        now_provider: Callable[[], str] | None = None,
        base_backoff: float = RETRY_BASE_SECONDS,
        max_backoff: float = RETRY_MAX_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> None:
        self.uow = uow
        self.sink = sink or LoggingDispatchSink()
        self.sink_id = sink_id
        self.batch_size = batch_size
        self.idle_seconds = idle_seconds
        #: Injectable clock (ISO UTC string) for deterministic backoff tests.
        self.now_provider: Callable[[], str] = now_provider or _now
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self.max_attempts = max_attempts
        # 循环状态（进程内；新实例天然安全）。
        self._task: asyncio.Task[Any] | None = None
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()

    # ------------------------------------------------------- resident loop

    @property
    def task(self) -> asyncio.Task[Any] | None:
        """The resident loop task (None when not started/stopped)."""
        return self._task

    @property
    def is_running(self) -> bool:
        task = self._task
        return task is not None and not task.done()

    def start(self) -> None:
        """Idempotently start the resident drain loop (spec 5.1).

        Must be called inside a running event loop. Calling twice never
        spawns a second loop. After a :meth:`stop`, ``start`` may be called
        again (the stop flag is cleared).
        """
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self.run_loop(), name="outbox-relay-loop")

    def wake(self) -> None:
        """Best-effort wake of an idle loop (call after appending outbox
        events to drain them promptly).

        Losing a wake is harmless: the loop polls at most every
        ``idle_seconds`` — the wake is an accelerator, polling is the
        correctness floor.
        """
        self._wake_event.set()

    async def stop(self, timeout: float = 5.0) -> None:
        """Graceful bounded shutdown (spec 5.1).

        Sets the stop flag, wakes the loop, then waits up to ``timeout``
        for the CURRENT batch (one short transaction) to finish. On timeout
        the task is force-cancelled; ``CancelledError`` is swallowed so an
        app shutdown can never hang ("app 关不掉" cannot happen). Idempotent.
        """
        self._stop_event.set()
        self.wake()
        task = self._task
        if task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(
                "outbox relay loop did not stop within %.1fs; force-cancelling",
                timeout,
            )
            task.cancel()
            await self._await_cancelled(task)
        except asyncio.CancelledError:
            # stop() 自身被取消（应用强制关停）：确保循环任务不泄漏后继续传播。
            task.cancel()
            await self._await_cancelled(task)
            raise
        except Exception:  # noqa: BLE001 - a crashed loop must never block shutdown
            logger.exception("outbox relay loop exited with an error")
            raise
        self._task = None

    @staticmethod
    async def _await_cancelled(task: asyncio.Task[Any]) -> None:
        _, pending = await asyncio.wait({task}, timeout=5.0)
        if pending:
            raise RuntimeError("Owned background task did not finish cancellation")
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - teardown must not raise
            logger.exception("outbox relay loop raised during force-cancel")
            raise

    async def run_loop(self) -> None:
        """Resident drain loop (spec 5.1). Spawned by :meth:`start`; may
        also be awaited directly in tests.

        - productive batches (dispatched+failed > 0) continue immediately;
        - drained OR fully time-gated batches (all skipped) idle-wait on
          :meth:`wake` with a bounded poll — backoff-parked rows therefore
          cannot cause a tight loop or 100% CPU;
        - one batch exception does not kill the loop: it is logged and the
          loop retries after the idle wait (no crash tight-loop);
        - ``CancelledError`` is cleaned up and RE-RAISED — cancellation is
          never swallowed into a stuck state.
        """
        logger.info(
            "outbox relay loop started (batch_size=%d, idle=%.1fs)",
            self.batch_size,
            self.idle_seconds,
        )
        try:
            while not self._stop_event.is_set():
                result: dict[str, int] | None = None
                try:
                    result = await self.process_batch(limit=self.batch_size)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - resident loop survives batch errors
                    logger.exception(
                        "outbox relay batch failed; retrying after idle wait"
                    )
                if (
                    result is not None
                    and result["dispatched"] + result["failed"] > 0
                ):
                    await asyncio.sleep(0)  # 还有工作：立即下一批（让出事件循环）
                    continue
                await self._idle_wait()
        except asyncio.CancelledError:
            logger.info("outbox relay loop cancelled")
            raise
        finally:
            logger.info("outbox relay loop stopped")

    async def _idle_wait(self) -> None:
        """Idle wait: ``wake()`` returns immediately; otherwise poll after
        ``idle_seconds``."""
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=self.idle_seconds)
        except asyncio.TimeoutError:
            pass
        self._wake_event.clear()

    # ------------------------------------------------------- batch + retry

    async def process_batch(
        self,
        limit: int = DEFAULT_BATCH_SIZE,
        *,
        now_provider: Callable[[], str] | None = None,
    ) -> dict[str, int]:
        """Dispatch up to ``limit`` eligible events; returns counts.

        Eligible = outbox rows with NO ledger row (immediately eligible),
        or whose ledger row still has ``last_error`` AND whose derived
        retry window has opened
        (``now >= dispatched_at + min(max_backoff, base_backoff * 2**attempts)``;
        spec 5.3). Rows whose window has not opened are SKIPPED this batch
        (counted in ``skipped``) and re-examined later. Rows with
        ``attempts >= max_attempts`` are parked permanently (never selected).

        ``now_provider`` overrides the instance clock for this call
        (returns an ISO UTC string). ``pending`` counts the candidate rows
        examined this batch (dispatched + failed + skipped); the queue-lag
        metric remains :meth:`pending_count` (all not-yet-succeeded rows).
        """
        now = self._resolve_now(now_provider)
        now_dt = _parse_iso_utc(now)
        if now_dt is None:
            raise ValueError(f"now_provider 返回了不可解析的时间戳: {now!r}")
        dispatched = 0
        failed = 0
        skipped = 0
        async with self.uow.transaction() as conn:
            rows = (
                await conn.execute(
                    self._candidate_select().limit(limit * _CANDIDATE_WINDOW_FACTOR)
                )
            ).all()
        # Dispatch outside the read transaction: consumers may write projections.
        # At-least-once delivery requires each sink to be idempotent.
        for row in rows:
            if dispatched + failed >= limit:
                break
            if not self._row_eligible(row, now_dt):
                skipped += 1
                continue
            event = {
                "outbox_id": row.outbox_id,
                "aggregate_type": row.aggregate_type,
                "aggregate_id": row.aggregate_id,
                "aggregate_version": row.aggregate_version,
                "event_sequence": row.event_sequence,
                "event_type": row.event_type,
                "audience": row.audience,
                "payload": row.payload,
                "created_at": row.created_at,
            }
            error: str | None = None
            try:
                await self.sink.dispatch(event)
                dispatched += 1
            except Exception as exc:  # noqa: BLE001 - isolate failing consumers
                failed += 1
                error = str(exc)[:_MAX_ERROR_LEN]
                if self._next_attempts(row.ledger_attempts) >= self.max_attempts:
                    error = f"attempt limit exceeded: {error}"
            async with self.uow.transaction() as conn:
                await self._record_dispatch(conn, event, dispatched_at=now, error=error)
        return {
            "pending": dispatched + failed + skipped,
            "dispatched": dispatched,
            "failed": failed,
            "skipped": skipped,
        }

    def _candidate_select(self) -> Any:
        """Candidate rows: no ledger row, or a failed row below the attempt
        cap. Rows parked at ``attempts >= max_attempts`` are excluded
        forever. The time gate itself is applied per row in Python (it
        needs the injectable clock)."""
        return (
            select(
                domain_outbox.c.outbox_id,
                domain_outbox.c.aggregate_type,
                domain_outbox.c.aggregate_id,
                domain_outbox.c.aggregate_version,
                domain_outbox.c.event_sequence,
                domain_outbox.c.event_type,
                domain_outbox.c.audience,
                domain_outbox.c.payload,
                domain_outbox.c.created_at,
                outbox_dispatch_ledger.c.attempts.label("ledger_attempts"),
                outbox_dispatch_ledger.c.last_error.label("ledger_last_error"),
                outbox_dispatch_ledger.c.dispatched_at.label("ledger_dispatched_at"),
            )
            .outerjoin(
                outbox_dispatch_ledger,
                outbox_dispatch_ledger.c.outbox_id == domain_outbox.c.outbox_id,
            )
            .where(
                or_(
                    outbox_dispatch_ledger.c.outbox_id.is_(None),
                    and_(
                        outbox_dispatch_ledger.c.last_error.is_not(None),
                        outbox_dispatch_ledger.c.attempts < self.max_attempts,
                    ),
                )
            )
            .order_by(domain_outbox.c.created_at, domain_outbox.c.outbox_id)
        )

    def _row_eligible(self, row: Any, now_dt: datetime) -> bool:
        """Time-gate one candidate row against the injected clock.

        - no ledger row → immediately eligible;
        - already succeeded (last_error NULL) → never re-picked (defensive;
          the SQL filter already excludes it);
        - attempts >= max_attempts → parked forever (defensive);
        - unparseable ``dispatched_at`` → FAIL-OPEN (eligible now): the
          at-least-once contract tolerates redelivery, a stalled event does
          not.
        """
        if row.ledger_attempts is None:
            return True
        if row.ledger_last_error is None:
            return False
        if row.ledger_attempts >= self.max_attempts:
            return False
        last_dt = _parse_iso_utc(row.ledger_dispatched_at)
        if last_dt is None:
            return True
        delay = _retry_delay_seconds(
            row.ledger_attempts, self.base_backoff, self.max_backoff
        )
        return now_dt >= last_dt + timedelta(seconds=delay)

    @staticmethod
    def _next_attempts(ledger_attempts: Any) -> int:
        return int(ledger_attempts or 0) + 1

    async def pending_count(self) -> int:
        """Total not-yet-succeeded events — the outbox-lag metric.

        Includes failed events awaiting their backoff window AND events
        parked at the attempt cap (they will never be dispatched again but
        still occupy the outbox). For "how many would the next batch
        actually attempt", use :meth:`eligible_count`.
        """
        async with self.uow.transaction() as conn:
            row = (
                await conn.execute(
                    select(domain_outbox.c.outbox_id)
                    .outerjoin(
                        outbox_dispatch_ledger,
                        outbox_dispatch_ledger.c.outbox_id == domain_outbox.c.outbox_id,
                    )
                    .where(
                        or_(
                            outbox_dispatch_ledger.c.outbox_id.is_(None),
                            outbox_dispatch_ledger.c.last_error.is_not(None),
                        )
                    )
                )
            ).all()
            return len(row)

    async def eligible_count(self, now: str | None = None) -> int:
        """How many events the next batch would ACTUALLY attempt right now:
        fresh events plus failed events whose derived backoff window has
        opened (attempt-cap-parked rows excluded).

        Contrast with :meth:`pending_count` (lag metric: everything not yet
        succeeded). ``now`` overrides the instance clock (ISO UTC string).
        """
        now_dt = _parse_iso_utc(now if now is not None else self._resolve_now())
        if now_dt is None:
            raise ValueError(f"now 不可解析: {now!r}")
        async with self.uow.transaction() as conn:
            rows = (await conn.execute(self._candidate_select())).all()
        return sum(1 for row in rows if self._row_eligible(row, now_dt))

    def _resolve_now(
        self, now_provider: Callable[[], str] | None = None
    ) -> str:
        provider = self.now_provider if now_provider is None else now_provider
        return provider()

    async def _record_dispatch(
        self,
        conn: Any,
        event: dict[str, Any],
        *,
        dispatched_at: str,
        error: str | None,
    ) -> None:
        """Insert-or-increment the ledger row in the SAME transaction."""
        existing = (
            await conn.execute(
                select(
                    outbox_dispatch_ledger.c.attempts,
                    outbox_dispatch_ledger.c.sink_id,
                ).where(outbox_dispatch_ledger.c.outbox_id == event["outbox_id"])
            )
        ).first()
        values = {
            "sink_id": self.sink_id,
            "dispatched_at": dispatched_at,
            "last_error": error,
        }
        if existing is None:
            await conn.execute(
                outbox_dispatch_ledger.insert().values(
                    outbox_id=event["outbox_id"],
                    aggregate_type=event["aggregate_type"],
                    aggregate_id=event["aggregate_id"],
                    aggregate_version=event["aggregate_version"],
                    event_sequence=event["event_sequence"],
                    event_type=event["event_type"],
                    attempts=1,
                    **values,
                )
            )
        else:
            await conn.execute(
                outbox_dispatch_ledger.update()
                .where(outbox_dispatch_ledger.c.outbox_id == event["outbox_id"])
                .values(attempts=existing.attempts + 1, **values)
            )


def _retry_delay_seconds(attempts: int, base: float, max_delay: float) -> float:
    """Derived backoff (spec 5.3): ``min(max_delay, base * 2**attempts)``.

    ``attempts`` is the CURRENT stored attempt count (the first failure
    stores attempts=1, so the first retry waits ``base * 2**1``). Derived
    from the existing ``dispatched_at`` + ``attempts`` ledger columns —
    NO new column, NO migration, restart-safe by construction.
    """
    return min(max_delay, base * (2 ** attempts))


def _parse_iso_utc(value: str) -> datetime | None:
    """Parse an ISO timestamp; naive values are treated as UTC. Returns
    None when unparseable (callers decide fail-open vs fail-loud)."""
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "DispatchSink",
    "LoggingDispatchSink",
    "OutboxRelayService",
    "RETRY_BASE_SECONDS",
    "RETRY_MAX_SECONDS",
    "MAX_ATTEMPTS",
    "DEFAULT_BATCH_SIZE",
    "DEFAULT_IDLE_SECONDS",
]
