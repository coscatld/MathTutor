"""Resource limits, loop responsiveness and ownership of document workers."""

from __future__ import annotations

import asyncio
import io
import threading
import time
from pathlib import Path

import pytest
from pypdf import PdfWriter

from mathtutor.application.desktop_files import PickedFile
from mathtutor.application.document_ingestion import DocumentBusyError, DocumentIngestionService
from mathtutor.domain.documents import DocumentParseError, ParsedBlock, ParsedTextDocument
from mathtutor.domain.embedding import EmbeddingDescriptor
from mathtutor.infrastructure import document_parser as parser_module
from mathtutor.infrastructure.chunking import TextChunker
from mathtutor.infrastructure.document_parser import DocumentParseLimits, LocalDocumentParser
from mathtutor.infrastructure.document_storage import DocumentStorage
from mathtutor.infrastructure.document_workers import DocumentWorkerPool
from mathtutor.repositories.document_repository import InMemoryDocumentRepository
from mathtutor.security.scopes import student_uuid


async def _started(event: threading.Event) -> None:
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def _event(event: asyncio.Event) -> None:
    await asyncio.wait_for(event.wait(), timeout=2)


class _SlowParser(LocalDocumentParser):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.started = threading.Event()
        self.release = threading.Event()
        self.stopped = threading.Event()

    def _parse_text(self, file_path, *, markdown, tex):
        self.started.set()
        try:
            # Model one synchronous library call: cancellation cannot stop it.
            self.release.wait(2)
            return super()._parse_text(file_path, markdown=markdown, tex=tex)
        finally:
            self.stopped.set()


@pytest.mark.asyncio
async def test_slow_parser_keeps_loop_scheduling_and_joins_repeated_cancellation(tmp_path):
    path = tmp_path / "note.txt"
    path.write_text("quadratic formula")
    assets = tmp_path / "assets"
    parser = _SlowParser()
    task = asyncio.create_task(parser.parse(path=str(path), asset_dir=str(assets)))
    try:
        await _started(parser.started)
        ticks = []
        for _ in range(6):
            before = time.monotonic()
            await asyncio.sleep(0.005)
            ticks.append(time.monotonic() - before)
        assert max(ticks) < 0.25
        task.cancel()
        await asyncio.sleep(0.01)
        task.cancel()
        assert not task.done(), "cancellation must join the still-running library call"
        parser.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert parser.stopped.is_set()
        assert not parser._workers._jobs
        assert not assets.exists()
        assert not list(tmp_path.glob(".parse-*"))
    finally:
        parser.release.set()
        await parser.aclose()


@pytest.mark.asyncio
async def test_document_queue_has_no_unbounded_executor_backlog():
    pool = DocumentWorkerPool(max_workers=1, max_jobs=2)
    started = threading.Event()
    release = threading.Event()

    def slow(control):
        started.set()
        release.wait(2)
        return 1

    first = asyncio.create_task(pool.run(slow, timeout_seconds=2))
    await _started(started)
    second = asyncio.create_task(pool.run(lambda control: 2, timeout_seconds=2))
    await asyncio.sleep(0)
    try:
        with pytest.raises(DocumentParseError) as error:
            await pool.run(lambda control: 3, timeout_seconds=2)
        assert error.value.classification == "PARSE_BUSY"
        assert len(pool._jobs) == 2
        release.set()
        assert await first == 1
        assert await second == 2
        assert await pool.run(lambda control: 4, timeout_seconds=2) == 4
    finally:
        release.set()
        await pool.aclose()
    with pytest.raises(DocumentParseError) as error:
        await pool.run(lambda control: 5, timeout_seconds=2)
    assert error.value.classification == "PARSE_CLOSED"


@pytest.mark.asyncio
@pytest.mark.parametrize("baseline", ["pypdf", "rich"])
async def test_pdf_page_limit_rejects_before_page_extraction(tmp_path, monkeypatch, baseline):
    if baseline == "rich":
        pytest.importorskip("fitz")
    else:
        monkeypatch.setattr(parser_module, "_pymupdf", lambda: None)
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    path = tmp_path / "many.pdf"
    path.write_bytes(stream.getvalue())
    parser = LocalDocumentParser(limits=DocumentParseLimits(max_pages=2))
    try:
        with pytest.raises(DocumentParseError) as error:
            await parser.parse(path=str(path))
        assert error.value.classification == "PARSE_PAGE_LIMIT"
    finally:
        await parser.aclose()


