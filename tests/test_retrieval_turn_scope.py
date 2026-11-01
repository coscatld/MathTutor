"""Concurrent response attempts use isolated counters over real retrieval/tools."""
import asyncio
import json
import threading

import pytest

from mathtutor.application.knowledge_qa import KnowledgeQA
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from mathtutor.infrastructure.observability import MathTutorMetrics
from test_knowledge_workbench import state
from test_phase6_observability import _execution
from test_tutor_p0 import client_at, collect, envelope


class InterleavedProvider:
    provider_id, model, supports_native_tools = "test", "scope-fixture", True

    def __init__(self):
        self.entered = {key: threading.Event() for key in ("A", "B")}
        self.release = {key: threading.Event() for key in ("A", "B")}

    async def complete(self, messages, **kwargs):
        request = json.loads(next(m["content"] for m in messages if m["role"] == "user"))["request"]
        key = "A" if "scope-A" in request else "B"
        if not any(m["role"] == "tool" for m in messages):
            self.entered[key].set()
            async with asyncio.timeout(8):
                while not self.release[key].is_set():
                    await asyncio.sleep(.001)
            if key == "A":
                # Three searches still mean one response needed a second retrieval.
                return CompletionResult(text="", provider_id=self.provider_id, model=self.model,
                    finish_reason="tool_calls", input_tokens=40, output_tokens=30,
                    tool_calls=tuple({"id": f"search-{i}", "type": "function", "function": {
                        "name": "search_knowledge", "arguments": json.dumps({"query": "移项"})}}
                        for i in range(3)))
        return CompletionResult(text=json.dumps({"claims": [], "uncertainties": ["请核对资料。"]}),
            provider_id=self.provider_id, model=self.model, finish_reason="stop", input_tokens=40, output_tokens=20)


async def prepare(product, owners):
    for owner, cid in owners:
        await product.conversations.ensure(owner, cid)
        lib = await product.knowledge.create_space(owner, "scope notes")
        await product.knowledge.save_markdown(owner, lib["space_id"], title="移项",
            body="# 移项\n等式两边同时减去相同的数，等式仍成立。", operation_id=f"note-{cid}")
        await product.knowledge.configure(owner, cid, space_ids=[lib["space_id"]], mode="knowledge")
    provider = InterleavedProvider()
    product.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
    return provider


async def entered(provider):
    async with asyncio.timeout(3):
        while not all(e.is_set() for e in provider.entered.values()):
            await asyncio.sleep(.001)


