from html import unescape

import pytest

from mathtutor.application.learning_actions import POLICY, plan_learning_actions
from mathtutor.application.network_qa import NetworkQA, NetworkReply, choose_network_task
from mathtutor.application.recommendations import RecommendationsService
from mathtutor.application.verification_backend import InProcessVerificationBackend
from test_learning_actions import add_event, catalog, event, service

E02_FIRST = "我能把括号展开，但常分不清什么时候该合并同类项。请从知乎找一份合适的入门资料，安排一次不超过十分钟的练习：先看什么，再做什么，最后怎样核对。"
E02_NEXT = "刚才我只是看懂了你展示的例子，还没有自己作答。下一次打开时，应该继续哪一步？请说明我的进度，并给我一个可选的独立检查目标，不要把观看例子算作掌握。"


def test_e02_current_request_produces_a_bounded_read_attempt_check_session():
    plan = plan_learning_actions([], "calculus", catalog(), request=E02_FIRST)
    assert plan["goal"] == plan["target"] == "combine_like_terms"
    assert plan["goal_source"] == "current_request" and plan["evidence_ids"] == []
    assert plan["time_budget_minutes"] == 10
    assert [s["kind"] for s in plan["steps"]] == ["read", "practice", "check"]
    assert sum(s["minutes"] for s in plan["steps"]) == 10
    assert "不代表不会" in plan["reason"]
    assert "通过" in plan["reason"] and "前置" in plan["check_goal"]
    assert not plan["resources"]  # The equality fixture cannot be attached to a like-terms request.


def test_e02_viewing_without_an_attempt_continues_at_an_optional_check():
    plan = plan_learning_actions([], "combine_like_terms", catalog(), request=E02_NEXT)
    assert plan["reason_code"] == "viewed_unchecked" and plan["action"] == "check"
    assert [s["kind"] for s in plan["steps"]] == ["practice", "check"]
    assert "按你本条说明" in plan["progress"] and "不据此认定掌握" in plan["progress"]
    assert plan["evidence_ids"] == plan["state_event_ids"] == plan["resources"] == []
    assert plan["check_goal"] and not any("答案" in s["detail"] for s in plan["steps"])


def test_confirmed_presentation_is_a_stage_record_and_never_mastery():
    shown = event(skill="combine_like_terms").model_copy(update={"event_type": "help_presented", "correctness": None,
        "evidence_kind": "none", "help_kind": "example"})
    plan = plan_learning_actions([shown], "combine_like_terms", catalog())
    assert plan["action"] == "check" and plan["state_event_ids"] == [shown.event_id]
    assert plan["evidence_count"] == 0 and plan["reason_code"] == "presented_unchecked"
    assert "已展示" in plan["reason"] and not any(s["kind"] == "read" for s in plan["steps"])


def test_an_open_task_outranks_a_new_automatic_assignment_without_claiming_mastery():
    started = event(skill="combine_like_terms").model_copy(update={"event_type": "problem_started", "correctness": None,
        "evidence_kind": "none", "lifecycle_status": "active"})
    plan = plan_learning_actions([started], "math_foundations", catalog())
    assert plan["target"] == "combine_like_terms" and plan["reason_code"] == "task_in_progress"
    assert plan["evidence_count"] == 0 and plan["state_event_ids"] == [started.event_id]
    assert "已经打开的题目" in plan["check_goal"] and plan["resources"] == []
    assert [step["kind"] for step in plan["steps"]] == ["practice", "check"]
    changed = plan_learning_actions([started], "math_foundations", catalog(), request="我现在只想学概率。")
    assert changed["goal"] == "probability" and changed["state_event_ids"] == []


def test_a_completed_task_is_not_resurrected_as_in_progress():
    started = event(skill="equality_preservation").model_copy(update={"event_type": "problem_started", "correctness": None,
        "evidence_kind": "none", "lifecycle_status": "active"})
    completed = event(2, correctness="correct").model_copy(update={"cycle_id": started.cycle_id})
    plan = plan_learning_actions([started, completed], "equality_preservation", catalog())
    assert plan["action"] == "continue" and plan["state_event_ids"] == []


def _task_fact(seq, cycle, kind="problem_started", correctness=None, **extra):
    return event(seq).model_copy(update={"cycle_id": cycle, "session_id": "session-" + cycle,
        "problem_revision": "revision-" + cycle, "problem_id": "problem-" + cycle,
        "event_type": kind, "correctness": correctness,
        "evidence_kind": "independent" if correctness else "none",
        "skill_ids": ("equality_preservation", "linear_isolation", "substitution_check"), **extra})


