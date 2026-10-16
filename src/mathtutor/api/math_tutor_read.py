"""MathTutor owner-scoped read endpoints (design doc §13.1).

Every endpoint resolves the StudentOwnerScope from the authenticated
principal and only ever returns that owner's data. Cross-owner access
returns 404 (existence is never leaked). Phase 1 keeps the same contract
with PostgreSQL composite-FK owner constraints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from mathtutor.api.conversation_guard import require_active
from mathtutor.application.conversation_trash import purge_conversation
from mathtutor.application.verification_notice import verification_notice_fields
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter()


class ConversationCreate(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=128)


def _session_summary(client_session_id: str, session) -> dict:
    # Student-channel commands ONLY — internal outcomes (e.g.
    # solution_shown_permitted) never reach the UI contract.
    from mathtutor.application.controller import student_allowed_inputs

    return {
        "client_session_id": client_session_id,
        "cycle_id": str(session.cycle.cycle_id),
        "state": session.state.value,
        "state_version": session.version,
        "allowed_next_inputs": student_allowed_inputs(session.state),
    }


@router.get("/sessions")
async def list_sessions(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[dict]:
    state = get_product_state()
    live = {
        client_session_id: _session_summary(client_session_id, session)
        for client_session_id, session in await state.store.iter_for_student(owner.student_id)
    }
    result = []
    for conversation in await state.conversations.list(owner.student_id):
        result.append({**live.get(conversation["conversation_id"], {"client_session_id": conversation["conversation_id"], "state": "", "state_version": 0, "allowed_next_inputs": []}), **conversation})
    return result


@router.post("/sessions", status_code=201)
async def create_session(
    payload: ConversationCreate,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    async with state.turn_requests.conversation(owner.student_id, payload.conversation_id.strip()):
        await require_active(state, owner.student_id, payload.conversation_id.strip())
        return await state.conversations.ensure(owner.student_id, payload.conversation_id.strip())


@router.get("/trash")
async def list_trash(owner: StudentOwnerScope = Depends(require_student_owner)):
    return await get_product_state().conversations.list(owner.student_id, trashed=True)


async def _trash_action(owner, session_id, action):
    state = get_product_state()
    if state.turn_requests.is_processing(owner.student_id, session_id):
        raise HTTPException(409, "此对话正在处理消息或资料，请稍后或先停止生成再操作。")
    async with state.turn_requests.conversation(owner.student_id, session_id):
        row = await state.conversations.get(owner.student_id, session_id)
        if not row or row.get("purged_at"):
            raise HTTPException(404, "对话不存在")
        if action == "purge":
            if not row.get("trashed_at"):
                raise HTTPException(409, "请先将对话移入垃圾桶")
            await purge_conversation(state, owner.student_id, session_id)
        else:
            await state.conversations.set_trash(owner.student_id, session_id, action == "trash")
    return {"ok": True}


@router.delete("/sessions/{session_id}")
async def trash_session(session_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await _trash_action(owner, session_id, "trash")


@router.post("/trash/{session_id}/restore")
async def restore_session(session_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await _trash_action(owner, session_id, "restore")


@router.delete("/trash/{session_id}")
async def purge_session(session_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    return await _trash_action(owner, session_id, "purge")


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    conversation = await require_active(state, owner.student_id, session_id)
    session = await state.store.load(owner.student_id, session_id)
    if session is None and conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")
    summary = _session_summary(session_id, session) if session is not None else {
        "client_session_id": session_id,
        "state": "",
        "state_version": 0,
        "allowed_next_inputs": [],
    }
    from mathtutor.application.student_contract import session_contract
    summary.update(await session_contract(state.store, owner.student_id, session,
        processing=state.turn_requests.is_processing(owner.student_id, session_id)))
    return {
        **summary,
        **(conversation or {}),
        "messages": [{**{key: value for key, value in message.items() if key != "continuation_context"},
                      **verification_notice_fields(message.get("continuation_context"))}
                     for message in await state.conversations.messages(owner.student_id, session_id)],
        "document_ids": [str(value) for value in await state.conversations.document_ids(owner.student_id, session_id)],
    }


@router.get("/cycles/{cycle_id}")
async def get_cycle(
    cycle_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    store = get_product_state().store
    sessions = await store.iter_for_student(owner.student_id)
    for _client_id, session in sessions:
        conversation = await get_product_state().conversations.get(owner.student_id, _client_id)
        if conversation and (conversation.get("trashed_at") or conversation.get("purged_at")):
            continue
        if str(session.cycle.cycle_id) == cycle_id:
            return {
                "cycle_id": cycle_id,
                "session_id": _client_id,
                "state": session.state.value,
                "state_version": session.version,
                "transitions": [
                    {
                        "from_state": t.from_state,
                        "to_state": t.to_state,
                        "trigger_command": t.trigger_command,
                        "prior_version": t.prior_version,
                        "new_version": t.new_version,
                    }
                    for t in session.transitions
                ],
            }
    raise HTTPException(status_code=404, detail="Cycle not found")


@router.get("/offers")
async def list_offers(
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> list[dict]:
    """Phase 5 contract: this student's practice offers — NO solution data.

    The projection is strictly public: offer id/status, curriculum labels,
    difficulty, timestamps and the parent cycle. Never a solution, answer
    key, verification log, attestation or mastery value. ``EXPIRED`` is
    projected lazily (the stored status stays ACTIVE until consumed).
    """
    from datetime import datetime, timezone

    from mathtutor.application.practice_release import (
        labels_for_mapping_ids,
    )

    state = get_product_state()
    practice = getattr(state, "practice_repository", None) or getattr(
        getattr(state, "capability", None), "practice_repository", None
    )
    if practice is None:
        raise HTTPException(status_code=500, detail="practice repository 未配置")
    offers = await practice.offers_for_student_with_detail(owner.student_id)
    from mathtutor.application.practice_offer_view import enrich_offer, feedback_for
    history = await state.student_state.events(str(owner.student_id)) if state.student_state else []
    feedback = await feedback_for(state, owner.student_id)
    now = datetime.now(timezone.utc)
    result: list[dict] = []
    for offer, exercise in offers:
        status = (
            "EXPIRED"
            if offer.status == "ACTIVE" and offer.expires_at <= now
            else offer.status
        )
        labels = labels_for_mapping_ids(offer.target_mapping_ids)
        result.append(await enrich_offer(state, practice, owner.student_id, offer,
            {
                "offer_id": str(offer.offer_id),
                "status": status,
                "skill_labels": labels["skill_labels"],
                "concept_labels": labels["concept_labels"],
                "difficulty": exercise.difficulty if exercise is not None else None,
                "offered_at": offer.offered_at.isoformat(),
                "expires_at": offer.expires_at.isoformat(),
                "parent_cycle_id": str(offer.parent_cycle_id),
            }, history=history, feedback=feedback)
        )
    return result


class OfferFeedbackInput(BaseModel):
    kind: str = Field(pattern="^(later|not_relevant)$")


@router.post("/offers/{offer_id}/resume")
async def resume_offer(offer_id: str, owner: StudentOwnerScope = Depends(require_student_owner)):
    from uuid import UUID
    state = get_product_state()
    try:
        identifier = UUID(offer_id)
    except ValueError as exc:
        raise HTTPException(404, "未找到进行中的练习。") from exc
    async with state.turn_requests.owner(owner.student_id):
        child = await state.store.load_child_cycle_for_offer(owner.student_id, identifier)
        if child is None or child.state.value.upper() in {"SOLVED", "CLOSED"}:
            raise HTTPException(409, "这道练习已结束或无法继续，请刷新列表。")
        client_id = next((cid for cid, session in await state.store.iter_for_student(owner.student_id)
            if session.cycle.cycle_id == child.cycle.cycle_id), None)
        if client_id is None:
            raise HTTPException(404, "原练习会话不可用。")
        if not await require_active(state, owner.student_id, client_id):
            raise HTTPException(404, "原练习会话不可用。")
        await state.store.focus_cycle(owner.student_id, client_id, str(child.cycle.cycle_id))
    return {"session_id": client_id}


@router.post("/offers/{offer_id}/feedback")
async def offer_feedback(offer_id: str, body: OfferFeedbackInput, owner: StudentOwnerScope = Depends(require_student_owner)):
    from uuid import UUID
    from mathtutor.security.scopes import student_uuid
    from mathtutor.application.practice_offer_view import save_feedback
    state = get_product_state()
    try:
        identifier = UUID(offer_id)
    except ValueError as exc:
        raise HTTPException(404, "未找到推荐练习。") from exc
    async with state.turn_requests.owner(owner.student_id):
        offer = await state.practice_repository.load_offer(identifier)
        if offer is None or offer.student_id != student_uuid(owner.student_id):
            raise HTTPException(404, "未找到推荐练习。")
        from datetime import datetime, timezone
        if offer.status != "ACTIVE" or offer.expires_at <= datetime.now(timezone.utc):
            raise HTTPException(409, "这条推荐已更新，请刷新后重试。")
        await save_feedback(state, owner.student_id, identifier, body.kind)
    return {"ok": True}


__all__ = ["router"]
