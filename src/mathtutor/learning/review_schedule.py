"""Durable review milestones anchored to the first independently correct practice."""
from copy import deepcopy
from datetime import datetime, timedelta


VERSION = "anchored_days_1_3_7"
DAYS = (1, 3, 7)


def schedule_next(payload, now):
    day = DAYS[payload["review_round"]]
    anchor = datetime.fromisoformat(payload["anchor_at"])
    # When a learner returns late, adjacent reviews still need separate retrieval occasions.
    due = max(anchor + timedelta(days=day), now + timedelta(days=1))
    payload.update(phase="waiting", current_probe=None, due_at=due.isoformat())


def checkpoint(payload):
    return payload["checkpoints"].setdefault(str(DAYS[payload["review_round"]]), {})


def upgrade(payload):
    """Read v1 rows using their real attempts. Preserve agreed due times and historical credits."""
    if "schedule_version" in payload:
        return payload
    updated = deepcopy(payload)
    updated.update(schedule_version=VERSION, anchor_at=None, checkpoints={})
    completed = 0
    for event in updated["attempts"]:
        if not event.get("independent") or event.get("correctness") != "correct":
            continue
        phase, observed = event["phase"], event["occurred_at"]
        if phase == "practice" and updated["anchor_at"] is None:
            updated["anchor_at"] = observed
        if phase not in {"review", "transfer"} or completed >= 2:
            continue
        record = updated["checkpoints"].setdefault(str(DAYS[completed]), {"from_legacy": True})
        if phase == "review":
            record.update(reviewed_at=observed, review_probe_id=event["probe_id"])
        else:
            record.update(completed_at=observed, transfer_probe_id=event["probe_id"])
            completed += 1
    if ((updated["phase"] in {"waiting", "review", "transfer", "complete"} and not updated["anchor_at"])
            or completed != updated["review_round"]):
        updated["schedule_version"] = "historical"
        return updated
    if updated["phase"] == "complete" and completed == 2:
        last = updated["checkpoints"][str(DAYS[completed - 1])]["completed_at"]
        schedule_next(updated, datetime.fromisoformat(last))
    elif updated["phase"] == "waiting" and updated.get("due_at") and updated.get("anchor_at"):
        target = datetime.fromisoformat(updated["anchor_at"]) + timedelta(days=DAYS[completed])
        updated["due_at"] = max(target, datetime.fromisoformat(updated["due_at"])).isoformat()
    return updated


def public_schedule(payload):
    if payload.get("schedule_version") != VERSION:
        return None
    anchor = datetime.fromisoformat(payload["anchor_at"]) if payload.get("anchor_at") else None
    return {
        "anchor_at": payload.get("anchor_at"),
        "checkpoints": [{
            "day": day,
            "target_at": (anchor + timedelta(days=day)).isoformat() if anchor else None,
            **payload["checkpoints"].get(str(day), {}),
        } for day in DAYS],
    }