@pytest.mark.asyncio
async def test_optional_rich_parser_is_serial_and_lock_wait_is_cancellable(tmp_path, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    calls = []

    class SerialRichParser(LocalDocumentParser):
        def _parse_pdf_pymupdf(self, fitz, file_path, *, asset_dir, asset_ref_prefix):
            calls.append(file_path.name)
            started.set()
            release.wait(2)
            parser_module._ACTIVE_BUDGET.get().check()
            return [], parser_module._parse_stats(
                total_pages=1, text_pages=0, empty_pages=1, extractable_chars=0,
                empty_warning="empty", parser_id="pymupdf",
            )

    monkeypatch.setattr(parser_module, "_pymupdf", lambda: object())
    monkeypatch.setattr(parser_module, "try_mineru_parse", lambda *args, **kwargs: None)
    first = SerialRichParser()
    second = SerialRichParser()
    one = asyncio.create_task(first.parse(path=str(tmp_path / "one.pdf")))
    two = None
    try:
        await _started(started)
        two = asyncio.create_task(second.parse(path=str(tmp_path / "two.pdf")))
        await asyncio.sleep(0.01)
        two.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(two, timeout=1)
        assert calls == ["one.pdf"]
        release.set()
        await one
    finally:
        release.set()
        await first.aclose()
        await second.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limits", "text", "classification"),
    [
        (DocumentParseLimits(max_text_chars=5), "123456", "PARSE_TEXT_LIMIT"),
        (DocumentParseLimits(max_blocks=1), "one\n\ntwo", "PARSE_BLOCK_LIMIT"),
    ],
)
async def test_output_budget_failure_preserves_previous_assets(tmp_path, limits, text, classification):
    path = tmp_path / "note.txt"
    path.write_text(text)
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "previous.png").write_bytes(b"original asset")
    parser = LocalDocumentParser(limits=limits)
    try:
        with pytest.raises(DocumentParseError) as error:
            await parser.parse(path=str(path), asset_dir=str(assets))
        assert error.value.classification == classification
        assert (assets / "previous.png").read_bytes() == b"original asset"
        assert not list(tmp_path.glob(".parse-*"))
    finally:
        await parser.aclose()


class _ImagePage:
    def find_tables(self):
        return []

    def get_text(self, mode):
        return {"blocks": [{"type": 0, "lines": [{"spans": [{"text": "text layer", "size": 12}]}]}]}

    def get_images(self, full=True):
        return [(1,), (2,)]


class _ImageDocument:
    page_count = 1
    needs_pass = False

    def __iter__(self):
        return iter([_ImagePage()])

    def extract_image(self, xref):
        return {"width": 64, "height": 64, "image": b"12345678", "ext": "png"}

    def close(self):
        pass


@pytest.mark.asyncio
@pytest.mark.parametrize("limits", [DocumentParseLimits(max_assets=1), DocumentParseLimits(max_asset_bytes=7)])
async def test_partial_image_output_is_removed_at_asset_limit(tmp_path, monkeypatch, limits):
    class FakeFitz:
        @staticmethod
        def open(path):
            return _ImageDocument()

    monkeypatch.setattr(parser_module, "_pymupdf", lambda: FakeFitz)
    path = tmp_path / "lesson.pdf"
    path.write_bytes(b"fake pdf handled by test adapter")
    assets = tmp_path / "assets"
    parser = LocalDocumentParser(limits=limits)
    try:
        with pytest.raises(DocumentParseError) as error:
            await parser.parse(path=str(path), asset_dir=str(assets))
        assert error.value.classification == "PARSE_ASSET_LIMIT"
        assert not assets.exists()
        assert not list(tmp_path.glob(".parse-*"))
    finally:
        await parser.aclose()


def _service(tmp_path, *, parser=None, chunker=None):
    return DocumentIngestionService(
        repository=InMemoryDocumentRepository(),
        storage=DocumentStorage(tmp_path / "data"),
        parser=parser,
        chunker=chunker,
    )


