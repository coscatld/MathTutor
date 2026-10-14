"""The uncalibrated legacy mastery estimate never reaches generation."""
from mathtutor.application.adaptive_practice import _build_statement
from mathtutor.application.llm_candidate_generator import build_llm_prompt
from mathtutor.domain.practice_context import PracticeGenerationContext


def context(**overrides):
    fields = PracticeGenerationContext.model_fields
    base = {"student_id": "00000000-0000-0000-0000-000000000001", "target_skill_ids": ("linear_transpose",), "desired_difficulty": 2}
    data = {key: value for key, value in base.items() if key in fields}
    return PracticeGenerationContext.model_validate({**data, **overrides})


def test_prompt_and_template_statement_carry_no_mastery_number():
    raw = {"current_mastery": [{"skill_id": "linear_transpose", "mastery": 0.123}],
           "recent_attempt_summary": [{"skill_id": "linear_transpose", "correctness": "incorrect",
                                       "effective_assistance_level": 0, "attempt_index": 1}]}
    ctx = context(**raw)
    prompt = build_llm_prompt(ctx)
    assert "mastery" not in prompt and "0.123" not in prompt
    statement = _build_statement(ctx, 0)
    assert "掌握度" not in statement and "0.12" not in statement
    assert "出错最多的技能是 linear_transpose（1 次）" in statement
