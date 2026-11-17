"""Owner-scoped conversation history and document membership."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL

from sqlalchemy import exists, select

from mathtutor.infrastructure.schema import (
    conversation_documents,
    conversation_messages,
    conversations,
)
from mathtutor.repositories.sqlite_runtime import ensure_student
from mathtutor.repositories.uow import MathTutorUow


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def message_id_for(student_id: str, conversation_id: str, event_key: str) -> str:
    return str(uuid5(NAMESPACE_URL, repr((student_id, conversation_id, event_key))))


def _title(text: str) -> str:
    compact = " ".join(text.strip().split())
    return (compact[:38] + "…") if len(compact) > 38 else (compact or "新对话")




class SQLiteConversationRepository:
    def __init__(self, engine: Any = None) -> None:
        if engine is None:
            from mathtutor.infrastructure.memory_database import create_memory_engine
            engine = create_memory_engine()
        self.uow = MathTutorUow(engine)

    async def ensure(self, student_id: str, conversation_id: str, *, title: str = "新对话") -> dict:
        now = _now()
        async with self.uow.transaction() as conn:
            await ensure_student(conn, student_id=student_id)
            await conn.execute(conversations.insert().prefix_with("OR IGNORE").values(conversation_id=conversation_id, student_id=student_id, title=title, created_at=now, updated_at=now))
            row = (await conn.execute(select(conversations).where(conversations.c.student_id == student_id, conversations.c.conversation_id == conversation_id))).first()
        return dict(row._mapping)

    async def append_message(self, student_id: str, conversation_id: str, *, role: str, content: str, action: str = "", assistance_level: int = 0, event_key: str = "", status: str = "COMPLETED", finish_reason: str = "FINAL_ANSWER", turn_id: str = "", continuation_context: str = "", attachments: list | None = None) -> None:
        content = content.strip()
        if not content and not attachments:
            return
        await self.ensure(student_id, conversation_id)
        now = _now()
        unique = event_key or str(uuid4())
        async with self.uow.transaction() as conn:
            await conn.execute(conversation_messages.insert().prefix_with("OR IGNORE").values(message_id=message_id_for(student_id, conversation_id, unique), conversation_id=conversation_id, student_id=student_id, role=role, content=content, action=action, assistance_level=assistance_level, event_key=unique, created_at=now, status=status, finish_reason=finish_reason, turn_id=turn_id, continuation_context=continuation_context, attachments=attachments or []))
            current = (await conn.execute(select(conversations.c.title).where(conversations.c.student_id == student_id, conversations.c.conversation_id == conversation_id))).scalar_one_or_none()
            values: dict[str, str] = {"updated_at": now}
            if role == "student" and current == "新对话":
                values["title"] = _title(content or ("图片问题" if attachments else ""))
            await conn.execute(conversations.update().where(conversations.c.student_id == student_id, conversations.c.conversation_id == conversation_id).values(**values))

    async def finalize_turn(self, student_id, conversation_id, turn_id, *, status, finish_reason):
        async with self.uow.transaction() as conn:
            await conn.execute(conversation_messages.update().where(
                conversation_messages.c.student_id == student_id,
                conversation_messages.c.conversation_id == conversation_id,
                conversation_messages.c.turn_id == turn_id,
                conversation_messages.c.role == "tutor",
            ).values(status=status, finish_reason=finish_reason))

    async def save_turn_message(self, student_id, conversation_id, turn_id, **values):
        event_key = f"tutor:{turn_id}:result"
        await self.append_message(student_id, conversation_id, event_key=event_key, turn_id=turn_id, **values)
        async with self.uow.transaction() as conn:
            await conn.execute(conversation_messages.update().where(
                conversation_messages.c.student_id == student_id,
                conversation_messages.c.conversation_id == conversation_id,
                conversation_messages.c.event_key == event_key,
            ).values(**values))

    async def list(self, student_id: str, *, trashed: bool = False, all_records: bool = False) -> list[dict]:
        async with self.uow.transaction() as conn:
            has_student_message = exists(
                select(conversation_messages.c.message_id).where(
                    conversation_messages.c.student_id == student_id,
                    conversation_messages.c.conversation_id == conversations.c.conversation_id,
                    conversation_messages.c.role == "student",
                )
            )
            rows = (await conn.execute(select(conversations).where(
                conversations.c.student_id == student_id,
                conversations.c.purged_at.is_(None),
                True if all_records else (conversations.c.trashed_at.is_not(None) if trashed else conversations.c.trashed_at.is_(None)),
                has_student_message,
            ).order_by(conversations.c.updated_at.desc()))).all()
        return [dict(row._mapping) for row in rows]

    async def get(self, student_id: str, conversation_id: str) -> dict | None:
        async with self.uow.transaction() as conn:
            row = (await conn.execute(select(conversations).where(conversations.c.student_id == student_id, conversations.c.conversation_id == conversation_id))).first()
        return dict(row._mapping) if row else None

    async def messages(self, student_id: str, conversation_id: str) -> list[dict]:
        async with self.uow.transaction() as conn:
            rows = (await conn.execute(select(conversation_messages).where(conversation_messages.c.student_id == student_id, conversation_messages.c.conversation_id == conversation_id).order_by(conversation_messages.c.created_at))).all()
        return [dict(row._mapping) for row in rows]

    async def attach_document(self, student_id: str, conversation_id: str, document_id: UUID) -> None:
        await self.ensure(student_id, conversation_id)
        async with self.uow.transaction() as conn:
            await conn.execute(conversation_documents.insert().prefix_with("OR IGNORE").values(conversation_id=conversation_id, document_id=str(document_id), student_id=student_id, created_at=_now()))

    async def detach_document(self, student_id: str, conversation_id: str, document_id: UUID) -> bool:
        async with self.uow.transaction() as conn:
            result = await conn.execute(conversation_documents.delete().where(conversation_documents.c.student_id == student_id, conversation_documents.c.conversation_id == conversation_id, conversation_documents.c.document_id == str(document_id)))
        return result.rowcount > 0

    async def document_ids(self, student_id: str, conversation_id: str) -> list[UUID]:
        async with self.uow.transaction() as conn:
            values = (await conn.execute(select(conversation_documents.c.document_id).where(conversation_documents.c.student_id == student_id, conversation_documents.c.conversation_id == conversation_id).order_by(conversation_documents.c.created_at))).scalars().all()
        return [UUID(value) for value in values]

    async def conversation_ids_for_document(self, student_id: str, document_id: UUID) -> list[str]:
        async with self.uow.transaction() as conn:
            values = (await conn.execute(select(conversation_documents.c.conversation_id).where(conversation_documents.c.student_id == student_id, conversation_documents.c.document_id == str(document_id)))).scalars().all()
        return list(values)

    async def set_trash(self, owner, cid, trashed):
        async with self.uow.transaction() as conn:
            await conn.execute(conversations.update().where(
                conversations.c.student_id == owner, conversations.c.conversation_id == cid,
                conversations.c.purged_at.is_(None),
            ).values(trashed_at=_now() if trashed else None))

    async def purge(self, owner, cid):
        # Minimal tombstone prevents old URLs/queued requests resurrecting history.
        async with self.uow.transaction() as conn:
            for table in (conversation_messages, conversation_documents):
                await conn.execute(table.delete().where(table.c.student_id == owner, table.c.conversation_id == cid))
            from mathtutor.infrastructure.schema import turn_requests, turn_traces
            for table in (turn_requests, turn_traces):
                await conn.execute(table.delete().where(table.c.student_id == owner, table.c.conversation_id == cid))
            await conn.execute(conversations.update().where(
                conversations.c.student_id == owner, conversations.c.conversation_id == cid,
            ).values(title="", purged_at=_now()))
