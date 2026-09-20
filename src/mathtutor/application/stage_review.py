"""Evidence-only stage reviews. Separate from DKT and assessment authority.

The first implementation deliberately uses auditable rules, not a profile LLM.
Outbox messages contain identities only; the consumer rechecks deletion generation.
"""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.infrastructure.knowledge_schema import reviews, preferences
from mathtutor.learning.knowledge_tracing.schema import learning_generations
from mathtutor.learning.knowledge_tracing.events import valid_events, utcnow
from mathtutor.repositories.uow import append_outbox_events

STYLES = {"default": "保持当前讲解方式", "stepwise": "分步讲解，每步检查理解", "concise": "先给简短提示，再按需展开"}


class StageReviewService:
    def __init__(self, engine, student_state):
        self.engine, self.student_state = engine, student_state

    async def read(self, owner):
        async with self.engine.begin() as db:
            row = (await db.execute(select(reviews.c.payload).where(reviews.c.student_id == str(owner)))).scalar_one_or_none()
            pref = (await db.execute(select(preferences.c.payload).where(preferences.c.student_id == str(owner)))).scalar_one_or_none()
        return {**(row or {"status": "no_evidence", "facts": [], "review": None}), "preferences": pref or {},
                "mechanism": "evidence_rules_v1", "model_calls": 0, "provider_quality": "NOT_RUN", "dkt_mastery": None}

    async def on_event(self, db, event):
        finished = (event.event_type == "attempt_assessed" and event.correctness == "correct"
                    and event.completion_scope == "full_problem" and not event.duplicate_response)
        await self.refresh(db, event.student_id, trigger="practice_completed" if finished else event.event_type)

    async def refresh(self, db, owner, *, trigger):
        owner = str(owner)
        await db.execute(insert(learning_generations).values(student_id=owner, generation=0).on_conflict_do_nothing())
        generation = (await db.execute(select(learning_generations.c.generation).where(learning_generations.c.student_id == owner))).scalar_one()
        history = await self.student_state.events(owner, conn=db)
        # Only assessed first whole-task independent evidence can count as success.
        facts = [{"event_id": e.event_id, "assessment_id": e.assessment_id, "cycle_id": e.cycle_id,
                  "correctness": e.correctness, "evidence_kind": e.evidence_kind,
                  "response_format": e.response_format, "independent": e.independent_target,
                  "skill_ids": list(e.skill_ids)}
                 for e in valid_events(history) if e.event_type == "attempt_assessed"]
        pref = (await db.execute(select(preferences.c.payload).where(preferences.c.student_id == owner))).scalar_one_or_none() or {}
        evidence_revision = max((e.event_seq for e in history if e.event_type in {"attempt_assessed", "evidence_invalidated"}), default=0)
        key = hashlib.sha256(json.dumps([facts, pref, evidence_revision], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        old = (await db.execute(select(reviews.c.payload).where(reviews.c.student_id == owner))).scalar_one_or_none() or {}
        previous = old.get("review")
        reviewed_ids = {x["event_id"] for x in (previous or {}).get("basis", [])}
        observations = len([x for x in facts if x["event_id"] not in reviewed_ids])
        pending = old.get("pending_key", "")
        should_review = bool(pending) or trigger in {"problem_ended", "practice_completed", "goal_changed", "manual", "evidence_invalidated"} or observations >= 3
        if should_review and key != (previous or {}).get("evidence_key") and key != pending:
            pending = key
            # Unique key includes generation and immutable evidence revision; repeated requests coalesce.
            await append_outbox_events(db, [{"aggregate_type": "stage_review", "aggregate_id": owner + ":" + key,
                "aggregate_version": generation, "event_sequence": 1, "event_type": "stage_review_requested",
                "payload": {"student_id": owner, "generation": generation, "evidence_key": key}}])
        payload = {"status": "pending" if pending == key else "ready" if (previous or {}).get("evidence_key") == key else "observing", "facts": facts,
                   "review": previous, "pending_key": pending, "preferences": pref}
        values = dict(student_id=owner, generation=generation, last_event_seq=max((e.event_seq for e in history), default=0),
                      evidence_key=key, payload=payload)
        await db.execute(insert(reviews).values(**values).on_conflict_do_update(index_elements=["student_id"], set_=values))
        return payload

    async def request(self, owner):
        async with self.engine.begin() as db:
            return await self.refresh(db, owner, trigger="manual")

    async def set_preferences(self, owner, *, goal, style):
        if style not in STYLES or len(goal) > 240:
            raise ValueError("invalid explicit preference")
        async with self.engine.begin() as db:
            prior = (await db.execute(select(preferences.c.payload).where(preferences.c.student_id == str(owner)))).scalar_one_or_none() or {}
            changed = prior.get("goal") != goal or prior.get("style") != style
            value = {"goal": goal, "style": style, "origin": "user_explicit", "revision": prior.get("revision", 0) + int(changed)}
            await db.execute(insert(preferences).values(student_id=str(owner), payload=value).on_conflict_do_update(
                index_elements=["student_id"], set_={"payload": value}))
            return await self.refresh(db, owner, trigger="goal_changed")

    async def dispatch(self, event):
        if event["event_type"] != "stage_review_requested":
            return
        task = event["payload"]
        owner = task["student_id"]
        async with self.engine.begin() as db:
            # Acquire the writer lock and check deletion generation before reading or committing.
            matched = await db.execute(learning_generations.update().where(
                learning_generations.c.student_id == owner, learning_generations.c.generation == task["generation"]
            ).values(generation=learning_generations.c.generation))
            if not matched.rowcount:
                return
            row = (await db.execute(select(reviews).where(reviews.c.student_id == owner))).mappings().first()
            if not row or row["evidence_key"] != task["evidence_key"] or row["generation"] != task["generation"]:
                return
            payload = dict(row["payload"])
            previous = payload.get("review") or {}
            if previous.get("evidence_key") == task["evidence_key"]:
                return
            facts = payload["facts"]
            independent = [f for f in facts if f["independent"]]
            old_ids = {f["event_id"] for f in previous.get("basis", [])}
            new_ids = {f["event_id"] for f in facts}
            style = payload.get("preferences", {}).get("style", "default")
            payload["review"] = {
                "evidence_key": task["evidence_key"], "created_at": utcnow(), "basis": facts,
                "changes": {"new_observations": len(new_ids - old_ids), "removed_observations": len(old_ids - new_ids)},
                "independent_correct": sum(f["correctness"] == "correct" for f in independent),
                "independent_incorrect": sum(f["correctness"] == "incorrect" for f in independent),
                "uncertain": ["这些是历史作答观察，不是掌握度。", "阅读、收藏和自述懂了不计独立成功。"],
                "hypotheses": [], "teaching_style": style, "recommendation": STYLES[style],
                "next_observation": "在未看答案、未受助的情况下完成一道新的可核验题目。",
            }
            payload.update(status="ready" if facts else "no_evidence", pending_key="")
            await db.execute(reviews.update().where(reviews.c.student_id == owner).values(payload=payload))


class ReviewDispatchSink:
    def __init__(self, reviews_service, fallback):
        self.reviews, self.fallback = reviews_service, fallback

    async def dispatch(self, event):
        if event["event_type"] == "stage_review_requested":
            await self.reviews.dispatch(event)
        else:
            await self.fallback.dispatch(event)