@pytest.mark.asyncio
async def test_timeout_marks_failed_without_chunks_and_cleans_staging(tmp_path):
    parser = _SlowParser(limits=DocumentParseLimits(timeout_seconds=0.02))
    service = _service(tmp_path, parser=parser)
    task = asyncio.create_task(service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"lesson text",
    )))
    try:
        await _started(parser.started)
        await asyncio.sleep(0.04)
        assert not task.done(), "timeout must drain a library call before cleanup"
        parser.release.set()
        doc = await task
        assert doc.status == "failed"
        assert doc.classification == "PARSE_TIMEOUT"
        assert await service._repo.list_chunks("alice", doc.document_id) == []
        directory = service._storage.document_dir(student_uuid("alice"), doc.document_id)
        assert not list(directory.glob(".*-*"))
        assert not (directory / "assets").exists()
        assert parser.stopped.is_set()
    finally:
        parser.release.set()
        await service.aclose()


@pytest.mark.asyncio
async def test_delete_joins_cancelled_parser_before_removing_original(tmp_path):
    parser = _SlowParser()
    service = _service(tmp_path, parser=parser)
    ingest = asyncio.create_task(service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"lesson text",
    )))
    try:
        await _started(parser.started)
        doc = (await service.list_documents("alice"))[0]
        original = service._storage.resolve(doc.storage_ref)
        delete = asyncio.create_task(service.delete("alice", doc.document_id))
        await asyncio.sleep(0.01)
        assert original.exists()
        assert not delete.done()
        parser.release.set()
        assert await delete is True
        with pytest.raises(asyncio.CancelledError):
            await ingest
        assert parser.stopped.is_set()
        assert not original.exists()
        assert not list(original.parent.glob(".ingest-*"))
        assert await service._repo.list_chunks("alice", doc.document_id) == []
    finally:
        parser.release.set()
        await service.aclose()


@pytest.mark.asyncio
async def test_shutdown_cancels_and_drains_import_before_rejecting_new_work(tmp_path):
    parser = _SlowParser()
    service = _service(tmp_path, parser=parser)
    ingest = asyncio.create_task(service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"lesson text",
    )))
    await _started(parser.started)
    close = asyncio.create_task(service.aclose())
    await asyncio.sleep(0.01)
    assert not close.done()
    parser.release.set()
    await close
    with pytest.raises(asyncio.CancelledError):
        await ingest
    doc = (await service.list_documents("alice"))[0]
    assert doc.status == "failed"
    assert doc.classification == "PARSE_CANCELLED"
    assert not service._operations
    assert not service._workers._jobs
    assert not parser._workers._jobs
    with pytest.raises(DocumentBusyError):
        await service.ingest("alice", PickedFile(filename="new.txt", mime_type="text/plain", data=b"new"))


@pytest.mark.asyncio
async def test_cancelled_chunker_cannot_publish_parser_assets_or_chunks(tmp_path):
    started = threading.Event()
    release = threading.Event()

    class AssetParser:
        def parser_version(self):
            return "test-assets"

        async def parse(self, *, path, asset_dir, asset_ref_prefix):
            Path(asset_dir).mkdir(exist_ok=True)
            (Path(asset_dir) / "figure.png").write_bytes(b"asset")
            return ParsedTextDocument(
                blocks=(ParsedBlock(text="lesson"),), extractable_chars=6,
                parse_mode="text_layer", image_count=1,
            )

    class SlowChunker(TextChunker):
        def chunk(self, blocks):
            started.set()
            release.wait(2)
            return super().chunk(blocks)

    service = _service(tmp_path, parser=AssetParser(), chunker=SlowChunker())
    task = asyncio.create_task(service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"lesson",
    )))
    try:
        await _started(started)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        doc = (await service.list_documents("alice"))[0]
        assert doc.status == "failed"
        assert doc.classification == "PARSE_CANCELLED"
        assert await service._repo.list_chunks("alice", doc.document_id) == []
        directory = service._storage.document_dir(student_uuid("alice"), doc.document_id)
        assert not (directory / "assets").exists()
        assert not list(directory.glob(".ingest-*"))
    finally:
        release.set()
        await service.aclose()


