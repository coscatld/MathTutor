"""Use the shipped trained weights with attributable, independent target items."""

import pytest

from mathtutor.learning.knowledge_tracing.events import LearningEvent
from mathtutor.learning.knowledge_tracing.mapped_dkt import forecast_for
from mathtutor.learning.knowledge_tracing.model_package import load_bundled
from mathtutor.pedagogy.dkt_policy import dkt_may_adjust


@pytest.fixture(scope="module")
def package():
    return load_bundled()


def observation(identity="one", **changes):
    values = dict(event_id=identity, student_id="alice", session_id="session", cycle_id=identity,
        event_seq=1, event_type="attempt_assessed", problem_id=identity, problem_revision=identity,
        item_family_id="linear", skill_ids=("linear_isolation",), assessment_id=identity, attempt_id=identity,
        correctness="incorrect", evidence_kind="independent")
    values.update(changes)
    return LearningEvent(**values)


def test_actual_forecast_with_only_another_skill_does_not_open_the_gate(package):
    history = [observation(skill_ids=("signed_operations",), item_family_id="arithmetic")]
    forecast = forecast_for(package, history, ("quadratic_roots",))
    assert forecast["history_updates"] == 1
    assert forecast["target_skill_ids"] == ["quadratic_roots"]
    assert forecast["target_history_updates"] == 0
    assert forecast["target_history_by_skill"] == {"quadratic_roots": 0}
    assert not dkt_may_adjust(forecast)


def test_actual_eligible_item_changes_the_trained_forecast_and_target_gate(package):
    cold = forecast_for(package, [], ("linear_isolation",))
    personal = forecast_for(package, [observation()], ("linear_isolation",))
    assert cold["target_history_updates"] == 0
    assert personal["target_history_updates"] == 1
    assert personal["target_history_by_skill"] == {"linear_isolation": 1}
    assert personal["probability"] != cold["probability"]
    assert dkt_may_adjust(personal, skill_ids=("linear_isolation",))
    assert not dkt_may_adjust(personal, skill_ids=("quadratic_roots",))
    assert not personal["learning_effect_verified"]


@pytest.mark.parametrize("changes", [
    {"evidence_kind": "assisted"},
    {"evidence_kind": "post_solution"},
    {"evidence_kind": "unknown"},
    {"completion_scope": "subgoal"},
    {"correctness": "unknown"},
    {"correctness": "partial"},
    {"task_purpose": "diagnostic"},
    {"task_purpose": "error_analysis"},
    {"response_format": "single_choice"},
    {"target_answer_exposed_before_attempt": True},
    {"provenance_uncertain": True},
    {"duplicate_response": True},
])
def test_help_and_non_targets_cannot_become_personal_model_evidence(package, changes):
    forecast = forecast_for(package, [observation(**changes)], ("linear_isolation",))
    assert forecast["history_updates"] == forecast["target_history_updates"] == 0
    assert forecast["target_history_by_skill"] == {"linear_isolation": 0}
    assert not dkt_may_adjust(forecast)


def test_repeated_problem_and_excluded_fact_do_not_create_target_evidence(package):
    first = observation()
    repeat = observation("two", event_seq=2, problem_revision=first.problem_revision)
    forecast = forecast_for(package, [first, repeat], ("linear_isolation",))
    assert forecast["history_updates"] == forecast["target_history_updates"] == 1
    invalidation = LearningEvent(event_id="exclude", student_id="alice", session_id="session", cycle_id="one",
        event_seq=3, event_type="evidence_invalidated", problem_id="one", problem_revision="one",
        item_family_id="linear", invalidates_event_id=first.event_id)
    rebuilt = forecast_for(package, [first, repeat, invalidation], ("linear_isolation",))
    assert rebuilt["history_updates"] == rebuilt["target_history_updates"] == 0
    assert not dkt_may_adjust(rebuilt)


def test_joint_observation_is_counted_once_without_claiming_separate_mastery(package):
    joint = observation(skill_ids=("linear_isolation", "signed_operations"))
    forecast = forecast_for(package, [joint], ("linear_isolation", "signed_operations"))
    assert forecast["history_updates"] == forecast["target_history_updates"] == 1
    assert forecast["target_history_by_skill"] == {"linear_isolation": 1, "signed_operations": 1}
    assert "mastery" not in forecast


def test_high_school_unmapped_topic_never_acquires_a_fake_probability(package):
    forecast = forecast_for(package, [observation()], ("derivatives", "statistical_inference"))
    assert forecast["target_history_updates"] == 0
    assert forecast["target_skill_ids"] == []
    assert forecast["probability"] is None
    assert not dkt_may_adjust(forecast)
