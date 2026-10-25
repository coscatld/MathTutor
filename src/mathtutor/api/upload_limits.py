"""Bound uploaded copies and the multipart body before it reaches the spool."""

from __future__ import annotations

import re

import anyio
from fastapi import HTTPException, UploadFile
from starlette.responses import JSONResponse

from mathtutor.domain.documents import MAX_DOCUMENT_BYTES

_MIB = 1024 * 1024
_MULTIPART_OVERHEAD = 64 * 1024
_DESKTOP = "/api/v2/math-tutor/desktop"


async def read_upload_limited(
    file: UploadFile, limit: int, *, detail: str = "文件超过导入大小限制。"
) -> bytes:
    """Read at most one byte beyond the business limit; always close the file.

    This bounds the additional bytes copy. UploadBodyLimitMiddleware separately
    bounds the request consumed by the multipart parser, including chunked data.
    """
    try:
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, detail)
        return data
    finally:
        # A rolled disk spool closes in a thread. Shield its checkpoint when
        # an enclosing AnyIO request scope has already been cancelled.
        with anyio.CancelScope(shield=True):
            await file.close()


def upload_body_limit(path: str) -> int | None:
    path = path.rstrip("/")
    if path == _DESKTOP + "/community/documents/import":
        # Up to 1000 files share the existing 20 MiB aggregate quota. Reserve
        # independent space for their names, MIME headers and form metadata.
        return MAX_DOCUMENT_BYTES + 2 * _MIB
    if path in {
        _DESKTOP + "/community/import",
        _DESKTOP + "/community/plugins/import",
        _DESKTOP + "/community/sources/import",
    }:
        return 32 * _MIB + _MULTIPART_OVERHEAD
    if path == "/api/v2/math-tutor/images":
        return 10 * _MIB + _MULTIPART_OVERHEAD
    if path in {
        _DESKTOP + "/documents/import",
        _DESKTOP + "/content/question-packs/import",
    } or re.fullmatch(re.escape(_DESKTOP) + r"/knowledge/libraries/[^/]+/imports", path):
        return MAX_DOCUMENT_BYTES + _MULTIPART_OVERHEAD
    return None


class UploadBodyLimitMiddleware:
    """Count actual ASGI body bytes, without buffering another complete body."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        limit = upload_body_limit(scope.get("path", "")) if scope["type"] == "http" else None
        if limit is None or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            announced = int(headers.get(b"content-length", b"0"))
        except ValueError:
            announced = 0  # Actual received bytes remain authoritative.
        if announced > limit:
            await JSONResponse({"detail": "上传请求超过大小限制。"}, status_code=413)(scope, receive, send)
            return
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    # HTTPException passes through FastAPI's body parsing and
                    # lets Starlette close all partially spooled upload files.
                    raise HTTPException(413, "上传请求超过大小限制。")
            return message

        await self.app(scope, bounded_receive, send)
