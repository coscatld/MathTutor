"""Bounded WS admission, reachable controls and durable retry through SQLite."""
import asyncio
import json
import sqlite3
import threading
import time
from contextlib import closing
from types import SimpleNamespace

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from test_tutor_p0 import client_at, envelope, send


class ControlledProvider:
    provider_id = "controlled"
    model = "test"

    def __init__(self):
        self.started = threading.Event()
        self.cancelled = threading.Event()
        self.calls = 0

    async def complete(self, *args, **kwargs):
        self.calls += 1
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


def start_slow(ws, provider):
    get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
    ws.send_json(envelope("send_message", "active", {"text": "你好"}, session="c"))
    assert ws.receive_json()["event_type"] == "assistant_start"
    assert provider.started.wait(3)


def fill(ws, count=16, session="c"):
    for i in range(count):
        ws.send_json(envelope("submit_problem", f"queued-{i}", {"text": "2x+3=7"}, session=session))


def until_end(ws):
    frames = []
    for _ in range(64):
        frame = ws.receive_json()
        frames.append(frame)
        if frame["event_type"] == "turn_end":
            return frames
    raise AssertionError("missing bounded terminal sequence")


def journal_ids(db):
    with closing(sqlite3.connect(db)) as connection:
        return {row[0] for row in connection.execute("SELECT request_id FROM turn_requests")}


def test_full_sixteen_request_queue_keeps_cancel_reachable_and_discards_old_work(tmp_path):
    db = tmp_path / "cancel.db"
    provider = ControlledProvider()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        start_slow(ws, provider)
        fill(ws)
        started = time.monotonic()
        ws.send_json(envelope("cancel_turn", "cancel", session="c"))
        assert provider.cancelled.wait(2), "full normal queue must not delay cancellation"
        assert time.monotonic() - started < 2
        frames = until_end(ws)
        rejected = [f for f in frames if f["payload"].get("error_code") == "REQUEST_CANCELLED_BEFORE_START"]
        assert {f["payload"]["turn_id"] for f in rejected} == {f"queued-{i}" for i in range(16)}
        assert all(f["payload"]["accepted"] is False and f["payload"]["retryable"] for f in rejected)
        terminal = next(f for f in frames if f["payload"].get("turn_id") == "active" and f["event_type"] == "assistant_error")
        assert terminal["payload"]["status"] == "CANCELLED"
        assert terminal["payload"]["finish_reason"] == "USER_CANCELLED"
        assert journal_ids(db) == {"active"}
        # Explicit retry keeps its original identity; subsequent retry replays
        # the exact receipt and cannot make a second problem submission.
        first = send(ws, "submit_problem", "queued-0", {"text": "2x+3=7"}, session="c")
        assert send(ws, "submit_problem", "queued-0", {"text": "2x+3=7"}, session="c") == first
        assert journal_ids(db) == {"active", "queued-0"}
        assert provider.calls == 1


def test_overload_is_correlated_unclaimed_and_wrong_session_cancel_has_no_effect(tmp_path):
    db = tmp_path / "overload.db"
    provider = ControlledProvider()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        start_slow(ws, provider)
        fill(ws)
        ws.send_json(envelope("submit_problem", "overflow", {"text": "3x=9"}, session="c"))
        rejection = ws.receive_json()["payload"]
        assert rejection["turn_id"] == "overflow" and rejection["error_code"] == "REQUEST_QUEUE_FULL"
        assert rejection["accepted"] is False and rejection["retryable"] is True
        assert "overflow" not in journal_ids(db)
        ws.send_json(envelope("cancel_turn", "wrong", session="other"))
        assert ws.receive_json()["payload"]["error_code"] == "CANCEL_SESSION_MISMATCH"
        assert not provider.cancelled.is_set()
        ws.send_json(envelope("cancel_turn", "cancel", session="c"))
        assert provider.cancelled.wait(2)
        until_end(ws)
        done = send(ws, "submit_problem", "overflow", {"text": "3x=9"}, session="c")
        assert any(f["event_type"] == "assistant_complete" for f in done)
        assert send(ws, "submit_problem", "overflow", {"text": "3x=9"}, session="c") == done


