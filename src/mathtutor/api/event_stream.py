"""Small MathTutor-only async event stream used by the product WebSocket."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from mathtutor.application.controller import (
    MathTutorEvent,
    MathTutorEventType,
)


class MathTutorEventStream:
    """Single-turn typed sink/iterator with no generic runtime event surface."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[MathTutorEvent | None] = asyncio.Queue()
        self._closed = False

    async def emit(self, event: MathTutorEvent) -> None:
        if not self._closed:
            await self._queue.put(event)

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
        if not self._closed:
            self._closed = True
            await self._queue.put(None)

    async def subscribe(self) -> AsyncIterator[MathTutorEvent]:
        while True:
            event = await self._queue.get()
            if event is None:
                return
            yield event


__all__ = ["MathTutorEventStream"]

