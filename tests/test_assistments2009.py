from dataclasses import replace
import pytest
from mathtutor.learning.knowledge_tracing.assistments2009 import adapt, temporal_views, split_audit


def row(order=1, **values):
    return dict(order_id=str(order), user_id="s", problem_id=str(order), template_id=str(order),
                original="1", correct="0", first_action="0", hint_count="0", attempt_count="1",
                answer_type="algebra", skill_id="277", skill_name="Addition and Subtraction Integers", **values)


def changed(order=1, **values):
    return {**row(order), **values}


@pytest.mark.parametrize("changes,label,reason", [
    ({"correct":"1"}, 1, ""),
    ({"hint_count":"3", "attempt_count":"2"}, 0, ""),
    ({"first_action":"1", "hint_count":"3"}, None, "help_before_first_attempt"),
    ({"first_action":"2"}, None, "help_before_first_attempt"),
    ({"first_action":"NA"}, None, "first_action_unknown"),
    ({"answer_type":"open_response", "correct":"1"}, None, "unverified_answer_type"),
    ({"correct":"1", "hint_count":"1"}, None, "contradictory_correct_and_help"),
])
def test_first_independent_source_label(changes, label, reason):
    rows, _ = adapt([changed(**changes)])
    assert rows[0].label == label and rows[0].exclusion == reason


def test_dedup_keeps_skill_union_and_unknown_first_occupies_position():
    rows, report = adapt([changed(first_action="NA"), changed(skill_id="279", skill_name="Multiplication and Division Integers", first_action="NA"),
                         changed(2, problem_id="1", correct="1")])
    assert report["duplicate_or_skill_expansion_rows_removed"] == 1
    assert rows[0].source_skills == ("277", "279")
    assert rows[0].mapped_skills == ("signed_operations",)
    assert rows[1].label is None and rows[1].prior_problem_seen
    with pytest.raises(ValueError, match="conflicting duplicate"):
        adapt([row(), changed(correct="1")])


def test_exact_checkpoints_do_not_skip_unknown_or_leak_query_outcome():
    rows, _ = adapt([changed(1, first_action="1"), row(2), changed(3, original="0"), row(4), row(5)])
    views = list(temporal_views(rows))
    assert [v["checkpoint"] for v in views] == [0, 1, 3]
    assert views[0]["label"] is None and views[0]["history"] == ()
    assert views[1]["query_order_id"] == 2 and len(views[1]["history"]) == 1
    assert views[2]["query_order_id"] == 5 and len(views[2]["history"]) == 4
    changed_rows = [replace(r, label=1, hint_count=99) if r.order_id >= 2 else r for r in rows]
    changed_view = list(temporal_views(changed_rows))[1]
    assert changed_view["history"] == views[1]["history"]
    assert changed_view["query"] == views[1]["query"]
    assert set(views[1]["query"]) == {"problem_id", "source_skills", "mapped_skills"}


def test_source_student_holdout_allows_shared_course_questions():
    rows, _ = adapt([changed(i, user_id=str(s)) for s in range(10) for i in range(1, 15)])
    main = split_audit(rows, 17, "student")
    stress = split_audit(rows, 17, "student_item")
    assert main["discarded_by_joint_holdout"] == 0
    assert stress["discarded_by_joint_holdout"] > 0
    assert sum(f["students"] for f in main["folds"].values()) == 10
    assert main["folds"]["test"]["checkpoints"]["10"]["legal"] == 2
