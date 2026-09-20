"""Retrieval Safety Hardening (Phase A2) — scope fail-closed + visibility gate.

Two defects closed here, both recorded in docs/CURRENT_STATE_RAG_AUDIT.md:

D1  ``current_document_scope()`` returns ``None`` when no scope was set, and
    the repository reads ``document_ids=None`` as "no filter" — i.e. every
    document the owner has. A caller outside a conversation turn therefore
    retrieved owner-wide instead of failing closed.

D11 ``list_chunks`` is owner-scoped only. Feeding retrieved text to a model
    was safe *only* because the one caller happened to pass documents drawn
    from its own pre-filtered list; the data layer held no independent guard.

These tests pin the fixed behaviour so neither regression can return.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from mathtutor.application.chat_documents import ChatDocumentContext
from mathtutor.application.context_assembler import (
    ContextAssembler,
    StaticCurriculumProvider,
    UserDocumentsSourceProvider,
)
from mathtutor.application.conversation_scope import (
    current_document_scope,
    reset_document_scope,
    set_document_scope,
)
from mathtutor.application.desktop_files import PickedFile
from mathtutor.application.document_ingestion import DocumentIngestionService
from mathtutor.domain.documents import DocumentChunk, UserDocument
from mathtutor.domain.retrieval_policy import RetrievalIntent, RetrievalSource
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.repositories.document_repository import InMemoryDocumentRepository
from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.security.scopes import student_uuid

pytestmark = pytest.mark.asyncio

_OWNER = "safety-owner"
_OTHER = "safety-other"
_BODY = "一元二次方程的求根公式是 x = (-b ± √(b²-4ac)) / (2a)。".encode("utf-8")


# --------------------------------------------------------------- helpers


def _async_return(value):
    async def _call(*args, **kwargs):
        return value

    return _call


def _doc(**overrides) -> UserDocument:
    values = dict(
        document_id=uuid4(),
        student_id=student_uuid(_OWNER),
        filename="安全.txt",
        mime_type="text/plain",
        content_hash="h",
        storage_ref="r",
        status="ready",
        size_bytes=1,
        chunk_count=1,
    )
    values.update(overrides)
    return UserDocument(**values)


def _chunk(document_id: UUID, text: str = "内容") -> DocumentChunk:
    return DocumentChunk(
        chunk_id=uuid4(),
        student_id=student_uuid(_OWNER),
        document_id=document_id,
        sequence=0,
        text=text,
        content_hash="chunk-hash",
    )


class _CountingSearchable:
    """Records whether search was reached at all."""

    def __init__(self) -> None:
        self.calls = 0

    async def search(self, student_id, *, query, limit=5, document_ids=None):
        self.calls += 1
        return SimpleNamespace(hits=(), vector_used=False)


# ------------------------------------------------- D1 scope fails closed


async def test_no_scope_does_not_retrieve_owner_wide():
    """The regression: scope None used to mean "filter nothing"."""
    searchable = _CountingSearchable()
    assert current_document_scope() is None, "no scope is set in this task"

    outcome = await UserDocumentsSourceProvider(searchable).retrieve(
        student_id=_OWNER, intent=RetrievalIntent.USE_MY_DOCUMENT, query_hint="求根公式"
    )

    assert outcome.payload is None
    assert outcome.empty_data is True
    assert outcome.detail == "no conversation document scope"
    assert searchable.calls == 0, "an unset scope must never reach the retriever"


async def test_empty_scope_is_distinguishable_from_unset_scope():
    token = set_document_scope([])
    try:
        outcome = await UserDocumentsSourceProvider(_CountingSearchable()).retrieve(
            student_id=_OWNER, intent=RetrievalIntent.USE_MY_DOCUMENT, query_hint="求根公式"
        )
    finally:
        reset_document_scope(token)

    assert outcome.empty_data is True
    assert outcome.detail == "conversation has no documents"


async def test_assembler_without_scope_yields_no_document_source():
    """End-to-end through the assembler, not just the provider.

    USER_DOCUMENTS under USE_MY_DOCUMENT is REQUIRED, so a fail-open here
    would not merely be an empty result — it would pull every document the
    student owns into a REQUIRED source.
    """
    searchable = _CountingSearchable()
    assembler = ContextAssembler(
        providers={
            # USE_MY_DOCUMENT also REQUIRES curriculum; the document source is
            # the one under test.
            RetrievalSource.CURRICULUM: StaticCurriculumProvider(),
            RetrievalSource.USER_DOCUMENTS: UserDocumentsSourceProvider(searchable),
        }
    )
    assert current_document_scope() is None

    context = await assembler.assemble(
        student_id=_OWNER, intent=RetrievalIntent.USE_MY_DOCUMENT, query_hint="求根公式"
    )

    assert context.user_documents == ()
    assert searchable.calls == 0
    record = context.provenance_for(RetrievalSource.USER_DOCUMENTS)
    assert record is not None and record.status == "empty"
    assert record.detail == "no conversation document scope"


async def test_scoped_retrieval_still_works():
    """The fix must not break the legitimate path.

    Since F1 the legitimate path is the shared orchestrator, not a search of
    the provider's own: the provider is a projection adapter now.
    """

    class _Orchestrator:
        def __init__(self):
            self.calls = 0

        async def retrieve_for_turn(self, owner, document_ids, user_query, **kwargs):
            self.calls += 1
            from mathtutor.domain.evidence import RetrievalExecution, build_evidence_pack

            return build_evidence_pack(
                query=user_query,
                evidences=[],
                execution=RetrievalExecution(retrieval_ran=True, decision="conversation_documents"),
            )

    orchestrator = _Orchestrator()
    token = set_document_scope([uuid4()])
    try:
        outcome = await UserDocumentsSourceProvider(orchestrator=orchestrator).retrieve(
            student_id=_OWNER, intent=RetrievalIntent.USE_MY_DOCUMENT, query_hint="求根公式"
        )
    finally:
        reset_document_scope(token)

    assert orchestrator.calls == 1
    assert outcome.empty_data is True  # ran, found nothing — not "blocked"


# ------------------------------------------- D11 visibility gate (memory)


def _memory_repo(doc: UserDocument, chunks: list[DocumentChunk]) -> InMemoryDocumentRepository:
    repo = InMemoryDocumentRepository()
    repo._documents[doc.document_id] = doc
    repo._chunks[doc.document_id] = chunks
    return repo


@pytest.mark.parametrize(
    "overrides,visible",
    [
        ({}, True),
        ({"retrieval_enabled": False}, False),
        ({"status": "needs_ocr"}, False),
        ({"status": "failed"}, False),
        ({"status": "ready_with_warnings"}, True),
        ({"chunk_count": 0}, True),  # is_retrievable() ignores the count on purpose
    ],
)
async def test_list_retrievable_chunks_enforces_document_visibility(overrides, visible):
    doc = _doc(**overrides)
    repo = _memory_repo(doc, [_chunk(doc.document_id)])

    result = await repo.list_retrievable_chunks(_OWNER, doc.document_id)

    assert bool(result) is visible


async def test_list_retrievable_chunks_rejects_soft_deleted_and_cross_owner():
    from datetime import datetime, timezone

    doc = _doc(deleted_at=datetime.now(timezone.utc))
    repo = _memory_repo(doc, [_chunk(doc.document_id)])
    assert await repo.list_retrievable_chunks(_OWNER, doc.document_id) == []

    live = _doc()
    repo = _memory_repo(live, [_chunk(live.document_id)])
    assert await repo.list_retrievable_chunks(_OTHER, live.document_id) == []
    assert await repo.list_retrievable_chunks(_OWNER, live.document_id) != []


async def test_list_chunks_stays_permissive_for_versioning():
    """snapshot()/build_index() must still read disabled documents."""
    doc = _doc(retrieval_enabled=False)
    repo = _memory_repo(doc, [_chunk(doc.document_id)])

    assert len(await repo.list_chunks(_OWNER, doc.document_id)) == 1
    assert await repo.list_retrievable_chunks(_OWNER, doc.document_id) == []


# --------------------------------------------- D11 visibility gate (SQL)


@pytest_asyncio.fixture()
async def sqlite_repo(tmp_path):
    db_file = tmp_path / "rag.db"
    upgrade_db(str(db_file))
    engine = create_db_engine(db_file)
    yield SQLiteDocumentRepository(engine), DocumentIngestionService(
        repository=SQLiteDocumentRepository(engine),
        storage=DocumentStorage(tmp_path / "data"),
        index_manager=None,
    )
    await engine.dispose()


async def _ingest(service: DocumentIngestionService, owner: str = _OWNER):
    return await service.ingest(
        owner, PickedFile(filename="安全.txt", mime_type="text/plain", data=_BODY)
    )


async def test_sqlite_visibility_gate_matches_search_exactly(sqlite_repo):
    repo, service = sqlite_repo
    doc = await _ingest(service)
    assert await repo.list_retrievable_chunks(_OWNER, doc.document_id)

    await repo.set_retrieval_enabled(_OWNER, doc.document_id, False)
    assert await repo.list_retrievable_chunks(_OWNER, doc.document_id) == []
    assert await repo.list_chunks(_OWNER, doc.document_id) != []

    await repo.set_retrieval_enabled(_OWNER, doc.document_id, True)
    assert await repo.list_retrievable_chunks(_OWNER, doc.document_id) != []

    await repo.soft_delete_document(_OWNER, doc.document_id)
    assert await repo.list_retrievable_chunks(_OWNER, doc.document_id) == []


async def test_sqlite_visibility_gate_rejects_cross_owner(sqlite_repo):
    repo, service = sqlite_repo
    doc = await _ingest(service)
    assert await repo.list_retrievable_chunks(_OTHER, doc.document_id) == []


# --------------------------------------------------- D11 chat integration


async def test_chat_overview_never_reads_a_disabled_document():
    """A disabled document must not reach the chat projection at all.

    Neither through retrieval (it never becomes a candidate) nor through the
    overview fallback (only eligible documents are read).
    """
    from mathtutor.domain.documents import DocumentQueryResult
    from mathtutor.domain.retrieval_policy import RetrievalSource  # noqa: F401

    doc_id = uuid4()
    chunk = SimpleNamespace(chunk_id=uuid4(), sequence=0, text="秘密内容" * 20)
    doc = SimpleNamespace(
        document_id=doc_id,
        filename="禁用.txt",
        deleted_at=None,
        status="ready",
        retrieval_enabled=False,  # disabled by the user
        can_enable_retrieval=lambda: True,
    )
    documents = SimpleNamespace(get_document=_async_return(doc))
    guarded = SimpleNamespace(
        list_retrievable_chunks=_async_return([]),
        list_chunks=_async_return([chunk]),
    )
    searches: list[dict] = []

    class _Kernel:
        async def search(self, sid, *, query, limit=5, document_ids=None):
            searches.append({"document_ids": document_ids})
            return DocumentQueryResult(query=query, hits=(), vector_used=False, degraded=True)

    service = ChatDocumentContext(documents, guarded, _Kernel())
    token = set_document_scope([doc_id])
    try:
        result = await service.build(_OWNER, "请总结这个文档")
    finally:
        reset_document_scope(token)

    assert result["chunks"] == []
    assert searches == [], "a disabled document must not even be searched"


def _async_return(value):
    async def _call(*args, **kwargs):
        return value

    return _call
