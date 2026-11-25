"""An ordinary, first independent linear-equation solution starts a delayed review."""
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from mathtutor.learning import diagnostic_probes, review_schedule
from mathtutor.learning.knowledge_tracing.schema import learning_loop_episodes as episodes


DOMAIN = "linear_equation"


def eligible(event):
    return event.item_family_id == "linear" and event.correctness == "correct" and event.independent_target


def seeded(event):
    payload = {
        "domain": DOMAIN, "policy": "learning_loop_v1", "probe_policy": diagnostic_probes.POLICY_VERSION,
        "episode_id": str(uuid5(NAMESPACE_URL, f"mathtutor/linear-review/{event.student_id}/{event.event_id}")),
        "schedule_version": review_schedule.VERSION, "anchor_at": event.occurred_at,
        "source_event_id": event.event_id, "source_cycle_id": event.cycle_id, "updated_at": event.occurred_at,
        "diagnosis": [], "served_ids": [], "exposed_ids": [], "attempts": [], "receipts": [], "feedback": None,
        "current_helped": False, "review_round": 0, "checkpoints": {},
        "evidence": {"independent_practice": 1, "delayed_review": 0, "structural_transfer": 0},
    }
    review_schedule.schedule_next(payload, datetime.fromisoformat(event.occurred_at))
    return payload


async def register(conn, event):
    if not eligible(event):
        return
    fresh = seeded(event)
    inserted = await conn.execute(insert(episodes).values(student_id=event.student_id, domain=DOMAIN, payload=fresh)
                                  .on_conflict_do_nothing())
    if inserted.rowcount:
        return
    key = (episodes.c.student_id == event.student_id, episodes.c.domain == DOMAIN)
    saved = (await conn.execute(select(episodes.c.payload).where(*key))).scalar_one()
    if saved.get("schedule_version") == "source_excluded":
        for field in ("attempts", "served_ids", "exposed_ids"):
            fresh[field] = saved[field]
        fresh["evidence"] = {**saved["evidence"], "independent_practice": saved["evidence"]["independent_practice"] + 1}
        await conn.execute(episodes.update().where(*key, episodes.c.payload == saved).values(payload=fresh))


async def exclude_anchor(conn, student_id, event_id):
    key = (episodes.c.student_id == str(student_id), episodes.c.domain == DOMAIN)
    saved = (await conn.execute(select(episodes.c.payload).where(*key))).scalar_one_or_none()
    if saved and saved.get("source_event_id") == event_id:
        # Keep attempts and item exposure. The next independent equation can supply a new anchor.
        updated = dict(saved, schedule_version="source_excluded", due_at=None, current_probe=None,
                       source_event_id=None, source_cycle_id=None, anchor_at=None)
        updated["evidence"] = {**saved["evidence"], "independent_practice": max(0, saved["evidence"]["independent_practice"] - 1)}
        await conn.execute(episodes.update().where(*key).values(payload=updated))
