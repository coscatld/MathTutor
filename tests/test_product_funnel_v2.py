import pytest

from mathtutor.learning.knowledge_tracing.events import (
    LearningEvent, evidence_category, independent_opportunity, valid_events,
)
from mathtutor.learning.knowledge_tracing.product_metrics import product_funnel


def event(cycle, seq, kind, **values):
    return LearningEvent(event_id=f"{cycle}-{seq}-{kind}", student_id="alice", session_id="s", cycle_id=cycle,
        event_seq=seq, event_type=kind, problem_id=f"problem-{cycle}", problem_revision=f"revision-{cycle}",
        item_family_id="linear", skill_ids=("linear_isolation",), **values)


def start(cycle, seq, **values):
    return event(cycle, seq, "problem_started", eligible_cycle=True, **values)


def assessed(cycle, seq, correctness="correct", evidence_kind="independent", **values):
    return event(cycle, seq, "attempt_assessed", correctness=correctness, evidence_kind=evidence_kind,
        attempt_id=f"attempt-{seq}", assessment_id=f"assessment-{seq}", **values)


def test_missing_start_denominator_is_unavailable_not_zero_percent():
    result = product_funnel([assessed("a", 1)])
    assert result["student_problem_solved"]["value"] is None
    assert result["eligibility"]["unknown_start_eligibility"] == 1
    assert result["completion_rounds"]["median"] is None
    assert result["system_solution_availability"]["value"] is None


def test_exits_failures_and_unknowns_remain_in_started_denominator():
    events = [
        start("independent", 1), assessed("independent", 2),
        start("assisted", 10), event("assisted", 11, "help_presented", help_kind="hint"),
        assessed("assisted", 12, evidence_kind="assisted"),
        start("post", 20), event("post", 21, "help_presented", help_kind="solution", target_answer_exposed=True),
        assessed("post", 22, evidence_kind="post_solution", target_answer_exposed_before_attempt=True),
        start("exit", 30), event("exit", 31, "problem_ended", lifecycle_status="exited"),
        start("unknown", 40), assessed("unknown", 41, correctness="unknown", evidence_kind="unknown"),
        start("failed", 50), event("failed", 51, "problem_ended", lifecycle_status="failed"),
    ]
    result = product_funnel(events)
    assert result["student_problem_solved"]["numerator"] == 2
    assert result["student_problem_solved"]["denominator"] == 6
    assert result["solving_breakdown"] == {
        "solved_independent": 1, "solved_assisted": 1, "solved_help_provenance_unknown": 0,
        "solved_diagnostic": 0, "solved_after_retry": 0,
        "exited_unsolved": 1, "failed_unsolved": 1, "unknown_or_incomplete": 2}
    assert result["post_solution_reproduction"]["numerator"] == 1
    assert result["assisted_completion"]["numerator"] == 1
    assert result["first_independent_unknown"] == 1
    assert result["first_independent_correct"]["denominator"] == 2


def test_transfer_counts_skips_unknown_outcomes_without_hiding_them():
    result = product_funnel([start("a", 1, task_purpose="transfer"), assessed("a", 2),
                            start("b", 3, task_purpose="transfer"),
                            event("b", 4, "problem_ended", lifecycle_status="exited")])
    assert result["transfer_success"]["numerator"] == 1
    assert result["transfer_success"]["denominator"] == 2


def test_requested_committed_and_presented_solution_are_different_facts():
    events = [start("a", 1), event("a", 2, "help_requested", help_kind="solution", request_id="request"),
              event("a", 3, "help_committed", help_kind="solution", request_id="request", target_answer_exposed=True)]
    result = product_funnel(events)
    assert result["system_solution_availability"]["numerator"] == 0
    assert result["system_solution_availability"]["denominator"] == 1
    presented = event("a", 4, "help_presented", help_kind="solution", request_id="request",
                      target_answer_exposed=True, target_answer_authorized=True, delivery_id="message")
    result = product_funnel(events + [presented, presented])
    assert result["system_solution_availability"]["numerator"] == 1
    assert result["unexpected_target_exposure"]["value"] is None
    assert not result["learning_effect_verified"]