@pytest.mark.asyncio
async def test_failed_reparse_preserves_complete_previous_chunks_and_assets(tmp_path):
    service = _service(tmp_path)
    try:
        doc = await service.ingest("alice", PickedFile(
            filename="note.txt", mime_type="text/plain", data=b"previous lesson",
        ))
        before = await service._repo.list_chunks("alice", doc.document_id)
        assets = service._storage.assets_dir(student_uuid("alice"), doc.document_id)
        (assets / "previous.png").write_bytes(b"original asset")
        service._parser.limits = DocumentParseLimits(max_text_chars=1)
        failed = await service.reparse("alice", doc.document_id)
        assert failed.status == "failed"
        assert failed.classification == "PARSE_TEXT_LIMIT"
        assert await service._repo.list_chunks("alice", doc.document_id) == before
        assert (assets / "previous.png").read_bytes() == b"original asset"
        assert not list(assets.parent.glob(".ingest-*"))
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_cancellation_during_publication_joins_complete_write(tmp_path):
    class PausedRepository(InMemoryDocumentRepository):
        def __init__(self):
            super().__init__()
            self.publishing = asyncio.Event()
            self.release = asyncio.Event()

        async def publish_parse_result(self, student_id, doc, chunks):
            self.publishing.set()
            await self.release.wait()
            return await super().publish_parse_result(student_id, doc, chunks)

    repository = PausedRepository()
    service = DocumentIngestionService(repository=repository, storage=DocumentStorage(tmp_path / "data"))
    task = asyncio.create_task(service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"complete lesson",
    )))
    try:
        await _event(repository.publishing)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        repository.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        doc = (await service.list_documents("alice"))[0]
        chunks = await repository.list_chunks("alice", doc.document_id)
        assert doc.status == "failed"
        assert doc.retrieval_enabled is False
        assert doc.chunk_count == len(chunks) > 0
        assert [chunk.sequence for chunk in chunks] == list(range(len(chunks)))
        assets = service._storage.assets_dir(student_uuid("alice"), doc.document_id)
        assert not list(assets.parent.glob(".previous-*"))
        assert not list(assets.parent.glob(".ingest-*"))
    finally:
        repository.release.set()
        await service.aclose()


@pytest.mark.asyncio
async def test_optional_mineru_process_is_killed_and_joined_at_deadline(tmp_path, monkeypatch):
    import subprocess
    from mathtutor.infrastructure import parse_adapters

    processes = []

    class SlowProcess:
        def __init__(self, args, **kwargs):
            assert kwargs["stdout"] == subprocess.DEVNULL
            assert kwargs["stderr"] == subprocess.DEVNULL
            self.killed = False
            self.joined = False
            self.returncode = None
            processes.append(self)

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            if self.killed:
                self.joined = True
                return self.returncode
            time.sleep(0.005)
            raise subprocess.TimeoutExpired("mineru", timeout)

        def kill(self):
            self.killed = True
            self.returncode = -9

    monkeypatch.setattr(parser_module, "_pymupdf", lambda: None)
    monkeypatch.setattr(parse_adapters.shutil, "which", lambda name: "/test/mineru")
    monkeypatch.setattr(subprocess, "Popen", SlowProcess)
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    stream = io.BytesIO()
    writer.write(stream)
    path = tmp_path / "blank.pdf"
    path.write_bytes(stream.getvalue())
    parser = LocalDocumentParser(limits=DocumentParseLimits(timeout_seconds=0.025))
    try:
        with pytest.raises(DocumentParseError) as error:
            await parser.parse(path=str(path), asset_dir=str(tmp_path / "assets"))
        assert error.value.classification == "PARSE_TIMEOUT"
        assert len(processes) == 1
        assert processes[0].killed and processes[0].joined
        assert not list(tmp_path.glob(".parse-*"))
    finally:
        await parser.aclose()


