"""F3 / D10 — historical citation authorization, separate from retrieval.

Active retrieval and historical citation answer different questions:

    active retrieval    may this owner read this document NOW?
    historical citation was this exact range surfaced before, and is that
                        immutable version still intact?

A receipt must survive the document being DISABLED (a citation the student was
already given does not stop being verifiable because retrieval was later turned
off) and must NOT survive DELETION (privacy deletion overrides historical
citation availability — the F3 decision).

Above all it must never widen: a receipt proves a range was surfaced, it does
not grant a read.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from test_knowledge_workbench import seed, state  # noqa: F401  (fixtures)

from mathtutor.application.knowledge import KnowledgeError
from mathtutor.application.knowledge_tools import KnowledgeTools

pytestmark = pytest.mark.asyncio


async def _seed(state):
    """Idempotent: mount alice's library into conversation A.

    Without this the conversation has NO scope, so search returns nothing —
    which is the correct product behaviour and a silent way to write a test
    that passes for the wrong reason.
    """
    await seed(state)


async def _tools(state, owner="alice", cid="A") -> KnowledgeTools:
    generation = await state.knowledge.generation(owner)
    return KnowledgeTools(state, owner, cid, generation=generation)


async def _issue(state, *, owner="alice", cid="A", index=0):
    """Surface one real range and return its receipt — via the real tool path."""
    await _seed(state)  # mount the library into the conversation
    tools = await _tools(state, owner, cid)
    search = await tools.execute("search_knowledge", {"query": "移项"}, f"s-{index}")
    assert search["ok"], search
    hit = search["result"]["hits"][0]
    read = await tools.execute("read_source", {
        "document_id": hit["document_id"], "version": hit["version"],
        "start": hit["start"], "end": hit["end"],
    }, f"r-{index}")
    assert read["ok"], read
    return read["result"]


# --------------------------------------------------------- B6: no escalation


async def test_receipt_reads_exactly_its_own_range(state):
    result = await _issue(state)
    again = await state.knowledge.read_citation_receipt(
        "alice", "A", result["receipt_id"], result["start"], result["end"]
    )
    assert again["historical"] is True
    assert again["text"] == result["text"]


@pytest.mark.parametrize("shift", [{"start": 1}, {"end": 1}, {"start": -1}, {"end": -1}])
async def test_receipt_rejects_any_other_range(state, shift):
    """A receipt is an exact tuple, never a licence to read around it."""
    result = await _issue(state)
    start = result["start"] + shift.get("start", 0)
    end = result["end"] + shift.get("end", 0)

    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt(
            "alice", "A", result["receipt_id"], start, end
        )


async def test_receipt_cannot_be_used_to_read_the_whole_document(state):
    """The specific fear: 'cited it once, so now I can read everything'."""
    result = await _issue(state, index=1)
    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt(
            "alice", "A", result["receipt_id"], 0, 6000
        )


async def test_guessed_receipt_id_is_rejected(state):
    await _issue(state, index=2)
    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt("alice", "A", "cr-guessed", 0, 10)


async def test_receipt_is_conversation_bound(state):
    """A receipt issued in conversation A must not be usable from B."""
    result = await _issue(state, index=3)
    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt(
            "alice", "B", result["receipt_id"], result["start"], result["end"]
        )


async def test_receipt_is_owner_bound(state):
    """Owner scoping is structural: the lookup itself carries the owner."""
    result = await _issue(state, index=4)
    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt(
            "bob", "A", result["receipt_id"], result["start"], result["end"]
        )


# ------------------------------------------------------ B5: lifecycle rules


async def test_receipt_survives_the_document_being_disabled(state):
    """Disabling is not deleting. A citation the student already received must
    stay verifiable even though new retrieval is now forbidden."""
    from uuid import UUID

    result = await _issue(state, index=5)
    document_id = UUID(result["document_id"])

    await state.document_repository.set_retrieval_enabled("alice", document_id, False)
    assert (await state.documents.get_document("alice", document_id)).is_retrievable() is False

    again = await state.knowledge.read_citation_receipt(
        "alice", "A", result["receipt_id"], result["start"], result["end"]
    )
    assert again["text"] == result["text"]

    # ...while new retrieval for that document is genuinely closed.
    tools = await _tools(state)
    search = await tools.execute("search_knowledge", {"query": "移项"}, "after-disable")
    assert all(hit["document_id"] != result["document_id"] for hit in search["result"]["hits"])

    await state.document_repository.set_retrieval_enabled("alice", document_id, True)


async def test_receipt_fails_closed_after_deletion(state):
    """F3 decision: deletion is physical, and privacy deletion overrides
    historical citation availability. The receipt must not resurrect content."""
    from uuid import UUID

    result = await _issue(state, index=6)
    document_id = UUID(result["document_id"])

    assert await state.data_lifecycle.delete_document("alice", document_id) is True

    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt(
            "alice", "A", result["receipt_id"], result["start"], result["end"]
        )


async def test_deletion_removes_the_receipt_row_itself(state):
    """Not just unreadable — not retained. A receipt names a document and a
    range; keeping it after the content is gone is retention the student did
    not ask for."""
    from sqlalchemy import select

    from mathtutor.infrastructure.knowledge_schema import receipts

    result = await _issue(state, index=7)
    document_id = UUID(result["document_id"])
    await state.data_lifecycle.delete_document("alice", document_id)

    async with state.knowledge.engine.connect() as db:
        rows = (await db.execute(select(receipts.c.receipt_id).where(
            receipts.c.student_id == "alice",
            receipts.c.receipt_id == result["receipt_id"],
        ))).scalars().all()
    assert rows == []


async def test_body_hash_is_reverified_not_trusted(state):
    """A receipt whose immutable body no longer hashes to what was recorded
    must fail closed rather than serve the text."""
    from sqlalchemy import update

    from mathtutor.infrastructure.knowledge_schema import versions

    result = await _issue(state, index=8)
    async with state.knowledge.engine.begin() as db:
        await db.execute(update(versions).where(
            versions.c.student_id == "alice",
            versions.c.document_id == result["document_id"],
            versions.c.version == result["version"],
        ).values(body_hash="tampered"))

    with pytest.raises(KnowledgeError):
        await state.knowledge.read_citation_receipt(
            "alice", "A", result["receipt_id"], result["start"], result["end"]
        )


# ------------------------------------------------- reading via the tool path


async def test_read_citation_tool_is_a_distinct_mode(state):
    """``read_citation`` must not require a live search hit (the range was
    surfaced in an earlier turn), yet must still enforce the receipt checks."""
    result = await _issue(state, index=9)
    # A fresh tool instance = a fresh turn: search_hits is empty.
    later = await _tools(state)

    ok = await later.execute("read_citation", {
        "receipt_id": result["receipt_id"],
        "start": result["start"], "end": result["end"],
    }, "c-1")
    widened = await later.execute("read_citation", {
        "receipt_id": result["receipt_id"],
        "start": result["start"], "end": result["end"] + 5,
    }, "c-2")

    assert ok["ok"] is True and ok["result"]["text"] == result["text"]
    assert widened["ok"] is False and widened["code"] == "REJECTED"
