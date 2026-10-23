"""Embedding abstraction + index lifecycle tests (§37 EMBEDDING group).

Everything here runs on the deterministic FAKE backend — no model weights,
no network. It proves the CONTRACT the index lifecycle depends on:
determinism, descriptor versioning, degrade-without-backend, and
rebuild-on-signature-change without re-importing files.
"""

from __future__ import annotations

import math
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from mathtutor.application.document_ingestion import DocumentIndexManager
from mathtutor.domain.documents import DocumentChunk, UserDocument
from mathtutor.domain.embedding import (
    EmbeddingDescriptor,
    EmbeddingUnavailableError,
    validate_vector,
)
from mathtutor.infrastructure.embedding_runtime import (
    FAKE_BACKEND_ID,
    FAKE_DIMENSION,
    FAKE_MODEL_ID,
    EmbeddingRuntime,
    FakeEmbeddingBackend,
    build_fake_embedding_runtime,
)
from mathtutor.repositories.document_repository import InMemoryDocumentRepository

pytestmark = pytest.mark.asyncio

_STUDENT = "student-a"


@pytest.fixture()
def fake_backend() -> FakeEmbeddingBackend:
    return FakeEmbeddingBackend()


async def test_fake_backend_is_deterministic(fake_backend):
    text = "一元二次方程的求根公式"
    first = await fake_backend.embed_texts([text, text])
    second = await fake_backend.embed_texts([text])
    assert first[0] == first[1] == second[0]


async def test_fake_backend_dimension_and_normalization(fake_backend):
    vector = await fake_backend.embed_query("判别式")
    assert len(vector) == FAKE_DIMENSION
    norm = math.sqrt(sum(v * v for v in vector))
    assert math.isclose(norm, 1.0, rel_tol=1e-9)


async def test_fake_backend_different_texts_differ(fake_backend):
    a = await fake_backend.embed_query("加法")
    b = await fake_backend.embed_query("乘法分配律")
    assert a != b


def test_descriptor_signature_changes_on_model_change():
    base = EmbeddingDescriptor(
        backend_id=FAKE_BACKEND_ID,
        model_id=FAKE_MODEL_ID,
        model_version="1",
        dimension=FAKE_DIMENSION,
    )
    changed = base.model_copy(update={"model_id": "fake-hash-v2"})
    assert base.index_signature() != changed.index_signature()
    assert changed.index_signature().count("|") == 4


def test_validate_vector_rejects_mismatch_and_nonfinite():
    descriptor = EmbeddingDescriptor(
        backend_id="b", model_id="m", model_version="1", dimension=4
    )
    with pytest.raises(ValueError):
        validate_vector(descriptor, (0.1, 0.2, 0.3))
    with pytest.raises(ValueError):
        validate_vector(descriptor, (0.1, float("nan"), 0.3, 0.4))
    validate_vector(descriptor, (0.1, 0.2, 0.3, 0.4))  # passes


async def test_unavailable_runtime_raises_on_vectors():
    runtime = EmbeddingRuntime()  # no backend — the DEFERRED default
    status = runtime.status()
    assert status.available is False
    with pytest.raises(EmbeddingUnavailableError):
        await runtime.embed_texts(["text"])
    with pytest.raises(EmbeddingUnavailableError):
        await runtime.embed_query("text")


async def test_build_fake_runtime_status():
    runtime = build_fake_embedding_runtime()
    status = runtime.status()
    assert status.available is True
    assert status.descriptor.backend_id == FAKE_BACKEND_ID


# ------------------------------------------------------- index lifecycle


