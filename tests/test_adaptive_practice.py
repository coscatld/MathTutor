"""Adaptive practice context + candidate generation tests (§37 PRACTICE group).

The release gate is structural here: a CandidateExercise is UNVERIFIED by
construction and carries no authority — only the Parser → Solver →
Verifier → Release Attestation chain (Phase 5) may produce offers.
Tested: the PracticeGenerationContext field sources, the documented
misconception-confidence heuristic, the deterministic fake generator,
and the end-to-end service flow over the assembled context.
"""

from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from mathtutor.application.adaptive_practice import (
    AdaptivePracticeService,
    CandidateExercise,
    FakeCandidateExerciseGenerator,
    practice_context_from_assembled,
)
from mathtutor.application.context_assembler import (
    BaseContextSourceProvider,
    ContextAssembler,
    LoadOutcome,
)
from mathtutor.domain.assembled_context import (
    AttemptSummaryEntry,
    ContextProvenance,
    CurriculumContext,
    CurriculumNodeRef,
    DocumentChunkRef,
    DocumentContextSelection,
    MasteryEntry,
    MemoryContextEntry,
    MisconceptionContext,
    MisconceptionEntry,
    PersonalMemoryContext,
    RecentAttemptsContext,
    StudentModelContext,
)
from mathtutor.domain.documents import (
    DocumentChunk,
    DocumentQueryResult,
    RetrievedChunk,
)
from mathtutor.domain.practice_context import (
    PRACTICE_CONTEXT_VERSION,
    ActiveMisconceptionEntry,
    ErrorPatternEntry,
    MasterySnapshotEntry,
    PracticeGenerationContext,
)
from mathtutor.domain.retrieval_policy import (
    RetrievalIntent,
    RetrievalPolicy,
    RetrievalSource,
)
from mathtutor.security.scopes import student_uuid

pytestmark = pytest.mark.asyncio

_STUDENT = "student-a"


class StubProvider(BaseContextSourceProvider):
    """Provider whose load/retrieve return fixed outcomes (or async callables)."""

    def __init__(self, source: RetrievalSource, *, on_load=None, on_retrieve=None):
        self.source = source
        self._on_load = on_load
        self._on_retrieve = on_retrieve
        self.load_calls: list[dict] = []
        self.retrieve_calls: list[dict] = []

    async def load(
        self,
        *,
        student_id: str,
        intent: RetrievalIntent,
        node_ids: Sequence[str] | None = None,
        query_hint: str = "",
    ) -> LoadOutcome:
        self.load_calls.append({"node_ids": node_ids, "query_hint": query_hint})
        return self._resolve(self._on_load, LoadOutcome(detail="stub load"))

    async def retrieve(
        self, *, student_id: str, intent: RetrievalIntent, query_hint: str
    ) -> LoadOutcome:
        self.retrieve_calls.append({"query_hint": query_hint})
        return self._resolve(self._on_retrieve, LoadOutcome(detail="stub retrieve"))

    @staticmethod
    def _resolve(handler: Any, default: LoadOutcome) -> LoadOutcome:
        # Fixed outcomes only — a plain LoadOutcome or None (default).
        return handler if isinstance(handler, LoadOutcome) else default


