"""Bounded authentication workers and process-local attempt admission."""
from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import time

from mathtutor.infrastructure.owned_task import join_owned


class AuthBusy(RuntimeError):
    pass


class AuthRateLimited(RuntimeError):
    pass


class AuthExecutor:
    """At most capacity submitted jobs, no unbounded executor work queue.

    Cancelling an HTTP waiter does not cancel its running password/file work
    or release its slot. A registration already admitted may commit after
    disconnect; clients resolve the outcome via status/login.
    """
    def __init__(self, capacity: int = 2):
        if capacity < 1:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._pool = ThreadPoolExecutor(max_workers=capacity, thread_name_prefix="mathtutor-auth")
        self._lock = Lock()
        self._futures = set()
        self._closed = False
        self._shutdown_task = None

    @property
    def active(self):
        with self._lock:
            return len(self._futures)

    async def run(self, function, *args):
        with self._lock:
            if self._closed or len(self._futures) >= self.capacity:
                raise AuthBusy("Authentication is busy; retry shortly")
            future = self._pool.submit(function, *args)
            self._futures.add(future)

        def completed(done):
            with self._lock:
                self._futures.discard(done)

        future.add_done_callback(completed)
        wrapped = asyncio.wrap_future(future)
        # Retrieve abandoned exceptions too; the owner is the runtime, not
        # the cancelled request task. shield prevents cancellation forwarding.
        wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        return await asyncio.shield(wrapped)

    async def shutdown(self):
        if self._shutdown_task is None:
            with self._lock:
                self._closed = True
                futures = tuple(self._futures)

            async def finish():
                if futures:
                    await asyncio.gather(*(asyncio.wrap_future(f) for f in futures), return_exceptions=True)
                self._pool.shutdown(wait=False)

            self._shutdown_task = asyncio.create_task(finish(), name="auth-shutdown")
        await join_owned(self._shutdown_task)


class AuthAttemptBudget:
    """60 attempts/process/minute, 12 per ASGI peer; bounded in-memory state.

    Raw Forwarded/X-Forwarded-For headers are never read. Behind an explicitly
    configured trusted proxy, the ASGI server owns client-address resolution.
    This process-local budget is not a distributed multi-worker limiter.
    """
    def __init__(self, *, per_peer=12, total=60, window=60.0, max_peers=256, clock=time.monotonic):
        self.per_peer, self.total, self.window, self.max_peers = per_peer, total, window, max_peers
        self.clock = clock
        self._global = deque()
        self._peers = OrderedDict()
        self._lock = Lock()

    def admit(self, peer):
        now = self.clock()
        with self._lock:
            while self._global and self._global[0] <= now - self.window:
                self._global.popleft()
            if len(self._global) >= self.total:
                raise AuthRateLimited("Too many authentication attempts; retry later")
            bucket = self._peers.setdefault(peer, deque())
            self._peers.move_to_end(peer)
            while bucket and bucket[0] <= now - self.window:
                bucket.popleft()
            if len(bucket) >= self.per_peer:
                raise AuthRateLimited("Too many authentication attempts; retry later")
            bucket.append(now)
            self._global.append(now)
            while len(self._peers) > self.max_peers:
                self._peers.popitem(last=False)
