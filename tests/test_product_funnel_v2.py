from mathtutor.learning.knowledge_tracing.events import LearningEvent
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
