"""Unit of Work for the MathTutor SQLite database (Phase 1, §11.2/§11.3).

The UoW is a SHORT transaction scope — READ → COMPUTE → COMMIT, never a
transaction spanning LLM/verifier/solver work (SQLite has a single writer).

Every education commit writes attempt + assessment + evidence + state +
action + transition + outbox events in ONE transaction: all-or-nothing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Callable

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


class MathTutorUow:
    """Short-transaction scope over the product database."""

    def __init__(
        self,
        engine: AsyncEngine,
        *,
        on_commit: Callable[[], None] | None = None,
    ) -> None:
        self.engine = engine
        #: Best-effort callback after a CLEAN commit (e.g. the resident
        #: outbox relay's ``wake``). Never called on rollback. Optional and
        #: sync — losing the notification must be harmless by contract.
        self.on_commit = on_commit

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """One short read/write transaction; commits on clean exit, rolls
        back on any exception (including unverified content paths)."""
        async with self.engine.connect() as conn:
            async with conn.begin():
                yield conn
        if self.on_commit is not None:
            self.on_commit()


async def append_outbox_events(
    conn: AsyncConnection,
    events: list[dict[str, Any]],
) -> None:
    """Insert domain events into the outbox INSIDE the caller's transaction.

    ``events``: dicts with aggregate_type / aggregate_id / aggregate_version /
    event_sequence / event_type / audience / payload. Uniqueness of
    (aggregate_type, aggregate_id, aggregate_version, event_sequence) makes
    replay-after-crash idempotent (relay de-duplicates).
    """
    from mathtutor.infrastructure.schema import domain_outbox
    from uuid import uuid4
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    for event in events:
        await conn.execute(
            domain_outbox.insert().values(
                outbox_id=str(uuid4()),
                aggregate_type=event["aggregate_type"],
                aggregate_id=event["aggregate_id"],
                aggregate_version=event["aggregate_version"],
                event_sequence=event["event_sequence"],
                event_type=event["event_type"],
                audience=event.get("audience", "student"),
                payload=event["payload"],
                created_at=now,
            )
        )


__all__ = ["MathTutorUow", "append_outbox_events"]