def _success_after_older_help():
    return [_task_fact(1, "first"), _task_fact(3, "first", "attempt_assessed", "correct"),
        _task_fact(49, "old-example"), _task_fact(57, "old-example", "help_presented", help_kind="solution"),
        _task_fact(58, "current"), _task_fact(60, "current", "attempt_assessed", "incorrect"),
        _task_fact(62, "current", "attempt_assessed", "correct"), _task_fact(63, "next")]


def test_newer_joint_task_state_supersedes_old_presentation_without_component_mastery():
    history = _success_after_older_help()
    for end, reason, state_id, evidence_id in [(6, "task_needs_review", "event-58", "event-60"),
                                             (7, "task_completed", None, "event-62"),
                                             (8, "task_in_progress", "event-63", "event-62")]:
        plan = plan_learning_actions(history[:end], "linear_isolation", catalog())
        assert plan["goal"] == plan["target"] == "linear_isolation"
        assert plan["reason_code"] == reason
        assert plan["evidence_ids"] == [evidence_id] and plan["evidence_count"] == 1
        assert plan["state_event_ids"] == ([state_id] if state_id else [])
        assert not any(row["observed"] for row in plan["prerequisites"])
        assert plan["resources"] == []
    assert "已经打开的题目" in plan["check_goal"]


def test_newer_presentation_and_explicit_request_keep_their_own_priority():
    history = _success_after_older_help()
    later = _task_fact(64, "next", "help_presented", help_kind="example")
    shown = plan_learning_actions([*history, later], "linear_isolation", catalog())
    assert shown["reason_code"] == "presented_unchecked" and shown["state_event_ids"] == [later.event_id]
    assert shown["evidence_ids"] == ["event-62"]
    assert "已经打开的题目" not in shown["check_goal"]
    explicit = plan_learning_actions(history, "linear_isolation", catalog(), request="我现在想学概率。")
    assert explicit["goal"] == "probability" and explicit["evidence_ids"] == []
    assert explicit["state_event_ids"] == []
    viewed = plan_learning_actions(history, "linear_isolation", catalog(), request=E02_NEXT)
    assert viewed["reason_code"] == "viewed_unchecked" and viewed["state_event_ids"] == []


def test_an_excluded_later_outcome_cannot_restore_an_obsolete_help_stage():
    history = _success_after_older_help()
    invalidation = history[-1].model_copy(update={"event_id": "invalidate-later", "event_seq": 65,
        "event_type": "evidence_invalidated", "invalidates_event_id": "event-62"})
    plan = plan_learning_actions([*history, invalidation], "linear_isolation", catalog())
    assert plan["reason_code"] == "task_in_progress"
    assert plan["evidence_ids"] == ["event-60"] and plan["state_event_ids"] == ["event-63"]


async def test_recommendation_service_keeps_current_task_after_real_multiskill_event_replay(service):
    await service.configure("alice", enabled=False, goal="linear_isolation")
    for fact in _success_after_older_help():
        await add_event(service, fact)
    before = await service.student_state.events("alice")
    view = await service.get("alice")
    assert view["plan"]["reason_code"] == "task_in_progress"
    assert view["plan"]["evidence_ids"] == ["event-62"]
    assert (await service.plan_for("alice", request="下一步怎么继续？"))["state_event_ids"] == ["event-63"]
    assert await service.student_state.events("alice") == before
    assert not service.client.calls


def test_completed_target_is_not_reassigned_intro_work_but_explicit_review_wins():
    done = event(skill="equality_preservation", correctness="correct")
    plan = plan_learning_actions([done], "equality_preservation", catalog())
    assert plan["action"] == "continue" and plan["resources"] == []
    assert not any(step["kind"] == "read" for step in plan["steps"])
    review = plan_learning_actions([done], "equality_preservation", catalog(), request="我想复习等式两边同做运算。")
    assert review["action"] == "explain" and review["reason_code"] == "requested_review"
    assert review["evidence_ids"] == [done.event_id] and review["steps"][0]["kind"] == "read"


def test_resources_need_exact_topic_and_satisfied_assessed_prerequisites():
    source = catalog()
    assert plan_learning_actions([], "equality_preservation", source)["resources"] == []
    ready = [event(skill="signed_operations", correctness="correct")]
    assert plan_learning_actions(ready, "equality_preservation", source)["resources"][0]["resource_id"] == "fixture-equality"
    wrong = plan_learning_actions(ready, "fraction_operations", source)
    assert wrong["resources"] == []
    difficult = plan_learning_actions([event(skill="equality_preservation")], "linear_isolation", source)
    assert difficult["action"] == "review_prerequisite" and difficult["target"] == "equality_preservation"


