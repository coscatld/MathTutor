from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.infrastructure.exploration_schema import generations, inquiries

MAX_INQUIRIES = 50
MAX_PAYLOAD_BYTES = 300_000


class ExplorationConflict(ValueError):
    pass


class ExplorationRepository:
    def __init__(self, engine):
        self.engine = engine

    @staticmethod
    def _where(owner, inquiry_id):
        return inquiries.c.student_id == str(owner), inquiries.c.inquiry_id == inquiry_id

    async def generation(self, owner, *, conn=None) -> int:
        if conn is None:
            async with self.engine.connect() as connection:
                return await self.generation(owner, conn=connection)
        value = (await conn.execute(select(generations.c.generation).where(
            generations.c.student_id == str(owner)))).scalar_one_or_none()
        return value or 0

    async def list(self, owner) -> dict:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(select(inquiries).where(inquiries.c.student_id == str(owner))
                .order_by(inquiries.c.updated_at.desc()).limit(MAX_INQUIRIES))).mappings().all()
            return {"generation": await self.generation(owner, conn=conn), "items": [
                {"inquiry_id": row["inquiry_id"], "question": row["payload"]["question"],
                 "goal": row["payload"]["goal"], "revision": row["revision"], "updated_at": row["updated_at"]}
                for row in rows]}

    async def get(self, owner, inquiry_id, *, conn=None):
        if conn is None:
            async with self.engine.connect() as connection:
                return await self.get(owner, inquiry_id, conn=connection)
        row = (await conn.execute(select(inquiries).where(*self._where(owner, inquiry_id)))).mappings().one_or_none()
        return dict(row) if row else None

    async def can_create(self, owner, expected_generation):
        async with self.engine.connect() as conn:
            if await self.generation(owner, conn=conn) != expected_generation:
                raise ExplorationConflict("探索记录已发生变化，请刷新后再继续。")
            count = (await conn.execute(select(func.count()).select_from(inquiries)
                .where(inquiries.c.student_id == str(owner)))).scalar_one()
            if count >= MAX_INQUIRIES:
                raise ExplorationConflict("已保存 50 个探索问题，请先删除不再需要的记录。")

    async def save(self, owner, inquiry_id, payload, *, expected_revision, expected_generation=None):
        if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_PAYLOAD_BYTES:
            raise ExplorationConflict("本次探索内容超过保存上限，请缩小问题范围。")
        now = datetime.now(UTC).isoformat()
        async with self.engine.begin() as conn:
            if expected_revision == 0:
                if await self.generation(owner, conn=conn) != expected_generation:
                    raise ExplorationConflict("探索记录已发生变化，请刷新后再继续。")
                count = (await conn.execute(select(func.count()).select_from(inquiries)
                    .where(inquiries.c.student_id == str(owner)))).scalar_one()
                if count >= MAX_INQUIRIES:
                    raise ExplorationConflict("已保存 50 个探索问题，请先删除不再需要的记录。")
                statement = insert(inquiries).values(student_id=str(owner), inquiry_id=inquiry_id,
                    payload=payload, revision=1, updated_at=now).on_conflict_do_nothing()
            else:
                statement = inquiries.update().where(*self._where(owner, inquiry_id),
                    inquiries.c.revision == expected_revision).values(payload=payload,
                    revision=expected_revision + 1, updated_at=now)
            await asyncio.sleep(0)
            result = await conn.execute(statement)
            if result.rowcount != 1:
                raise ExplorationConflict("此问题已有更新，请重新打开后继续。")
            await asyncio.sleep(0)
        return {"inquiry_id": inquiry_id, "revision": expected_revision + 1, "payload": payload, "updated_at": now}

    async def delete(self, owner, inquiry_id):
        async with self.engine.begin() as conn:
            await conn.execute(inquiries.delete().where(*self._where(owner, inquiry_id)))
            await bump_generation(conn, owner)


async def bump_generation(conn, owner):
    await conn.execute(insert(generations).values(student_id=str(owner), generation=1)
        .on_conflict_do_update(index_elements=["student_id"], set_={"generation": generations.c.generation + 1}))
