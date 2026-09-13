"""Owner-scoped learning evidence reads, exclusions and explicit replay."""
from fastapi import APIRouter, Depends, HTTPException, Query
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.security.scopes import StudentOwnerScope
from mathtutor.application.learning_profile import evidence_page, revoke_pending

router = APIRouter()


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
