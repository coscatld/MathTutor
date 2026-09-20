"""ContextAssembler tests (§37 CONTEXT group).

The assembler is the ONLY path from repositories to LLM consumers.
Tested here: the REQUIRED three-state semantics (empty / disabled_by_user
/ fail-closed), OPTIONAL routing (budget + query hint), provenance for
every source, and the document-selection projection (capped text,
ranked selections). Personal memory permission is enforced at the DATA
layer, so the assembler can never pull a disabled memory.
"""

from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

import pytest

from mathtutor.application.context_assembler import (
    BaseContextSourceProvider,
    ContextAssembler,
    ContextRouter,
    LoadOutcome,
    PersonalMemorySourceProvider,
    RequiredSourceUnavailableError,
    StaticCurriculumProvider,
    TokenBudget,
    UserDocumentsSourceProvider,
    estimate_payload_tokens,
    estimate_text_tokens,
)
from mathtutor.domain.assembled_context import (
    AttemptSummaryEntry as AssembledAttemptEntry,
)
from mathtutor.domain.assembled_context import (
    CurriculumContext,
    CurriculumNodeRef,
    DocumentChunkRef,
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
from mathtutor.domain.retrieval_policy import (
    RetrievalIntent,
    RetrievalPolicy,
    RetrievalSource,
)
from mathtutor.application.conversation_scope import (
    reset_document_scope,
    set_document_scope,
)
from mathtutor.repositories.memory_repository import InMemoryMemoryRepository
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


def _student_model(*, skill_ids=("LINEAR_EQUATION",), mastery=0.6, active=("rule-sign-error",)):
    return StudentModelContext(
        estimator_version="mvp-v1",
        projection_version=3,
        skill_mastery=tuple(MasteryEntry(skill_id=sid, mastery=mastery) for sid in skill_ids),
        active_misconception_rule_ids=tuple(active),
    )


def _providers_for_practice() -> dict[RetrievalSource, StubProvider]:
    """All four REQUIRED sources loaded, optionals loaded (happy path)."""
    return {
        RetrievalSource.STUDENT_MODEL: StubProvider(
            RetrievalSource.STUDENT_MODEL, on_load=LoadOutcome(payload=_student_model())
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
            on_load=LoadOutcome(
                payload=MisconceptionContext(
                    entries=(MisconceptionEntry(rule_id="rule-sign-error", observation_count=2),)
                )
            ),
        ),
        RetrievalSource.RECENT_ATTEMPTS: StubProvider(
            RetrievalSource.RECENT_ATTEMPTS,
            on_load=LoadOutcome(
                payload=RecentAttemptsContext(
                    entries=(
                        AssembledAttemptEntry(
                            skill_id="LINEAR_EQUATION",
                            correctness="incorrect",
                            effective_assistance_level=1,
                            attempt_index=2,
                        ),
                    )
                )
            ),
        ),
        RetrievalSource.PERSONAL_MEMORY: StubProvider(
            RetrievalSource.PERSONAL_MEMORY,
            on_load=LoadOutcome(
                payload=PersonalMemoryContext(
                    entries=(
                        MemoryContextEntry(
                            memory_id=UUID(int=1),
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
    }



class StubOrchestrator:
    """Stands in for ConversationRetrievalOrchestrator in projection tests.

    The provider no longer searches (F1): it projects an EvidencePack. These
    tests therefore exercise the PROJECTION, while retrieval/ranking themselves
    are covered by tests/test_retrieval_orchestration.py.
    """

    def __init__(self, result: DocumentQueryResult):
        self.result = result
        self.calls: list = []

    async def retrieve_for_turn(self, owner, document_ids, user_query, **kwargs):
        from mathtutor.domain.evidence import (
            Evidence,
            RetrievalExecution,
            build_evidence_pack,
            make_source_id,
            text_hash,
        )

        self.calls.append({"document_ids": list(document_ids)})
        evidences = [
            Evidence(
                source_id=make_source_id(hit.document_id, hit.chunk.chunk_id),
                document_id=hit.document_id,
                filename=hit.filename,
                chunk_id=hit.chunk.chunk_id,
                sequence=hit.chunk.sequence,
                page=hit.chunk.page,
                section=hit.chunk.section,
                text=hit.chunk.text,
                text_hash=text_hash(hit.chunk.text),
                score=hit.score,
                lexical_score=hit.lexical_score,
                rerank_score=hit.score,
            )
            for hit in self.result.hits
        ]
        return build_evidence_pack(
            query=user_query,
            evidences=evidences,
            execution=RetrievalExecution(retrieval_ran=True, decision="conversation_documents"),
        )


# --------------------------------------------------------- budget / estimates


def test_estimate_and_budget_accounting():
    assert estimate_text_tokens("") == 1  # never zero — conservative floor
    assert estimate_text_tokens("二次方程") == 2
    assert estimate_payload_tokens(CurriculumContext(version_code="v")) > 0
    budget = TokenBudget(100)
    assert budget.remaining() == 100
    budget.consume(30)
    assert budget.remaining() == 70


# ------------------------------------------------------- REQUIRED semantics


async def test_missing_required_provider_fails_closed():
    assembler = ContextAssembler(providers={})  # nothing registered
    with pytest.raises(RequiredSourceUnavailableError):
        await assembler.assemble(
            student_id=_STUDENT, intent=RetrievalIntent.GENERATE_PRACTICE
        )


async def test_unavailable_required_source_fails_closed():
    assembler = ContextAssembler(
        providers={
            RetrievalSource.STUDENT_MODEL: StubProvider(RetrievalSource.STUDENT_MODEL),
        }
    )
    # Default stub load returns neither empty nor disabled → genuinely unavailable.
    with pytest.raises(RequiredSourceUnavailableError):
        await assembler.assemble(
            student_id=_STUDENT, intent=RetrievalIntent.GENERATE_PRACTICE
        )


async def test_required_empty_data_is_legitimate_new_student():
    empty = LoadOutcome(empty_data=True, detail="no data yet")
    providers = {
        RetrievalSource.STUDENT_MODEL: StubProvider(RetrievalSource.STUDENT_MODEL, on_load=empty),
        RetrievalSource.CURRICULUM: StubProvider(RetrievalSource.CURRICULUM, on_load=empty),
        RetrievalSource.MISCONCEPTION_HISTORY: StubProvider(
            RetrievalSource.MISCONCEPTION_HISTORY, on_load=empty
        ),
        RetrievalSource.RECENT_ATTEMPTS: StubProvider(
            RetrievalSource.RECENT_ATTEMPTS, on_load=empty
        ),
    }
    context = await ContextAssembler(providers=providers).assemble(
        student_id=_STUDENT, intent=RetrievalIntent.GENERATE_PRACTICE
    )
    assert context.student_model is None
    for source in (
        RetrievalSource.STUDENT_MODEL,
        RetrievalSource.CURRICULUM,
        RetrievalSource.MISCONCEPTION_HISTORY,
        RetrievalSource.RECENT_ATTEMPTS,
    ):
        assert context.provenance_for(source).status == "empty"


async def test_disabled_by_user_outranks_required():
    providers = _providers_for_practice()
    providers[RetrievalSource.STUDENT_MODEL] = StubProvider(
        RetrievalSource.STUDENT_MODEL,
        on_load=LoadOutcome(disabled_by_user=True, detail="user disabled"),
    )
    context = await ContextAssembler(providers=providers).assemble(
        student_id=_STUDENT, intent=RetrievalIntent.GENERATE_PRACTICE
    )
    # User permission outranks the policy matrix: recorded, NOT fatal.
    entry = context.provenance_for(RetrievalSource.STUDENT_MODEL)
    assert entry.status == "disabled_by_user"
    assert context.student_model is None


# ------------------------------------------------------- OPTIONAL routing


async def test_forbidden_sources_recorded_structurally_absent():
    # SOLVE_PROBLEM: misconception history + recent attempts are FORBIDDEN.
    providers = {
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM,
            on_load=LoadOutcome(payload=CurriculumContext(version_code="v")),
        ),
    }
    context = await ContextAssembler(providers=providers).assemble(
        student_id=_STUDENT, intent=RetrievalIntent.SOLVE_PROBLEM
    )
    assert context.provenance_for(RetrievalSource.MISCONCEPTION_HISTORY).status == "forbidden"
    assert context.provenance_for(RetrievalSource.RECENT_ATTEMPTS).status == "forbidden"
    assert context.misconception_history is None


async def test_router_skips_documents_without_query_hint():
    providers = {
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM,
            on_load=LoadOutcome(payload=CurriculumContext(version_code="v")),
        ),
        RetrievalSource.PERSONAL_MEMORY: StubProvider(
            RetrievalSource.PERSONAL_MEMORY,
            on_load=LoadOutcome(payload=PersonalMemoryContext(entries=())),
        ),
        RetrievalSource.USER_DOCUMENTS: StubProvider(RetrievalSource.USER_DOCUMENTS),
    }
    context = await ContextAssembler(providers=providers).assemble(
        student_id=_STUDENT, intent=RetrievalIntent.SOLVE_PROBLEM, query_hint=""
    )
    assert context.provenance_for(RetrievalSource.USER_DOCUMENTS).status == "router_skipped"
    assert providers[RetrievalSource.USER_DOCUMENTS].retrieve_calls == []  # never called


async def test_optional_trimmed_by_token_budget():
    # Tiny budget + zero floor: REQUIRED loads consume the budget, the
    # OPTIONAL student-model payload no longer fits → budget_trimmed.
    providers = {
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM,
            on_load=LoadOutcome(payload=CurriculumContext(version_code="v", nodes=())),
        ),
        RetrievalSource.STUDENT_MODEL: StubProvider(
            RetrievalSource.STUDENT_MODEL, on_load=LoadOutcome(payload=_student_model())
        ),
    }
    assembler = ContextAssembler(
        providers=providers,
        token_budget=30,
        router=ContextRouter(optional_floor_tokens=0),
    )
    context = await assembler.assemble(
        student_id=_STUDENT, intent=RetrievalIntent.SOLVE_PROBLEM
    )
    entry = context.provenance_for(RetrievalSource.STUDENT_MODEL)
    assert entry.status == "budget_trimmed"
    assert context.student_model is None  # never leaked past the budget


async def test_optional_source_loaded_and_provenanced():
    providers = _providers_for_practice()
    context = await ContextAssembler(providers=providers).assemble(
        student_id=_STUDENT,
        intent=RetrievalIntent.GENERATE_PRACTICE,
        query_hint="解一元一次方程",
    )
    memory_entry = context.provenance_for(RetrievalSource.PERSONAL_MEMORY)
    assert memory_entry.status == "loaded"
    assert memory_entry.item_count == 1
    assert context.personal_memory.entries[0].object_json == {"pace": "慢一点"}
    assert context.policy_version == RetrievalPolicy.POLICY_VERSION
    assert context.student_id == student_uuid(_STUDENT)


# ------------------------------------------------- documents (USE_MY_DOCUMENT)


def _hit(
    document_id: UUID,
    *,
    filename: str,
    sequence: int,
    text: str,
    score: float,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk=DocumentChunk(
            document_id=document_id,
            student_id=UUID(int=1),
            sequence=sequence,
            text=text,
            content_hash="h",
            chunker_version="mt-chunker-v1",
        ),
        document_id=document_id,
        filename=filename,
        score=score,
        lexical_score=score,
    )


class StubSearchable:
    """Fake DocumentSearchable returning a canned DocumentQueryResult."""

    def __init__(self, result: DocumentQueryResult):
        self._result = result

    async def search(self, student_id, *, query, limit=5, document_ids=None):
        return self._result


async def test_use_my_document_requires_provider_fails_closed():
    providers = {
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM,
            on_load=LoadOutcome(payload=CurriculumContext(version_code="v")),
        ),
        # USER_DOCUMENTS is REQUIRED for USE_MY_DOCUMENT but unregistered.
    }
    with pytest.raises(RequiredSourceUnavailableError):
        await ContextAssembler(providers=providers).assemble(
            student_id=_STUDENT,
            intent=RetrievalIntent.USE_MY_DOCUMENT,
            query_hint="求根公式",
        )


async def test_use_my_document_no_hits_is_empty_state():
    providers = {
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM,
            on_load=LoadOutcome(payload=CurriculumContext(version_code="v")),
        ),
        RetrievalSource.USER_DOCUMENTS: UserDocumentsSourceProvider(
            orchestrator=StubOrchestrator(
                DocumentQueryResult(query="求根公式", hits=(), degraded=True)
            )
        ),
    }
    context = await ContextAssembler(providers=providers).assemble(
        student_id=_STUDENT, intent=RetrievalIntent.USE_MY_DOCUMENT, query_hint="求根公式"
    )
    assert context.provenance_for(RetrievalSource.USER_DOCUMENTS).status == "empty"
    assert context.user_documents == ()


async def test_document_selection_projected_ranked_and_capped():
    doc_a = UUID(int=10)
    doc_b = UUID(int=11)
    result = DocumentQueryResult(
        query="求根公式",
        hits=(
            _hit(doc_a, filename="a.md", sequence=0, text="A0" * 400, score=0.7),
            _hit(doc_b, filename="b.md", sequence=0, text="B0", score=0.9),
            _hit(doc_a, filename="a.md", sequence=1, text="A1", score=0.5),
        ),
        degraded=True,
    )
    providers = {
        RetrievalSource.CURRICULUM: StubProvider(
            RetrievalSource.CURRICULUM,
            on_load=LoadOutcome(payload=CurriculumContext(version_code="v")),
        ),
        RetrievalSource.USER_DOCUMENTS: UserDocumentsSourceProvider(
            orchestrator=StubOrchestrator(result)
        ),
    }
    # Production always establishes the conversation scope before the
    # controller runs (math_tutor_ws.py:312). Retrieval is no longer allowed
    # to fall back to owner-wide when that scope is absent.
    token = set_document_scope([doc_a, doc_b])
    try:
        context = await ContextAssembler(providers=providers).assemble(
            student_id=_STUDENT, intent=RetrievalIntent.USE_MY_DOCUMENT, query_hint="求根公式"
        )
    finally:
        reset_document_scope(token)
    # NOTE: this exercises the PROJECTION (EvidencePack -> DocumentContextSelection).
    # Retrieval itself is covered by test_retrieval_orchestration.py; the
    # provider deliberately has no search of its own any more (F1).
    assert context.provenance_for(RetrievalSource.USER_DOCUMENTS).status == "loaded"
    selections = context.user_documents
    assert [s.document_id for s in selections] == [doc_b, doc_a]  # ranked by max score
    assert selections[0].filename == "b.md"
    assert selections[0].chunks[0].filename == "b.md"
    assert selections[0].chunks[0].sequence == 0
    assert selections[0].chunks[0].score == 0.9
    assert len(selections[1].chunks) == 2  # both chunks of doc a grouped
    # Per-chunk text projection is capped for LLM consumers.
    long_ref = selections[1].chunks[0]
    assert len(long_ref.text) <= 600
    assert all(isinstance(chunk, DocumentChunkRef) for chunk in selections[1].chunks)


# ----------------------------------------------- personal memory data layer


async def test_personal_memory_disabled_enforced_at_data_layer():
    from mathtutor.application.personal_memory_service import PersonalMemoryService

    repo = InMemoryMemoryRepository()
    svc = PersonalMemoryService(repo)
    node = await svc.add_explicit(
        _STUDENT,
        memory_type="user_note",
        subject="秘密",
        predicate="记",
        object_json={"note": "不要给 AI"},
    )
    await svc.set_retrieval_enabled(_STUDENT, node.memory_id, False)

    provider = PersonalMemorySourceProvider(repo)
    outcome = await provider.load(
        student_id=_STUDENT, intent=RetrievalIntent.SOLVE_PROBLEM
    )
    assert outcome.disabled_by_user is True  # live memory exists but hidden


async def test_personal_memory_empty_data_for_new_student():
    provider = PersonalMemorySourceProvider(InMemoryMemoryRepository())
    outcome = await provider.load(
        student_id=_STUDENT, intent=RetrievalIntent.SOLVE_PROBLEM
    )
    assert outcome.empty_data is True


# --------------------------------------------------------------- curriculum


async def test_static_curriculum_provider_filters_nodes():
    provider = StaticCurriculumProvider()
    outcome = await provider.load(student_id=_STUDENT, intent=RetrievalIntent.SOLVE_PROBLEM)
    assert outcome.payload.version_code == "mt-curriculum-mvp-v1"
    assert len(outcome.payload.nodes) == 10  # 5 supported families + 5 concepts
    assert {node.node_id for node in outcome.payload.nodes if node.kind == "skill"} == {
        "ARITHMETIC", "POLYNOMIAL_BASIC", "LINEAR_EQUATION", "QUADRATIC_EQUATION", "LINEAR_SYSTEM",
    }
    assert "CONCEPT_LINEAR_SYSTEMS" in {node.node_id for node in outcome.payload.nodes}

    sliced = await provider.load(
        student_id=_STUDENT,
        intent=RetrievalIntent.SOLVE_PROBLEM,
        node_ids=["LINEAR_EQUATION"],
    )
    assert [n.node_id for n in sliced.payload.nodes] == ["LINEAR_EQUATION"]