def _assembled(*, with_documents: bool = False) -> Any:
    """A fully-loaded GENERATE_PRACTICE assembled context."""
    from mathtutor.domain.assembled_context import AssembledContext

    plan = RetrievalPolicy().resolve(RetrievalIntent.GENERATE_PRACTICE)
    student = student_uuid(_STUDENT)
    doc_id = uuid4()
    selections = ()
    if with_documents:
        selections = (
            DocumentContextSelection(
                document_id=doc_id,
                filename="错题本.md",
                chunks=(
                    DocumentChunkRef(
                        chunk_id=uuid4(),
                        document_id=doc_id,
                        sequence=0,
                        text="移项时忘记变号。",
                        score=0.8,
                    ),
                ),
            ),
        )
    return AssembledContext(
        intent=RetrievalIntent.GENERATE_PRACTICE,
        student_id=student,
        policy_version=RetrievalPolicy.POLICY_VERSION,
        plan=plan,
        student_model=StudentModelContext(
            estimator_version="mvp-v1",
            projection_version=2,
            skill_mastery=(
                MasteryEntry(skill_id="LINEAR_EQUATION", mastery=0.45),
                MasteryEntry(skill_id="QUADRATIC_EQUATION", mastery=0.8),
            ),
            active_misconception_rule_ids=("rule-sign-error", "rule-old"),
        ),
        curriculum=CurriculumContext(
            version_code="mt-curriculum-mvp-v1",
            nodes=(CurriculumNodeRef(node_id="LINEAR_EQUATION", code="LINEAR_EQUATION", kind="skill", title="一元一次方程"),),
        ),
        misconception_history=MisconceptionContext(
            entries=(
                MisconceptionEntry(rule_id="rule-sign-error", observation_count=3),
                MisconceptionEntry(rule_id="rule-distribute", observation_count=1),
            )
        ),
        recent_attempts=RecentAttemptsContext(
            entries=(
                AttemptSummaryEntry(
                    skill_id="LINEAR_EQUATION",
                    correctness="incorrect",
                    effective_assistance_level=2,
                    attempt_index=3,
                ),
            )
        ),
        personal_memory=PersonalMemoryContext(
            entries=(
                MemoryContextEntry(
                    memory_id=uuid4(),
                    memory_type="learning_preference",
                    subject="节奏",
                    predicate="喜欢",
                    object_json={"pace": "慢一点"},
                    source_type="USER_EXPLICIT",
                    confidence=0.9,
                ),
            )
        ),
        user_documents=selections,
        provenance=(ContextProvenance(source=RetrievalSource.STUDENT_MODEL, status="loaded", item_count=2),),
    )


# ------------------------------------------------- candidate contract


def test_candidate_is_unverified_by_construction():
    candidate = CandidateExercise(
        student_id=student_uuid(_STUDENT),
        problem_statement="x",
        generated_by="mt-fake-candidate-v1",
        difficulty=2,  # required — the generator must decide, no silent default
    )
    # No verified flag exists anywhere on the candidate model — only the
    # release gate may grant authority, so candidates carry none.
    assert "verified" not in candidate.model_dump()
    with pytest.raises(Exception):
        candidate.problem_statement = "mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        CandidateExercise(
            student_id=student_uuid(_STUDENT),
            problem_statement="x",
            generated_by="g",
            difficulty=6,  # out of 1..5
        )


# ------------------------------------------- practice_context_from_assembled


def test_mastery_mapped_and_filtered_to_targets():
    context = practice_context_from_assembled(
        _assembled(), target_skill_ids=("LINEAR_EQUATION",)
    )
    assert context.current_mastery == (
        MasterySnapshotEntry(skill_id="LINEAR_EQUATION", mastery=0.45),
    )
    # No target filter → the full snapshot.
    unfiltered = practice_context_from_assembled(_assembled())
    assert [e.skill_id for e in unfiltered.current_mastery] == [
        "LINEAR_EQUATION",
        "QUADRATIC_EQUATION",
    ]
    assert context.context_version == PRACTICE_CONTEXT_VERSION
    assert context.student_id == student_uuid(_STUDENT)


def test_misconception_confidence_heuristic_documented():
    # count=0 → base 0.75; count=1 → 0.65; count=2 → 0.75; cap 0.95.
    context = practice_context_from_assembled(_assembled())
    by_rule = {e.rule_id: e.confidence for e in context.active_misconceptions}
    assert by_rule["rule-sign-error"] == pytest.approx(min(0.95, 0.55 + 0.1 * 3))
    assert by_rule["rule-old"] == pytest.approx(0.75)  # no observations → base

    def with_counts(counts: dict[str, int]):
        base = _assembled()
        return base.model_copy(
            update={
                "misconception_history": MisconceptionContext(
                    entries=tuple(
                        MisconceptionEntry(rule_id=rid, observation_count=cnt)
                        for rid, cnt in counts.items()
                    )
                )
            }
        )

    one = practice_context_from_assembled(with_counts({"rule-sign-error": 1}))
    assert one.active_misconceptions[0].confidence == pytest.approx(0.65)
    capped = practice_context_from_assembled(with_counts({"rule-sign-error": 20}))
    assert capped.active_misconceptions[0].confidence == pytest.approx(0.95)


