"""Phase D — the system-side initial retrieval must be READABLE.

Phase C retrieves before the model is called. But ``read_source`` accepts only
``(document_id, version, start, end)`` tuples a search actually produced, so
without bridging the two, initial evidence would be context the model can see
but never cite — forcing a redundant search for anything it wants to quote.

:meth:`KnowledgeTools.seed_evidence` bridges them by DERIVING the offsets and
verifying them against the versioned body before registering. These tests pin
both halves: the bridge works, and it does not widen what the model can read.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from test_knowledge_workbench import seed, state  # noqa: F401  (fixtures)

from mathtutor.application.knowledge_tools import KnowledgeTools
from mathtutor.domain.evidence import (
    Evidence,
    build_evidence_pack,
    make_source_id,
    text_hash,
)

pytestmark = pytest.mark.asyncio


async def _tools(state, owner="alice", cid="A") -> KnowledgeTools:
    generation = await state.knowledge.generation(owner)
    return KnowledgeTools(state, owner, cid, generation=generation)


async def _evidence_for(state, document_id: UUID, sequence: int) -> Evidence:
    chunks = sorted(
        await state.document_repository.list_chunks("alice", document_id),
        key=lambda chunk: chunk.sequence,
    )
    chunk = next(item for item in chunks if item.sequence == sequence)
    return Evidence(
        source_id=make_source_id(document_id, chunk.chunk_id),
        document_id=document_id,
        filename="doc.md",
        chunk_id=chunk.chunk_id,
        sequence=chunk.sequence,
        section=chunk.section,
        text=chunk.text,
        text_hash=text_hash(chunk.text),
    )


async def test_seeded_evidence_becomes_readable(state):
    """The whole point: pre-fetched evidence can now be cited without a
    redundant search."""
    _lib, docs = await seed(state)
    document_id = UUID(docs[0]["document_id"])
    evidence = await _evidence_for(state, document_id, 0)
    tools = await _tools(state)
    pack = build_evidence_pack(query="移项", evidences=[evidence])

    seeded = await tools.seed_evidence(pack)

    assert seeded == 1
    assert len(tools.search_hits) == 1
    key = next(iter(tools.search_hits))
    # Internal registration alone is insufficient: the real model must receive
    # the exact validated tuple, not guess offsets or repeat search.
    import json
    from mathtutor.application.knowledge_qa import KnowledgeQA
    instruction = KnowledgeQA(state)._evidence_instruction(pack, tools.search_hits)
    assert json.dumps(dict(zip(("document_id", "version", "start", "end"), key)), ensure_ascii=False) in instruction
    receipt = await tools.execute(
        "read_source",
        dict(zip(("document_id", "version", "start", "end"), key)),
        "seed-1",
    )
    assert receipt["ok"] is True
    assert receipt["result"]["text"] == evidence.text


async def test_seeding_registers_nothing_when_the_text_does_not_address(state):
    """Fail closed: a range is trusted only once it demonstrably addresses the
    exact text. Otherwise the seed would be a way to mint a citation."""
    _lib, docs = await seed(state)
    document_id = UUID(docs[0]["document_id"])
    honest = await _evidence_for(state, document_id, 0)
    tampered = honest.model_copy(update={"text": "这段文字并不存在于任何版本中。"})
    tools = await _tools(state)

    seeded = await tools.seed_evidence(build_evidence_pack(query="q", evidences=[tampered]))

    assert seeded == 0
    assert tools.search_hits == {}


async def test_seeding_registers_nothing_for_an_unknown_chunk(state):
    _lib, docs = await seed(state)
    document_id = UUID(docs[0]["document_id"])
    honest = await _evidence_for(state, document_id, 0)
    ghost = honest.model_copy(update={"chunk_id": uuid4()})
    tools = await _tools(state)

    assert await tools.seed_evidence(build_evidence_pack(query="q", evidences=[ghost])) == 0


async def test_seeding_does_not_widen_the_hit_restriction(state):
    """A seeded range is readable; a guessed one is still rejected."""
    _lib, docs = await seed(state)
    document_id = UUID(docs[0]["document_id"])
    evidence = await _evidence_for(state, document_id, 0)
    tools = await _tools(state)
    await tools.seed_evidence(build_evidence_pack(query="q", evidences=[evidence]))
    registered = next(iter(tools.search_hits))
    version = registered[1]

    guessed = await tools.execute(
        "read_source",
        {"document_id": str(document_id), "version": version, "start": 0, "end": 4},
        "guess-1",
    )
    wrong_document = await tools.execute(
        "read_source",
        {"document_id": str(uuid4()), "version": version, "start": registered[2],
         "end": registered[3]},
        "guess-2",
    )

    assert guessed["ok"] is False and guessed["code"] == "REJECTED"
    assert wrong_document["ok"] is False and wrong_document["code"] == "REJECTED"


async def test_seeding_an_empty_or_absent_pack_is_a_no_op(state):
    _lib, _docs = await seed(state)
    tools = await _tools(state)
    assert await tools.seed_evidence(None) == 0
    assert await tools.seed_evidence(build_evidence_pack(query="q", evidences=[])) == 0
    assert tools.search_hits == {}


async def test_every_evidence_in_a_multi_hit_pack_is_seeded(state):
    _lib, docs = await seed(state)
    document_id = UUID(docs[0]["document_id"])
    chunks = await state.document_repository.list_chunks("alice", document_id)
    evidences = [
        await _evidence_for(state, document_id, chunk.sequence)
        for chunk in sorted(chunks, key=lambda c: c.sequence)[:3]
    ]
    tools = await _tools(state)

    seeded = await tools.seed_evidence(build_evidence_pack(query="q", evidences=evidences))

    assert seeded == len(evidences)
    assert len(tools.search_hits) == len(evidences)
