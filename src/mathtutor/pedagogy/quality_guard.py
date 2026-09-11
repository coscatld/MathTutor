"""Bounded teaching quality guard over the disclosed material.

No verifier verdict is delegated to a model. Unsafe/unbound prose falls back
once to an answerable, problem-specific template, before any bytes are sent.
"""
import re
from mathtutor.pedagogy.tutor_writer import TemplateTutorWriter

_UNSUPPORTED_PRAISE = re.compile(r"已经掌握|完全理解|你.*(?:[步写做算答].*(?:对|正确|不错)|会了|懂了)|做得很棒|回答正确|答对了|思路正确")


async def enforce_teaching_quality(utterance, raw, view, disclosure, action, policy):
    fallback = await TemplateTutorWriter().write(problem_view=view, disclosure=disclosure,
                                                policy=policy, action=action)
    reason = None
    if _UNSUPPORTED_PRAISE.search(raw.text):
        reason = "unsupported_student_claim"
    elif not raw.text.strip():
        reason = "empty_response"
    elif view.teaching_plan.get("support_mode") == "choice":
        reason = "stagnation_choice"
    elif action.action in {"SHOW_EXAMPLE", "SHOW_SOLUTION"} or disclosure.approved_step or disclosure.approved_prefix:
        # Render approved mathematical material exactly. Arbitrary LLM-added
        # equations are not independently verified simply because L5 is allowed.
        reason = "verified_material_rendering"
    elif not any(token in raw.text for token in ("等式", "分母", "同类项", "方程", "系数", "运算", "判别", "根", "消元", "条件")):
        reason = "no_answerable_bound_operation"
    elif utterance.fallback_used:
        reason = "disclosure_fallback"
    else:
        from mathtutor.pedagogy.guard_math import extract_math_fragments, parse_fragment
        from mathtutor.solving import nodes as n
        from mathtutor.solving.parser import parse_problem
        source = parse_problem(view.display_latex)
        source_ast = source.problem.normalized_ast if source.problem else None
        # A topic keyword is not evidence for a newly invented equation.
        for fragment in extract_math_fragments(raw.text):
            parsed = parse_fragment(fragment)
            if parsed is not None and isinstance(parsed.ast, n.Equation) and parsed.normalized_ast != source_ast:
                reason = "unverified_writer_equation"
                break
    if reason:
        updates = {"text": fallback.text, "fallback_used": True, "leak": reason}
        if reason == "stagnation_choice":
            updates.update(action="ASK_STUDENT", assistance_level=0)
        from mathtutor.application.tutor_runtime import current_turn
        from mathtutor.domain.turn_result import FinishReason
        turn = current_turn.get()
        if turn is not None:
            # A complete approved template is a complete response even if the
            # discarded model draft ended at a token boundary.
            turn.stop(FinishReason.FINAL_ANSWER, fallback.text)
        return utterance.model_copy(update=updates)
    return utterance
