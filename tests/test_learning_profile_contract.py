"""Chronological labels, exclusion tombstones and deletion/replay races."""
import asyncio
import pytest
from sqlalchemy import select
from mathtutor.learning.knowledge_tracing.events import valid_events, baseline_prediction
from mathtutor.learning.knowledge_tracing.dataset import split_events
from mathtutor.learning.knowledge_tracing.__main__ import synthetic_events
from mathtutor.learning.knowledge_tracing.service import StudentStateService
from mathtutor.learning.knowledge_tracing.schema import learning_predictions, student_state_snapshots
from mathtutor.application.learning_profile import profile_projection
from mathtutor.application.data_lifecycle import DataLifecycleService
from mathtutor.repositories.uow import MathTutorUow
from mathtutor.repositories.turn_repository import TurnRequestRepository
from test_knowledge_tracking_v2 import service, attempt, context


@pytest.mark.parametrize("first,help_before,help_after,expected", [
    ("correct", False, False, 1), ("incorrect", False, True, 0),
    ("correct", True, False, None), ("unknown", False, False, None),
])
async def test_chronological_first_target(service, first, help_before, help_after, expected):
    await service.prepare_prediction("alice", prediction_id="presentation:cycle", **context())
    if help_before:
        await service.record_help("alice", event_id="help-before", **context())
    await attempt(service, "first", correctness=first)
    if help_after:
        await service.record_help("alice", event_id="help-after", **context())
    await attempt(service, "second", correctness="correct")
    history = await service.events("alice")
    targets = [e for e in valid_events(history) if e.independent_target]
    assert [int(e.correctness == "correct") for e in targets] == ([] if expected is None else [expected])
    forecast = await service.prepare_prediction("alice", prediction_id="presentation:cycle", **context())
    assert forecast["prediction_label"] == expected
    assert forecast["history_cutoff_seq"] == 0
    assert forecast["baseline_probability"] == .5


async def test_excluded_attempt_still_occupies_first_position_after_restart(service):
    first = await attempt(service, "first", correctness="incorrect")
    await service.invalidate("alice", event_id="exclude:first", invalidates_event_id=first.event_id)
    second = await attempt(service, "second")
    assert not second.independent_target
    restarted = StudentStateService(service.engine)
    await restarted.recompute("alice")
    assert not any(e.independent_target for e in valid_events(await restarted.events("alice")))
    async with service.engine.connect() as conn:
        predictions = (await conn.execute(select(learning_predictions.c.payload))).scalars().all()
    assert next(p for p in predictions if p["prediction_id"] == "prediction:second")["prediction_label"] is None
    assert next(p for p in predictions if p["prediction_id"] == "prediction:first")["label_excluded"] is True
    with pytest.raises(ValueError):
        await restarted.invalidate("bob", event_id="bad", invalidates_event_id=first.event_id)
    await restarted.record_help("alice", event_id="help", **context())
    with pytest.raises(ValueError):
        await restarted.invalidate("alice", event_id="bad-help", invalidates_event_id="help")


async def test_delete_rejects_captured_replay_and_removes_attempt_occupancy(service):
    from mathtutor.infrastructure.schema import metadata
    async with service.engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    await attempt(service, "before")
    old = await service.prepare_replay("alice")
    await DataLifecycleService(uow=MathTutorUow(service.engine)).delete_educational_history("alice")
    assert await service.commit_replay(old) is False
    async with service.engine.connect() as conn:
        assert (await conn.execute(select(student_state_snapshots))).first() is None
    assert await service.events("alice") == []
    assert (await attempt(service, "new-after-delete")).independent_target
    assert not await service.commit_replay(old)  # same sequence number, different deletion generation
    assert (await service.recompute("alice"))["learning_generation"] == 1


async def test_replay_also_rejects_new_events_and_model_change(service):
    old = await service.prepare_replay("alice")
    await attempt(service)
    assert not await service.commit_replay(old)
    current = await service.prepare_replay("alice")
    assert not await service.commit_replay({**current, "model_version": "different"})
    assert await service.commit_replay(current)


async def test_owner_coordination_serializes_different_conversations():
    journal = TurnRequestRepository()
    ready, release, deleted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def turn():
        async with journal.conversation("alice", "tab-1"):
            ready.set()
            await release.wait()
    async def deletion():
        await ready.wait()
        async with journal.owner("alice"):
            deleted.set()
    running, deleting = asyncio.create_task(turn()), asyncio.create_task(deletion())
    await ready.wait()
    await asyncio.sleep(0)
    assert not deleted.is_set()
    async with journal.owner("bob"):
        pass  # another owner's work is independent
    release.set()
    await asyncio.gather(running, deleting)
    assert deleted.is_set()


def test_student_cold_start_allows_shared_course_items_without_duplicate_attempts():
    events = synthetic_events(students=12, events_per_student=12)
    events = [e.model_copy(update={"problem_revision": f"shared-{e.event_seq}", "leakage_group_id": f"shared-{e.event_seq}"}) for e in events]
    splits = split_events(events + events, mode="student")
    assert sum(len(splits[k]) for k in ("train", "validation", "test")) == len(events)
    assert splits["audit"]["purged_cross_split_item_events"] == 0
    assert splits["audit"]["shared_course_items_before_filter"] == 12
    owners = [{e.student_id for e in splits[k]} for k in ("train", "validation", "test")]
    assert not owners[0] & owners[1] and not owners[0] & owners[2]
    strict = split_events(events, mode="student_item")
    items = [{e.problem_revision for e in strict[k]} for k in ("train", "validation", "test")]
    assert not items[0] & items[1] and not items[1] & items[2] and not items[0] & items[2]


def test_a_probability_and_profile_empty_state_remain_separate():
    assert baseline_prediction([], ["divide_nonzero"]) == .5
    event = synthetic_events(students=1, events_per_student=1)[0].model_copy(update={"skill_ids": ("divide_nonzero",), "correctness": "correct"})
    assert baseline_prediction([event], ["divide_nonzero"]) == pytest.approx(2/3)
    assert baseline_prediction([event], ["divide_nonzero", "linear_isolation"]) == pytest.approx((2/3+.5)/2)
    profile = profile_projection([], has_conversations=True)
    assert profile["has_conversations"] and not profile["has_independent_evidence"]
    assert all(s["mastery"] is None for s in profile["skills"])
