"""Public next-action projection, separate from offer acceptance state."""
from datetime import datetime, timezone
from urllib.parse import urlencode
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from mathtutor.learning.knowledge_tracing.schema import practice_feedback
from mathtutor.learning.knowledge_tracing.events import valid_events
from mathtutor.domain.practice_recommendation import PURPOSE_LABELS


async def feedback_for(state, sid):
    if state.student_state:
        async with state.student_state.engine.connect() as conn:
            rows = (await conn.execute(select(practice_feedback).where(practice_feedback.c.student_id == str(sid)))).mappings().all()
            return {row["offer_id"]: row["kind"] for row in rows}
    return getattr(state, "practice_feedback", {}).get(str(sid), {})


async def save_feedback(state, sid, offer_id, kind):
    if state.student_state:
        async with state.student_state.engine.begin() as conn:
            values = dict(student_id=str(sid), offer_id=str(offer_id), kind=kind, created_at=datetime.now(timezone.utc).isoformat())
            await conn.execute(insert(practice_feedback).values(**values).on_conflict_do_update(
                index_elements=["student_id", "offer_id"], set_=values))
    else:
        if not hasattr(state, "practice_feedback"):
            state.practice_feedback = {}
        state.practice_feedback.setdefault(str(sid), {})[str(offer_id)] = kind


async def enrich_offer(state, practice, sid, offer, public, *, history, feedback):
    recommendation = await practice.recommendation_for_offer(sid, offer.offer_id)
    purpose = recommendation.purpose if recommendation else None
    basis = recommendation.basis if recommendation else None
    reason = "生成时的学习依据已不可用。"
    if basis:
        reason = ("根据已经核验的错误记录，先练习仍不稳定的步骤。" if basis.reason_code == "verified_error_history"
                  else "根据这道题的作答记录，换题检查独立完成情况。" if basis.reason_code == "parent_attempt"
                  else "围绕当前题目安排一次相关练习。")
        if basis.initial_assessment_run_id:
            reason += "难度参考初评练习起点，并结合后续首次独立作答调整。"
    public.update({"purpose": purpose, "title": PURPOSE_LABELS.get(purpose, "相关练习"),
        "reason": reason,
        "observation_goal": "观察新题是否能独立完成，以及哪些步骤仍需帮助。",
        "evidence_ids": list(basis.evidence_ids) if basis else [], "question_count": 1,
        "history_cutoff_seq": basis.history_cutoff_seq if basis else None,
        "basis": basis.model_dump(mode="json") if basis else None,
        "feedback": feedback.get(str(offer.offer_id)), "display_status": "pending" if public["status"] == "ACTIVE" else "history",
        "resume_session_id": None, "child_cycle_id": None, "result_summary": None,
        "update_reason": "这条建议需要重新评估。" if public["status"] in {"EXPIRED", "REVOKED"} else None})
    if public["feedback"] and public["status"] == "ACTIVE":
        public["display_status"] = "later" if public["feedback"] == "later" else "history"
    if public["status"] == "ACCEPTED":
        child = await state.store.load_child_cycle_for_offer(sid, offer.offer_id)
        if child:
            cycle_id = str(child.cycle.cycle_id)
            child_context = await state.store.teaching.load(sid, cycle_id) or {}
            rows = [e for e in valid_events(history) if e.cycle_id == cycle_id and e.event_type == "attempt_assessed" and not e.duplicate_response]
            completed = child.state.value.upper() == "SOLVED" or any(t.to_state.upper() == "SOLVED" for t in child.transitions)
            completed = completed or any(e.cycle_id == cycle_id and e.event_type == "problem_ended" and e.lifecycle_status == "completed" for e in history)
            client_id = next((client_id for client_id, session in await state.store.iter_for_student(sid)
                if str(session.cycle.cycle_id) == cycle_id), child_context.get("client_session_id"))
            conversation = await state.conversations.get(sid, client_id)
            available = bool(conversation and not conversation.get("trashed_at") and not conversation.get("purged_at"))
            active = child.state.value.upper() != "CLOSED" and child_context.get("lifecycle") not in {"ended", "skipped"}
            public.update(child_cycle_id=cycle_id, resume_session_id=client_id if available and active and not completed else None,
                display_status="completed" if completed else "in_progress" if available and active else "history")
            public["evidence_href"] = "/math-tutor/profile?" + urlencode({"cycle": cycle_id})
            public["result_summary"] = {"independent_correct": sum(e.independent_target and e.correctness == "correct" for e in rows),
                "helped": sum(e.evidence_kind in {"assisted", "post_solution"} for e in rows), "observations": len(rows)}
    return public