def test_error_patterns_and_attempts_and_preferences_mapped():
    context = practice_context_from_assembled(_assembled())
    assert context.recent_error_patterns == (
        ErrorPatternEntry(rule_id="rule-sign-error", occurrence_count=3),
        ErrorPatternEntry(rule_id="rule-distribute", occurrence_count=1),
    )
    assert context.recent_attempt_summary[0].skill_id == "LINEAR_EQUATION"
    assert context.recent_attempt_summary[0].correctness == "incorrect"
    assert context.personal_preferences is not None
    assert context.personal_preferences.entries[0].object_json == {"pace": "慢一点"}
    assert context.document_context is None  # no documents in this fixture


def test_document_context_takes_first_selection():
    context = practice_context_from_assembled(_assembled(with_documents=True))
    assert context.document_context is not None
    assert context.document_context.filename == "错题本.md"
    assert context.document_context.chunks[0].text == "移项时忘记变号。"
    assert context.document_context.chunks[0].sequence == 0
    assert context.document_context.chunks[0].score == 0.8
    assert context.provenance == _assembled().provenance  # provenance passthrough


# --------------------------------------------------------- fake generator


async def test_fake_generator_deterministic_and_sources_context():
    context = practice_context_from_assembled(_assembled())
    generator = FakeCandidateExerciseGenerator()
    first = await generator.generate(context, count=2)
    second = await generator.generate(context, count=2)
    # candidate_id is a fresh UUID per generation; the CONTENT is
    # deterministic for identical contexts.
    assert [c.problem_statement for c in first] == [c.problem_statement for c in second]
    assert first[0].model_dump(exclude={"candidate_id"}) == second[0].model_dump(
        exclude={"candidate_id"}
    )
    assert len(first) == 2
    candidate = first[0]
    assert candidate.student_id == context.student_id
    assert candidate.skill_ids == context.target_skill_ids
    assert candidate.difficulty == context.desired_difficulty
    assert candidate.generated_by == "mt-fake-candidate-v1"
    assert candidate.context_version == PRACTICE_CONTEXT_VERSION
    assert candidate.provenance == context.provenance


def test_fake_statement_mentions_weakest_skill_and_active_rules():
    context = practice_context_from_assembled(
        _assembled(), target_skill_ids=("LINEAR_EQUATION",)
    )
    statement = _build_statement_for_test(context)
    assert "LINEAR_EQUATION" in statement  # weakest mastered skill (0.45)
    assert "rule-sign-error" in statement
    assert "难度等级 2/5" in statement


def _build_statement_for_test(context: PracticeGenerationContext) -> str:
    from mathtutor.application.adaptive_practice import _build_statement

    return _build_statement(context, 0)


# ------------------------------------------------------- end-to-end service


def _practice_providers():
    """REQUIRED loaded + OPTIONAL memory loaded + documents retrievable."""
    providers = {
        RetrievalSource.STUDENT_MODEL: StubProvider(
            RetrievalSource.STUDENT_MODEL,
            on_load=LoadOutcome(
                payload=StudentModelContext(
                    estimator_version="mvp-v1",
                    projection_version=1,
                    skill_mastery=(MasteryEntry(skill_id="LINEAR_EQUATION", mastery=0.45),),
                )
            ),
        ),
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM,
            on_load=LoadOutcome(
                payload=CurriculumContext(
                    version_code="mt-curriculum-mvp-v1",
                    nodes=(CurriculumNodeRef(node_id="LINEAR_EQUATION", code="LINEAR_EQUATION", kind="skill", title="一元一次方程"),),
                )
            ),
        ),
        RetrievalSource.MISCONCEPTION_HISTORY: StubProvider(
            RetrievalSource.MISCONCEPTION_HISTORY,
            on_load=LoadOutcome(empty_data=True, detail="no observations yet"),
        ),
        RetrievalSource.RECENT_ATTEMPTS: StubProvider(
            RetrievalSource.RECENT_ATTEMPTS,
            on_load=LoadOutcome(empty_data=True, detail="no attempts yet"),
        ),
        RetrievalSource.PERSONAL_MEMORY: StubProvider(
            RetrievalSource.PERSONAL_MEMORY,
            on_load=LoadOutcome(
                payload=PersonalMemoryContext(
                    entries=(
                        MemoryContextEntry(
                            memory_id=uuid4(),
                            memory_type="learning_preference",
                            subject="节奏",
                            predicate="喜欢",
                            object_json={"pace": "慢一点"},
                            source_type="USER_EXPLICIT",
                            confidence=0.9,
                        ),
                    )
                )
            ),
        ),
        RetrievalSource.USER_DOCUMENTS: StubProvider(
            RetrievalSource.USER_DOCUMENTS,
            on_retrieve=LoadOutcome(empty_data=True, detail="no document hits"),
        ),
    }
    return providers


