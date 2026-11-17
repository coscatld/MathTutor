"""Desktop diagnostics HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


@router.get("/diagnostics/turns")
async def turn_diagnostics(
    status: str | None = None,
    limit: int = 200,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Persisted turn health and recent turns: structure only, no text."""
    from mathtutor.repositories.turn_trace_repository import health

    state = get_product_state()
    traces = getattr(state, "turn_traces", None)
    if traces is None:
        return {"health": {"turns": 0, "alerts": []}, "turns": []}
    limit = max(1, min(limit, 1000))
    rows = await traces.recent(str(owner.student_id), limit=limit)
    shown = [row for row in rows if not status or row["status"] == status]
    return {
        "health": health(rows),
        "turns": [{k: v for k, v in row.items() if k != "student_id"} for row in shown],
    }