def test_full_queue_still_processes_owner_scoped_presentation_receipt(tmp_path, monkeypatch):
    provider = ControlledProvider()
    seen = threading.Event()
    owners = []
    with client_at(tmp_path / "receipt.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        original = state.controller.mark_delivery
        async def mark(owner, delivery, status):
            owners.append((owner, delivery, status))
            value = await original(owner, delivery, status)
            seen.set()
            return value
        monkeypatch.setattr(state.controller, "mark_delivery", mark)
        start_slow(ws, provider)
        fill(ws)
        ws.send_json({"type": "delivery_presented", "delivery_id": "missing-receipt"})
        assert seen.wait(2)
        assert len(owners) == 1 and owners[0][1:] == ("missing-receipt", "presented")
        assert owners[0][0]
        ws.send_json(envelope("cancel_turn", "cancel", session="c"))
        assert provider.cancelled.wait(2)
        until_end(ws)


def test_disconnect_behind_saturated_queue_cancels_provider_without_queued_effects(tmp_path):
    db = tmp_path / "disconnect.db"
    provider = ControlledProvider()
    with client_at(db) as client:
        with client.websocket_connect("/api/v2/math-tutor/ws") as ws:
            start_slow(ws, provider)
            fill(ws)
        assert provider.cancelled.wait(2)
        assert journal_ids(db) == {"active"}


def test_cancel_preserves_other_conversation_queue_and_duplicates_do_not_fill_it(tmp_path):
    db = tmp_path / "dedup.db"
    provider = ControlledProvider()
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        start_slow(ws, provider)
        for _ in range(20):
            ws.send_json(envelope("send_message", "active", {"text": "你好"}, session="c"))
        fill(ws, 1, session="other")
        ws.send_json(envelope("cancel_turn", "cancel", session="c"))
        assert provider.cancelled.wait(2)
        frames = until_end(ws)
        assert not any(f["payload"].get("error_code") == "REQUEST_CANCELLED_BEFORE_START" for f in frames)
        other = until_end(ws)
        assert any(f["event_type"] == "assistant_complete" and f["payload"].get("conversation_id") == "other" for f in other)
        assert journal_ids(db) == {"active", "queued-0"}
        assert provider.calls == 1


class FakeSocket:
    def __init__(self, frames=()):
        self.frames = asyncio.Queue()
        for frame in frames:
            self.frames.put_nowait(json.dumps(frame))
        self.send_started = asyncio.Event()
        self.send_cancelled = asyncio.Event()
        self.closed = []
        self.send_calls = 0
        self.simultaneous = 0
        self.max_simultaneous = 0

    async def accept(self):
        pass

    async def receive_text(self):
        return await self.frames.get()

    async def send_text(self, text):
        self.send_calls += 1
        self.simultaneous += 1
        self.max_simultaneous = max(self.max_simultaneous, self.simultaneous)
        self.send_started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.send_cancelled.set()
            raise
        finally:
            self.simultaneous -= 1

    async def close(self, **kwargs):
        self.closed.append(kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["full", "timeout"])
async def test_slow_socket_has_one_bounded_writer_and_closes_without_stalling_reader(monkeypatch, mode):
    import mathtutor.api.math_tutor_ws as module
    ws = FakeSocket([envelope("send_message", "one", {"text": "你好"}, session="c")])
    async def owner(_):
        return SimpleNamespace(student_id="owner")
    monkeypatch.setattr(module, "ws_require_student_owner", owner)
    monkeypatch.setattr(module, "get_product_state", lambda: SimpleNamespace())
    monkeypatch.setattr(module, "SEND_TIMEOUT_SECONDS", .05)
    observed_sizes = []
    real_queue = asyncio.Queue
    class Queue(real_queue):
        def put_nowait(self, item):
            value = super().put_nowait(item)
            observed_sizes.append((self.maxsize, self.qsize()))
            return value
    monkeypatch.setattr(module.asyncio, "Queue", Queue)
    async def process(state, owner, session, message, key, text, send, active, reason):
        active(asyncio.current_task(), session)
        for i in range(module.OUTGOING_CAPACITY + 2 if mode == "full" else 1):
            await send({"event_type": "assistant_start", "payload": {"turn_id": str(i)}})
            if i == 0:
                await ws.send_started.wait()
        await asyncio.Future()
    monkeypatch.setattr(module, "_process_request", process)
    await asyncio.wait_for(module.math_tutor_websocket(ws), 1)
    assert ws.closed[-1]["code"] == 1013
    assert ws.send_cancelled.is_set() and ws.max_simultaneous == 1
    assert all(0 < size <= maximum for maximum, size in observed_sizes)
    assert any(maximum == module.OUTGOING_CAPACITY for maximum, _ in observed_sizes)
    assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and t.get_name().startswith("math-tutor-ws-")]


