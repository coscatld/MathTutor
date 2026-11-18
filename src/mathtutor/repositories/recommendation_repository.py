from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.infrastructure.recommendation_schema import recommendations as table
from mathtutor.learning.knowledge_tracing.schema import learning_events

DAILY_CALL_LIMIT = 2
LEASE_SECONDS = 45
CACHE_SECONDS = 6 * 60 * 60


def budget_exhausted(row, now):
    day = datetime.fromtimestamp(now, UTC).date().isoformat()
    return row["budget_day"] == day and row["budget_calls"] >= DAILY_CALL_LIMIT


def defaults(owner):
    return dict(student_id=str(owner), generation=0, enabled=0, goal="math_foundations", cache_key="",
                payload={}, updated_at=0, expires_at=0, status="idle", lease_token="", lease_key="", lease_until=0,
                budget_day="", budget_calls=0)


async def clear_recommendations(conn, owner):
    """Use inside educational-data deletion, before old background jobs can commit."""
    await conn.execute(insert(table).values(**defaults(owner)).on_conflict_do_update(
        index_elements=["student_id"], set_={"generation": table.c.generation + 1, "enabled": 0,
            "goal": "math_foundations", "cache_key": "", "payload": {}, "updated_at": 0,
            "expires_at": 0, "status": "idle", "lease_token": "", "lease_key": "", "lease_until": 0}))


async def invalidate_recommendations(conn, owner):
    await conn.execute(table.update().where(table.c.student_id == str(owner)).values(
        generation=table.c.generation + 1, cache_key="", payload={}, updated_at=0,
        expires_at=0, status="idle", lease_token="", lease_key="", lease_until=0))


class RecommendationRepository:
    def __init__(self, engine):
        self.engine = engine

    async def get(self, owner, *, conn=None):
        if conn is None:
            async with self.engine.connect() as db:
                return await self.get(owner, conn=db)
        row = (await conn.execute(select(table).where(table.c.student_id == str(owner)))).mappings().one_or_none()
        return dict(row) if row else defaults(owner)

    async def configure(self, owner, *, enabled, goal):
        async with self.engine.begin() as conn:
            await conn.execute(insert(table).values(**defaults(owner)).on_conflict_do_nothing())
            row = await self.get(owner, conn=conn)
            if bool(row["enabled"]) != enabled or row["goal"] != goal:
                await conn.execute(table.update().where(table.c.student_id == str(owner)).values(
                    enabled=int(enabled), goal=goal, generation=table.c.generation + 1,
                    cache_key="", payload={}, updated_at=0, expires_at=0,
                    status="idle", lease_token="", lease_key="", lease_until=0))
            return await self.get(owner, conn=conn)

    async def select_goal(self, owner, *, goal, generation):
        """A chat plan may change its goal, never a newer setting or consent flag."""
        async with self.engine.begin() as conn:
            await conn.execute(insert(table).values(**defaults(owner)).on_conflict_do_nothing())
            await conn.execute(table.update().where(table.c.student_id == str(owner),
                table.c.generation == generation, table.c.goal != goal).values(
                    goal=goal, generation=table.c.generation + 1, cache_key="", payload={}, updated_at=0,
                    expires_at=0, status="idle", lease_token="", lease_key="", lease_until=0))
            return await self.get(owner, conn=conn)

    async def reserve(self, owner, *, generation, cache_key, now):
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        async with self.engine.begin() as conn:
            # Acquire SQLite's writer lock before inspecting the daily counter.
            await conn.execute(table.update().where(table.c.student_id == str(owner)).values(
                budget_calls=table.c.budget_calls))
            row = await self.get(owner, conn=conn)
            if (not row["enabled"] or row["generation"] != generation
                    or row["lease_until"] > now and row["lease_key"] == cache_key
                    or row["cache_key"] == cache_key and row["expires_at"] > now):
                return None
            calls = row["budget_calls"] if row["budget_day"] == day else 0
            if calls >= DAILY_CALL_LIMIT:
                await conn.execute(table.update().where(table.c.student_id == str(owner)).values(
                    status="rate_limited", lease_token="", lease_key="", lease_until=0))
                return None
            token = str(uuid4())
            await conn.execute(table.update().where(table.c.student_id == str(owner)).values(
                lease_token=token, lease_key=cache_key, lease_until=now + LEASE_SECONDS, status="running",
                budget_day=day, budget_calls=calls + 1))
            return token

    async def mark_limited(self, owner, *, generation, cache_key, now):
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        async with self.engine.begin() as conn:
            await conn.execute(table.update().where(table.c.student_id == str(owner),
                table.c.generation == generation, table.c.enabled == 1,
                table.c.budget_day == day, table.c.budget_calls >= DAILY_CALL_LIMIT,
                or_(table.c.cache_key != cache_key, table.c.expires_at <= now),
                or_(table.c.lease_key != cache_key, table.c.lease_until <= now)
            ).values(status="rate_limited", lease_token="", lease_key="", lease_until=0))

    async def finish(self, owner, *, token, generation, cache_key, payload, expected_stamp, now):
        async with self.engine.begin() as conn:
            await conn.execute(table.update().where(table.c.student_id == str(owner)).values(
                budget_calls=table.c.budget_calls))
            stamp = (await conn.execute(select(func.count(), func.coalesce(func.max(learning_events.c.event_seq), 0))
                .select_from(learning_events).where(learning_events.c.student_id == str(owner)))).one()
            where = (table.c.student_id == str(owner), table.c.generation == generation,
                     table.c.lease_token == token, table.c.enabled == 1)
            if tuple(stamp) != tuple(expected_stamp):
                await conn.execute(table.update().where(*where).values(lease_token="", lease_key="", lease_until=0, status="idle"))
                return False
            result = await conn.execute(table.update().where(*where).values(
                cache_key=cache_key, payload=payload, updated_at=now, expires_at=now + CACHE_SECONDS,
                status="cached", lease_token="", lease_key="", lease_until=0))
            return result.rowcount == 1

    async def fail(self, owner, token, status="failed"):
        async with self.engine.begin() as conn:
            await conn.execute(table.update().where(table.c.student_id == str(owner), table.c.lease_token == token)
                .values(status=status, lease_token="", lease_key="", lease_until=0))

    async def delete(self, owner):
        async with self.engine.begin() as conn:
            await clear_recommendations(conn, owner)
