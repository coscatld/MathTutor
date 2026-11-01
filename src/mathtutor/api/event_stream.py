"""Small MathTutor-only async event stream used by the product WebSocket."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from mathtutor.application.controller import (
    MathTutorEvent,
    MathTutorEventType,
)

EVENT_STREAM_CAPACITY = 32


class MathTutorEventStream:
    """Single-turn typed sink/iterator with no generic runtime event surface."""

    def __init__(self, capacity: int = EVENT_STREAM_CAPACITY) -> None:
        if capacity < 1:
            raise ValueError("event stream capacity must be positive")
        self._queue: asyncio.Queue[MathTutorEvent] = asyncio.Queue(maxsize=capacity)
        self._condition = asyncio.Condition()
        self._closed = False

    async def emit(self, event: MathTutorEvent) -> None:
        async with self._condition:
            await self._condition.wait_for(lambda: self._closed or not self._queue.full())
            if not self._closed:
                self._queue.put_nowait(event)
                self._condition.notify_all()

    async def content(
        self,
        text: str,
        source: str = "",
        stage: str = "",
        metadata: dict | None = None,
    ) -> None:
        await self.emit(
            MathTutorEvent(
                type=MathTutorEventType.CONTENT,
                content=text,
                source=source or "math_tutor",
                stage=stage,
                metadata=metadata or {},
            )
        )

    async def error(
        self,
        message: str,
        source: str = "",
        metadata: dict | None = None,
    ) -> None:
        await self.emit(
            MathTutorEvent(
                type=MathTutorEventType.ERROR,
                content=message,
                source=source or "math_tutor",
                metadata=metadata or {},
            )
        )

    async def close(self) -> None:
        # Closing never waits for capacity. A cancelled producer must be able
        # to wake the consumer even when its queue is full, and a disconnected
        # consumer must not leave another producer stuck on a sentinel slot.
        async with self._condition:
            self._closed = True
            self._condition.notify_all()

    async def subscribe(self) -> AsyncIterator[MathTutorEvent]:
        while True:
            async with self._condition:
                await self._condition.wait_for(lambda: self._closed or not self._queue.empty())
                if self._queue.empty():
                    return
                event = self._queue.get_nowait()
                self._condition.notify_all()
            yield event


__all__ = ["MathTutorEventStream"]

