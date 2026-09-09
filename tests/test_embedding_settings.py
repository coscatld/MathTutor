"""Opt-in Embedding settings, adapters and persistence regression tests."""

from __future__ import annotations

import sys
import types

import httpx
import pytest

from mathtutor.api.product_state import ProductState
from mathtutor.application.desktop_files import PickedFile
from mathtutor.application.verification_backend import InProcessVerificationBackend
from mathtutor.infrastructure.db import create_db_engine
from mathtutor.infrastructure.embedding_config import (
    EMBEDDING_SECRET_KEY,
    EmbeddingConfigService,
)
from mathtutor.infrastructure.embedding_runtime import (
    EmbeddingRuntime,
    LocalSentenceTransformerBackend,
    OpenAICompatibleEmbeddingBackend,
)
from mathtutor.infrastructure.migrate import upgrade_db
from mathtutor.infrastructure.secret_store import InMemorySecretStore

pytestmark = pytest.mark.asyncio


async def test_default_is_disabled_and_does_not_create_or_download(tmp_path) -> None:
    runtime = EmbeddingRuntime()
    service = EmbeddingConfigService(
        data_dir=tmp_path,
        secret_store=InMemorySecretStore(),
        runtime=runtime,
    )
    settings = await service.public_settings()
    assert settings["enabled"] is False
    assert settings["status"] == "disabled"
    assert settings["local_download_status"] == "not_downloaded"
    assert runtime.backend() is None
    assert not service.config_path.exists()
    assert not service.models_dir.exists()


async def test_cloud_without_key_persists_non_secret_fields_and_stays_lexical(tmp_path) -> None:
    runtime = EmbeddingRuntime()
    store = InMemorySecretStore()
    service = EmbeddingConfigService(data_dir=tmp_path, secret_store=store, runtime=runtime)
    settings = await service.update(
        enabled=True,
        provider="cloud",
        local_model_id="bge-small-zh-v1.5",
        cloud_base_url="https://embed.example/v1",
        cloud_model="text-embedding-model",
        cloud_api_key=None,
    )
    assert settings["status"] == "incomplete"
    assert runtime.backend() is None
    persisted = service.config_path.read_text(encoding="utf-8")
    assert "embed.example" in persisted
    assert "api_key" not in persisted


async def test_cloud_key_uses_secret_store_and_real_openai_adapter(tmp_path) -> None:
    runtime = EmbeddingRuntime()
    store = InMemorySecretStore()
    service = EmbeddingConfigService(data_dir=tmp_path, secret_store=store, runtime=runtime)
    settings = await service.update(
        enabled=True,
        provider="cloud",
        local_model_id="bge-small-zh-v1.5",
        cloud_base_url="https://embed.example/v1",
        cloud_model="embedding-zh",
        cloud_api_key="secret-value-1234",
    )
    assert settings["status"] == "cloud_configured"
    assert isinstance(runtime.backend(), OpenAICompatibleEmbeddingBackend)
    assert await store.get(EMBEDDING_SECRET_KEY) == "secret-value-1234"
    assert "secret-value-1234" not in service.config_path.read_text(encoding="utf-8")


async def test_openai_compatible_backend_discovers_and_validates_dimension() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer local-secret"
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.0, 1.0, 0.0]}]},
        )

    dimensions: list[int] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        backend = OpenAICompatibleEmbeddingBackend(
            base_url="https://embed.example/v1",
            api_key="local-secret",
            model="embedding-zh",
            http=client,
            on_dimension=dimensions.append,
        )
        vector = await backend.embed_query("求根公式")
    assert vector == (0.0, 1.0, 0.0)
    assert backend.describe().dimension == 3
    assert dimensions == [3]


async def test_invalid_cloud_embedding_does_not_fail_ingestion(tmp_path) -> None:
    from mathtutor.application.document_ingestion import (
        DocumentIndexManager,
        DocumentIngestionService,
    )
    from mathtutor.infrastructure.document_storage import DocumentStorage
    from mathtutor.repositories.document_repository import InMemoryDocumentRepository

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        runtime = EmbeddingRuntime(
            OpenAICompatibleEmbeddingBackend(
                base_url="https://embed.example/v1",
                api_key="invalid-key",
                model="embedding-zh",
                http=client,
            )
        )
        repository = InMemoryDocumentRepository()
        service = DocumentIngestionService(
            repository=repository,
            storage=DocumentStorage(tmp_path / "data"),
            index_manager=DocumentIndexManager(
                repository=repository,
                embedding_runtime=runtime,
            ),
        )
        document = await service.ingest(
            "student-a",
            PickedFile(
                filename="notes.md",
                mime_type="text/markdown",
                data="# 一元一次方程\n\n移项后合并同类项。".encode(),
            ),
        )
        result = await service._index.search("student-a", query="移项")

    assert document.status == "ready"
    assert result.hits
    assert result.vector_used is False
    assert result.degraded is True


