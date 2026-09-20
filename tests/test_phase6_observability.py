"""Phase 6 — observability tests (latency/tokens/lag/gate + readiness).

Covers: in-process latency histograms and counts, aggregate token COUNTS
(never content), outbox lag snapshots, release-gate counters, the
structural sanitization guarantee (API key / model reasoning / attestation
payload / full document content never appear in metrics or log values),
and the pure three-state readiness matrix.
"""

from __future__ import annotations

import pytest

from mathtutor.infrastructure.observability import (
    MathTutorMetrics,
    aggregate_readiness,
    sanitize_for_logs,
)

pytestmark = pytest.mark.asyncio


async def test_metrics_record_latency_tokens_lag_gate_and_sanitize():
    metrics = MathTutorMetrics()
    metrics.record_latency("turn", 12.5)
    metrics.record_latency("turn", 60.0)
    metrics.record_latency("turn", 260.0)
    metrics.record_latency("turn", 3000.0)
    metrics.record_latency("attempt", 150.0)
    metrics.record_latency("offer", 42.0)

    histogram = metrics.latency_histogram("turn")
    assert histogram.count == 4
    assert histogram.min_ms == 12.5
    assert histogram.max_ms == 3000.0
    buckets = dict(histogram.buckets)
    assert buckets[100.0] == 2
    assert buckets[1000.0] == 3
    assert buckets[5000.0] == 4
    assert metrics.latency_histogram("offer").count == 1

    metrics.record_tokens(1200, kind="input")
    metrics.record_tokens(3400, kind="output")
    metrics.record_tokens(4600)  # total
    assert metrics.tokens() == {"input": 1200, "output": 3400, "total": 4600}

    metrics.record_release_gate("passed")
    metrics.record_release_gate("passed")
    metrics.record_release_gate("denied")
    assert metrics.release_gate() == {"passed": 2, "denied": 1}

    metrics.record_outbox_lag(pending=5, oldest_seconds=120.5)
    assert metrics.outbox_lag() == {"pending": 5, "oldest_seconds": 120.5}
    snapshot = metrics.snapshot()
    assert snapshot["outbox_lag"]["pending"] == 5
    # 结构性保证：快照中不存在任何敏感键。
    metrics.assert_sanitized()

    # 消毒：API key / reasoning / attestation payload / 完整文档永远被替换。
    assert sanitize_for_logs("api_key", "sk-abc123") == "<redacted>"
    assert sanitize_for_logs("model_reasoning", "step-by-step reasoning") == "<redacted>"
    assert sanitize_for_logs("attestation_payload", {"problem_hash": "x"}) == "<redacted>"
    assert sanitize_for_logs("full_document_text", "the whole document...") == "<redacted>"
    assert sanitize_for_logs("notes", "Bearer sk-secret") == "<redacted>"
    # 合法指标键与普通值原样保留；token 计数是合法日志值。
    assert sanitize_for_logs("turn_latency_ms", 12.5) == 12.5
    assert sanitize_for_logs("tokens", 123) == 123
    assert sanitize_for_logs("outbox_lag", {"pending": 3}) == {"pending": 3}


async def test_readiness_three_state_matrix():
    """aggregate_readiness 纯函数三态矩阵：BLOCKED 优先于 DEGRADED。"""
    cases = [
        (True, "mt-005", True, True, "READY"),
        (False, "mt-005", True, True, "BLOCKED"),
        (True, None, True, True, "BLOCKED"),
        (True, "mt-005", False, True, "DEGRADED"),
        (True, "mt-005", True, False, "DEGRADED"),
        (True, "mt-005", False, False, "DEGRADED"),
        (True, None, False, False, "BLOCKED"),  # BLOCKED 盖过 DEGRADED
    ]
    for db_ok, migration_head, gateway, embedding, expected in cases:
        status, details = aggregate_readiness(
            db_ok=db_ok,
            migration_head=migration_head,
            gateway_configured=gateway,
            embedding_backend=embedding,
        )
        assert status == expected, cases
        assert details["db_ok"] == db_ok
        assert "reason" in details and details["reason"]


# ----------------------------------------------------- RAG telemetry (§20)

from mathtutor.domain.evidence import Evidence, RetrievalExecution, build_evidence_pack


