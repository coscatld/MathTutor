"""Explicit event recorder for relay tests; never used by product wiring."""

from copy import deepcopy

from mathtutor.application.outbox_relay import LoggingDispatchSink


class RecordingSink(LoggingDispatchSink):
    def __init__(self) -> None:
        super().__init__()
        self.dispatched: list[dict] = []

    async def dispatch(self, event: dict) -> None:
        await super().dispatch(event)
        self.dispatched.append(deepcopy(event))
