"""The trained forecast may change the next sentence and one difficulty step."""
import pytest

from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
from mathtutor.pedagogy.teaching_plan import TeachingPlan, apply_trained_dkt
from mathtutor.pedagogy.tutor_writer import PublicProblemView, _build_user_prompt
from mathtutor.application.practice_policy import apply_dkt_difficulty


def _plan(**changes):
    values = dict(action="ASK_STUDENT", strategy="focused_question", question_goal="隔离未知数",
                  target_subgoal_id="isolate", target_skill_ids=("linear_isolation",), reason_codes=("CURRENT_SUBGOAL",),
                  support_mode="guided", exit_options=("request_solution",), max_assistance_level=1)
    values.update(changes)
    return TeachingPlan(**values)


def _forecast(**changes):
    values = dict(controls_teaching=True, probability=0.2, history_updates=1,
                  mapped_product_skills=["linear_isolation"], learning_effect_verified=False,
                  target_skill_ids=["linear_isolation"], target_history_updates=1,
                  target_history_by_skill={"linear_isolation": 1})
    values.update(changes)
    return values


def test_cold_start_does_not_narrate_someone_elses_history_or_move_difficulty():
    plan = _plan()
    assert apply_trained_dkt(plan, _forecast(history_updates=0, probability=0.2)) == plan
    level, _reason = apply_dkt_difficulty(3, _forecast(history_updates=0, probability=0.2))
    assert level == 3


def test_personal_low_probability_scaffolds_without_printing_a_percent():
    guided = apply_trained_dkt(_plan(), _forecast())
    assert "等式隔离这一步" in guided.student_guidance
    assert "%" not in guided.student_guidance and "掌握" not in guided.student_guidance
    assert guided.max_assistance_level == 2 and "DKT_UNSTEADY" in guided.reason_codes
    level, reason = apply_dkt_difficulty(3, _forecast())
    assert level == 2 and "0." not in reason
    steady = apply_trained_dkt(_plan(max_assistance_level=3), _forecast(probability=0.9))
    assert steady.max_assistance_level == 2 and "DKT_STEADY" in steady.reason_codes
    solution = apply_trained_dkt(_plan(action="SHOW_SOLUTION", max_assistance_level=5), _forecast(probability=0.9))
    assert solution.max_assistance_level == 5 and solution.action == "SHOW_SOLUTION"


def test_writer_is_told_to_follow_the_sentence_and_not_invent_mastery():
    view = PublicProblemView(problem_type="linear", display_latex="2x+3=7",
                             teaching_plan={"student_guidance": "先只写等式隔离这一步，不用一次算完。"})
    prompt = _build_user_prompt(view, DisclosedSolutionContext(assistance_level=1),
                                TutorAction(action="ASK_STUDENT", effective_assistance_level=1))
    assert "先只写等式隔离这一步" in prompt
    assert "不要改写成掌握百分比" in prompt


def test_dkt_moves_at_most_one_notch_and_needs_a_mapping_and_the_switch(monkeypatch):
    plan = _plan(max_assistance_level=0)
    assert apply_trained_dkt(plan, _forecast()).max_assistance_level == 1
    assert apply_trained_dkt(plan, _forecast(mapped_product_skills=[])) == plan
    assert apply_dkt_difficulty(3, _forecast(mapped_product_skills=[]))[0] == 3
    monkeypatch.setenv("MATHTUTOR_DKT_TEACHING", "off")
    assert apply_trained_dkt(plan, _forecast()) == plan
    assert apply_dkt_difficulty(3, _forecast())[0] == 3


def test_adjustments_are_recorded_on_the_turn_trace():
    from mathtutor.application.tutor_runtime import current_turn
    from mathtutor.domain.turn_result import TutorTurnResult
    from mathtutor.repositories.turn_trace_repository import health
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        apply_trained_dkt(_plan(), _forecast())
        apply_dkt_difficulty(3, _forecast(probability=0.9))
    finally:
        current_turn.reset(token)
    assert turn.details["dkt"] == {"teaching_more_support": 1, "difficulty_up": 1}
    row = {"status": "COMPLETED", "finish_reason": "NATURAL_STOP", "latency_ms": 1, "input_tokens": 0,
           "output_tokens": 0, "details": turn.details}
    assert health([row, {**row, "details": {}}])["dkt_adjust_rate"] == 0.5