def test_loopback_network_saturated_queue_cancels_within_two_seconds(tmp_path):
    """Real TCP/WebSocket framing, local mock model; no browser or live model."""
    import socket
    import uvicorn
    from websockets import connect
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings

    reset_product_state()
    db = tmp_path / "network.db"
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    app = create_math_tutor_app(MathTutorSecuritySettings(environment="development", host="127.0.0.1",
        allowed_hosts=(f"127.0.0.1:{port}",), allowed_origins=(origin,)), auth_enabled=False, db_path=str(db))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=lambda: server.run(sockets=[listener]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        provider = ControlledProvider()
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        async def exercise():
            async with connect(f"ws://127.0.0.1:{port}/api/v2/math-tutor/ws", open_timeout=3, origin=origin) as ws:
                await ws.send(json.dumps(envelope("send_message", "active", {"text": "你好"}, session="c")))
                assert json.loads(await asyncio.wait_for(ws.recv(), 2))["event_type"] == "assistant_start"
                assert provider.started.wait(2)
                for i in range(16):
                    await ws.send(json.dumps(envelope("submit_problem", f"queued-{i}", {"text": "2x+3=7"}, session="c")))
                started = time.monotonic()
                await ws.send(json.dumps(envelope("cancel_turn", "cancel", session="c")))
                frames = []
                while True:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), max(.001, 2 - (time.monotonic() - started))))
                    frames.append(frame)
                    if frame["event_type"] == "turn_end":
                        break
                assert time.monotonic() - started < 2
                assert provider.cancelled.is_set()
                assert sum(f["payload"].get("error_code") == "REQUEST_CANCELLED_BEFORE_START" for f in frames) == 16
                assert any(f["payload"].get("status") == "CANCELLED" for f in frames)
                assert journal_ids(db) == {"active"}
        asyncio.run(exercise())
    finally:
        server.should_exit = True
        thread.join(5)
        listener.close()
        reset_product_state()
    assert not thread.is_alive()


def test_cancel_in_admitted_request_prelude_never_starts_provider(tmp_path, monkeypatch):
    import mathtutor.api.math_tutor_ws as module
    entered, release = threading.Event(), threading.Event()
    async def budget(*args):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.001)
        return False
    monkeypatch.setattr(module, "_budget_exhausted", budget)
    provider = ControlledProvider()
    with client_at(tmp_path / "prelude.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        get_product_state().gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        ws.send_json(envelope("send_message", "active", {"text": "你好"}, session="c"))
        assert entered.wait(2)
        ws.send_json(envelope("cancel_turn", "cancel", session="c"))
        # This later control rejection proves the reader consumed cancellation
        # before the prelude is allowed to construct its controller task.
        ws.send_json(envelope("cancel_turn", "barrier", session="other"))
        assert ws.receive_json()["payload"]["error_code"] == "CANCEL_SESSION_MISMATCH"
        release.set()
        frames = until_end(ws)
        assert any(f["payload"].get("status") == "CANCELLED" for f in frames)
        assert provider.calls == 0


@pytest.mark.asyncio
async def test_oversized_input_closes_before_json_parsing(monkeypatch):
    import mathtutor.api.math_tutor_ws as module
    ws = FakeSocket()
    ws.frames.put_nowait("x" * (module.MAX_INCOMING_CHARS + 1))
    async def owner(_):
        return SimpleNamespace(student_id="owner")
    monkeypatch.setattr(module, "ws_require_student_owner", owner)
    monkeypatch.setattr(module, "get_product_state", lambda: SimpleNamespace())
    def forbidden_parse(*args, **kwargs):
        raise AssertionError("oversized input was parsed")
    monkeypatch.setattr(module.json, "loads", forbidden_parse)
    await asyncio.wait_for(module.math_tutor_websocket(ws), 1)
    assert ws.closed[-1]["code"] == 1009


@pytest.mark.asyncio
async def test_event_stream_backpressure_is_bounded_and_close_needs_no_free_slot():
    from mathtutor.api.event_stream import MathTutorEventStream, EVENT_STREAM_CAPACITY
    stream = MathTutorEventStream()
    for i in range(EVENT_STREAM_CAPACITY):
        await stream.content(str(i))
    blocked = asyncio.create_task(stream.content("not admitted"))
    await asyncio.sleep(0)
    assert not blocked.done()
    assert stream._queue.qsize() == stream._queue.maxsize == EVENT_STREAM_CAPACITY
    await asyncio.wait_for(stream.close(), .2)
    await asyncio.wait_for(blocked, .2)
    values = [event.content async for event in stream.subscribe()]
    assert values == [str(i) for i in range(EVENT_STREAM_CAPACITY)]
    assert stream._queue.qsize() == 0


@pytest.mark.asyncio
async def test_cancelled_event_producer_closes_full_stream_and_consumer_drains():
    from mathtutor.api.event_stream import MathTutorEventStream
    stream = MathTutorEventStream(capacity=1)
    async def produce():
        try:
            await stream.content("approved")
            await stream.content("still waiting")
        finally:
            await stream.close()
    producer = asyncio.create_task(produce())
    await asyncio.sleep(0)
    producer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(producer, .2)
    assert [event.content async for event in stream.subscribe()] == ["approved"]


@pytest.mark.asyncio
async def test_event_stream_close_wakes_empty_consumer_and_preserves_backpressure_order():
    from mathtutor.api.event_stream import MathTutorEventStream
    stream = MathTutorEventStream(capacity=1)
    async def consume():
        return [event.content async for event in stream.subscribe()]
    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)
    await stream.close()
    assert await asyncio.wait_for(consumer, .2) == []
    stream = MathTutorEventStream(capacity=1)
    async def produce():
        for value in range(100):
            await stream.content(str(value))
        await stream.close()
    producer = asyncio.create_task(produce())
    assert [event.content async for event in stream.subscribe()] == [str(value) for value in range(100)]
    await producer