async def test_service_generate_candidates_end_to_end():
    providers = _practice_providers()
    assembler = ContextAssembler(providers=providers)
    service = AdaptivePracticeService(assembler=assembler, desired_difficulty=3)
    candidates = await service.generate_candidates(
        _STUDENT, target_skill_ids=["LINEAR_EQUATION"], count=2
    )
    assert len(candidates) == 2
    candidate = candidates[0]
    assert candidate.skill_ids == ("LINEAR_EQUATION",)
    assert candidate.difficulty == 3
    assert candidate.generated_by == "mt-fake-candidate-v1"
    assert candidate.student_id == student_uuid(_STUDENT)
    assert "LINEAR_EQUATION" in candidate.problem_statement
    # The generator received the assembled context: REQUIRED all loaded,
    # provenance explains every source.
    statuses = {p.source: p.status for p in candidate.provenance}
    assert statuses[RetrievalSource.STUDENT_MODEL] == "loaded"
    assert statuses[RetrievalSource.MISCONCEPTION_HISTORY] == "empty"
    assert statuses[RetrievalSource.RECENT_ATTEMPTS] == "empty"
    assert statuses[RetrievalSource.PERSONAL_MEMORY] == "loaded"


async def test_service_fails_closed_when_required_unavailable():
    service = AdaptivePracticeService(assembler=ContextAssembler(providers={}))
    with pytest.raises(Exception):
        await service.generate_candidates(_STUDENT)


async def test_generate_candidates_query_is_chinese_not_skill_code():
    providers = _practice_providers()
    service = AdaptivePracticeService(
        assembler=ContextAssembler(providers=providers), desired_difficulty=3
    )
    await service.generate_candidates(_STUDENT, target_skill_ids=["LINEAR_EQUATION"])
    calls = providers[RetrievalSource.USER_DOCUMENTS].retrieve_calls
    assert calls, "documents must be queried when a Chinese hint exists"
    hint = calls[0]["query_hint"]
    assert "一元一次方程" in hint
    assert "LINEAR_EQUATION" not in hint.split()
    assert hint.strip() != "LINEAR_EQUATION"


async def test_chain_consumes_document_context_instead_of_bank():
    from mathtutor.application.llm_candidate_generator import (
        PracticeGeneratorChain,
        build_llm_prompt,
        has_usable_document_context,
    )

    context = practice_context_from_assembled(
        _assembled(with_documents=True), target_skill_ids=("LINEAR_EQUATION",)
    )
    assert has_usable_document_context(context)
    prompt = build_llm_prompt(context)
    assert "document_context" in prompt
    assert "错题本.md" in prompt
    assert "sequence" in prompt
    assert "score" in prompt
    assert "移项时忘记变号" in prompt

    chain = PracticeGeneratorChain(gateway=None)
    candidates = await chain.generate(context, count=1)
    assert candidates
    assert candidates[0].generated_by == "mt-template-document-grounded-v1"
    assert not candidates[0].generated_by.startswith("mt-bank-")


def test_build_retrieval_query_joins_titles_aliases_and_problem():
    from mathtutor.application.retrieval_query import build_retrieval_query

    query = build_retrieval_query(
        skill_ids=("LINEAR_EQUATION",),
        problem_text="解方程 2x+3=7",
        misconception_ids=("miscon-transposition-error",),
    )
    assert "一元一次方程" in query
    assert "移项" in query
    assert "解方程 2x+3=7" in query
    assert "LINEAR_EQUATION" not in query.split()