@pytest.mark.parametrize("probability", [float("nan"), float("inf"), float("-inf"), -0.1, 1.1, True, "0.2", 10**1000])
def test_invalid_probabilities_never_control_teaching(probability):
    plan = _plan()
    assert apply_trained_dkt(plan, _forecast(probability=probability)) == plan


def test_other_skill_history_and_old_forecasts_do_not_justify_current_support():
    plan = _plan()
    assert apply_trained_dkt(plan, _forecast(history_updates=50, target_history_updates=0,
        target_history_by_skill={"linear_isolation": 0})) == plan
    assert apply_trained_dkt(plan, _forecast(target_skill_ids=["signed_operations"],
        mapped_product_skills=["signed_operations"], target_history_by_skill={"signed_operations": 1})) == plan
    assert apply_trained_dkt(plan, _forecast(target_history_by_skill={"linear_isolation": 0, "signed_operations": 1})) == plan
    legacy = _forecast()
    for field in ("target_history_updates", "target_history_by_skill", "target_skill_ids"):
        legacy.pop(field)
    assert apply_trained_dkt(plan, legacy) == plan


def test_model_guidance_is_composed_with_verified_error_guidance_and_reaches_writer():
    plan = _plan(strategy="locate_verified_error", support_mode="scaffold",
                 student_guidance="这一步的移项没有保持等式相等。", reason_codes=("VERIFIED_ERROR",))
    guided = apply_trained_dkt(plan, _forecast())
    assert guided.strategy == "locate_verified_error"
    assert guided.student_guidance.startswith(plan.student_guidance)
    assert guided.model_guidance and guided.model_guidance in guided.student_guidance
    assert "DKT_UNSTEADY" in guided.reason_codes
    view = PublicProblemView(problem_type="linear", display_latex="7*x+2=30", teaching_plan=guided.public())
    prompt = _build_user_prompt(view, DisclosedSolutionContext(assistance_level=2),
                               TutorAction(action="ASK_STUDENT", effective_assistance_level=2))
    assert plan.student_guidance in prompt and guided.model_guidance in prompt


@pytest.mark.parametrize("changes,context,student_request", [
    ({"reason_codes": ("LANGUAGE_CONFUSION",)}, {}, ""),
    ({"reason_codes": ("VERIFIED_ERROR",)}, {}, ""),
    ({}, {"stuck_count": 1}, ""),
    ({}, {"help_without_progress": 2}, ""),
    ({"action": "EXPLAIN_CONCEPT"}, {}, ""),
    ({"action": "SHOW_EXAMPLE"}, {}, ""),
    ({"action": "GIVE_HINT"}, {}, ""),
    ({}, {}, "为什么这一步要除以系数？"),
    ({}, {}, "我还是不明白"),
    ({}, {}, "请给我完整解答"),
])
def test_high_source_probability_never_withdraws_requested_or_current_help(changes, context, student_request):
    plan = _plan(max_assistance_level=3, **changes)
    assert apply_trained_dkt(plan, _forecast(probability=0.9), context=context, student_request=student_request) == plan


def test_high_probability_at_zero_support_does_not_increase_help():
    result = apply_trained_dkt(_plan(max_assistance_level=0), _forecast(probability=0.9))
    assert result.max_assistance_level == 0


@pytest.mark.parametrize("action", ["EXPLAIN_CONCEPT", "SHOW_EXAMPLE", "GIVE_HINT"])
def test_low_probability_changes_granularity_but_retains_the_requested_material(action):
    plan = _plan(action=action, strategy="definition_to_problem", support_mode="explanation", max_assistance_level=1)
    result = apply_trained_dkt(plan, _forecast())
    assert (result.action, result.strategy, result.support_mode, result.max_assistance_level) == (
        plan.action, plan.strategy, plan.support_mode, plan.max_assistance_level)
    assert result.model_guidance and "保留学生请求" in result.model_guidance


def test_low_probability_does_not_replace_an_explanation_request_with_a_question():
    plan = _plan(max_assistance_level=1)
    result = apply_trained_dkt(plan, _forecast(), student_request="为什么等式两边可以同除以非零数？")
    assert (result.strategy, result.max_assistance_level) == (plan.strategy, plan.max_assistance_level)
    assert "保留学生请求的讲解" in result.model_guidance
