"""Regression tests for bounded copies, streaming body limits and cleanup."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, File, HTTPException, UploadFile
from starlette.formparsers import MultiPartParser

from mathtutor.api import desktop_api
from mathtutor.api.upload_limits import (
    UploadBodyLimitMiddleware,
    read_upload_limited,
    upload_body_limit,
)
from mathtutor.domain.documents import MAX_DOCUMENT_BYTES


class RecordingUpload:
    filename = "notes.txt"
    content_type = "text/plain"

    def __init__(self, data=b"", error=None):
        self.data, self.error = data, error
        self.reads = []
        self.closed = False

    async def read(self, size):
        self.reads.append(size)
        if self.error:
            raise self.error
        return self.data[:size]

    async def close(self):
        self.closed = True


@pytest.mark.parametrize("size,accepted", [(MAX_DOCUMENT_BYTES, True), (MAX_DOCUMENT_BYTES + 1, False)])
async def test_legacy_import_reads_only_limit_plus_one_and_closes(monkeypatch, size, accepted):
    uploaded = RecordingUpload(b"x" * size)
    calls = []

    async def ingest(owner, picked, **kwargs):
        calls.append(len(picked.data))
        return {"status": "ready"}

    monkeypatch.setattr(desktop_api, "_ingest", ingest)
    owner = SimpleNamespace(student_id="owner")
    if accepted:
        assert await desktop_api.import_document(file=uploaded, owner=owner) == {"status": "ready"}
        assert calls == [size]
    else:
        with pytest.raises(HTTPException) as error:
            await desktop_api.import_document(file=uploaded, owner=owner)
        assert error.value.status_code == 413
        assert calls == []
    assert uploaded.reads == [MAX_DOCUMENT_BYTES + 1]
    assert uploaded.closed


@pytest.mark.parametrize("error", [OSError("read failed"), asyncio.CancelledError()])
async def test_upload_read_error_or_cancellation_closes(error):
    uploaded = RecordingUpload(error=error)
    with pytest.raises(type(error)):
        await read_upload_limited(uploaded, 10)
    assert uploaded.closed


async def test_cancelled_anyio_scope_closes_real_disk_spool():
    import tempfile

    import anyio

    spool = tempfile.SpooledTemporaryFile(max_size=1)
    spool.write(b"disk-backed-upload")
    spool.seek(0)
    uploaded = UploadFile(file=spool, filename="notes.txt")
    with anyio.CancelScope() as scope:
        scope.cancel()
        await read_upload_limited(uploaded, 100)
        pytest.fail("the read should have been cancelled")
    assert spool.closed


def test_multipart_quotas_keep_multi_file_and_community_allowances():
    base = "/api/v2/math-tutor/desktop"
    assert upload_body_limit(base + "/documents/import") == MAX_DOCUMENT_BYTES + 65536
    assert upload_body_limit(base + "/knowledge/libraries/one/imports") == MAX_DOCUMENT_BYTES + 65536
    assert upload_body_limit(base + "/community/documents/import") == MAX_DOCUMENT_BYTES + 2 * 1024 * 1024
    assert upload_body_limit(base + "/community/import") == 32 * 1024 * 1024 + 65536
    assert upload_body_limit(base + "/settings") is None


def upload_app(monkeypatch, limit=256):
    monkeypatch.setattr("mathtutor.api.upload_limits.upload_body_limit", lambda path: limit)
    app = FastAPI()
    app.add_middleware(UploadBodyLimitMiddleware)
    app.state.calls = 0

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        app.state.calls += 1
        return {"size": len(await read_upload_limited(file, limit))}

    return app


async def test_large_announced_body_rejected_before_multipart_parser(monkeypatch):
    app = upload_app(monkeypatch)
    def unexpected_parser(*args, **kwargs):
        pytest.fail("oversized Content-Length must be refused before multipart parsing")
    monkeypatch.setattr(MultiPartParser, "__init__", unexpected_parser)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upload", content=b"", headers={"Content-Length": "257"})
    assert response.status_code == 413
    assert app.state.calls == 0


@pytest.mark.parametrize("content_length", [None, "1"])
async def test_streaming_body_uses_actual_count_and_closes_partial_spool(monkeypatch, content_length):
    import starlette.formparsers as formparsers

    app = upload_app(monkeypatch)
    spools = []
    original = formparsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        file = original(*args, **kwargs)
        spools.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool)
    header = b'--bound\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\n'

    async def chunks():
        yield header + b"a" * 16
        yield b"b" * 300
        pytest.fail("request body must stop being consumed at the limit")

    headers = {"Content-Type": "multipart/form-data; boundary=bound"}
    if content_length is not None:
        headers["Content-Length"] = content_length
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upload", content=chunks(), headers=headers)
    assert response.status_code == 413
    assert app.state.calls == 0
    assert len(spools) == 1 and spools[0].closed


async def test_legal_streaming_multipart_still_imports(monkeypatch):
    app = upload_app(monkeypatch, limit=1024)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 200
    assert response.json() == {"size": 5}
    assert app.state.calls == 1


async def test_cancelling_multipart_receive_closes_partial_spool(monkeypatch):
    import starlette.formparsers as formparsers

    app = upload_app(monkeypatch)
    spools = []
    original = formparsers.SpooledTemporaryFile

    def spool(*args, **kwargs):
        file = original(*args, **kwargs)
        spools.append(file)
        return file

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", spool)

    async def interrupted():
        yield b'--bound\r\nContent-Disposition: form-data; name="file"; filename="a.txt"\r\n\r\nfirst'
        raise asyncio.CancelledError()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        with pytest.raises(asyncio.CancelledError):
            await client.post("/upload", content=interrupted(),
                headers={"Content-Type": "multipart/form-data; boundary=bound"})
    assert app.state.calls == 0
    assert len(spools) == 1 and spools[0].closed
