"""The trained forecast may change the next sentence and one difficulty step."""
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
                  mapped_product_skills=["linear_isolation"], learning_effect_verified=False)
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
