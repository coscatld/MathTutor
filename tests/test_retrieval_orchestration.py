"""Phase C — ConversationRetrievalOrchestrator, rerank, expansion, EvidencePack.

Route 2 (docs/CURRENT_STATE_RAG_AUDIT.md §4.3): the retrieval kernel is not
reimplemented here. These tests cover the orchestration stage built on top of
``DocumentIndexManager.search``, and the two properties that stage must hold:

- **bounded**: no configuration or input turns top-K into a whole-document read;
- **honest**: what actually ran (lexical vs hybrid, reranker, expansion, why
  degraded) is recorded rather than inferred from configuration.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from mathtutor.application.context_expansion import (
    MAX_EXPANSION_CHARS,
    ContextExpander,
    needs_expansion,
)
from mathtutor.application.conversation_scope import (
    reset_document_scope,
    set_document_scope,
)
from mathtutor.application.rerank import ProductionReranker
from mathtutor.application.retrieval_orchestrator import (
    REASON_EMBEDDING_UNAVAILABLE,
    REASON_EMPTY_SCOPE,
    REASON_HINTS_ONLY,
    REASON_SMALL_TALK,
    ConversationRetrievalOrchestrator,
    RetrievalDecision,
    decide_retrieval,
    rewrite_query,
)
from mathtutor.domain.documents import (
    DocumentChunk,
    DocumentQueryResult,
    RetrievedChunk,
)
from mathtutor.domain.evidence import (
    MAX_EVIDENCE_CHARS,
    MAX_EVIDENCE_ITEMS,
    Evidence,
    build_evidence_pack,
    make_source_id,
)
from mathtutor.security.scopes import student_uuid

pytestmark = pytest.mark.asyncio

_OWNER = "orch-owner"


# --------------------------------------------------------------- fixtures


def _chunk(document_id: UUID, sequence: int, text: str, section: str = "") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        student_id=student_uuid(_OWNER),
        sequence=sequence,
        text=text,
        content_hash=f"h{sequence}",
        section=section,
    )


def _hit(chunk: DocumentChunk, *, score: float = 0.5, filename: str = "notes.md") -> RetrievedChunk:
    return RetrievedChunk(
        chunk=chunk,
        document_id=chunk.document_id,
        filename=filename,
        score=score,
        lexical_score=score,
    )


class _Kernel:
    """Stands in for DocumentIndexManager; records what it was asked."""

    def __init__(self, hits=(), *, vector_used: bool = False):
        self.hits = list(hits)
        self.vector_used = vector_used
        self.calls: list[dict] = []

    async def search(self, student_id, *, query, limit=5, document_ids=None):
        self.calls.append({"query": query, "limit": limit, "document_ids": document_ids})
        return DocumentQueryResult(
            query=query,
            hits=tuple(self.hits[:limit]),
            vector_used=self.vector_used,
            degraded=not self.vector_used,
        )


class _Repo:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    async def list_chunk_neighbourhood(
        self, sid, did, *, sequence_start, sequence_end, chunk_ids=()
    ):
        wanted = {str(c) for c in chunk_ids}
        return [
            chunk
            for chunk in self.chunks
            if chunk.document_id == did
            and (
                sequence_start <= chunk.sequence <= sequence_end
                or str(chunk.chunk_id) in wanted
            )
        ]


# ------------------------------------------------------- retrieval decision


@pytest.mark.parametrize(
    "query,scope,hints,expected_reason",
    [
        ("", [uuid4()], False, "no_query_hint"),
        ("第二章讲了什么", [], False, REASON_EMPTY_SCOPE),
        ("你好", [uuid4()], False, REASON_SMALL_TALK),
        ("第二章讲了什么", [uuid4()], True, REASON_HINTS_ONLY),
    ],
)
def test_decision_is_none_when_retrieval_cannot_help(query, scope, hints, expected_reason):
    decision, reasons = decide_retrieval(query, document_ids=scope, hints_only=hints)
    assert decision is RetrievalDecision.NONE
    assert expected_reason in reasons


def test_decision_retrieves_on_a_substantive_question():
    decision, reasons = decide_retrieval("第二章讲了什么", document_ids=[uuid4()])
    assert decision is RetrievalDecision.CONVERSATION_DOCUMENTS
    assert reasons == ()


def test_ambiguity_retrieves_rather_than_starving_the_model():
    """A grounded-answer system suffers more from missing evidence than from
    one extra search, and the scope already bounds what a search can reach."""
    decision, _ = decide_retrieval("嗯？", document_ids=[uuid4()])
    assert decision is RetrievalDecision.CONVERSATION_DOCUMENTS


# ---------------------------------------------------------------- rewrite


def test_referential_turn_absorbs_recent_context():
    """The requirement doc's own example: "这一步为什么错" alone has no token
    for the lexical index to match on."""
    query = rewrite_query(
        "这一步为什么错",
        history=[{"role": "student", "content": "解方程 2x+3=7"}],
    )
    assert query.referential is True
    assert "解方程" in query.text
    assert query.original == "这一步为什么错"


def test_non_referential_turn_is_not_widened_with_history():
    query = rewrite_query(
        "二次方程求根公式",
        history=[{"role": "student", "content": "无关的历史内容" * 20}],
    )
    assert query.referential is False
    assert "无关的历史内容" not in query.text
    assert query.text == "二次方程求根公式"


def test_rewritten_query_is_bounded_not_the_transcript():
    history = [{"role": "student", "content": "很长的一段话" * 200} for _ in range(10)]
    query = rewrite_query("这个怎么解", history=history)
    assert len(query.text) < 1000


def test_problem_text_becomes_part_of_the_query():
    query = rewrite_query("这一步为什么错", problem_text="2x + 3 = 7")
    assert "2x + 3 = 7" in query.text


# ---------------------------------------------------------------- reranker


def test_reranker_reads_the_real_chunk_text():
    """Regression: the previous reranker took ``Sequence[Any]`` and read
    ``getattr(candidate, "text", "")``, which is empty for a RetrievedChunk —
    it silently scored every real hit zero."""
    document_id = uuid4()
    matching = _hit(_chunk(document_id, 0, "一元二次方程的求根公式"), score=0.1)
    unrelated = _hit(_chunk(document_id, 1, "完全无关的段落"), score=0.9)

    ranked = ProductionReranker().rerank("求根公式", [unrelated, matching])

    assert ranked[0].hit is matching
    assert ranked[0].coverage > 0
    assert ranked[1].coverage == 0


def test_reranker_is_deterministic_and_stable():
    document_id = uuid4()
    hits = [_hit(_chunk(document_id, i, "同分文本"), score=0.5) for i in range(3)]
    first = ProductionReranker().rerank("同分文本", hits)
    second = ProductionReranker().rerank("同分文本", hits)
    assert [row.hit.chunk.chunk_id for row in first] == [
        row.hit.chunk.chunk_id for row in second
    ]


def test_reranker_truncates_without_inventing_candidates():
    document_id = uuid4()
    hits = [_hit(_chunk(document_id, i, f"文本{i}"), score=0.5 - i * 0.01) for i in range(10)]
    ranked = ProductionReranker().rerank("文本", hits, limit=3)
    assert len(ranked) == 3
    assert {row.hit.chunk.chunk_id for row in ranked} <= {hit.chunk.chunk_id for hit in hits}


# -------------------------------------------------------- context expansion


def test_expansion_trigger_is_conservative():
    assert needs_expansion("两边同时减三，得") is True       # cut mid-sentence
    assert needs_expansion("因此我们知道") is True            # opens with a continuation
    assert needs_expansion("两边同时减三，得 x=2。") is False  # self-contained
    assert needs_expansion("") is False


async def test_expansion_restores_neighbours_in_sequence_order():
    document_id = uuid4()
    chunks = [
        _chunk(document_id, 0, "前面讲过移项。"),
        _chunk(document_id, 1, "两边同时减三，得"),
        _chunk(document_id, 2, "x 等于二。"),
    ]
    expander = ContextExpander(_Repo(chunks))

    expanded = await expander.expand(_OWNER, [_hit(chunks[1])])

    assert expanded[0].expanded is True
    assert len(expanded[0].expanded_from) == 2
    assert expanded[0].text.index("前面讲过移项") < expanded[0].text.index("x 等于二")
    # The matched chunk itself is untouched — "what matched" stays knowable.
    assert expanded[0].hit.chunk is chunks[1]


async def test_expansion_does_not_trigger_for_self_contained_chunks():
    document_id = uuid4()
    chunks = [_chunk(document_id, 0, "a。"), _chunk(document_id, 1, "自足的段落。")]
    expander = ContextExpander(_Repo(chunks))
    expanded = await expander.expand(_OWNER, [_hit(chunks[1])])
    assert expanded[0].expanded is False
    assert expanded[0].text == "自足的段落。"


async def test_expansion_never_exceeds_its_character_budget():
    document_id = uuid4()
    huge = "很长的邻居段落" * 500
    chunks = [_chunk(document_id, 0, huge), _chunk(document_id, 1, "被截断的，因此")]
    expander = ContextExpander(_Repo(chunks), max_chars=100)
    expanded = await expander.expand(_OWNER, [_hit(chunks[1])])
    assert len(expanded[0].text) <= len(chunks[1].text) + 100


async def test_expansion_caps_the_number_of_expanded_hits():
    document_id = uuid4()
    chunks = [_chunk(document_id, i, "因此继续" if i % 2 else "邻居。") for i in range(20)]
    hits = [_hit(chunks[i]) for i in range(1, 20, 2)]
    expander = ContextExpander(_Repo(chunks), max_items=2)
    expanded = await expander.expand(_OWNER, hits)
    assert sum(1 for item in expanded if item.expanded) == 2


async def test_expansion_read_failure_keeps_the_hit():
    class _Broken:
        async def list_chunk_neighbourhood(self, *a, **k):
            raise RuntimeError("db down")

    document_id = uuid4()
    chunk = _chunk(document_id, 1, "被截断的，因此")
    expander = ContextExpander(_Broken())
    expanded = await expander.expand(_OWNER, [_hit(chunk)])

    assert expanded[0].expanded is False
    assert expanded[0].text == chunk.text  # the hit survives
    assert expander.read_failures == 1     # ...and the degradation is visible


# ------------------------------------------------------------ EvidencePack


def test_pack_enforces_hard_caps():
    document_id = uuid4()
    evidences = [
        Evidence(
            source_id=make_source_id(document_id, uuid4()),
            document_id=document_id,
            filename="n.md",
            chunk_id=uuid4(),
            sequence=index,
            text="x" * 5000,
        )
        for index in range(30)
    ]
    pack = build_evidence_pack(query="q", evidences=evidences)
    assert len(pack.evidences) <= MAX_EVIDENCE_ITEMS
    assert pack.chars() <= MAX_EVIDENCE_CHARS


def test_pack_drops_blank_evidence():
    document_id = uuid4()
    pack = build_evidence_pack(
        query="q",
        evidences=[
            Evidence(
                source_id="e-1",
                document_id=document_id,
                filename="n.md",
                chunk_id=uuid4(),
                sequence=0,
                text="   ",
            )
        ],
    )
    assert pack.empty is True


def test_pack_is_immutable():
    pack = build_evidence_pack(query="q", evidences=[])
    with pytest.raises(Exception):
        pack.query = "mutated"  # type: ignore[misc]


def test_public_projection_hides_internal_scores():
    document_id = uuid4()
    pack = build_evidence_pack(
        query="q",
        evidences=[
            Evidence(
                source_id="e-1",
                document_id=document_id,
                filename="n.md",
                chunk_id=uuid4(),
                sequence=0,
                text="内容",
                body_hash="secret-internal",
            )
        ],
    )
    projection = pack.public_projection()
    assert "body_hash" not in projection["evidences"][0]
    assert "text_hash" not in projection["evidences"][0]


# ------------------------------------------------------------ orchestrator


async def test_orchestrator_requires_an_explicit_scope():
    """D1 guard: there is no default that means 'all documents'."""
    kernel = _Kernel()
    orchestrator = ConversationRetrievalOrchestrator(kernel=kernel)
    pack = await orchestrator.retrieve_for_turn(_OWNER, [], "第二章讲了什么")
    assert pack.empty
    assert kernel.calls == []
    assert REASON_EMPTY_SCOPE in pack.execution.degraded_reasons


async def test_orchestrator_passes_scope_to_the_kernel_unchanged():
    document_id = uuid4()
    kernel = _Kernel([_hit(_chunk(document_id, 0, "内容。"))])
    orchestrator = ConversationRetrievalOrchestrator(kernel=kernel)
    await orchestrator.retrieve_for_turn(_OWNER, [document_id], "内容")
    assert kernel.calls[0]["document_ids"] == [document_id]


async def test_orchestrator_records_lexical_degradation_with_a_reason():
    document_id = uuid4()
    kernel = _Kernel([_hit(_chunk(document_id, 0, "一元二次方程求根公式。"))], vector_used=False)
    orchestrator = ConversationRetrievalOrchestrator(kernel=kernel)

    pack = await orchestrator.retrieve_for_turn(_OWNER, [document_id], "求根公式")

    assert pack.execution.retrieval_ran is True
    assert pack.execution.mode == "lexical"
    assert REASON_EMBEDDING_UNAVAILABLE in pack.execution.degraded_reasons
    assert pack.execution.degraded is True


async def test_orchestrator_reports_hybrid_when_a_vector_pass_contributed():
    """The mode keeps ``hybrid`` in its domain even though the shipped runtime
    only ever produces ``lexical`` — an observed default must not freeze the
    architecture's capability."""
    document_id = uuid4()
    kernel = _Kernel([_hit(_chunk(document_id, 0, "一元二次方程。"))], vector_used=True)
    orchestrator = ConversationRetrievalOrchestrator(kernel=kernel)

    pack = await orchestrator.retrieve_for_turn(_OWNER, [document_id], "方程")

    assert pack.execution.mode == "hybrid"
    assert REASON_EMBEDDING_UNAVAILABLE not in pack.execution.degraded_reasons


