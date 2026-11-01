"""Join owned work before propagating cancellation to its caller."""
from __future__ import annotations

import asyncio
from typing import TypeVar

T = TypeVar("T")


async def join_owned(task: asyncio.Task[T]) -> T:
    """Repeated caller cancellation cannot abandon an owned file/runtime task.

    Cancellation is still reported, after the task reaches a terminal state.
    An exception is retrieved even when cancellation wins the caller's result.
    """
    cancelled = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
        except Exception as error:
            if cancelled:
                raise asyncio.CancelledError from error
            raise
    if cancelled:
        raise asyncio.CancelledError
    return result
