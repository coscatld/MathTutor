"""Evidence projections agree on what first independent work can establish."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mathtutor.application.evidence_projection import public_evidence, teaching_evidence
from mathtutor.application.learning_profile import profile_projection
from mathtutor.application.practice_offer_view import enrich_offer
from mathtutor.learning.knowledge_tracing.events import LearningEvent, baseline_prediction, evidence_summary
from mathtutor.learning.knowledge_tracing.service import StudentStateService


def observation(identity="first", **changes):
    values = dict(event_id=identity, student_id="alice", session_id="session", cycle_id="cycle",
        event_seq=1, event_type="attempt_assessed", problem_id="problem", problem_revision="revision",
        item_family_id="linear", skill_ids=("linear_isolation",), assessment_id=identity, attempt_id=identity,
        correctness="correct", evidence_kind="independent")
    return LearningEvent(**(values | changes))


@pytest.mark.parametrize("changes, category", [
    ({}, "independent"),
    ({"response_format": "single_choice"}, "diagnostic"),
    ({"task_purpose": "diagnostic"}, "diagnostic"),
    ({"task_purpose": "error_analysis"}, "diagnostic"),
    ({"completion_scope": "subgoal"}, "diagnostic"),
    ({"correctness": "partial"}, "diagnostic"),
    ({"evidence_kind": "assisted"}, "assisted"),
    ({"evidence_kind": "post_solution"}, "post_solution"),
    ({"evidence_kind": "assisted", "response_format": "single_choice"}, "diagnostic"),
    ({"evidence_kind": "post_solution", "completion_scope": "subgoal"}, "diagnostic"),
    ({"target_answer_exposed_before_attempt": True}, "post_solution"),
    ({"task_purpose": "diagnostic", "correctness": "unknown"}, "unknown"),
    ({"response_format": "single_choice", "provenance_uncertain": True}, "unknown"),
    ({"evidence_kind": "none"}, "unknown"),
    ({"skill_ids": ()}, "unknown"),
])
def test_public_and_internal_totals_use_the_same_evidence_boundary(changes, category):
    event = observation(**changes)
    before = event.model_dump()
    summary = evidence_summary([event])
    public = public_evidence([event])
    for key in ("independent", "assisted", "post_solution", "diagnostic", "unknown"):
        assert summary["totals"][key] == int(category == key)
        assert public["ungradable" if key == "unknown" else key] == int(category == key)
    assert summary["totals"]["independent"] == int(event.independent_target)
    assert baseline_prediction([event], ["linear_isolation"]) == (2 / 3 if event.independent_target else .5)
    assert event.model_dump() == before  # projection never rewrites the audit trail


@pytest.mark.asyncio
async def test_stored_choice_is_diagnostic_and_new_free_response_still_counts():
    service = await StudentStateService.create_memory()
    context = dict(session_id="session", cycle_id="cycle", problem_id="problem", problem_revision="choice",
        item_family_id="linear", skill_ids=("linear_isolation",))
    try:
        choice = await service.record_attempt("alice", **context, assessment_id="choice", attempt_id="choice",
            correctness="correct", response_format="single_choice")
        history = await service.events("alice")
        profile = profile_projection(history)
        skill = next(row for row in profile["skills"] if row["code"] == "linear_isolation")
        assert not choice.independent_target and choice.evidence_kind == "independent"
        assert not profile["has_independent_evidence"]
        assert skill["counts"]["independent"] == {"correct": 0, "incorrect": 0}
        assert skill["counts"]["diagnostic"] == {"correct": 1, "incorrect": 0}
        assert public_evidence(history)["diagnostic"] == 1
        assert (await service.summary("alice"))["totals"]["independent"] == 0
        assert teaching_evidence(history, ["linear_isolation"])["independent_correct_items"] == 0

        await service.record_attempt("alice", **(context | {"problem_revision": "fresh"}),
            assessment_id="free", attempt_id="free", correctness="correct")
        history = await service.events("alice")
        assert public_evidence(history)["independent"] == 1
        assert profile_projection(history)["has_independent_evidence"]
        assert (await service.summary("alice"))["totals"]["independent"] == 1
        assert len(history) == 2 and history[0] == choice
        assert await service.events("bob") == []
    finally:
        await service.engine.dispose()


@pytest.mark.parametrize("invalidate_first", [False, True])
def test_exclusion_and_another_session_do_not_promote_a_retry(invalidate_first):
    history = [observation(correctness="incorrect"), observation("retry", event_seq=2, session_id="other")]
    if invalidate_first:
        history.append(LearningEvent(event_id="exclude", student_id="alice", session_id="session", cycle_id="cycle",
            event_seq=3, event_type="evidence_invalidated", problem_id="problem", problem_revision="revision",
            item_family_id="linear", invalidates_event_id="first"))
    summary = evidence_summary(history)
    assert summary["totals"]["independent"] == int(not invalidate_first)
    assert public_evidence(history)["independent"] == int(not invalidate_first)
    assert summary["skills"][0]["independent"]["correct"] == 0
    assert teaching_evidence(history, ["linear_isolation"])["independent_correct_items"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [
    [observation(response_format="single_choice")],
    [observation(correctness="incorrect"), observation("retry", event_seq=2)],
    [observation(target_answer_exposed_before_attempt=True)],
])
async def test_accepted_offer_cannot_promote_choice_or_retry_to_independent_success(history):
    child = SimpleNamespace(cycle=SimpleNamespace(cycle_id="cycle"), state=SimpleNamespace(value="SOLVED"), transitions=[])
    state = SimpleNamespace(
        store=SimpleNamespace(load_child_cycle_for_offer=AsyncMock(return_value=child),
            teaching=SimpleNamespace(load=AsyncMock(return_value={"client_session_id": "session"})),
            iter_for_student=AsyncMock(return_value=[("session", child)])),
        conversations=SimpleNamespace(get=AsyncMock(return_value={"session_id": "session"})))
    result = await enrich_offer(state, SimpleNamespace(recommendation_for_offer=AsyncMock(return_value=None)),
        "alice", SimpleNamespace(offer_id="offer"), {"status": "ACCEPTED"}, history=history, feedback={})
    assert result["display_status"] == "completed"
    assert result["result_summary"]["independent_correct"] == 0
    assert result["result_summary"]["observations"] == len(history)
