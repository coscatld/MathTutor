from __future__ import annotations

import pytest

from mathtutor.repositories.conversation_repository import InMemoryConversationRepository

pytestmark = pytest.mark.asyncio


async def test_empty_draft_is_not_listed_or_persisted_as_history() -> None:
    repository = InMemoryConversationRepository()
    for index in range(5):
        await repository.ensure("student", f"empty-{index}")
    assert await repository.list("student") == []


async def test_first_message_persists_exactly_one_conversation() -> None:
    repository = InMemoryConversationRepository()
    await repository.ensure("student", "draft")
    await repository.ensure("student", "draft")
    await repository.append_message(
        "student", "draft", role="student", content="为什么这个极限不能直接代入？"
    )
    rows = await repository.list("student")
    assert len(rows) == 1
    assert rows[0]["conversation_id"] == "draft"
    assert rows[0]["title"] == "为什么这个极限不能直接代入？"
