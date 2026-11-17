from copy import deepcopy

import pytest

from mathtutor.application.exploration_learning import (
    Curriculum,
    LearningObservation,
    build_learning_plan,
    catalog_manifest,
    explain_check,
    grade_check,
    public_check,
)


def event(event_id="e1", *, concept="target", correct=True, **changes):
    values = {
        "event_id": event_id, "event_type": "attempt", "concept_id": concept,
        "actor": "learner", "item_id": "item_" + event_id, "attempt_id": "try_" + event_id,
        "answer": "A", "correct": correct, "verification": "rule", "assistance": "none",
        "occurred_at": "2026-11-18T01:00:00+00:00",
    }
    return LearningObservation(**(values | changes))


GRAPH = {
    "nodes": [{"concept_id": "basic", "title": "基础"}, {"concept_id": "target", "title": "目标"}],
    "prerequisites": [{"before": "basic", "after": "target"}],
}


def plan(observations=(), goal="understand", **changes):
    return build_learning_plan("  我想理解这个条件，为什么必须满足？  ", goal, observations,
                               concept_id="target", curriculum=GRAPH, **changes)


def test_preserves_question_and_cold_start_is_a_suggestion_not_a_diagnosis():
    result = plan()
    assert result.original_question == "  我想理解这个条件，为什么必须满足？  "
    assert result.evidence_state == "unknown"
    assert not result.basis_observation_ids and result.independent_successes == 0
    assert result.steps[0].action == "review_prerequisite"
    assert "不等于你不会" in result.steps[0].reason
    assert 1 <= len(result.steps) <= 3
    assert "mastery" not in result.model_dump()


@pytest.mark.parametrize("kind", ["view", "bookmark", "self_report"])
def test_reading_and_self_reports_do_not_establish_independent_evidence(kind):
    result = plan([event(event_type=kind)])
    assert result.evidence_state == "unknown"
    assert result.independent_successes == 0
    assert not result.basis_observation_ids


@pytest.mark.parametrize("changes", [
    {"actor": "system"}, {"verification": "none"}, {"correct": None},
    {"item_id": None}, {"attempt_id": None},
])
def test_unverified_or_system_answers_are_not_learner_success(changes):
    result = plan([event(**changes)])
    assert result.evidence_state == "unknown" and result.independent_successes == 0


@pytest.mark.parametrize("assistance", ["hint", "answer_seen"])
def test_helped_success_requests_fresh_independent_check(assistance):
    result = plan([event(assistance=assistance)])
    assert result.evidence_state == "assisted_only"
    assert result.steps[0].action == "independent_check"
    assert result.steps[0].basis_observation_ids == ("e1",)
    assert result.independent_successes == 0


def test_single_independent_success_is_not_stable_mastery_and_goal_is_preserved():
    result = plan([event()], goal="compare")
    assert result.evidence_state == "independent_observed"
    assert result.steps[0].action == "transfer_check"
    assert "不代表稳定掌握" in result.steps[0].reason
    assert result.steps[1].action == "compare_methods"
    assert result.goal == "compare" and result.basis_observation_ids == ("e1",)


def test_conflicting_observations_need_clarification_and_retraction_rebuilds_state():
    observations = [event(), event("e2", correct=False)]
    result = plan(observations)
    assert result.evidence_state == "mixed_observations"
    assert result.steps[0].action == "clarify_conflict"
    assert set(result.basis_observation_ids) == {"e1", "e2"}
    retained = plan(observations, retracted_observation_ids=("e1",))
    assert retained.evidence_state == "needs_check" and retained.basis_observation_ids == ("e2",)
    empty = plan(observations, retracted_observation_ids=("e1", "e2"))
    assert empty.evidence_state == "unknown" and not empty.basis_observation_ids


def test_duplicate_attempt_and_repeat_item_do_not_add_evidence_or_rewrite_first_result():
    first = event(correct=False)
    repeated = event("e2", item_id=first.item_id, attempt_id="new_try", correct=True)
    duplicate = event("e3", item_id="new_item", attempt_id=first.attempt_id, correct=True)
    result = plan([first, first, repeated, duplicate])
    assert result.independent_successes == 0
    assert result.evidence_state == "needs_check"
    assert result.basis_observation_ids == ("e1",)


def test_retracting_a_grade_does_not_reclassify_a_retry_as_independent():
    first = event("first", concept="square_root", item_id="root.negative", correct=False)
    retry = event("retry", concept="square_root", item_id="root.negative", correct=True)
    result = build_learning_plan("sqrt(x²)", observations=[first, retry], retracted_observation_ids=("first",))
    assert result.evidence_state == "unknown" and result.independent_successes == 0
    assert not result.basis_observation_ids
    assert result.check and result.check.check_id != "root.negative"


def test_observation_identity_cannot_be_rewritten():
    with pytest.raises(ValueError, match="rewritten"):
        plan([event(), event(correct=False)])


def test_only_relevant_observed_prerequisite_changes_default_frontier():
    initial = plan()
    unrelated = plan([event(concept="elsewhere")])
    ready = plan([event(concept="basic")])
    assert initial.steps == unrelated.steps
    assert ready.steps[0].action == "read"
    assert ready.evidence_state == "unknown"
    assert ready.independent_successes == 0
    assert ready.basis_observation_ids == ("e1",)


