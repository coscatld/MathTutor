"""Desktop learning settings HTTP adapter."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.desktop_contracts import CostSettings
from mathtutor.api.product_state import get_product_state
from mathtutor.api.routers.schemas import CostSettingsUpdate, LearnerUpdate
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


@router.get("/settings/cost", response_model=CostSettings)
async def get_cost_settings(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """Prices, budget and today's usage. Costs exist only where prices are set."""
    state = get_product_state()
    policy = getattr(state, "cost_policy", None)
    if policy is None:
        raise HTTPException(status_code=503, detail="成本设置不可用")
    start, end = policy.utc_day_bounds()
    if getattr(state, "turn_traces", None) is None:
        aggregate = {"tokens": 0, "cost": 0, "turns": 0}
    else:
        aggregate = await state.turn_traces.usage_for_day(
            str(owner.student_id), start=start, end=end
        )
    usage = policy.usage_from_aggregate(aggregate, date=start)
    return {
        **policy.current().model_dump(),
        "today": usage,
        "over_budget": policy.over_budget(usage),
    }


@router.put("/settings/cost", response_model=CostSettings)
async def put_cost_settings(
    update: CostSettingsUpdate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    policy = getattr(get_product_state(), "cost_policy", None)
    if policy is None:
        raise HTTPException(status_code=503, detail="成本设置不可用")
    try:
        policy.update(update.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return await get_cost_settings(owner)


def _learner_service(state):
    service = getattr(state, "learner_settings", None)
    if service is None:
        from mathtutor.infrastructure.learner_settings import LearnerSettingsService

        service = state.learner_settings = LearnerSettingsService(None)
    return service


@router.get("/settings/learner")
async def get_learner_settings(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    """The learner's stage and grade; the question bank defaults to this stage."""
    return _learner_service(get_product_state()).public()


@router.put("/settings/learner")
async def put_learner_settings(
    update: LearnerUpdate, owner: StudentOwnerScope = Depends(require_student_owner)
) -> dict:
    try:
        return _learner_service(get_product_state()).update(update.stage, update.grade)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
