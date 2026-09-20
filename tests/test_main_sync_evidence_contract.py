"""Mac M1 plus Week02: physical submission, derived labels and replay agree."""
import pytest

from mathtutor.learning.knowledge_tracing.events import LearningEvent, ordered_attempts, valid_events
from mathtutor.learning.knowledge_tracing.service import StudentStateService


def context():
    return dict(session_id="session", cycle_id="cycle", problem_id="problem",
                problem_revision="canonical", item_family_id="linear", skill_ids=["divide_nonzero"])


def fact(identity, seq, kind="attempt_assessed", **changes):
    data = dict(context(), student_id="alice", event_id=identity, event_seq=seq, event_type=kind)
    if kind == "attempt_assessed":
        data.update(attempt_id=identity, assessment_id=identity, correctness="correct", evidence_kind="independent")
    data.update(changes)
    return LearningEvent(**data)


@pytest.mark.parametrize("first_kind", ["attempt_submitted", "attempt_assessed"])
def test_export_derivation_preserves_first_slot_even_without_stored_flag(first_kind):
    first = fact("first", 1, first_kind)
    second = fact("second", 2, "attempt_submitted")
    assessment = fact("judged", 3, submission_event_id="second")
    invalidation = fact("excluded", 4, "evidence_invalidated", invalidates_event_id="first")
    history = [first, second, assessment, invalidation]
    judged = next(e for e in valid_events(history) if e.event_id == "judged")
    assert judged.prior_task_attempt and not judged.independent_target


def test_own_raw_submission_is_not_a_repeat_and_derivation_is_idempotent():
    raw = fact("raw", 1, "attempt_submitted")
    judged = fact("judged", 2, submission_event_id="raw")
    duplicate_binding = fact("different-assessment", 3, submission_event_id="raw")
    derived = ordered_attempts([judged, raw, duplicate_binding, raw])
    assert len(derived) == 3
    assert derived[1].independent_target
    assert derived[2].prior_task_attempt and not derived[2].independent_target
    assert ordered_attempts(derived) == derived


def test_export_first_slot_and_invalidation_are_owner_scoped():
    history = [fact("raw", 1, "attempt_submitted"), fact("same", 2, submission_event_id="raw"),
               fact("same", 1, student_id="bob"),
               fact("exclude", 3, "evidence_invalidated", invalidates_event_id="same")]
    surviving = [e for e in valid_events(history) if e.event_type == "attempt_assessed"]
    assert len(surviving) == 1 and surviving[0].student_id == "bob"
    assert surviving[0].independent_target


@pytest.fixture
async def service():
    result = await StudentStateService.create_memory()
    yield result
    await result.engine.dispose()


async def test_stored_first_submission_and_read_time_profile_agree(service):
    await service.record_submission("alice", event_id="raw", response_fingerprint="digest", **context())
    event = await service.record_attempt("alice", assessment_id="first", attempt_id="first",
        correctness="incorrect", submission_event_id="raw", **context())
    assert event.independent_target
    summary = await service.summary("alice")
    assert summary["skills"][0]["independent"] == {"correct": 0, "incorrect": 1}
    assert summary["totals"]["repeat_attempts"] == 0
    replay = await service.prepare_replay("alice")
    assert replay["evidence_summary"]["skills"] == summary["skills"]
    assert await service.commit_replay(replay)


async def test_partial_first_submission_cannot_turn_later_success_into_first_label(service):
    before = await service.prepare_prediction("alice", prediction_id="presentation:cycle", at_presentation=True, **context())
    await service.record_submission("alice", event_id="s1", response_fingerprint="step", **context())
    await service.record_attempt("alice", assessment_id="step", attempt_id="step", correctness="partial",
        completion_scope="subgoal", submission_event_id="s1", prediction_id="presentation:cycle", **context())
    partial = await service.presentation("alice", "cycle")
    assert "observed_event_seq" not in partial
    await service.record_submission("alice", event_id="s2", response_fingerprint="whole", **context())
    result = await service.record_attempt("alice", assessment_id="whole", attempt_id="whole", correctness="correct",
        submission_event_id="s2", prediction_id="presentation:cycle", **context())
    after = await service.presentation("alice", "cycle")
    assert result.prior_task_attempt and not result.independent_target
    assert after["prediction_label"] is None and after["assessment_id"] == "whole"
    assert after["frozen_forecast"] == before["frozen_forecast"]
    assert after["label_policy_version"] == "first_content_submission_v1"


async def test_legacy_attempt_prediction_still_labels_existing_presentation_once(service):
    before = await service.prepare_prediction("alice", prediction_id="presentation:cycle", at_presentation=True, **context())
    await service.record_attempt("alice", assessment_id="wrong", attempt_id="wrong", correctness="incorrect", **context())
    await service.record_attempt("alice", assessment_id="right", attempt_id="right", correctness="correct", **context())
    after = await service.presentation("alice", "cycle")
    assert after["prediction_label"] == 0 and after["assessment_id"] == "wrong"
    assert after["frozen_forecast"] == before["frozen_forecast"]


def test_legacy_partial_assessment_still_reserves_physical_first_position():
    history = [fact("step", 1, completion_scope="subgoal", correctness="partial"), fact("whole", 2)]
    derived = ordered_attempts(history)
    assert derived[1].prior_task_attempt and not derived[1].independent_target