@pytest.mark.asyncio
async def test_simultaneous_reparse_is_claimed_before_repository_read_and_delete(tmp_path):
    service = _service(tmp_path)
    parser = _SlowParser()
    try:
        doc = await service.ingest("alice", PickedFile(
            filename="note.txt", mime_type="text/plain", data=b"lesson",
        ))
        service._parser = parser
        first = asyncio.create_task(service.reparse("alice", doc.document_id))
        # No sleep is needed to manufacture a stale ready read: the claim
        # must exist as soon as the first coroutine enters the repository.
        await _started(parser.started)
        with pytest.raises(DocumentBusyError):
            await service.reparse("alice", doc.document_id)
        delete = asyncio.create_task(service.delete("alice", doc.document_id))
        await asyncio.sleep(0.01)
        assert not delete.done()
        parser.release.set()
        assert await delete is True
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not service._active_documents
        assert parser.stopped.is_set()
    finally:
        parser.release.set()
        await service.aclose()


@pytest.mark.asyncio
async def test_cancellation_during_initial_add_drains_and_marks_visible_import_failed(tmp_path):
    class PausedAdd(InMemoryDocumentRepository):
        def __init__(self):
            super().__init__()
            self.added = asyncio.Event()
            self.release = asyncio.Event()

        async def add_document(self, student_id, doc):
            result = await super().add_document(student_id, doc)
            self.added.set()
            await self.release.wait()
            return result

    repository = PausedAdd()
    service = DocumentIngestionService(repository=repository, storage=DocumentStorage(tmp_path / "data"))
    task = asyncio.create_task(service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"lesson",
    )))
    try:
        await _event(repository.added)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        repository.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        doc = (await service.list_documents("alice"))[0]
        assert doc.status == "failed"
        assert doc.classification == "PARSE_CANCELLED"
        assert await service._storage.exists(doc.storage_ref)
        assert await repository.list_chunks("alice", doc.document_id) == []
    finally:
        repository.release.set()
        await service.aclose()


@pytest.mark.asyncio
async def test_cancellation_during_initial_add_failure_removes_unregistered_file(tmp_path):
    class FailedAdd(InMemoryDocumentRepository):
        def __init__(self):
            super().__init__()
            self.adding = asyncio.Event()
            self.release = asyncio.Event()

        async def add_document(self, student_id, doc):
            self.adding.set()
            await self.release.wait()
            raise OSError("failed insert")

    repository = FailedAdd()
    storage = DocumentStorage(tmp_path / "data")
    service = DocumentIngestionService(repository=repository, storage=storage)
    task = asyncio.create_task(service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"lesson",
    )))
    try:
        await _event(repository.adding)
        task.cancel()
        repository.release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await service.list_documents("alice") == []
        assert not list(storage.uploads_root().rglob("*.txt"))
    finally:
        repository.release.set()
        await service.aclose()


@pytest.mark.asyncio
async def test_cancellation_during_reparse_status_write_does_not_leave_parsing(tmp_path):
    class PausedUpdate(InMemoryDocumentRepository):
        def __init__(self):
            super().__init__()
            self.parsing = asyncio.Event()

        async def update_document(self, student_id, doc):
            result = await super().update_document(student_id, doc)
            if doc.status == "parsing":
                self.parsing.set()
                await asyncio.Future()
            return result

    repository = InMemoryDocumentRepository()
    storage = DocumentStorage(tmp_path / "data")
    service = DocumentIngestionService(repository=repository, storage=storage)
    doc = await service.ingest("alice", PickedFile(
        filename="note.txt", mime_type="text/plain", data=b"lesson",
    ))
    paused = PausedUpdate()
    paused._documents = repository._documents
    paused._chunks = repository._chunks
    service._repo = paused
    task = asyncio.create_task(service.reparse("alice", doc.document_id))
    try:
        await _event(paused.parsing)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        current = await service.get_document("alice", doc.document_id)
        assert current.status == "failed"
        assert current.classification == "PARSE_CANCELLED"
        assert not service._active_documents
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_memory_publication_prepares_metadata_before_replacing_chunks(tmp_path, monkeypatch):
    service = _service(tmp_path)
    try:
        doc = await service.ingest("alice", PickedFile(
            filename="note.txt", mime_type="text/plain", data=b"old lesson",
        ))
        before = await service._repo.list_chunks("alice", doc.document_id)
        new_chunks = [before[0].model_copy(update={"text": "new lesson"})]
        original = type(doc).model_copy

        def fail_metadata(value, **kwargs):
            if value is doc:
                raise OSError("metadata construction failed")
            return original(value, **kwargs)

        monkeypatch.setattr(type(doc), "model_copy", fail_metadata)
        with pytest.raises(OSError, match="metadata construction"):
            await service._repo.publish_parse_result("alice", doc, new_chunks)
        assert await service._repo.list_chunks("alice", doc.document_id) == before
        assert (await service.get_document("alice", doc.document_id)).status == "ready"
    finally:
        await service.aclose()