def _execution(**overrides) -> RetrievalExecution:
    values = dict(
        retrieval_ran=True,
        mode="lexical",
        reranker_used=True,
        items_returned=3,
        candidates_considered=12,
        decision="conversation_documents",
    )
    values.update(overrides)
    return RetrievalExecution(**values)


def test_rag_counters_fold_one_execution():
    metrics = MathTutorMetrics()
    metrics.record_retrieval(_execution(), latency_ms=42.0, rerank_ms=3.0, context_chars=800)
    rag = metrics.rag()

    assert rag["rag_retrieval_requested_total"] == 1
    assert rag["rag_lexical_only_total"] == 1
    assert rag["rag_hybrid_total"] == 0
    assert rag["rag_candidates_considered"] == 12
    assert rag["rag_evidence_items"] == 3
    assert rag["rag_evidence_chars"] == 800
    assert metrics.latency_histogram("retrieval").count == 1
    assert metrics.latency_histogram("rerank").count == 1


def test_skipped_retrieval_is_counted_separately():
    """'We chose not to search' must not be indistinguishable from 'we
    searched and found nothing' — the rates below depend on the difference."""
    metrics = MathTutorMetrics()
    metrics.record_retrieval(
        RetrievalExecution(retrieval_ran=False, decision="none",
                           degraded_reasons=("decision_none_small_talk",))
    )
    rag = metrics.rag()
    assert rag["rag_retrieval_skipped_total"] == 1
    assert rag["rag_retrieval_requested_total"] == 0
    assert rag["rag_empty_retrieval_total"] == 0


def test_empty_retrieval_counts_only_when_retrieval_actually_ran():
    metrics = MathTutorMetrics()
    metrics.record_retrieval(_execution(items_returned=0))
    assert metrics.rag()["rag_empty_retrieval_total"] == 1
    assert metrics.rag()["empty_retrieval_rate"] == 1.0


def test_degradation_reasons_are_counted_without_parsing_prose():
    metrics = MathTutorMetrics()
    metrics.record_retrieval(
        _execution(degraded_reasons=("embedding_runtime_unavailable",))
    )
    metrics.record_retrieval(
        _execution(mode="hybrid", items_returned=1, degraded_reasons=())
    )
    rag = metrics.rag()
    assert rag["rag_degraded_total"] == 1
    assert rag["rag_vector_unavailable_total"] == 1
    assert rag["rag_hybrid_total"] == 1


def test_second_retrieval_rate_is_defined_over_turns_not_calls():
    """Of the turns that retrieved, how many needed the agent to search again?

    The denominator is TURNS, so three searches in one turn still count as one
    turn the initial retrieval did not satisfy — a call-count ratio would
    overstate how often the initial retrieval was insufficient.
    """
    metrics = MathTutorMetrics()

    metrics.record_retrieval(_execution())          # turn 1: needs a 2nd search
    metrics.record_tool_call("search_knowledge")
    metrics.record_tool_call("search_knowledge")    # same turn, still one turn
    metrics.end_retrieval_turn()

    for _ in range(3):                              # turns 2-4: initial suffices
        metrics.record_retrieval(_execution())
        metrics.end_retrieval_turn()

    metrics.record_tool_call("read_source")
    metrics.record_tool_call("save_note")           # not a retrieval tool

    rag = metrics.rag()
    assert rag["tool_search_calls"] == 2
    assert rag["tool_read_calls"] == 1
    assert rag["rag_turns_with_initial_total"] == 4
    assert rag["rag_turns_with_second_total"] == 1
    assert rag["second_retrieval_rate"] == 0.25
    # The cost signal is kept separate so neither number is mistaken for the
    # other: 2 searches across 4 turns.
    assert rag["average_second_search_calls"] == 0.5


def test_turn_closure_is_required_for_the_rates_to_mean_anything():
    """Without end_retrieval_turn the denominator stays 0 — the rate reads
    0.0, which is indistinguishable from 'never needed a second search'."""
    metrics = MathTutorMetrics()
    metrics.record_retrieval(_execution())
    metrics.record_tool_call("search_knowledge")

    assert metrics.rag()["second_retrieval_rate"] == 0.0
    assert metrics.rag()["rag_turns_with_initial_total"] == 0

    metrics.end_retrieval_turn()
    assert metrics.rag()["second_retrieval_rate"] == 1.0