async def test_orchestrator_end_to_end_produces_traceable_evidence():
    document_id = uuid4()
    chunks = [
        _chunk(document_id, 0, "这一节讲移项。"),
        _chunk(document_id, 1, "两边同时减三，得"),
        _chunk(document_id, 2, "x 等于二。"),
    ]
    kernel = _Kernel([_hit(chunks[1], score=0.4)])
    orchestrator = ConversationRetrievalOrchestrator(
        kernel=kernel, expander=ContextExpander(_Repo(chunks))
    )

    pack = await orchestrator.retrieve_for_turn(_OWNER, [document_id], "移项怎么做")

    assert pack.execution.decision == RetrievalDecision.CONVERSATION_DOCUMENTS.value
    assert pack.execution.reranker_used is True
    assert pack.execution.expansion_used is True

    evidence = pack.evidences[0]
    assert evidence.document_id == document_id
    assert evidence.chunk_id == chunks[1].chunk_id
    assert evidence.sequence == 1
    assert evidence.source_id.startswith("e-")
    assert evidence.text_hash
    assert evidence.rerank_score is not None
    assert evidence.expanded_from


async def test_orchestrator_is_reachable_for_small_talk_without_touching_the_kernel():
    kernel = _Kernel()
    orchestrator = ConversationRetrievalOrchestrator(kernel=kernel)
    pack = await orchestrator.retrieve_for_turn(_OWNER, [uuid4()], "你好")
    assert pack.empty
    assert kernel.calls == []
    assert pack.execution.retrieval_ran is False