async def test_model_identity_mismatch_never_scores_old_vectors() -> None:
    from uuid import uuid4

    from mathtutor.application.document_ingestion import DocumentIndexManager
    from mathtutor.domain.documents import DocumentChunk, UserDocument
    from mathtutor.infrastructure.embedding_runtime import build_fake_embedding_runtime
    from mathtutor.repositories.document_repository import InMemoryDocumentRepository

    repository = InMemoryDocumentRepository()
    doc = await repository.add_document(
        "student-a",
        UserDocument(
            student_id=uuid4(), filename="notes.md", mime_type="text/markdown",
            content_hash="model-switch", storage_ref="uploads/notes.md", status="ready",
            size_bytes=8, parser_version="parser-v1",
        ),
    )
    await repository.replace_chunks(
        "student-a", doc.document_id,
        [DocumentChunk(student_id=uuid4(), document_id=doc.document_id, sequence=0,
                       text="判别式", content_hash="chunk", chunker_version="mt-chunker-v1")],
    )
    first = DocumentIndexManager(
        repository=repository,
        embedding_runtime=build_fake_embedding_runtime(
            backend_id="old-backend", model_id="old-model"
        ),
    )
    await first.build_index("student-a", doc.document_id)
    switched = DocumentIndexManager(
        repository=repository,
        embedding_runtime=build_fake_embedding_runtime(
            backend_id="new-backend", model_id="new-model"
        ),
    )
    result = await switched.search("student-a", query="判别式")
    assert result.hits
    assert result.vector_used is False
    assert result.degraded is True
    assert result.hits[0].vector_score is None


async def test_download_status_ready_then_delete_without_writing_repo(tmp_path, monkeypatch) -> None:
    runtime = EmbeddingRuntime()
    service = EmbeddingConfigService(
        data_dir=tmp_path,
        secret_store=InMemorySecretStore(),
        runtime=runtime,
    )

    def fake_download(_model_id, target) -> None:
        target.mkdir(parents=True)
        (target / "config.json").write_text("{}", encoding="utf-8")
        (target / "model.safetensors").write_bytes(b"weights")

    monkeypatch.setattr(service, "_download_snapshot_sync", fake_download)
    await service.start_download("bge-small-zh-v1.5")
    assert service._download_task is not None
    await service._download_task
    assert (await service.public_settings())["local_download_status"] == "ready"
    await service.delete_local_model("bge-small-zh-v1.5")
    assert (await service.public_settings())["local_download_status"] == "not_downloaded"
    assert not service.model_dir("bge-small-zh-v1.5").exists()


async def test_enabled_local_backend_writes_sqlite_chunk_vectors(tmp_path, monkeypatch) -> None:
    class FakeSentenceTransformer:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def encode(self, texts, **_kwargs):
            return [[1.0] + [0.0] * 511 for _ in texts]

    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(
        "mathtutor.infrastructure.embedding_config.importlib.util.find_spec",
        lambda name: object() if name == "sentence_transformers" else None,
    )

    db_path = tmp_path / "math_tutor.db"
    upgrade_db(str(db_path))
    engine = create_db_engine(db_path)
    state = ProductState(
        engine=engine,
        data_dir=tmp_path,
        db_path=db_path,
        verification_backend=InProcessVerificationBackend(),
    )
    model_dir = state.embedding_config.model_dir("bge-small-zh-v1.5")
    model_dir.mkdir(parents=True)
    (model_dir / "config.json").write_text("{}", encoding="utf-8")
    (model_dir / "model.safetensors").write_bytes(b"test weights")
    settings = await state.embedding_config.update(
        enabled=True,
        provider="local",
        local_model_id="bge-small-zh-v1.5",
        cloud_base_url="",
        cloud_model="",
        cloud_api_key=None,
    )
    assert settings["status"] == "local_ready"
    assert isinstance(state.embedding_runtime.backend(), LocalSentenceTransformerBackend)

    doc = await state.documents.ingest(
        "student-a",
        PickedFile(
            filename="notes.md",
            mime_type="text/markdown",
            data="# 二次方程\n\n判别式和求根公式。".encode(),
        ),
    )
    vectors = await state.document_repository.get_vectors("student-a", doc.document_id)
    assert vectors
    assert all(descriptor.dimension == 512 for descriptor, _vector in vectors.values())
    await engine.dispose()
