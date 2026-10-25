"""Owned, bounded threads for local parsing and chunking.

Cancellation is cooperative: Python cannot stop a thread inside a PDF library.
The caller and shutdown both join admitted work before releasing its files.
The limit includes running AND queued jobs; saturation rejects immediately.
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, TypeVar

from mathtutor.domain.documents import DocumentParseError

_T = TypeVar("_T")


@dataclass
class DocumentWorkControl:
    deadline: float
    cancelled: threading.Event = field(default_factory=threading.Event)

    def check(self) -> None:
        if time.monotonic() >= self.deadline:
            raise DocumentParseError("PARSE_TIMEOUT", "文档处理超过时间限制。")
        if self.cancelled.is_set():
            raise DocumentParseError("PARSE_CANCELLED", "文档处理已取消。")


async def drain_document_work(future: asyncio.Future | asyncio.Task):
    """Join despite repeated caller cancellation; retrieve worker exceptions."""
    while True:
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            if future.done():
                return future.result()


class DocumentWorkerPool:
    def __init__(self, *, max_workers: int = 2, max_jobs: int = 4) -> None:
        if max_workers < 1 or max_jobs < max_workers:
            raise ValueError("document worker bounds must be positive and ordered")
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="mathtutor-document"
        )
        self._capacity = threading.BoundedSemaphore(max_jobs)
        self._jobs: dict[asyncio.Future, DocumentWorkControl] = {}
        self._closed = False

    async def run(
        self,
        function: Callable[[DocumentWorkControl], _T],
        *,
        timeout_seconds: float,
    ) -> _T:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("document timeout must be finite and positive")
        if self._closed:
            raise DocumentParseError("PARSE_CLOSED", "文档处理服务已关闭。")
        if not self._capacity.acquire(blocking=False):
            raise DocumentParseError("PARSE_BUSY", "文档处理队列已满，请稍后再试。")
        control = DocumentWorkControl(time.monotonic() + timeout_seconds)

        def execute():
            try:
                control.check()
                result = function(control)
                control.check()
                return result
            finally:
                self._capacity.release()

        try:
            concurrent = self._executor.submit(execute)
        except BaseException:
            self._capacity.release()
            raise
        future = asyncio.wrap_future(concurrent)
        self._jobs[future] = control
        try:
            return await asyncio.wait_for(asyncio.shield(future), timeout_seconds)
        except (asyncio.CancelledError, TimeoutError) as error:
            control.cancelled.set()
            # Never delete input/staging while a thread can still access it.
            try:
                await drain_document_work(future)
            except Exception:
                pass
            if isinstance(error, TimeoutError):
                raise DocumentParseError(
                    "PARSE_TIMEOUT", "文档处理超过时间限制。"
                ) from error
            raise
        finally:
            self._jobs.pop(future, None)

    async def aclose(self) -> None:
        self._closed = True
        jobs = tuple(self._jobs.items())
        for _, control in jobs:
            control.cancelled.set()
        for future, _ in jobs:
            try:
                await drain_document_work(future)
            except Exception:
                pass
        # All admitted jobs have finished; this join cannot hold a live parser.
        self._executor.shutdown(wait=True)
