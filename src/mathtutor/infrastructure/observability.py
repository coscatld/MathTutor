"""In-process observability: MathTutorMetrics + readiness aggregation.

Phase 6 productionization (§15/§17 SLO observability): latency histograms
(turn/attempt/offer), token COUNTS (caller-supplied aggregates — content is
never parsed or stored here), outbox lag, release-gate pass/deny counters,
and the readiness aggregation the product health endpoint consumes.

Sanitization is structural, not heuristic: metrics keys are a fixed
allowlist, :func:`sanitize_for_logs` redacts any key/value that could carry
API keys, model reasoning, attestation payloads or full documents, and
``MathTutorMetrics.assert_sanitized()`` FAILS LOUDLY if a forbidden key
ever appears in the snapshot (the permanent invariant: no API key / model
reasoning / attestation payload / full document in logs, events or errors).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Substrings that make a KEY forbidden in metrics/logs. Normalized to
#: lower-case, "-" and " " → "_" before matching. Deliberately the STRONG
#: set (permanent invariant §19: API key / model reasoning / attestation
#: payload / full document content). "token" is intentionally NOT here —
#: token COUNTS are a legitimate logged metric; actual secret tokens are
#: caught by the value markers below instead.
_FORBIDDEN_KEY_FRAGMENTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "secret",
    "password",
    "reasoning",
    "attestation",
    "payload",
    "document",
)

#: Value markers that force a value to be redacted (secret-looking strings).
_SENSITIVE_VALUE_MARKERS: tuple[str, ...] = (
    "sk-",
    "Bearer ",
    "api_key=",
    "attestation_hash",
    "<redacted>",
)

#: Latency histogram bucket upper bounds (ms).
LATENCY_BUCKETS_MS: tuple[float, ...] = (10, 50, 100, 250, 500, 1000, 2500, 5000)

_LATENCY_KINDS = ("turn", "attempt", "offer")
_RELEASE_GATE_OUTCOMES = ("passed", "denied")


@dataclass(frozen=True, slots=True)
class Histogram:
    """Count + fixed buckets; deterministic, dependency-free."""

    count: int = 0
    min_ms: float | None = None
    max_ms: float | None = None
    mean_ms: float = 0.0
    buckets: tuple[tuple[float, int], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "buckets": [list(pair) for pair in self.buckets],
        }


def sanitize_for_logs(key: str, value: Any) -> Any:
    """Return a log-safe value for ``key``; forbidden content → ``<redacted>``.

    Key-based redaction is absolute (structural): any key whose normalized
    form contains a forbidden fragment is redacted. Value markers catch
    obvious secret strings (``sk-``, ``Bearer ``) regardless of key.
    """
    normalized = key.lower().replace("-", "_").replace(" ", "_")
    if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
        return "<redacted>"
    if isinstance(value, dict):
        return {k: sanitize_for_logs(k, v) for k, v in value.items()}
    if isinstance(value, str) and any(
        marker in value for marker in _SENSITIVE_VALUE_MARKERS
    ):
        return "<redacted>"
    return value


def aggregate_readiness(
    *,
    db_ok: bool,
    migration_head: str | None,
    gateway_configured: bool,
    embedding_backend: bool,
) -> tuple[str, dict[str, Any]]:
    """Pure readiness aggregation → ("READY"|"DEGRADED"|"BLOCKED", details).

    - BLOCKED: database unreachable or migrations not at head (fail closed);
    - DEGRADED: core up, but a non-critical dependency is missing
      (gateway unconfigured / embedding backend unavailable);
    - READY: everything green.
    """
    details: dict[str, Any] = {
        "db_ok": db_ok,
        "migration_head": migration_head,
        "gateway_configured": gateway_configured,
        "embedding_backend": embedding_backend,
    }
    if not db_ok:
        return "BLOCKED", {**details, "reason": "数据库不可达"}
    if not migration_head:
        return "BLOCKED", {**details, "reason": "迁移未到 head"}
    problems: list[str] = []
    if not gateway_configured:
        problems.append("gateway 未配置")
    if not embedding_backend:
        problems.append("embedding backend 不可用")
    if problems:
        return "DEGRADED", {**details, "reason": "; ".join(problems)}
    return "READY", {**details, "reason": "全部就绪"}


class MathTutorMetrics:
    """Process-local metric registry (latency, tokens, lag, release gate)."""

    def __init__(self) -> None:
        self._latencies: dict[str, list[float]] = {kind: [] for kind in _LATENCY_KINDS}
        self._tokens: dict[str, int] = {"input": 0, "output": 0, "total": 0}
        self._release_gate: dict[str, int] = {outcome: 0 for outcome in _RELEASE_GATE_OUTCOMES}
        self._outbox_pending: int | None = None
        self._outbox_oldest_seconds: float | None = None

    # ----------------------------------------------------------- record

    def record_latency(self, kind: str, milliseconds: float) -> None:
        """Record one latency sample for turn/attempt/offer."""
        if kind not in self._latencies:
            raise ValueError(f"未知延迟类型: {kind!r}（允许 {_LATENCY_KINDS}）")
        self._latencies[kind].append(float(milliseconds))

    def record_tokens(self, count: int, *, kind: str = "total") -> None:
        """Aggregate a token COUNT. Values only — content is never parsed."""
        if kind not in self._tokens:
            raise ValueError(f"未知 token 类型: {kind!r}")
        self._tokens[kind] += int(count)

    def record_release_gate(self, outcome: str) -> None:
        """Count a release-gate decision: 'passed' | 'denied'."""
        if outcome not in self._release_gate:
            raise ValueError(f"未知 release gate 结果: {outcome!r}")
        self._release_gate[outcome] += 1

    def record_outbox_lag(self, *, pending: int, oldest_seconds: float | None) -> None:
        """Snapshot the relay backlog (pending count + oldest event age)."""
        self._outbox_pending = int(pending)
        self._outbox_oldest_seconds = (
            float(oldest_seconds) if oldest_seconds is not None else None
        )

    # ------------------------------------------------------------ read

    def latency_histogram(self, kind: str) -> Histogram:
        if kind not in self._latencies:
            raise ValueError(f"未知延迟类型: {kind!r}")
        samples = self._latencies[kind]
        if not samples:
            return Histogram()
        buckets = tuple(
            (upper, sum(1 for s in samples if s <= upper))
            for upper in LATENCY_BUCKETS_MS
        )
        return Histogram(
            count=len(samples),
            min_ms=min(samples),
            max_ms=max(samples),
            mean_ms=sum(samples) / len(samples),
            buckets=buckets,
        )

    def tokens(self) -> dict[str, int]:
        return dict(self._tokens)

    def release_gate(self) -> dict[str, int]:
        return dict(self._release_gate)

    def outbox_lag(self) -> dict[str, Any]:
        return {
            "pending": self._outbox_pending,
            "oldest_seconds": self._outbox_oldest_seconds,
        }

    def snapshot(self) -> dict[str, Any]:
        """Full sanitized snapshot — the ONLY surface for logs/exports."""
        return {
            "latency": {kind: self.latency_histogram(kind).to_dict() for kind in _LATENCY_KINDS},
            "tokens": dict(self._tokens),
            "release_gate": dict(self._release_gate),
            "outbox_lag": self.outbox_lag(),
        }

    def assert_sanitized(self) -> None:
        """Fail loudly if any forbidden key/value ever enters the snapshot.

        Structural guarantee: metrics keys are a fixed allowlist today; this
        guard keeps future additions honest (permanent invariant §19).
        """
        snapshot = self.snapshot()
        forbidden: list[str] = []
        for key, value in _walk(snapshot):
            normalized = key.lower().replace("-", "_").replace(" ", "_")
            if any(fragment in normalized for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                forbidden.append(key)
            elif isinstance(value, str) and any(
                marker in value for marker in _SENSITIVE_VALUE_MARKERS
            ):
                forbidden.append(key)
        if forbidden:
            raise AssertionError(f"指标快照出现敏感键: {forbidden}")


def _walk(mapping: dict[str, Any], prefix: str = ""):
    for key, value in mapping.items():
        full = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _walk(value, full)
        else:
            yield full, value


__all__ = [
    "LATENCY_BUCKETS_MS",
    "Histogram",
    "MathTutorMetrics",
    "aggregate_readiness",
    "sanitize_for_logs",
]