# ------------------------------------------- F1: one orchestrator, all paths


async def test_every_initial_retrieval_consumer_shares_one_orchestrator(tmp_path):
    """F1: Tutor chat, Knowledge QA, hint/explain and practice must all reach
    the SAME orchestrator instance.

    Asserting identity rather than "it works": a second orchestrator would
    still pass behavioural tests while reintroducing two sets of scoping,
    rewriting, reranking and expansion rules — the defect F1 names.

    Needs a durable state: the knowledge QA path only exists when there is a
    database behind it.
    """
    from mathtutor.api.product_state import ProductState
    from mathtutor.domain.retrieval_policy import RetrievalSource
    from mathtutor.infrastructure.db import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db

    db_file = tmp_path / "orch.db"
    upgrade_db(str(db_file))
    engine = create_db_engine(db_file)
    state = ProductState(engine=engine, data_dir=tmp_path)
    try:
        shared = state.retrieval_orchestrator

        # 1. Structured path (hint / explain / practice) — via ContextAssembler.
        provider = state.context_assembler._providers[RetrievalSource.USER_DOCUMENTS]
        assert provider._orchestrator is shared
        # ...and it must NOT hold a retrieval of its own any more.
        assert provider._searchable is None

        # 2. Tutor chat path.
        assert state.controller.chat_documents.orchestrator is shared

        # 3. Knowledge QA path.
        assert state.controller.knowledge_qa.orchestrator is shared
    finally:
        await state.shutdown_runtime()
        await engine.dispose()


