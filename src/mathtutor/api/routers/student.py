"""Desktop student HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import StudentSummary
from mathtutor.api.product_state import get_product_state
from mathtutor.learning.skills import (
    SKILL_ARITHMETIC,
    SKILL_LINEAR_EQUATION,
    SKILL_POLYNOMIAL_BASIC,
    SKILL_QUADRATIC_EQUATION,
)
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()

_SKILL_DISPLAY: dict[str, tuple[str, str]] = {
    SKILL_ARITHMETIC: ("四则运算", "小学"),
    SKILL_POLYNOMIAL_BASIC: ("整式运算", "初中"),
    SKILL_LINEAR_EQUATION: ("一元一次方程", "初中"),
    SKILL_QUADRATIC_EQUATION: ("一元二次方程", "初中"),
}


async def _student_projection(
    state, student_id: str
) -> tuple[dict | None, int, set[str]]:
    """(projection, total_attempts, observed_skill_ids) from the SQLite
    education tables in both durable and ephemeral SQLite databases."""
    if state.uow is None:
        return None, 0, set()
    from sqlalchemy import func, select

    from mathtutor.infrastructure.schema import attempts
    from mathtutor.repositories import sqlite_education

    async with state.uow.transaction() as conn:
        projection = await sqlite_education.load_student_projection(conn, student_id)
        total = await conn.execute(
            select(func.count())
            .select_from(attempts)
            .where(attempts.c.student_id == student_id)
        )
        evidence = await sqlite_education.load_evidence_for_student(conn, student_id)
        return (
            projection,
            int(total.scalar() or 0),
            {item.skill_id for item in evidence},
        )


@router.get("/student-summary", response_model=StudentSummary)
async def student_summary(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Read-only evidence observations; probabilities remain internal."""
    from mathtutor.application.evidence_projection import public_evidence
    from mathtutor.application.learning_profile import profile_projection

    state = get_product_state()
    history = (
        await state.student_state.events(str(owner.student_id))
        if state.student_state
        else []
    )
    conversations = await state.conversations.list(owner.student_id)
    result = profile_projection(
        history,
        has_conversations=bool(conversations),
        model_status=state.student_state.dkt_mode
        if state.student_state
        else "not_trained",
    )
    result["evidence_summary"] = public_evidence(history)
    return result
