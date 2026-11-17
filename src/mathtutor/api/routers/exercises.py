"""Desktop exercises HTTP adapter."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.learning_settings import _learner_service
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()

_QUESTION_BANK = None


def _question_bank():
    """One shared bank: the catalog and its verified problems are static content."""
    global _QUESTION_BANK
    if _QUESTION_BANK is None:
        from mathtutor.question_bank.service import QuestionBankService

        _QUESTION_BANK = QuestionBankService()
    return _QUESTION_BANK


@router.get("/exercise-bank")
async def get_question_bank(
    stage: str | None = None, owner: StudentOwnerScope = Depends(require_student_owner)
) -> dict:
    """Catalog tree for one stage (default: the learner's stage; none set → all stages)."""
    from mathtutor.question_bank.service import STAGES

    if stage is not None and stage not in STAGES:
        raise HTTPException(
            status_code=422, detail="学段只能是 primary、middle 或 high"
        )
    chosen = stage or _learner_service(get_product_state()).current().stage
    return await asyncio.to_thread(_question_bank().tree, chosen)


@router.get("/exercise-bank/points/{code}")
async def get_question_bank_point(
    code: str, owner: StudentOwnerScope = Depends(require_student_owner)
) -> dict:
    detail = await _question_bank().point(code)
    if detail is None:
        raise HTTPException(status_code=404, detail="没有这个知识点")
    return detail