def test_unexpected_exposure_denominator_is_non_solution_teaching_deliveries():
    events = [start("a", 1), event("a", 2, "help_presented", target_answer_authorized=False,
        target_answer_exposed=False, help_kind="hint", delivery_id="safe"),
        event("a", 3, "help_presented", target_answer_authorized=False, target_answer_exposed=True,
              help_kind="hint", delivery_id="leak"),
        event("a", 4, "help_presented", target_answer_authorized=True, target_answer_exposed=True,
              help_kind="solution", delivery_id="authorized")]
    metric = product_funnel(events)["unexpected_target_exposure"]
    assert metric["numerator"] == 1 and metric["denominator"] == 2


def test_retry_frames_do_not_inflate_completed_rounds():
    events = [start("a", 1), assessed("a", 2), start("b", 3), assessed("b", 4)]
    turns = [{"student_id": "alice", "cycle_id": "a", "turn_id": "first",
              "student_math_message": True, "tutor_presented": True},
             {"student_id": "alice", "cycle_id": "b", "turn_id": "b-first",
              "student_math_message": True, "tutor_presented": True},
             {"student_id": "alice", "cycle_id": "b", "turn_id": "b-second",
              "student_math_message": True, "tutor_presented": True}]
    result = product_funnel(events, turn_records=turns + [turns[0]])
    assert result["completion_rounds"]["median"] == 1.5
    assert result["completion_rounds"]["p90"] == 2
    assert result["completion_rounds"]["completed_cycles_without_turn_telemetry"] == 0


@pytest.mark.parametrize("response_format", ["free_response", "single_choice"])
def test_option_exposure_is_diagnostic_in_events_and_transfer_funnel(response_format):
    facts = [start("transfer", 1, task_purpose="transfer"),
             event("transfer", 2, "options_exposed"),
             assessed("transfer", 3, response_format=response_format)]
    original = [fact.model_dump() for fact in facts]
    replayed = valid_events(facts)[-1]
    assert replayed.options_exposed
    assert evidence_category(replayed) == "diagnostic"
    assert not replayed.independent_target and not independent_opportunity(replayed)
    result = product_funnel(facts)
    assert result["schema_version"] == "product_funnel_v2"
    assert result["independent_opportunity_policy"] == "first_unassisted_free_response_v1"
    assert result["transfer_success"]["numerator"] == 0
    assert result["transfer_success"]["denominator"] == 1
    assert result["first_independent_correct"]["numerator"] == 0
    assert result["first_independent_correct"]["denominator"] == 0
    assert result["solving_breakdown"]["solved_independent"] == 0
    assert result["solving_breakdown"]["solved_diagnostic"] == 1
    assert sum(result["solving_breakdown"].values()) == 1
    assert result["assisted_completion"]["denominator"] == 0  # Options are not a tutor hint.
    assert result["unexpected_target_exposure"]["denominator"] == 0
    assert [fact.model_dump() for fact in facts] == original


@pytest.mark.parametrize("changes", [
    {"response_format": "single_choice"}, {"options_exposed": True},
    {"prior_task_attempt": True}, {"duplicate_response": True},
    {"target_answer_exposed_before_attempt": True}, {"provenance_uncertain": True},
    {"prior_help_event_ids": ("hint",)}, {"evidence_kind": "assisted"},
    {"evidence_kind": "unknown"}, {"evidence_kind": "none"},
    {"completion_scope": "subgoal"}, {"task_purpose": "diagnostic"},
    {"task_purpose": "error_analysis"}, {"skill_ids": ()},
])
def test_ineligible_assessment_cannot_supply_an_independent_target_or_opportunity(changes):
    attempt = assessed("a", 2).model_copy(update=changes)
    assert not independent_opportunity(attempt)
    assert not attempt.independent_target
    result = product_funnel([start("a", 1, task_purpose="transfer"), attempt])
    assert result["first_independent_correct"]["denominator"] == 0
    assert result["transfer_success"]["numerator"] == 0
    assert result["transfer_success"]["denominator"] == 1


@pytest.mark.parametrize("correctness,evidence_kind,unknown", [
    ("unknown", "unknown", 1), (None, "unknown", 1), ("partial", "independent", 0),
    ("incorrect", "independent", 0), ("correct", "independent", 0),
])
def test_independent_opportunity_does_not_require_a_binary_verdict(correctness, evidence_kind, unknown):
    attempt = assessed("a", 2, correctness=correctness, evidence_kind=evidence_kind)
    assert independent_opportunity(attempt)
    assert attempt.independent_target == (correctness in {"correct", "incorrect"})
    result = product_funnel([start("a", 1, task_purpose="transfer"), attempt])
    assert result["first_independent_correct"]["denominator"] == 1
    assert result["first_independent_correct"]["numerator"] == int(correctness == "correct")
    assert result["first_independent_unknown"] == unknown
    assert result["transfer_success"]["denominator"] == 1