@pytest_asyncio.fixture()
async def seeded() -> tuple[InMemoryDocumentRepository, UserDocument]:
    repo = InMemoryDocumentRepository()
    doc = await repo.add_document(
        _STUDENT,
        UserDocument(
            student_id=uuid4(),  # repository stamps the real owner
            filename="notes.md",
            mime_type="text/markdown",
            content_hash="hash-1",
            storage_ref="uploads/x/y/notes.md",
            status="ready",
            size_bytes=10,
            parser_version="mt-local-parser-v1",
        ),
    )
    chunks = [
        DocumentChunk(
            student_id=uuid4(),  # repository stamps the real owner
            document_id=doc.document_id,
            sequence=i,
            text=text,
            content_hash=f"chunk-hash-{i}",
            chunker_version="mt-chunker-v1",
        )
        for i, text in enumerate(("二次方程的求根公式", "判别式决定根的数量"))
    ]
    await repo.replace_chunks(_STUDENT, doc.document_id, chunks)
    return repo, doc


async def test_build_index_and_idempotence(seeded):
    repo, doc = seeded
    manager = DocumentIndexManager(
        repository=repo, embedding_runtime=build_fake_embedding_runtime()
    )
    record = await manager.build_index(_STUDENT, doc.document_id)
    assert record is not None
    assert record.index_version == 1
    assert record.embedding_backend_id == FAKE_BACKEND_ID
    assert await manager.is_current(_STUDENT, doc.document_id)

    vectors = await repo.get_vectors(_STUDENT, doc.document_id)
    assert len(vectors) == 2
    for descriptor, vector in vectors.values():
        assert descriptor.dimension == FAKE_DIMENSION
        assert len(vector) == FAKE_DIMENSION

    # Idempotent: same signature → same record, no new build row.
    again = await manager.build_index(_STUDENT, doc.document_id)
    assert again == record


async def test_rebuild_on_model_change_increments_version(seeded):
    repo, doc = seeded
    manager = DocumentIndexManager(
        repository=repo, embedding_runtime=build_fake_embedding_runtime()
    )
    first = await manager.build_index(_STUDENT, doc.document_id)

    # "User switches embedding model" → signature change → rebuild.
    changed = DocumentIndexManager(
        repository=repo,
        embedding_runtime=build_fake_embedding_runtime(model_id="fake-hash-v2"),
    )
    assert not await changed.is_current(_STUDENT, doc.document_id)
    second = await changed.build_index(_STUDENT, doc.document_id)
    assert second is not None and second.index_version == first.index_version + 1
    assert second.embedding_model_id == "fake-hash-v2"
    vectors = await repo.get_vectors(_STUDENT, doc.document_id)
    assert all(descriptor.model_id == "fake-hash-v2" for descriptor, _ in vectors.values())


async def test_build_index_fails_closed_without_backend(seeded):
    repo, doc = seeded
    manager = DocumentIndexManager(repository=repo, embedding_runtime=EmbeddingRuntime())
    with pytest.raises(EmbeddingUnavailableError):
        await manager.build_index(_STUDENT, doc.document_id)


async def test_search_degraded_lexical_without_backend(seeded):
    repo, doc = seeded
    manager = DocumentIndexManager(repository=repo, embedding_runtime=EmbeddingRuntime())
    result = await manager.search(_STUDENT, query="求根公式")
    assert result.degraded is True
    assert result.vector_used is False
    assert len(result.hits) >= 1
    assert all(hit.vector_score is None for hit in result.hits)
    assert all(hit.lexical_score > 0 for hit in result.hits)


async def test_search_fuses_vector_when_backend_present(seeded):
    repo, doc = seeded
    manager = DocumentIndexManager(
        repository=repo, embedding_runtime=build_fake_embedding_runtime()
    )
    await manager.build_index(_STUDENT, doc.document_id)
    result = await manager.search(
        _STUDENT, query="求根公式", document_ids=[doc.document_id]
    )
    assert result.degraded is False
    assert result.vector_used is True
    assert result.embedding_backend_id == FAKE_BACKEND_ID
    assert result.index_version == 1  # single-document query carries build provenance
    assert all(hit.vector_score is not None for hit in result.hits)
    # Top hit is the lexically+semantically best chunk.
    assert "求根" in result.hits[0].chunk.text


