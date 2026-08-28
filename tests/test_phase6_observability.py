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
