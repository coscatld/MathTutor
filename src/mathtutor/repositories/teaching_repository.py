"""Durable, owner-scoped teaching context and rendered-content receipts.

No transaction spans model inference. Callers can commit progress alongside
the assessment by passing its connection. Delivery never means comprehension.
"""
from copy import deepcopy
from datetime import datetime, timezone
from contextlib import asynccontextmanager
import anyio

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert


class TeachingRepository:
    def __init__(self, engine=None):
        self.engine = engine
        self.contexts = {}
        self.deliveries = {}

    @asynccontextmanager
    async def connection(self, conn=None):
        if conn is not None:
            yield conn
        elif self.engine is not None:
            transaction = self.engine.begin()
            opened = await transaction.__aenter__()
            try:
                yield opened
            except BaseException as original:
                # ASGI disconnect uses level cancellation: every unshielded
                # await can be cancelled again, including rollback/close.
                from mathtutor.infrastructure.lifecycle_trace import trace
                trace(id(self.engine), "transaction_cancel_or_error", error=original)
                try:
                    with anyio.fail_after(5, shield=True):
                        await transaction.__aexit__(type(original), original, original.__traceback__)
                except BaseException as cleanup_error:
                    trace(id(self.engine), "transaction_cleanup_failed", error=cleanup_error)
                    raise original from cleanup_error
                raise
            else:
                with anyio.fail_after(5, shield=True):
                    await transaction.__aexit__(None, None, None)
        else:
            yield None

    async def load(self, student_id, cycle_id, *, conn=None):
        if self.engine is None:
            return deepcopy(self.contexts.get((student_id, str(cycle_id))))
        from mathtutor.infrastructure.schema import teaching_contexts as table
        async with self.connection(conn) as db:
            row = (await db.execute(select(table.c.payload).where(
                table.c.student_id == student_id, table.c.cycle_id == str(cycle_id)))).first()
        return deepcopy(row.payload) if row else None

    async def save(self, student_id, cycle_id, payload, *, conn=None):
        if self.engine is None:
            self.contexts[(student_id, str(cycle_id))] = deepcopy(payload)
            return
        from mathtutor.infrastructure.schema import teaching_contexts as table
        async with self.connection(conn) as db:
            stmt = insert(table).values(student_id=student_id, cycle_id=str(cycle_id),
                                        payload=payload, updated_at=datetime.now(timezone.utc).isoformat())
            await db.execute(stmt.on_conflict_do_update(index_elements=[table.c.student_id, table.c.cycle_id],
                                                        set_={"payload": payload, "updated_at": stmt.excluded.updated_at}))

    async def delivery(self, student_id, cycle_id, delivery_id, payload, *, status="committed", conn=None):
        if self.engine is None:
            self.deliveries.setdefault((student_id, delivery_id), {**payload, "cycle_id": str(cycle_id), "status": status})
            return
        from mathtutor.infrastructure.schema import teaching_deliveries as table
        async with self.connection(conn) as db:
            await db.execute(insert(table).values(student_id=student_id, cycle_id=str(cycle_id), delivery_id=delivery_id,
                status=status, payload=payload, updated_at=datetime.now(timezone.utc).isoformat()).on_conflict_do_nothing())

    async def mark_delivery(self, student_id, delivery_id, status, *, conn=None):
        if status not in {"possibly_exposed", "presented"}:
            raise ValueError("invalid delivery status")
        if self.engine is None:
            row = self.deliveries.get((student_id, delivery_id))
            if row and row["status"] != "presented":
                row["status"] = status
            return deepcopy(row)
        from mathtutor.infrastructure.schema import teaching_deliveries as table
        async with self.connection(conn) as db:
            row = (await db.execute(select(table).where(table.c.student_id == student_id,
                                                       table.c.delivery_id == delivery_id))).mappings().first()
            if not row:
                return None
            if row["status"] != "presented":
                await db.execute(table.update().where(table.c.student_id == student_id,
                    table.c.delivery_id == delivery_id).values(status=status, updated_at=datetime.now(timezone.utc).isoformat()))
            return {**row["payload"], "cycle_id": row["cycle_id"], "status": status}

    async def for_cycle(self, student_id, cycle_id):
        if self.engine is None:
            return [deepcopy(row) for (owner, _), row in self.deliveries.items()
                    if owner == student_id and row["cycle_id"] == str(cycle_id)]
        from mathtutor.infrastructure.schema import teaching_deliveries as table
        async with self.engine.connect() as db:
            rows = (await db.execute(select(table).where(table.c.student_id == student_id,
                table.c.cycle_id == str(cycle_id)).order_by(table.c.updated_at))).mappings().all()
        return [{**row["payload"], "status": row["status"]} for row in rows]