async def test_build_index_no_chunks_returns_none(seeded):
    repo, doc = seeded
    empty = await repo.add_document(
        _STUDENT,
        UserDocument(
            student_id=uuid4(),
            filename="empty.md",
            mime_type="text/markdown",
            content_hash="hash-2",
            storage_ref="uploads/x/y/empty.md",
            status="ready",
            size_bytes=1,
            parser_version="mt-local-parser-v1",
        ),
    )
    manager = DocumentIndexManager(
        repository=repo, embedding_runtime=build_fake_embedding_runtime()
    )
    assert await manager.build_index(_STUDENT, empty.document_id) is None


async def test_reparse_invalidates_vectors_and_rebuilds(tmp_path):
    from mathtutor.application.desktop_files import PickedFile
    from mathtutor.application.document_ingestion import DocumentIngestionService
    from mathtutor.infrastructure.document_storage import DocumentStorage
    from mathtutor.repositories.document_repository import StaleIndexGenerationError

    repo = InMemoryDocumentRepository()
    runtime = build_fake_embedding_runtime()
    manager = DocumentIndexManager(repository=repo, embedding_runtime=runtime)
    service = DocumentIngestionService(
        repository=repo,
        storage=DocumentStorage(tmp_path / "data"),
        index_manager=manager,
    )
    picked = PickedFile(
        filename="方程.txt", mime_type="text/plain",
        data="一元二次方程的求根公式。判别式决定根的数量。".encode("utf-8"),
    )
    doc = await service.ingest(_STUDENT, picked)
    assert await manager.is_current(_STUDENT, doc.document_id)
    old_ids = {chunk.chunk_id for chunk in await repo.list_chunks(_STUDENT, doc.document_id)}
    old_version = (await repo.get_index_build(_STUDENT, doc.document_id)).index_version
    await service.reparse(_STUDENT, doc.document_id)
    new_ids = {chunk.chunk_id for chunk in await repo.list_chunks(_STUDENT, doc.document_id)}
    assert new_ids and new_ids != old_ids
    vectors = await repo.get_vectors(_STUDENT, doc.document_id)
    assert set(vectors) == new_ids
    assert await manager.is_current(_STUDENT, doc.document_id)
    rebuilt = await repo.get_index_build(_STUDENT, doc.document_id)
    assert rebuilt.index_version == old_version + 1
    result = await manager.search(_STUDENT, query="求根公式", document_ids=[doc.document_id])
    assert result.vector_used is True
    assert all(hit.vector_score is not None for hit in result.hits)

    service._index = DocumentIndexManager(repository=repo, embedding_runtime=EmbeddingRuntime())
    await service.reparse(_STUDENT, doc.document_id)
    assert not await service._index.is_current(_STUDENT, doc.document_id)
    lexical = await service._index.search(_STUDENT, query="求根公式", document_ids=[doc.document_id])
    assert lexical.vector_used is False and lexical.hits

    restored = DocumentIndexManager(repository=repo, embedding_runtime=build_fake_embedding_runtime())
    record = await restored.build_index(_STUDENT, doc.document_id)
    assert record is not None and await restored.is_current(_STUDENT, doc.document_id)

    original_embed = runtime.embed_texts

    async def expire(texts):
        chunks = [
            chunk.model_copy(update={"chunk_id": uuid4()})
            for chunk in await repo.list_chunks(_STUDENT, doc.document_id)
        ]
        await repo.replace_chunks(_STUDENT, doc.document_id, chunks)
        return await original_embed(texts)

    runtime.embed_texts = expire
    expiring = DocumentIndexManager(repository=repo, embedding_runtime=runtime)
    with pytest.raises(StaleIndexGenerationError):
        await expiring.build_index(_STUDENT, doc.document_id, force=True)
    live_ids = {chunk.chunk_id for chunk in await repo.list_chunks(_STUDENT, doc.document_id)}
    assert set(await repo.get_vectors(_STUDENT, doc.document_id)) != live_ids or not await repo.get_vectors(_STUDENT, doc.document_id)
