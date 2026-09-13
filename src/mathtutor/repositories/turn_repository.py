"""Request journal: claim before effects, replay approved frames, never rerun.

Conversation locks serialize sockets in the single product process. SQLite's
unique owner/conversation/request key also protects claims across restarts.
An abandoned RUNNING request is returned as interrupted, not re-executed:
its assessment may already have committed. Resuming unfinished orchestration
requires an explicit checkpoint, not a blind retry.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import select

from mathtutor.infrastructure.schema import turn_requests
from mathtutor.repositories.uow import MathTutorUow


class TurnRequestRepository:
    def __init__(self, engine=None):
        self.uow = MathTutorUow(engine) if engine is not None else None
        self._rows = {}
        self._locks = {}
        self._owners = {}

    @asynccontextmanager
    async def owner(self, student_id):
        """Serialize learning writes and deletion across this owner's tabs."""
        key = str(student_id)
        entry = self._owners.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with entry[0]:
                yield
        finally:
            entry[1] -= 1
            if not entry[1]:
                self._owners.pop(key, None)

    def is_processing(self, student_id, conversation_id):
        entry = self._locks.get((student_id, conversation_id))
        return bool(entry and entry[0].locked())

    @asynccontextmanager
    async def conversation(self, student_id: str, conversation_id: str):
        key = (student_id, conversation_id)
        entry = self._locks.setdefault(key, [asyncio.Lock(), 0])
        entry[1] += 1
        try:
            async with self.owner(student_id), entry[0]:
                yield
        finally:
            entry[1] -= 1
            if not entry[1]:
                self._locks.pop(key, None)

    @staticmethod
    def _where(student_id, conversation_id, request_id):
        return (
            turn_requests.c.student_id == student_id,
            turn_requests.c.conversation_id == conversation_id,
            turn_requests.c.request_id == request_id,
        )

    async def claim(self, student_id, conversation_id, request_id, payload_hash):
        """Return (created, row); callers compare hashes even for finished rows."""
        key = (student_id, conversation_id, request_id)
        values = dict(student_id=student_id, conversation_id=conversation_id,
                      request_id=request_id, payload_hash=payload_hash,
                      status="RUNNING", frames=[],
                      created_at=datetime.now(timezone.utc).isoformat())
        if self.uow is None:
            created = key not in self._rows
            self._rows.setdefault(key, values)
            return created, deepcopy(self._rows[key])
        async with self.uow.transaction() as conn:
            inserted = await conn.execute(turn_requests.insert().prefix_with("OR IGNORE").values(**values))
            row = (await conn.execute(select(turn_requests).where(*self._where(*key)))).mappings().one()
        return inserted.rowcount == 1, dict(row)

    async def record(self, student_id, conversation_id, request_id, frames, *, finished=False):
        key = (student_id, conversation_id, request_id)
        values = {"frames": deepcopy(frames), "status": "FINISHED" if finished else "RUNNING"}
        if self.uow is None:
            self._rows[key].update(values)
            return
        async with self.uow.transaction() as conn:
            await conn.execute(turn_requests.update().where(*self._where(*key)).values(**values))

    async def forget(self, owner, cid):
        if self.uow is None:
            self._rows = {key: row for key, row in self._rows.items() if key[:2] != (owner, cid)}
        else:
            async with self.uow.transaction() as conn:
                await conn.execute(turn_requests.delete().where(
                    turn_requests.c.student_id == owner, turn_requests.c.conversation_id == cid))