def assert_closed(metrics, *, second):
    rag = metrics.rag()
    assert rag["rag_turn_semantics_version"] == 2
    assert rag["rag_turns_total"] == rag["rag_turns_with_initial_total"] == 2
    assert rag["rag_retrieval_requested_total"] == 2
    assert rag["rag_turns_with_second_total"] == second
    assert rag["second_retrieval_rate"] == metrics.rag_health()["second_retrieval_rate"] == second / 2
    assert rag["tool_search_calls"] == (3 if second else 0)
    metrics.assert_sanitized()
    encoded = json.dumps(metrics.snapshot())
    assert all(secret not in encoded for secret in ("alice", "bob", "scope-A", "scope-B", "等式两边"))


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["A", "B"])
async def test_real_retrieval_and_tools_keep_each_response_scope(state, first):
    provider = await prepare(state, [("alice", "A"), ("bob", "other")])
    qa = KnowledgeQA(state)
    tasks = {key: asyncio.create_task(qa.respond(owner, "A" if key == "A" else "other", f"解释移项资料 scope-{key}"))
             for owner, key in (("alice", "A"), ("bob", "B"))}
    try:
        await entered(provider)
        assert state.metrics.rag()["rag_retrieval_requested_total"] == 2
        assert state.metrics.rag()["rag_turns_total"] == 0
        provider.release[first].set()
        await tasks[first]
        assert state.metrics.rag()["rag_turns_with_initial_total"] == 1
        provider.release["B" if first == "A" else "A"].set()
        await asyncio.gather(*tasks.values())
        assert_closed(state.metrics, second=1)
    finally:
        for event in provider.release.values():
            event.set()
        await asyncio.gather(*tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_response_does_not_clear_the_other_scope(state):
    provider = await prepare(state, [("alice", "A"), ("bob", "other")])
    qa = KnowledgeQA(state)
    a = asyncio.create_task(qa.respond("alice", "A", "解释移项资料 scope-A"))
    b = asyncio.create_task(qa.respond("bob", "other", "解释移项资料 scope-B"))
    try:
        await entered(provider)
        a.cancel()
        with pytest.raises(asyncio.CancelledError):
            await a
        provider.release["B"].set()
        await b
        assert_closed(state.metrics, second=0)
    finally:
        for event in provider.release.values():
            event.set()
        await asyncio.gather(a, b, return_exceptions=True)


def test_close_is_idempotent_and_late_unscoped_work_cannot_change_turn_facts():
    metrics = MathTutorMetrics()
    turn = metrics.begin_retrieval_turn()
    metrics.record_retrieval(_execution(), turn_stats=turn)
    metrics.end_retrieval_turn(turn)
    metrics.record_tool_call("search_knowledge", turn_stats=turn)
    metrics.record_retrieval(_execution())  # Other retrieval consumers have no QA scope.
    metrics.end_retrieval_turn(turn)
    assert metrics.rag()["rag_turns_total"] == 1
    assert metrics.rag()["rag_turns_with_initial_total"] == 1
    assert metrics.rag()["rag_turns_with_second_total"] == 0
    assert turn.closed and not turn.had_second
    with pytest.raises(ValueError):
        MathTutorMetrics().end_retrieval_turn(turn)


@pytest.mark.asyncio
async def test_standalone_retrieval_preserves_legacy_metric_sink_signature():
    from mathtutor.application.retrieval_orchestrator import ConversationRetrievalOrchestrator

    class Sink:
        def __init__(self):
            self.calls = []

        def record_retrieval(self, execution, *, latency_ms=None, rerank_ms=None, context_chars=0):
            self.calls.append(execution)

    sink = Sink()
    pack = await ConversationRetrievalOrchestrator(kernel=None, metrics=sink).retrieve_for_turn("owner", [], "query")
    assert len(sink.calls) == 1 and sink.calls[0] is pack.execution


@pytest.mark.asyncio
async def test_error_closes_once_and_fresh_attempt_gets_a_new_scope():
    from types import SimpleNamespace
    metrics = MathTutorMetrics()
    qa = KnowledgeQA(SimpleNamespace(metrics=metrics))
    observed = []

    async def fail(*args, retrieval_turn, **kwargs):
        observed.append(retrieval_turn)
        metrics.record_retrieval(_execution(), turn_stats=retrieval_turn)
        raise RuntimeError("controlled failure")

    qa._respond = fail
    for _ in range(2):
        with pytest.raises(RuntimeError, match="controlled failure"):
            await qa.respond("owner", "session", "query")
    assert observed[0] is not observed[1] and all(t.closed for t in observed)
    assert metrics.rag()["rag_turns_total"] == metrics.rag()["rag_turns_with_initial_total"] == 2


@pytest.mark.parametrize("first", ["A", "B", "cancel-A"])
def test_two_real_ws_sessions_preserve_scope_and_replay_does_not_add_attempt(tmp_path, first, monkeypatch):
    from mathtutor.api.product_state import get_product_state
    from mathtutor.api import math_tutor_ws
    from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
    # Existing owner-level write locks serialize one owner's conversations.
    # Authentication is the only stub: two fixed server-owned identities make
    # the real product path concurrent without weakening production locks.
    owners = iter(StudentOwnerScope(PrincipalScope(name, name, "student"), name)
                  for name in ("alice", "bob"))

    async def authenticated_owner(ws):
        return next(owners)

    monkeypatch.setattr(math_tutor_ws, "ws_require_student_owner", authenticated_owner)
    with client_at(tmp_path / "two-sessions.db") as client:
        product = get_product_state()
        provider = client.portal.call(prepare, product, [("alice", "A"), ("bob", "B")])
        with client.websocket_connect("/api/v2/math-tutor/ws") as a, \
             client.websocket_connect("/api/v2/math-tutor/ws") as b:
            sockets = {"A": a, "B": b}
            requests = {key: envelope("send_message", f"request-{key}",
                {"text": f"解释移项资料 scope-{key}"}, session=key) for key in sockets}
            try:
                for key, ws in sockets.items():
                    ws.send_json(requests[key])
                if not all(e.wait(3) for e in provider.entered.values()):
                    for event in provider.release.values():
                        event.set()
                    frames = {key: collect(ws) for key, ws in sockets.items()}
                    pytest.fail(f"provider did not enter: {frames}")
                cancel = first == "cancel-A"
                first = "A" if cancel else first
                if cancel:
                    sockets[first].send_json(envelope("cancel_turn", "stop-A", session="A"))
                else:
                    provider.release[first].set()
                first_frames = collect(sockets[first])
                if cancel:
                    assert any(f["payload"].get("status") == "CANCELLED"
                               and f["payload"].get("finish_reason") == "USER_CANCELLED" for f in first_frames)
                else:
                    assert any(f["event_type"] == "assistant_complete" for f in first_frames)
                other = "B" if first == "A" else "A"
                provider.release[other].set()
                assert any(f["event_type"] == "assistant_complete" for f in collect(sockets[other]))
                assert_closed(product.metrics, second=0 if cancel else 1)
                sockets[first].send_json(requests[first])
                assert collect(sockets[first]) == first_frames
                assert_closed(product.metrics, second=0 if cancel else 1)
            finally:
                for event in provider.release.values():
                    event.set()
