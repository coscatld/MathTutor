"""Owner-scoped learning evidence reads, exclusions and explicit replay."""
from fastapi import APIRouter, Depends, HTTPException, Query
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.security.scopes import StudentOwnerScope
from mathtutor.application.learning_profile import evidence_page, revoke_pending

router = APIRouter()

from pydantic import BaseModel, Field, ConfigDict
from typing import Literal


class InitialAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=64)
    index: int = Field(ge=0, le=9)
    option_id: Literal["A", "B", "C", "D", "unsure"]
    version: str = Field(min_length=1, max_length=128)


class InitialRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=64)


class InitialResume(InitialRun):
    version: str = Field(min_length=1, max_length=128)


@router.get("/initial-assessment")
async def initial_assessment(owner: StudentOwnerScope = Depends(require_student_owner)):
    service = tracking_state().initial_assessment
    return service.public(await service.read(owner.student_id))


@router.post("/initial-assessment/start")
async def start_initial_assessment(owner: StudentOwnerScope = Depends(require_student_owner)):
    state = tracking_state()
    async with state.turn_requests.owner(owner.student_id):
        return await state.initial_assessment.ensure(owner.student_id)


@router.post("/initial-assessment/answer")
async def answer_initial_assessment(body: InitialAnswer, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = tracking_state()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await state.initial_assessment.submit(owner.student_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.post("/initial-assessment/skip")
async def skip_initial_assessment(body: InitialRun, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = tracking_state()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await state.initial_assessment.skip(owner.student_id, body.run_id)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


@router.post("/initial-assessment/resume")
async def resume_initial_assessment(body: InitialResume, owner: StudentOwnerScope = Depends(require_student_owner)):
    state = tracking_state()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await state.initial_assessment.resume(owner.student_id, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc


def tracking_state():
    state = get_product_state()
    if state.student_state is None:
        raise HTTPException(409, "学习证据操作需要本地数据库。")
    return state


@router.get("/student-evidence")
async def evidence(skill_id: str | None = None, cycle_id: str | None = None,
                   cursor: int | None = Query(None, ge=1), owner: StudentOwnerScope = Depends(require_student_owner)):
    state = tracking_state()
    return await evidence_page(state, str(owner.student_id), skill_id=skill_id, cycle_id=cycle_id, before=cursor)


@router.post("/student-evidence/{event_id}/exclude")
async def exclude(event_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    state, sid = tracking_state(), str(owner.student_id)
    async with state.turn_requests.owner(sid):
        try:
            async with state.student_state.engine.begin() as conn:
                await state.student_state.invalidate(sid, event_id=f"exclude:{event_id}",
                    invalidates_event_id=event_id, conn=conn)
                await revoke_pending(conn, sid, excluded_event_id=event_id)
        except ValueError as exc:
            raise HTTPException(404, "未找到可排除的作答记录。") from exc
    return {"ok": True, "message": "已排除该判定；曾经作答的事实保留，同题再答不会变成首次作答。"}


@router.post("/privacy/recompute-profile")
async def recompute(owner: StudentOwnerScope = Depends(require_student_owner)):
    state = tracking_state()
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await state.student_state.recompute(str(owner.student_id))
        except (ValueError, ArithmeticError) as exc:
            raise HTTPException(409, "画像重算未完成，请稍后重试。原始记录已保留。") from exc