def test_help_retry_unknown_and_exit_have_disjoint_breakdowns_and_stable_denominators():
    facts = [
        start("help", 1, task_purpose="transfer"),
        event("help", 2, "help_presented", help_kind="hint"),
        assessed("help", 3, evidence_kind="assisted", prior_help_event_ids=("hint",)),
        start("retry", 4, task_purpose="transfer"), assessed("retry", 5, correctness="incorrect"),
        assessed("retry", 6),
        start("unknown", 7, task_purpose="transfer"),
        assessed("unknown", 8, correctness="unknown", evidence_kind="unknown"),
        start("exit", 9, task_purpose="transfer"), event("exit", 10, "problem_ended", lifecycle_status="exited"),
        start("free", 11, task_purpose="transfer"), assessed("free", 12),
        start("choice", 13, task_purpose="transfer"), assessed("choice", 14, response_format="single_choice"),
    ]
    result = product_funnel(facts)
    assert result["solving_breakdown"] == {
        "solved_independent": 1, "solved_assisted": 1, "solved_diagnostic": 1,
        "solved_after_retry": 1, "solved_help_provenance_unknown": 0,
        "exited_unsolved": 1, "failed_unsolved": 0, "unknown_or_incomplete": 1,
    }
    assert sum(result["solving_breakdown"].values()) == 6
    assert result["student_problem_solved"]["numerator"] == 4
    assert result["student_problem_solved"]["denominator"] == 6
    assert result["first_independent_correct"]["numerator"] == 1
    assert result["first_independent_correct"]["denominator"] == 3
    assert result["first_independent_unknown"] == 1
    assert result["transfer_success"]["numerator"] == 1
    assert result["transfer_success"]["denominator"] == 6


def test_unknown_assessment_after_help_or_with_uncertain_provenance_is_not_an_independent_opportunity():
    facts = [start("helped", 1), assessed("helped", 2, correctness="unknown", evidence_kind="unknown",
             prior_help_event_ids=("other-session-hint",)), start("uncertain", 3),
             assessed("uncertain", 4, correctness="unknown", evidence_kind="unknown", provenance_uncertain=True)]
    result = product_funnel(facts)
    assert result["first_independent_correct"]["denominator"] == 0
    assert result["first_independent_unknown"] == 0
    assert result["student_problem_solved"]["denominator"] == 2


def test_options_in_an_older_session_survive_replay_and_do_not_affect_other_owners():
    exposed = event("old", 1, "options_exposed").model_copy(update={"session_id": "old-session"})
    reopened = [start("new", 2, task_purpose="transfer"), assessed("new", 3)]
    reopened = [x.model_copy(update={"problem_revision": exposed.problem_revision, "session_id": "new-session"})
                for x in reopened]
    other_owner = [x.model_copy(update={"student_id": "bob", "cycle_id": "bob-transfer"}) for x in reopened]
    facts = [exposed, *reopened, *other_owner]
    result = product_funnel(facts)
    assert result["transfer_success"]["numerator"] == 1
    assert result["transfer_success"]["denominator"] == 2
    assert result["solving_breakdown"]["solved_diagnostic"] == 1
    assert result["solving_breakdown"]["solved_independent"] == 1
    assert product_funnel([LearningEvent.model_validate_json(x.model_dump_json()) for x in facts]) == result


def test_excluded_first_assessment_does_not_turn_retry_into_new_independent_opportunity():
    first = assessed("a", 2, correctness="incorrect")
    facts = [start("a", 1, task_purpose="transfer"), first,
             event("a", 3, "evidence_invalidated", invalidates_event_id=first.event_id), assessed("a", 4)]
    result = product_funnel(facts)
    assert result["first_independent_correct"]["denominator"] == 0
    assert result["transfer_success"]["numerator"] == 0
    assert result["transfer_success"]["denominator"] == 1
    assert result["solving_breakdown"]["solved_after_retry"] == 1
