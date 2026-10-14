"""Evidence-first public projections. Model probabilities stay internal."""
from urllib.parse import urlencode

from mathtutor.learning.diagnosis import RULES
from mathtutor.learning.knowledge_tracing.events import evidence_summary, valid_events
from mathtutor.learning.skill_graph import SKILLS

_RULE_BY_SIGNAL = {signal: rule for rule in RULES for signal in rule.signals}


def active_misconceptions(accepted):
    """Diagnosis rules seen in a wrong or partial attempt on a skill and not
    yet followed by an independent correct attempt on that skill."""
    active = {}
    attempts = [e for e in accepted if e.event_type == "attempt_assessed" and not e.duplicate_response]
    for event in sorted(attempts, key=lambda e: (e.event_seq, e.occurred_at, e.event_id)):
        if event.independent_target and event.correctness == "correct":
            for key in [k for k in active if k[1] in event.skill_ids]:
                del active[key]
        elif event.correctness in ("incorrect", "partial"):
            for signal in event.misconception_codes:
                rule = _RULE_BY_SIGNAL.get(signal)
                for skill in event.skill_ids if rule else ():
                    active[(rule.rule_id, skill)] = (rule, event.occurred_at)
    by_rule = {}
    for (rule_id, skill), (rule, seen) in active.items():
        row = by_rule.setdefault(rule_id, {"rule_id": rule_id, "label": rule.title, "skill_ids": [], "last_seen_at": seen})
        row["skill_ids"].append(skill)
        row["last_seen_at"] = max(row["last_seen_at"] or "", seen or "") or None
    return sorted(by_rule.values(), key=lambda row: row["rule_id"])


def profile_projection(history, *, has_conversations=False, model_status="not_trained"):
    summary = evidence_summary(history)
    indexed = {row["skill_id"]: row for row in summary["skills"]}
    accepted = valid_events(history)
    rows = []
    for code, skill in SKILLS.items():
        counts = indexed.get(code, {})
        events = [e for e in accepted if e.event_type == "attempt_assessed" and code in e.skill_ids and not e.duplicate_response]
        independent = counts.get("independent", {"correct": 0, "incorrect": 0})
        successes = {e.problem_revision for e in events if e.independent_target and e.correctness == "correct" and len(e.skill_ids) == 1}
        if successes:
            observation = f"有 {len(successes)} 道新题首次独立完成，仍可换题检查。"
        elif independent["incorrect"]:
            observation = "独立作答中遇到了困难，可以换一道题再检查。"
        elif counts.get("assisted", {}).get("correct", 0):
            observation = "已有提示后完成的记录，下一步检查独立作答。"
        elif counts.get("post_solution", {}).get("correct", 0):
            observation = "已有看过解答后的作答，下一步用新题检查。"
        elif events:
            observation = "已有相关记录，独立整题表现仍需确认。"
        else:
            observation = "尚未检查"
        flat = {k: sum(counts.get(k, {}).values()) for k in ("independent", "assisted", "post_solution", "diagnostic")}
        flat["ungradable"] = counts.get("unknown", 0)
        rows.append({"code": code, "label": skill.label, "mastery": None, "grade_band": None,
            "observation": observation, "evidence_status": observation,
            "evidence_summary": flat, "counts": {k: counts.get(k, {"correct": 0, "incorrect": 0})
                for k in ("independent", "assisted", "post_solution", "diagnostic")},
            "joint_task_evidence": counts.get("joint_task_evidence", 0),
            "last_checked_at": max((e.occurred_at for e in events), default=None),
            "evidence_count": len(events), "next_action": "查看推荐练习",
            "next_href": "/math-tutor/offers?" + urlencode({"skill": code})})
    misconceptions = active_misconceptions(accepted)
    return {"schema_version": "learning_profile_v1", "skills": rows,
        "last_event_seq": summary["last_event_seq"], "model_status": model_status,
        "coverage": {"supported_skills": len(SKILLS), "observed_skills": sum(r["evidence_count"] > 0 for r in rows)},
        "total_attempts": sum(e.event_type == "attempt_assessed" and not e.duplicate_response for e in accepted),
        "active_misconceptions": len(misconceptions), "misconceptions": misconceptions,
        "has_conversations": has_conversations,
        "has_independent_evidence": any(e.independent_target for e in accepted)}


async def evidence_page(state, sid, *, skill_id=None, cycle_id=None, before=None, limit=30):
    history = await state.student_state.events(sid)
    session_ids = {str(session.cycle.cycle_id): client_id for client_id, session in await state.store.iter_for_student(sid)}
    live = {e.event_id for e in valid_events(history)}
    attempts = [e for e in reversed(history) if e.event_type == "attempt_assessed"
        and (not skill_id or skill_id in e.skill_ids) and (not cycle_id or e.cycle_id == cycle_id)
        and (before is None or e.event_seq < before)]
    rows = []
    for event in attempts[:limit]:
        context = await state.store.teaching.load(sid, event.cycle_id) or {}
        client_id = session_ids.get(event.cycle_id) or context.get("client_session_id")
        conversation = await state.conversations.get(sid, client_id) if client_id else None
        available = bool(conversation and not conversation.get("trashed_at") and not conversation.get("purged_at"))
        record = next((r for r in context.get("assessments", [])
            if r.get("assessment_id") in {event.assessment_id, event.attempt_id}), {})
        rows.append({"event_id": event.event_id, "event_seq": event.event_seq, "cycle_id": event.cycle_id,
            "occurred_at": event.occurred_at, "skill_ids": list(event.skill_ids),
            "problem_text": str(context.get("display_text") or "原题详情暂不可用")[:1200],
            "student_response": str(record.get("raw_text") or record.get("student_text") or "")[:2000],
            "correctness": event.correctness, "evidence_kind": event.evidence_kind,
            "completion_scope": event.completion_scope, "first_target": event.independent_target and event.event_id in live,
            "excluded": event.event_id not in live, "session_id": client_id if available else None})
    return {"items": rows, "next_cursor": rows[-1]["event_seq"] if len(attempts) > limit else None}


async def revoke_pending(conn, sid, *, excluded_event_id=None):
    from sqlalchemy import select
    from mathtutor.infrastructure.schema import practice_offers, practice_recommendations
    from mathtutor.security.scopes import student_uuid
    sid = str(student_uuid(sid))
    await conn.execute(practice_offers.update().where(practice_offers.c.student_id == sid,
        practice_offers.c.status == "ACTIVE").values(status="REVOKED"))
    await conn.execute(practice_recommendations.update().where(practice_recommendations.c.student_id == sid,
        practice_recommendations.c.status.in_(("ACTIVE", "PREPARING"))).values(status="REVOKED"))
    # Accepted exercise snapshots survive, but deleted evidence must not survive
    # as an embedded recommendation reason. Keep this in the deletion transaction.
    rows = (await conn.execute(select(practice_recommendations).where(
        practice_recommendations.c.student_id == sid))).mappings().all()
    for row in rows:
        payload = dict(row["payload"])
        basis = payload.get("basis")
        if excluded_event_id is not None and (not basis or excluded_event_id not in basis.get("evidence_ids", [])):
            continue
        payload.update(basis=None, decision_reason="", status=row["status"])
        await conn.execute(practice_recommendations.update().where(
            practice_recommendations.c.recommendation_id == row["recommendation_id"]
        ).values(payload=payload))
