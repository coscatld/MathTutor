"""MT-RAG-004: delivered evidence, budget, and provenance must agree."""

from uuid import uuid4

import pytest

from mathtutor.application.context_expansion import ContextExpander
from mathtutor.application.retrieval_orchestrator import ConversationRetrievalOrchestrator
from mathtutor.domain.documents import DocumentChunk, DocumentQueryResult, RetrievedChunk
from mathtutor.domain.evidence import (
    MAX_EVIDENCE_CHARS,
    Evidence,
    EvidenceCoverage,
    RetrievalExecution,
    build_evidence_pack,
    make_source_id,
    text_hash,
)
from mathtutor.security.scopes import student_uuid


def _evidence(text, *, parent="", matched=None, neighbours=()):
    document_id, chunk_id = uuid4(), uuid4()
    return Evidence(
        source_id=make_source_id(document_id, chunk_id),
        document_id=document_id,
        filename="budget-fixture.md",
        chunk_id=chunk_id,
        sequence=0,
        text=text,
        text_hash=text_hash(text),
        matched_text=text if matched is None else matched,
        parent_text=parent,
        neighbour_texts=neighbours,
        expanded_from=tuple(uuid4() for _ in range(bool(parent) + len(neighbours))),
    )


@pytest.mark.parametrize(
    "sizes,expected_sizes,partial",
    [
        ([1900] * 7, [1900] * 6 + [600], True),
        ([500, 2500, 1800, 1999, 1901, 1800, 2000],
         [500, 2000, 1800, 1999, 1901, 1800, 2000], True),
        ([1700, 2000, 1800, 1999, 1901, 1800, 1000],
         [1700, 2000, 1800, 1999, 1901, 1800, 800], True),
        ([2000] * 6, [2000] * 6, False),
        ([2000] * 5 + [1999, 50], [2000] * 5 + [1999, 1], True),
    ],
)
def test_plain_evidence_honours_remaining_character_budget(sizes, expected_sizes, partial):
    candidates = [_evidence("数" * size) for size in sizes]
    pack = build_evidence_pack(query="条件是什么", evidences=candidates)
    assert pack.chars() <= MAX_EVIDENCE_CHARS
    assert [len(item.text) for item in pack.evidences] == expected_sizes
    assert pack.partial is partial
    assert pack.execution.coverage.truncated is partial
    for item in pack.evidences:
        assert item.text_hash == text_hash(item.text)
        assert item.matched_text == item.text
    assert [len(item.text) for item in candidates] == sizes  # input remains immutable


def test_exact_item_limit_is_complete_until_another_nonempty_item_is_dropped():
    candidates = [_evidence("条件") for _ in range(8)]
    assert not build_evidence_pack(query="q", evidences=candidates).partial
    assert build_evidence_pack(query="q", evidences=[*candidates, _evidence("其他条件")]).partial


def test_blank_candidates_after_a_full_pack_do_not_claim_budget_loss():
    candidates = [_evidence("数" * 2000) for _ in range(6)]
    pack = build_evidence_pack(query="q", evidences=[*candidates, _evidence(" \n ")])
    assert pack.chars() == MAX_EVIDENCE_CHARS
    assert not pack.partial


def test_hash_always_describes_delivered_text_without_changing_source_identity():
    original = _evidence("真实条件").model_copy(update={"text_hash": "stale"})
    item = build_evidence_pack(query="q", evidences=[original]).evidences[0]
    assert item.text_hash == text_hash(item.text)
    assert (item.source_id, item.chunk_id, item.document_id) == (
        original.source_id, original.chunk_id, original.document_id)


@pytest.mark.parametrize("group_size", [2000, 2001])
def test_parent_group_also_respects_the_per_item_boundary(group_size):
    parent = "条件：x不能为零。"
    matched = "解" * (group_size - len(parent) - 1)
    original = _evidence(f"{parent}\n{matched}", parent=parent, matched=matched)
    pack = build_evidence_pack(query="求解", evidences=[original])
    assert pack.partial is (group_size > 2000)
    assert bool(pack.evidences) is (group_size <= 2000)
    if pack.evidences:
        assert pack.evidences[0].text == original.text


@pytest.mark.parametrize("remaining", [1, 600, 601])
def test_parent_stem_and_solution_are_atomic_in_a_mixed_pack(remaining):
    # Make the group exactly 601 characters, including the separator.
    condition = "条件：x不能为零。"
    parent, matched = condition + "题" * (300 - len(condition)), "解" * 300
    group = f"{parent}\n{matched}"
    assert len(group) == 601
    prefixes = [_evidence("前" * 2000) for _ in range(5)]
    prefixes.append(_evidence("前" * (2000 - remaining)))
    child = _evidence(group, parent=parent, matched=matched)
    tail = _evidence("后" * 500)
    pack = build_evidence_pack(query="求解", evidences=[*prefixes, child, tail])
    kept_child = [item for item in pack.evidences if item.chunk_id == child.chunk_id]
    if remaining >= len(group):
        assert kept_child[0].text == group
        assert kept_child[0].expanded_from == child.expanded_from
        assert kept_child[0].text_hash == text_hash(group)
    else:
        assert not kept_child
        assert pack.evidences[-1].chunk_id == tail.chunk_id
        assert pack.evidences[-1].text == tail.text[:remaining]
    assert pack.chars() <= MAX_EVIDENCE_CHARS
    assert pack.partial


