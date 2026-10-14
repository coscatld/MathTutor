"""Persistent turn traces and the health metrics computed from them."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import insert, select

from mathtutor.infrastructure.schema import turn_traces
from mathtutor.repositories.uow import MathTutorUow

#: Alert when, over the most recent turns, failures or partial answers exceed
#: these rates. A small sample never alerts.
ALERT_MIN_TURNS = 20
ALERT_RATES = {"failed_rate": 0.10, "partial_rate": 0.20, "formula_refuted_rate": 0.05}


class TurnTraceRepository:
    def __init__(self, engine=None):
        self.uow = MathTutorUow(engine) if engine is not None else None
        self._rows: list[dict] = []

    async def record(self, row: dict) -> None:
        row = {"created_at": datetime.now(timezone.utc).isoformat(), **row}
        if self.uow is None:
            self._rows = [r for r in self._rows if (r["student_id"], r["conversation_id"], r["turn_id"])
                          != (row["student_id"], row["conversation_id"], row["turn_id"])] + [row]
            return
        async with self.uow.transaction() as conn:
            await conn.execute(insert(turn_traces).prefix_with("OR REPLACE").values(**row))

    async def recent(self, student_id: str, *, limit: int = 200, status: str | None = None) -> list[dict]:
        if self.uow is None:
            rows = [r for r in self._rows if r["student_id"] == student_id and (not status or r["status"] == status)]
            return sorted(rows, key=lambda r: r["created_at"], reverse=True)[:limit]
        query = select(turn_traces).where(turn_traces.c.student_id == student_id)
        if status:
            query = query.where(turn_traces.c.status == status)
        async with self.uow.transaction() as conn:
            rows = (await conn.execute(query.order_by(turn_traces.c.created_at.desc()).limit(limit))).mappings().all()
        return [dict(r) for r in rows]

    async def forget(self, student_id: str, conversation_id: str) -> None:
        if self.uow is None:
            self._rows = [r for r in self._rows if (r["student_id"], r["conversation_id"]) != (student_id, conversation_id)]
            return
        async with self.uow.transaction() as conn:
            await conn.execute(turn_traces.delete().where(turn_traces.c.student_id == student_id,
                                                          turn_traces.c.conversation_id == conversation_id))


def health(rows: list[dict]) -> dict:
    """Persisted counterpart of loop_health(), plus threshold alerts."""
    n = len(rows)
    if not n:
        return {"turns": 0, "alerts": []}
    latencies = sorted(r["latency_ms"] for r in rows)
    refuted = sum(1 for r in rows if (r.get("details") or {}).get("formulas", {}).get("refuted"))
    metrics = {
        "turns": n,
        "failed_rate": round(sum(r["status"] == "FAILED" for r in rows) / n, 4),
        "partial_rate": round(sum(r["status"] == "PARTIAL" for r in rows) / n, 4),
        "provider_error_rate": round(sum(r["finish_reason"] == "PROVIDER_ERROR" for r in rows) / n, 4),
        "formula_refuted_rate": round(refuted / n, 4),
        "template_fallback_rate": round(sum(bool((r.get("details") or {}).get("template_fallback")) for r in rows) / n, 4),
        "dkt_adjust_rate": round(sum(bool((r.get("details") or {}).get("dkt")) for r in rows) / n, 4),
        "latency_p50_ms": latencies[n // 2],
        "latency_p95_ms": latencies[min(n - 1, int(n * 0.95))],
        "tokens": sum(r["input_tokens"] + r["output_tokens"] for r in rows),
    }
    alerts = [f"{key} {metrics[key]} > {limit}" for key, limit in ALERT_RATES.items()
              if n >= ALERT_MIN_TURNS and metrics[key] > limit]
    return {**metrics, "alerts": alerts}


__all__ = ["ALERT_MIN_TURNS", "ALERT_RATES", "TurnTraceRepository", "health"]