def test_rag_health_is_scalars_only():
    metrics = MathTutorMetrics()
    metrics.record_retrieval(_execution(), latency_ms=11.0, rerank_ms=1.0, context_chars=200)
    metrics.record_tool_call("search_knowledge")
    metrics.end_retrieval_turn()
    metrics.record_citations(2, unsupported=1)

    health = metrics.rag_health()
    assert health["retrieval_request_rate"] == 1.0
    assert health["second_retrieval_rate"] == 1.0
    assert health["average_retrieved_candidates"] == 12.0
    assert health["average_retrieval_latency"] == 11.0
    assert health["citation_invalid_rate"] == 0.5
    # Structural: no field can carry text or an identifier.
    assert all(isinstance(value, (int, float)) for value in health.values())
    assert "rag_health" in metrics.snapshot()


def test_rates_do_not_divide_by_zero():
    metrics = MathTutorMetrics()
    rag = metrics.rag()
    assert rag["second_retrieval_rate"] == 0.0
    assert rag["empty_retrieval_rate"] == 0.0


def test_rag_snapshot_passes_the_structural_sanitization_guard():
    """RAG counters must stay inside the closed key allowlist."""
    metrics = MathTutorMetrics()
    metrics.record_retrieval(_execution(), latency_ms=10.0)
    metrics.record_tool_call("search_knowledge")
    metrics.record_citations(2)

    snapshot = metrics.snapshot()
    assert "rag" in snapshot
    metrics.assert_sanitized()  # raises if a forbidden key ever appears


def test_rag_counters_carry_no_document_text():
    """Structural: every RAG counter value is an int or float — there is no
    field a chunk of text could be smuggled into."""
    metrics = MathTutorMetrics()
    metrics.record_retrieval(_execution(), context_chars=1234)
    for key, value in metrics.rag().items():
        assert isinstance(value, (int, float)), f"{key} carries {type(value)}"


def test_tool_metrics_failure_never_breaks_the_tool_call():
    class _Exploding:
        def record_tool_call(self, name):
            raise RuntimeError("metrics down")

    from types import SimpleNamespace

    from mathtutor.application.knowledge_tools import KnowledgeTools

    tools = KnowledgeTools.__new__(KnowledgeTools)
    tools.state = SimpleNamespace(metrics=_Exploding())
    # Must not raise: telemetry is never allowed to break a tool call.
    tools._record_tool_metric("search_knowledge", {"ok": True})


@pytest.mark.asyncio
async def test_product_state_constructs_the_metrics_registry():
    """Regression: MathTutorMetrics existed but was constructed only by tests,
    so nothing in production recorded any of this."""
    from mathtutor.api.product_state import ProductState

    state = ProductState()
    try:
        assert state.metrics is not None
        state.metrics.record_retrieval(_execution())
        assert state.metrics.rag()["rag_retrieval_requested_total"] == 1
    finally:
        reset = getattr(ProductState, "reset", None)
        if reset is not None:
            state.reset()


@pytest.mark.asyncio
async def test_orchestrator_records_into_the_sink_it_is_given():
    from uuid import uuid4

    from mathtutor.application.retrieval_orchestrator import (
        ConversationRetrievalOrchestrator,
    )
    from mathtutor.domain.documents import DocumentChunk, DocumentQueryResult, RetrievedChunk
    from mathtutor.security.scopes import student_uuid

    document_id = uuid4()

    class _Kernel:
        async def search(self, sid, *, query, limit=5, document_ids=None):
            chunk = DocumentChunk(
                chunk_id=uuid4(), document_id=document_id,
                student_id=student_uuid("m"), sequence=0,
                text="一元二次方程的求根公式。", content_hash="h",
            )
            return DocumentQueryResult(
                query=query,
                hits=(RetrievedChunk(chunk=chunk, document_id=document_id,
                                     filename="n.md", score=0.5, lexical_score=0.5),),
                vector_used=False, degraded=True,
            )

    metrics = MathTutorMetrics()
    orchestrator = ConversationRetrievalOrchestrator(kernel=_Kernel(), metrics=metrics)
    await orchestrator.retrieve_for_turn("m", [document_id], "求根公式")
    await orchestrator.retrieve_for_turn("m", [document_id], "你好")

    rag = metrics.rag()
    assert rag["rag_retrieval_requested_total"] == 1
    assert rag["rag_retrieval_skipped_total"] == 1
    assert metrics.latency_histogram("retrieval").count == 1