def test_parent_neighbours_dropped_by_budget_leave_no_stale_sources_or_text():
    parent, matched = "不能除以零。" * 50, "解" * 1000
    neighbours = ("长" * 900, "保留的补充条件")
    group = f"{parent}\n{matched}"
    original = _evidence("\n".join((group, *neighbours)), parent=parent,
                         matched=matched, neighbours=neighbours)
    pack = build_evidence_pack(query="q", evidences=[original],
                               execution=RetrievalExecution(expansion_used=True))
    item = pack.evidences[0]
    assert item.text == f"{group}\n{neighbours[1]}"
    assert item.neighbour_texts == (neighbours[1],)
    assert item.expanded_from == (original.expanded_from[0], original.expanded_from[2])
    assert item.text_hash == text_hash(item.text)
    assert pack.partial
    assert pack.execution.expansion_used
    assert pack.execution.coverage.expansion_used


@pytest.mark.parametrize("matched_size,expected_neighbours", [(2000, ()), (1950, ("邻" * 49,))])
def test_plain_expansion_tracks_only_retained_neighbour_sources(matched_size, expected_neighbours):
    matched, neighbours = "解" * matched_size, ("邻" * 100, "后" * 100)
    original = _evidence("\n".join((matched, *neighbours)), matched=matched, neighbours=neighbours)
    pack = build_evidence_pack(query="q", evidences=[original],
                               execution=RetrievalExecution(expansion_used=True))
    item = pack.evidences[0]
    assert item.neighbour_texts == expected_neighbours
    assert item.expanded_from == original.expanded_from[:len(expected_neighbours)]
    assert item.matched_text == matched
    assert item.text_hash == text_hash(item.text)
    assert pack.execution.expansion_used is bool(expected_neighbours)
    assert pack.execution.coverage.expansion_used is bool(expected_neighbours)
    assert pack.public_projection()["evidences"][0]["expanded"] is bool(expected_neighbours)
    assert pack.partial


def test_dropped_expansion_does_not_claim_the_final_pack_used_it():
    plain = [_evidence("题" * 2000) for _ in range(6)]
    expanded = _evidence("题干\n解答", parent="题干", matched="解答")
    pack = build_evidence_pack(query="q", evidences=[*plain, expanded],
                               execution=RetrievalExecution(expansion_used=True))
    assert pack.partial
    assert not pack.execution.expansion_used
    assert not pack.execution.coverage.expansion_used


def test_existing_budget_cut_is_not_erased_by_a_second_projection():
    pack = build_evidence_pack(query="q", evidences=[_evidence("已裁剪证据")],
        execution=RetrievalExecution(coverage=EvidenceCoverage(truncated=True)))
    assert pack.partial


class _ScopedKernel:
    """Deterministic retrieved fixtures; exercises the production orchestrator."""

    def __init__(self, hits):
        self.hits, self.calls = hits, []

    async def search(self, student_id, *, query, limit, document_ids):
        self.calls.append((student_id, tuple(document_ids)))
        assert all(hit.document_id in document_ids for hit in self.hits)
        return DocumentQueryResult(query=query, hits=tuple(self.hits[:limit]), vector_used=False)


class _Neighbourhood:
    def __init__(self, owner, chunks):
        self.owner, self.chunks, self.calls = owner, chunks, []

    async def list_chunk_neighbourhood(self, owner, document_id, *, sequence_start, sequence_end, chunk_ids=()):
        self.calls.append((owner, document_id))
        assert owner == self.owner
        return [c for c in self.chunks if c.document_id == document_id
                and (sequence_start <= c.sequence <= sequence_end or c.chunk_id in chunk_ids)]


def _chunk(document_id, sequence, text, *, parent=None):
    return DocumentChunk(chunk_id=uuid4(), document_id=document_id,
        student_id=student_uuid("budget-owner"), sequence=sequence, text=text,
        content_hash=text_hash(text), parent_chunk_id=parent, section="二次方程")


@pytest.mark.asyncio
async def test_orchestrator_delivers_bounded_pack_with_final_hashes():
    document_id = uuid4()
    hits = [RetrievedChunk(chunk=_chunk(document_id, i, "二次方程" + "数" * 1896),
                           document_id=document_id, filename="scope.md", score=1.0)
            for i in range(7)]
    kernel = _ScopedKernel(hits)
    pack = await ConversationRetrievalOrchestrator(kernel=kernel).retrieve_for_turn(
        "budget-owner", [document_id], "二次方程的条件")
    assert pack.chars() == MAX_EVIDENCE_CHARS
    assert pack.partial
    assert kernel.calls == [("budget-owner", (document_id,))]
    assert all(item.text_hash == text_hash(item.text) for item in pack.evidences)
    assert pack.execution.items_returned == pack.execution.coverage.selected_count == 7


@pytest.mark.asyncio
async def test_real_expander_to_pack_preserves_parent_and_drops_unseen_neighbour():
    document_id = uuid4()
    parent = _chunk(document_id, 0, "条件：x不能为零。" + "题" * 200)
    child = _chunk(document_id, 1, "二次方程的解法。" + "解" * 1400, parent=parent.chunk_id)
    neighbour = _chunk(document_id, 2, "邻" * 600)
    repo = _Neighbourhood("budget-owner", [parent, child, neighbour])
    kernel = _ScopedKernel([RetrievedChunk(chunk=child, document_id=document_id,
                                          filename="scope.md", score=1.0)])
    pack = await ConversationRetrievalOrchestrator(kernel=kernel, expander=ContextExpander(reader=repo)).retrieve_for_turn(
        "budget-owner", [document_id], "二次方程的解法")
    assert repo.calls == [("budget-owner", document_id)]
    item = pack.evidences[0]
    assert item.text == f"{parent.text}\n{child.text}"
    assert item.parent_text == parent.text
    assert item.matched_text == child.text
    assert item.neighbour_texts == ()
    assert item.expanded_from == (parent.chunk_id,)
    assert item.text_hash == text_hash(item.text)
    assert pack.partial