@pytest.mark.parametrize("minutes", [2, 7, 15, 30])
def test_time_budget_is_a_general_request_constraint(minutes):
    plan = plan_learning_actions([], "fraction_operations", catalog(), request=f"安排{minutes}分钟的分数运算学习计划。")
    assert sum(s["minutes"] for s in plan["steps"]) == minutes
    assert all(s["minutes"] > 0 for s in plan["steps"])


def test_ordinary_plan_requests_use_the_plan_branch_without_a_seeded_example():
    assert choose_network_task("请安排七分钟的分数练习。").purpose == "learn"
    assert choose_network_task("请制定我的学习计划。").topics == ("math_foundations",)
    assert choose_network_task("数学基础下一步怎么学？").purpose == "learn"


async def test_current_request_overrides_saved_goal_without_overwriting_for_a_temporary_resource_search(service):
    await service.configure("alice", enabled=False, goal="calculus")
    before = await service.student_state.events("alice")
    plan = await service.plan_for("alice", "linear_isolation", request="我现在想学概率，不要推荐一次方程。")
    assert plan["goal"] == "probability" and plan["goal_source"] == "current_request"
    assert (await service.get("alice"))["goal"] == "calculus"
    assert await service.student_state.events("alice") == before
    assert service.client.calls == []


async def test_explicit_new_plan_survives_restart_and_does_not_reenable_network(service):
    await service.configure("alice", enabled=False, goal="calculus")
    plan = await service.plan_for("alice", "combine_like_terms", request=E02_FIRST)
    view = await service.get("alice")
    assert plan["goal"] == view["goal"] == "combine_like_terms" and not view["enabled"]
    reopened = RecommendationsService(service.repository.engine, service.student_state, service.client, catalog=catalog())
    try:
        follow = await reopened.plan_for("alice", "calculus", request=E02_NEXT)
    finally:
        await reopened.close()
    assert follow["goal"] == "combine_like_terms" and follow["action"] == "check"
    assert follow["reason_code"] == "viewed_unchecked" and follow["policy"] == POLICY
    assert not service.client.calls


async def test_older_plan_cannot_overwrite_a_newer_goal_consent_or_daily_budget(service):
    await service.configure("alice", enabled=True, goal="calculus")
    row = await service.repository.get("alice")
    await service.repository.reserve("alice", generation=row["generation"], cache_key="old", now=service.clock())
    original = service.repository.select_goal
    async def newer_goal_first(owner, **kwargs):
        await service.configure(owner, enabled=False, goal="probability")
        return await original(owner, **kwargs)
    service.repository.select_goal = newer_goal_first
    plan = await service.plan_for("alice", "combine_like_terms", request=E02_FIRST)
    current = await service.repository.get("alice")
    assert plan["goal"] == current["goal"] == "probability"
    assert not current["enabled"] and current["budget_calls"] == 1 and not current["lease_token"]
    assert plan["goal_source"] == "current_goal" and not service.client.calls


async def test_changed_current_goal_defeats_an_older_conversation_goal(service):
    await service.configure("alice", enabled=False, goal="probability")
    plan = await service.plan_for("alice", "calculus", request="接下来应该学哪一步？")
    assert plan["goal"] == "probability" and plan["goal_source"] == "current_goal"
    await service.configure("alice", enabled=False, goal="math_foundations")
    assert (await service.plan_for("alice", "calculus", request="接下来怎么学？"))["goal"] == "math_foundations"


async def test_network_advice_is_resolved_before_the_single_current_plan_is_rendered(service):
    await service.plan_for("alice", "combine_like_terms", request=E02_FIRST)
    qa = NetworkQA(service.client, InProcessVerificationBackend(), planner=service.plan_for)
    async def answered(owner, task):
        return NetworkReply("OLD_CONFLICTING_PLAN", "answered", task.query, (), (
            {"claim_id": "advice", "accepted": True, "kind": "ai_inference", "text": "已经全部掌握，下一步跳过独立练习。",
             "conditions": "", "dependencies": [], "evidence": [], "math": "none"},))
    qa.respond = answered
    result = await qa.maybe_respond("alice", text=E02_NEXT, prior_question=E02_FIRST, enabled=True)
    assert result.status == "local_plan"
    assert "OLD_CONFLICTING_PLAN" not in result.text and "已经全部掌握" not in result.text
    assert "按你本条说明" in unescape(result.text) and "独立检查" in unescape(result.text)
    assert result.planner_receipt["suppressed_advice_ids"] == ["advice"]
    assert result.planner_receipt["goal"] == "combine_like_terms"
    assert [s["kind"] for s in result.planner_receipt["steps"]] == ["practice", "check"]
    assert not service.client.calls