def test_assisted_prerequisite_is_visible_in_reason_but_not_independent_evidence():
    assisted = event("helped", concept="basic", assistance="hint")
    result = plan([assisted])
    assert result.evidence_state == "unknown" and result.independent_successes == 0
    assert result.steps[0].basis_observation_ids == ("helped",)
    assert result.basis_observation_ids == ("helped",)
    assert "帮助" in result.steps[0].reason
    retracted = plan([assisted], retracted_observation_ids=("helped",))
    assert not retracted.basis_observation_ids and not retracted.steps[0].basis_observation_ids


def test_equivalent_timestamp_offsets_and_ties_keep_first_attempt_identity():
    earlier = event("z-first", correct=False, item_id="same", occurred_at="2026-11-18T09:00:00+08:00")
    later = event("a-retry", correct=True, item_id="same", occurred_at="2026-11-18T01:01:00+00:00")
    assert plan([later, earlier]).evidence_state == "needs_check"
    same_clock = later.model_copy(update={"occurred_at": "2026-11-18T01:00:00+00:00"})
    assert plan([earlier, same_clock]).evidence_state == "needs_check"
    with pytest.raises(ValueError, match="timezone"):
        event(occurred_at="2026-11-18T01:00:00")


def test_goal_changes_learning_activity_without_overwriting_original_question():
    understood, applied, compared = [plan(goal=goal) for goal in ("understand", "apply", "compare")]
    assert understood.steps[1].action == "read"
    assert applied.steps[1].action == "worked_example"
    assert compared.steps[1].action == "compare_methods"
    assert len({p.original_question for p in (understood, applied, compared)}) == 1


def test_unknown_topic_keeps_a_useful_path_without_fabricated_check_or_source():
    result = build_learning_plan("How should I explore an unfamiliar proof?", "compare", language="en")
    assert result.target_concept == "open_inquiry"
    assert result.steps[0].action == "compare_methods"
    assert result.steps[1].action == "independent_check"
    assert result.check is None and result.prerequisite_basis == "none"
    assert result.original_question == "How should I explore an unfamiliar proof?"


@pytest.mark.parametrize("check_id,correct,wrong", [
    ("decimal.finite", "0.001", "0"),
    ("decimal.limit", "1", "0.999"),
    ("root.negative", "3", "-3"),
    ("root.condition", "B", "A"),
    ("division.zero", "B", "A"),
    ("derivative.absolute", "B", "A"),
    ("derivative.square", "0", "1"),
    ("series.half", "2", "1"),
    ("series.boundary", "B", "A"),
    ("probability.conditional", "2/5", "4/5"),
    ("probability.reverse", "B", "A"),
    ("linear.dependent", "A", "B"),
    ("linear.basis", "A", "B"),
])
def test_curated_math_boundaries_are_server_graded(check_id, correct, wrong):
    accepted = grade_check(check_id, correct, observation_id="ok")
    rejected = grade_check(check_id, wrong, observation_id="wrong")
    assert accepted.correctness == "correct" and rejected.correctness == "incorrect"
    assert accepted.independent and accepted.observation.verification == "rule"
    payload = public_check(check_id).model_dump()
    assert "answer" not in payload and "explanation" not in payload


def test_help_exposure_and_repeated_checks_cannot_regain_independence():
    assert "|x|" in explain_check("root.negative")
    assert "principal" in explain_check("root.negative", "en")
    first = grade_check("root.negative", "3", observation_id="a", helped=True)
    second = grade_check("root.negative", "3", observation_id="b", prior_observations=[first.observation])
    assert not first.independent and not second.independent
    exposed = event("exposure", concept="square_root", event_type="answer_exposed", item_id="root.negative")
    after_exposure = grade_check("root.negative", "3", observation_id="c", prior_observations=[exposed])
    assert not after_exposure.independent
    result = build_learning_plan("sqrt(x²)", observations=[first.observation, second.observation, exposed])
    assert result.evidence_state == "assisted_only" and result.independent_successes == 0
    assert result.check and result.check.check_id != "root.negative"


@pytest.mark.parametrize("answer", ["1/0", "__import__('os').system('true')", "nan", "1e999999", "", "1+2"])
def test_unparsed_answers_do_not_guess_or_expose_a_solution(answer):
    result = grade_check("root.negative", answer, observation_id="unparsed")
    assert result.correctness == "unknown" and not result.independent
    assert result.observation.correct is None
    assert "3" not in result.feedback
    retried = grade_check("root.negative", "3", observation_id="retried", prior_observations=[result.observation])
    assert retried.independent


def test_graph_cycles_unknown_edges_and_budgets_are_bounded():
    cyclic = deepcopy(GRAPH)
    cyclic["prerequisites"].append({"before": "target", "after": "basic"})
    with pytest.raises(ValueError, match="Cyclic"):
        Curriculum.model_validate(cyclic)
    bad = deepcopy(GRAPH)
    bad["prerequisites"][0]["before"] = "absent"
    with pytest.raises(ValueError, match="Unknown"):
        Curriculum.model_validate(bad)
    with pytest.raises(ValueError, match="budget"):
        plan([event(str(i)) for i in range(257)])
    with pytest.raises(ValueError):
        build_learning_plan("" )
    assert catalog_manifest()["training"] is False