@pytest.mark.asyncio
async def test_sqlite_metadata_failure_rolls_back_chunks_vectors_fts_and_assets(tmp_path, monkeypatch):
    from mathtutor.infrastructure.db import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db
    from mathtutor.repositories import sqlite_documents
    from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository

    database = tmp_path / "documents.db"
    upgrade_db(str(database))
    engine = create_db_engine(database)
    repository = SQLiteDocumentRepository(engine)
    storage = DocumentStorage(tmp_path / "data")
    service = DocumentIngestionService(repository=repository, storage=storage)

    class AssetParser:
        def parser_version(self):
            return "asset-test"

        async def parse(self, *, path, asset_dir, asset_ref_prefix):
            (Path(asset_dir) / "figure.png").write_bytes(b"new asset")
            return ParsedTextDocument(
                blocks=(ParsedBlock(text="new lesson"),), extractable_chars=10,
                parse_mode="text_layer", image_count=1,
            )

    try:
        doc = await service.ingest("alice", PickedFile(
            filename="note.txt", mime_type="text/plain", data=b"old lesson",
        ))
        before = await repository.list_chunks("alice", doc.document_id)
        descriptor = EmbeddingDescriptor(
            backend_id="test", model_id="test", model_version="1", dimension=2
        )
        await repository.replace_vectors(
            "alice", doc.document_id, [(before[0].chunk_id, descriptor, (1.0, 0.0))]
        )
        vectors_before = await repository.get_vectors("alice", doc.document_id)
        assets = storage.assets_dir(student_uuid("alice"), doc.document_id)
        (assets / "figure.png").write_bytes(b"old asset")
        # Force a real transaction failure AFTER new chunks/FTS have been
        # written, while letting the failed-state update itself succeed.
        update = sqlite_documents.update_user_document

        async def fail_metadata(conn, *, student_id, doc):
            if doc.status == "ready" and doc.parser_version == "asset-test":
                raise OSError("injected metadata write failure")
            return await update(conn, student_id=student_id, doc=doc)

        monkeypatch.setattr(sqlite_documents, "update_user_document", fail_metadata)
        service._parser = AssetParser()
        failed = await service.reparse("alice", doc.document_id)
        assert failed.status == "failed"
        assert "metadata write failure" in failed.parse_error
        assert await repository.list_chunks("alice", doc.document_id) == before
        assert await repository.get_vectors("alice", doc.document_id) == vectors_before
        assert (assets / "figure.png").read_bytes() == b"old asset"
        assert not list(assets.parent.glob(".previous-*"))
        assert not list(assets.parent.glob(".ingest-*"))
        from sqlalchemy import text
        async with engine.connect() as conn:
            rows = (await conn.execute(text("SELECT fts_text FROM document_chunks_fts"))).all()
        assert rows and all("new lesson" not in row[0] for row in rows)
    finally:
        await service.aclose()
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("classification", [
    "PARSE_TIMEOUT", "PARSE_CANCELLED", "PARSE_BUSY", "PARSE_CLOSED",
    "PARSE_PAGE_LIMIT", "PARSE_TEXT_LIMIT", "PARSE_BLOCK_LIMIT", "PARSE_ASSET_LIMIT",
])
async def test_sqlite_parse_failures_survive_database_close_and_reopen(tmp_path, monkeypatch, classification):
    """Exercise real failure transitions and Pydantic hydration after restart."""
    from mathtutor.infrastructure.db import create_db_engine
    from mathtutor.infrastructure.migrate import upgrade_db
    from mathtutor.repositories.sqlite_knowledge import SQLiteDocumentRepository

    database = tmp_path / "restart.db"
    upgrade_db(str(database))
    engine = create_db_engine(database)
    repository = SQLiteDocumentRepository(engine)
    storage = DocumentStorage(tmp_path / "data")
    parser = LocalDocumentParser()
    picked = PickedFile(filename="lesson.txt", mime_type="text/plain", data=b"lesson text")
    blocker = None
    release = threading.Event()
    reopened = None
    service = None
    try:
        if classification == "PARSE_TEXT_LIMIT":
            parser.limits = DocumentParseLimits(max_text_chars=2)
        elif classification == "PARSE_BLOCK_LIMIT":
            parser.limits = DocumentParseLimits(max_blocks=1)
            picked = PickedFile(filename="lesson.txt", mime_type="text/plain", data=b"one\n\ntwo")
        elif classification == "PARSE_PAGE_LIMIT":
            parser.limits = DocumentParseLimits(max_pages=1)
            writer = PdfWriter()
            for _ in range(2):
                writer.add_blank_page(width=100, height=100)
            payload = io.BytesIO()
            writer.write(payload)
            picked = PickedFile(filename="lesson.pdf", mime_type="application/pdf", data=payload.getvalue())
        elif classification == "PARSE_ASSET_LIMIT":
            class FakeFitz:
                @staticmethod
                def open(path):
                    return _ImageDocument()
            monkeypatch.setattr(parser_module, "_pymupdf", lambda: FakeFitz)
            parser.limits = DocumentParseLimits(max_assets=1)
            picked = PickedFile(filename="lesson.pdf", mime_type="application/pdf", data=b"test pdf adapter")
        elif classification == "PARSE_BUSY":
            await parser.aclose()
            parser = LocalDocumentParser(workers=DocumentWorkerPool(max_workers=1, max_jobs=1))
            started = threading.Event()
            def hold(control):
                started.set()
                release.wait(2)
            blocker = asyncio.create_task(parser._workers.run(hold, timeout_seconds=2))
            await _started(started)
        elif classification == "PARSE_CLOSED":
            await parser.aclose()
        elif classification in {"PARSE_TIMEOUT", "PARSE_CANCELLED"}:
            await parser.aclose()
            parser = _SlowParser(limits=DocumentParseLimits(
                timeout_seconds=0.02 if classification == "PARSE_TIMEOUT" else 2
            ))

        service = DocumentIngestionService(repository=repository, storage=storage, parser=parser)
        if classification in {"PARSE_TIMEOUT", "PARSE_CANCELLED"}:
            task = asyncio.create_task(service.ingest("alice", picked))
            await _started(parser.started)
            if classification == "PARSE_TIMEOUT":
                await asyncio.sleep(0.04)
                parser.release.set()
                document = await task
            else:
                task.cancel()
                parser.release.set()
                with pytest.raises(asyncio.CancelledError):
                    await task
                document = (await repository.list_documents("alice"))[0]
        else:
            document = await service.ingest("alice", picked)
        assert document.status == "failed"
        assert document.classification == classification
        assert document.retrieval_enabled is False
        assert await repository.list_chunks("alice", document.document_id) == []
        directory = storage.document_dir(student_uuid("alice"), document.document_id)
        assert not list(directory.glob(".ingest-*"))
        assert not (directory / "assets").exists()

        release.set()
        if blocker is not None:
            await blocker
        await service.aclose()
        await parser._workers.aclose()  # also owns the explicitly injected busy pool
        await engine.dispose()

        reopened = create_db_engine(database)
        fresh = SQLiteDocumentRepository(reopened)
        listed = await fresh.list_documents("alice")
        restored = await fresh.get_document("alice", document.document_id)
        assert len(listed) == 1
        assert listed[0].classification == restored.classification == classification
        assert restored.status == "failed"
        assert restored.parse_error
        assert restored.retrieval_enabled is False
        assert await fresh.list_chunks("alice", document.document_id) == []
    finally:
        release.set()
        if isinstance(parser, _SlowParser):
            parser.release.set()
        if blocker is not None:
            await blocker
        if service is not None:
            await service.aclose()
        await parser._workers.aclose()
        await engine.dispose()
        if reopened is not None:
            await reopened.dispose()
