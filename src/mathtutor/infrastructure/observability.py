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

_LATENCY_KINDS = (
    "turn",
    "attempt",
    "offer",
    # RAG stages. Recorded separately because "retrieval is slow" and
    # "reranking is slow" call for completely different fixes.
    "retrieval",
    "rerank",
    "context_build",
)
_RELEASE_GATE_OUTCOMES = ("passed", "denied")

#: RAG counter allowlist. Fixed, because :meth:`MathTutorMetrics.assert_sanitized`
#: is structural: it can only guarantee "no sensitive key ever appears" if the
#: key set is closed.
#:
#: NOTE on ``rag_reranker_unavailable_total`` from the requirements list: it is
#: deliberately ABSENT. The production reranker is deterministic and shipped
#: with the app, so it has no "unavailable" state — a counter that cannot fire
#: would imply a capability gap that does not exist. An optional model reranker
#: would introduce one, and should add the counter then.
_RAG_COUNTERS: tuple[str, ...] = (
    "rag_retrieval_requested_total",
    "rag_retrieval_skipped_total",
    "rag_empty_retrieval_total",
    "rag_lexical_only_total",
    "rag_hybrid_total",
    "rag_degraded_total",
    "rag_vector_unavailable_total",
    "rag_expansion_used_total",
    "rag_candidates_considered",
    "rag_evidence_items",
    "rag_evidence_chars",
    "tool_search_calls",
    "tool_read_calls",
    "citation_count",
    "unsupported_claim_count",
    # Turn-level denominators. `second_retrieval_rate` is defined over TURNS,
    # not calls: one turn that searches three times is still one turn the
    # initial retrieval did not satisfy.
    "rag_turns_total",
    "rag_turns_with_initial_total",
    "rag_turns_with_second_total",
)


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
        self._rag: dict[str, int] = {name: 0 for name in _RAG_COUNTERS}
        self._turn_had_initial_retrieval = False
        self._turn_had_second = False

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

    # --------------------------------------------------------------- RAG

    def record_retrieval(
        self,
        execution: Any,
        *,
        latency_ms: float | None = None,
        rerank_ms: float | None = None,
        context_chars: int = 0,
    ) -> None:
        """Fold one turn's :class:`RetrievalExecution` into the counters.

        Takes the execution object directly so the recorded facts are the ones
        the retrieval stack actually reported, not a re-derivation from config.
        Only counts and reason codes are stored — never chunk text.
        """
        asked = bool(getattr(execution, "retrieval_ran", False))
        decision = str(getattr(execution, "decision", "") or "")
        if asked:
            self._rag["rag_retrieval_requested_total"] += 1
            self._turn_had_initial_retrieval = True
        elif decision:
            self._rag["rag_retrieval_skipped_total"] += 1

        mode = str(getattr(execution, "mode", "lexical"))
        if asked:
            key = "rag_hybrid_total" if mode == "hybrid" else "rag_lexical_only_total"
            self._rag[key] += 1

        reasons = tuple(getattr(execution, "degraded_reasons", ()) or ())
        if reasons:
            self._rag["rag_degraded_total"] += 1
        if "embedding_runtime_unavailable" in reasons:
            self._rag["rag_vector_unavailable_total"] += 1
        if bool(getattr(execution, "expansion_used", False)):
            self._rag["rag_expansion_used_total"] += 1

        items = int(getattr(execution, "items_returned", 0) or 0)
        if asked and items == 0:
            self._rag["rag_empty_retrieval_total"] += 1
        self._rag["rag_candidates_considered"] += int(
            getattr(execution, "candidates_considered", 0) or 0
        )
        self._rag["rag_evidence_items"] += items
        self._rag["rag_evidence_chars"] += int(context_chars or 0)

        if latency_ms is not None:
            self.record_latency("retrieval", latency_ms)
        if rerank_ms is not None:
            self.record_latency("rerank", rerank_ms)

    def record_tool_call(self, tool_name: str) -> None:
        """Count an executed application-tool call by name.

        Only the two retrieval tools are counted; anything else is ignored
        rather than growing the key set at runtime.
        """
        if tool_name == "search_knowledge":
            self._rag["tool_search_calls"] += 1
            # Turn-level flag for `second_retrieval_rate`. Guarded so three
            # searches in one turn still count as ONE turn that needed a
            # second retrieval — a call-count ratio would overstate how often
            # the initial retrieval was insufficient.
            if self._turn_had_initial_retrieval and not self._turn_had_second:
                self._turn_had_second = True
        elif tool_name == "read_source":
            self._rag["tool_read_calls"] += 1

    def end_retrieval_turn(self) -> None:
        """Close the current turn's retrieval bookkeeping.

        Must be called once per turn by the turn owner. Without it the turn
        denominators never accumulate and the rates read as 0 forever — an
        absent measurement, not a healthy one.
        """
        self._rag["rag_turns_total"] += 1
        if self._turn_had_initial_retrieval:
            self._rag["rag_turns_with_initial_total"] += 1
            if self._turn_had_second:
                self._rag["rag_turns_with_second_total"] += 1
        self._turn_had_initial_retrieval = False
        self._turn_had_second = False

    def record_citations(self, count: int, *, unsupported: int = 0) -> None:
        """Count citations in a final answer, plus any that failed support."""
        self._rag["citation_count"] += max(0, int(count))
        self._rag["unsupported_claim_count"] += max(0, int(unsupported))

    def rag(self) -> dict[str, Any]:
        """RAG counters plus the rates that are meaningful only as ratios.

        The rates answer different questions and use different denominators on
        purpose:

        ``second_retrieval_rate``
            ``turns_with_second_retrieval / turns_with_initial_retrieval``.
            "Of the turns where the system retrieved, how many needed the
            agent to search again?" — the diagnostic for whether the initial
            retrieval is adequate.

        ``average_second_search_calls``
            ``tool_search_calls / turns_with_initial_retrieval``. "How many
            searches does a turn take on average?" — a cost signal. Kept
            separate so neither number is mistaken for the other.
        """
        requested = self._rag["rag_retrieval_requested_total"]
        turns_initial = self._rag["rag_turns_with_initial_total"]
        turns_second = self._rag["rag_turns_with_second_total"]
        searched = self._rag["tool_search_calls"]
        return {
            **dict(self._rag),
            "second_retrieval_rate": (
                round(turns_second / turns_initial, 4) if turns_initial else 0.0
            ),
            "average_second_search_calls": (
                round(searched / turns_initial, 4) if turns_initial else 0.0
            ),
            "empty_retrieval_rate": (
                round(self._rag["rag_empty_retrieval_total"] / requested, 4)
                if requested
                else 0.0
            ),
        }

    def rag_health(self) -> dict[str, float]:
        """Scalar-only RAG health aggregate (mirrors ``loop_health``).

        Structural guarantee: every value is a number. No query text, document
        name, student id or conversation id can appear here — there is no
        field for one.
        """
        turns_initial = self._rag["rag_turns_with_initial_total"]
        requested = self._rag["rag_retrieval_requested_total"]
        retrieval = self.latency_histogram("retrieval")
        rerank = self.latency_histogram("rerank")
        context = self.latency_histogram("context_build")
        citations = self._rag["citation_count"]

        def rate(numerator: int, denominator: int) -> float:
            return round(numerator / denominator, 4) if denominator else 0.0

        return {
            # Share of ALL closed turns where the system actually retrieved.
            # Dividing by `turns_initial` here would make this 9.0 for nine
            # searches in one turn — a ratio that cannot exceed 1 mislabelled
            # as a rate.
            "retrieval_request_rate": rate(
                self._rag["rag_turns_with_initial_total"], self._rag["rag_turns_total"]
            ),
            "empty_retrieval_rate": rate(
                self._rag["rag_empty_retrieval_total"], requested
            ),
            "second_retrieval_rate": rate(
                self._rag["rag_turns_with_second_total"], turns_initial
            ),
            "average_retrieved_candidates": rate(
                self._rag["rag_candidates_considered"], requested
            ),
            "average_context_chunks": rate(
                self._rag["rag_evidence_items"], requested
            ),
            "average_context_chars": rate(
                self._rag["rag_evidence_chars"], requested
            ),
            "average_retrieval_latency": retrieval.mean_ms,
            "average_rerank_latency": rerank.mean_ms,
            "average_context_build_latency": context.mean_ms,
            "citation_invalid_rate": rate(
                self._rag["unsupported_claim_count"], citations
            ),
        }

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
            "rag": self.rag(),
            "rag_health": self.rag_health(),
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
