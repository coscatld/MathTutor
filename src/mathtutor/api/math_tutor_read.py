"""MathTutor owner-scoped read endpoints (design doc §13.1).

Every endpoint resolves the StudentOwnerScope from the authenticated
principal and only ever returns that owner's data. Cross-owner access
returns 404 (existence is never leaked). Phase 1 keeps the same contract
with PostgreSQL composite-FK owner constraints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
    return await get_product_state().conversations.ensure(
        owner.student_id, payload.conversation_id.strip()
    )


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    owner: StudentOwnerScope = Depends(require_student_owner),
) -> dict:
    state = get_product_state()
    conversation = await state.conversations.get(owner.student_id, session_id)
    session = await state.store.load(owner.student_id, session_id)
    if session is None and conversation is None:
        raise HTTPException(status_code=404, detail="Session not found")
    summary = _session_summary(session_id, session) if session is not None else {
        "client_session_id": session_id,
        "state": "",
        "state_version": 0,
        "allowed_next_inputs": [],
    }
    return {
        **summary,
        **(conversation or {}),
        "messages": [{key: value for key, value in message.items() if key != "continuation_context"}
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
        if str(session.cycle.cycle_id) == cycle_id:
            return {
                "cycle_id": cycle_id,
                "session_id": session.session_id,
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
    now = datetime.now(timezone.utc)
    result: list[dict] = []
    for offer, exercise in offers:
        status = (
            "EXPIRED"
            if offer.status == "ACTIVE" and offer.expires_at <= now
            else offer.status
        )
        labels = labels_for_mapping_ids(offer.target_mapping_ids)
        result.append(
            {
                "offer_id": str(offer.offer_id),
                "status": status,
                "skill_labels": labels["skill_labels"],
                "concept_labels": labels["concept_labels"],
                "difficulty": exercise.difficulty if exercise is not None else None,
                "offered_at": offer.offered_at.isoformat(),
                "expires_at": offer.expires_at.isoformat(),
                "parent_cycle_id": str(offer.parent_cycle_id),
            }
        )
    return result


__all__ = ["router"]