async def test_structured_provider_refuses_without_an_orchestrator():
    """A second retrieval implementation must not sneak back in: with no
    orchestrator the provider reports empty rather than searching itself."""
    from mathtutor.application.context_assembler import UserDocumentsSourceProvider
    from mathtutor.domain.retrieval_policy import RetrievalIntent

    class _Exploding:
        async def search(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("the provider must not search on its own")

    provider = UserDocumentsSourceProvider(searchable=_Exploding())
    token = set_document_scope([uuid4()])
    try:
        outcome = await provider.retrieve(
            student_id=_OWNER, intent=RetrievalIntent.USE_MY_DOCUMENT, query_hint="求根公式"
        )
    finally:
        reset_document_scope(token)

    assert outcome.payload is None
    assert outcome.detail == "no retrieval orchestrator wired"


# --------------------------------------------- parent-first expansion (§1)


class _ParentRepo:
    """Neighbourhood reader whose visibility can be toggled per chunk."""

    def __init__(self, chunks, *, blocked=()):
        self.chunks = list(chunks)
        self.blocked = {str(c) for c in blocked}

    async def list_chunk_neighbourhood(
        self, sid, did, *, sequence_start, sequence_end, chunk_ids=()
    ):
        wanted = {str(c) for c in chunk_ids}
        visible = [c for c in self.chunks if str(c.chunk_id) not in self.blocked]
        return [
            chunk
            for chunk in visible
            if chunk.document_id == did
            and (sequence_start <= chunk.sequence <= sequence_end or str(chunk.chunk_id) in wanted)
        ]


def _child_and_parent():
    from uuid import UUID as _UUID

    document_id = uuid4()
    parent = _chunk(document_id, 0, "例：解方程 2x+3=7。")
    child = _chunk(document_id, 1, "解：两边同时减 3，得 2x=4。")
    child = child.model_copy(update={"parent_chunk_id": parent.chunk_id})
    return document_id, parent, child


async def test_parent_is_restored_for_a_child_hit():
    """P1: the matched solution child is not answerable without its stem."""
    _document_id, parent, child = _child_and_parent()
    expander = ContextExpander(_ParentRepo([parent, child]))

    expanded = await expander.expand(_OWNER, [_hit(child)])

    assert expanded[0].expanded is True
    assert parent.chunk_id in expanded[0].expanded_from
    assert "2x+3=7" in expanded[0].text


async def test_parent_outside_visibility_is_not_restored():
    """P2/P3: a parent is not implicitly readable because its child matched."""
    _document_id, parent, child = _child_and_parent()
    expander = ContextExpander(_ParentRepo([parent, child], blocked=[parent.chunk_id]))

    expanded = await expander.expand(_OWNER, [_hit(child)])

    assert parent.chunk_id not in expanded[0].expanded_from
    assert "2x+3=7" not in expanded[0].text


async def test_expansion_does_not_cross_a_section_boundary():
    """C5: sequence adjacency is a storage fact, not a semantic one.

    The last chunk of section A is adjacent to the first chunk of section B;
    pulling B in because of that would add a confident-looking irrelevant
    passage to the evidence.
    """
    document_id = uuid4()
    last_of_a = _chunk(document_id, 0, "判别式判断根的数量，因此", section="判别式")
    first_of_b = _chunk(document_id, 1, "韦达定理描述根与系数的关系。", section="韦达定理")
    expander = ContextExpander(_ParentRepo([last_of_a, first_of_b]))

    expanded = await expander.expand(_OWNER, [_hit(last_of_a)])

    assert expanded[0].expanded is False
    assert "韦达定理" not in expanded[0].text


async def test_expansion_still_fires_within_one_section():
    document_id = uuid4()
    first = _chunk(document_id, 0, "前面讲过移项。", section="解法")
    second = _chunk(document_id, 1, "两边同时减三，得", section="解法")
    expander = ContextExpander(_ParentRepo([first, second]))

    expanded = await expander.expand(_OWNER, [_hit(second)])

    assert expanded[0].expanded is True
    assert first.chunk_id in expanded[0].expanded_from


async def test_final_projection_keeps_parent_stem_and_long_solution():
    from mathtutor.application.adaptive_practice import _merged_document_context
    from mathtutor.application.context_assembler import UserDocumentsSourceProvider, project_evidence_text
    from mathtutor.application.retrieval_orchestrator import ConversationRetrievalOrchestrator
    from mathtutor.domain.evidence import build_evidence_pack

    document_id, parent, child = _child_and_parent()
    condition = "必要条件：未知数不等于零。"
    parent = parent.model_copy(update={"text": f"例：解方程 2x+3=7。{condition}"})
    child = child.model_copy(update={
        "parent_chunk_id": parent.chunk_id,
        "text": "解：" + ("两边同时减 3，得 2x=4。两边再除以 2，得 x=2。" * 30),
    })
    assert len(child.text) >= 700
    expander = ContextExpander(_ParentRepo([parent, child]))
    expanded = await expander.expand(_OWNER, [_hit(child)])
    assert parent.chunk_id in expanded[0].expanded_from
    assert expanded[0].parent_text
    assert condition in expanded[0].parent_text
    assert condition in expanded[0].text

    class _Kernel:
        async def search(self, *args, **kwargs):
            return DocumentQueryResult(query="2x+3=7", hits=(_hit(child),), degraded=True)

    orch = ConversationRetrievalOrchestrator(kernel=_Kernel(), expander=expander)
    pack = await orch.retrieve_for_turn(_OWNER, [document_id], "解方程")
    assert pack.evidences
    item = pack.evidences[0]
    assert item.parent_text
    assert condition in item.parent_text
    text, insufficient, delivered = project_evidence_text(item)
    assert not insufficient
    assert condition in text
    assert "2x=4" in text
    assert delivered >= len(item.parent_text) + 100
    assert len(text) > 600

    selections = UserDocumentsSourceProvider._project_pack(pack)
    merged = _merged_document_context(selections)
    assert merged is not None
    joined = "\n".join(chunk.text for chunk in merged.chunks)
    assert condition in joined
    assert "2x=4" in joined
    assert all(chunk.delivered_chars > 0 for chunk in merged.chunks)
    assert not any(chunk.insufficient_context for chunk in merged.chunks)


async def test_projection_caps_unexpanded_long_slice():
    from mathtutor.application.context_assembler import project_evidence_text
    from mathtutor.domain.evidence import Evidence, make_source_id

    document_id = uuid4()
    item = Evidence(
        source_id=make_source_id(document_id, uuid4()),
        document_id=document_id,
        filename="a.md",
        chunk_id=uuid4(),
        sequence=0,
        text="A0" * 400,
        score=0.7,
    )
    text, insufficient, delivered = project_evidence_text(item)
    assert not insufficient
    assert len(text) == 600
    assert delivered == 600
