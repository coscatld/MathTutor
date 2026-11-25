"""Describe verified responses and propose an unseen exercise for the observed difficulty."""
from functools import lru_cache

from mathtutor.application.llm_candidate_generator import candidate_problem_revision
from mathtutor.learning.knowledge_tracing.events import has_verified_outcome


# Each label describes something visible in the response. Exercises have no embedded answer.
EXERCISES = {
    "sign": ("(-8)-(-3)", "(-5)-(7)", "(6)-(-9)", "(-12)-(-2)"),
    "fraction": ("2/7+1/3", "3/5+1/4", "1/8+2/3", "3/7+1/5"),
    "arithmetic": ("(8-3)*4", "18-2*5", "(9+7)/4", "15-3*(2+1)"),
    "constant": ("3x-4=11", "5x+2=17", "4x-7=9", "2x+8=20"),
    "terms": ("5x-2x+4=16", "6x+2x-1=23", "7x-3x+5=25", "3x+2x-4=16"),
    "roots": ("x^2-7x+12=0", "x^2-9x+20=0", "x^2-5x-6=0", "x^2-2x-15=0"),
    "system": ("x+y=8;x-y=2", "x+y=7;x-y=3", "x+y=9;x-y=1", "x+y=13;x-y=5"),
    "interval": ("-2x+3<9", "3x-4>=8", "-3x+5<=11", "2x+7>15"),
    "quadratic_interval": ("x^2-4<0", "x^2-9>=0", "x^2-16<=0", "x^2-25>0"),
    "polynomial": ("3(x+2)-2x", "2(x-5)+3x", "4(x+1)-x", "2(x+3)+5x"),
}


@lru_cache(maxsize=len(EXERCISES))
def _candidates(focus):
    return tuple((text, candidate_problem_revision(text)) for text in EXERCISES[focus])


def _focus(event):
    family = event.item_family_id
    signals = set(event.misconception_codes)
    if not signals or signals == {"equivalent_equation"}:
        return None
    if family.endswith("inequality") and signals & {"wrong_value", "missing_root", "sign_flip"}:
        return "conditions", "interval", "quadratic_interval" if family == "quadratic_inequality" else "interval"
    if "missing_variable" in signals or (family == "linear_system" and signals & {"wrong_value", "conflicting_claims"}):
        return "conditions", "missing_variable" if "missing_variable" in signals else "system_check", "system"
    if signals & {"missing_root", "extraneous_root"}:
        return "conditions", "missing_root" if "missing_root" in signals else "extraneous_root", "roots"
    if "like_terms" in signals:
        return "calculation", "terms", "terms"
    if "wrong_operation" in signals:
        return "calculation", "constant", "constant"
    if "sign_flip" in signals:
        return "calculation", "sign", "sign"
    if family == "arithmetic" and "wrong_value" in signals:
        return "calculation", "value", "fraction" if "fraction_operations" in event.skill_ids else "arithmetic"
    if family == "polynomial":
        return "conditions", "expression", "polynomial"
    if family in {"linear", "quadratic", "linear_system"}:
        focus = {"linear": "constant", "quadratic": "roots", "linear_system": "system"}[family]
        return "conditions", "answer_form" if "wrong_family" in signals else "substitution", focus
    return None


def observed_errors(events, raw_history):
    # Excluding a verdict never makes a problem that the learner has seen fresh.
    seen = {event.problem_revision for event in raw_history}
    corrected, rows = set(), []
    for event in reversed(events):
        if not has_verified_outcome(event):
            continue
        if event.correctness == "correct":
            if event.completion_scope == "full_problem" and event.response_format == "free_response":
                corrected.add(event.problem_revision)
            continue
        details = _focus(event)
        if details is None:
            continue
        category, reason, focus = details
        if event.task_purpose == "transfer":
            category = "method_transfer"
        if event.target_answer_exposed_before_attempt or event.evidence_kind == "post_solution":
            mode = "post_solution"
        elif event.prior_help_event_ids or event.evidence_kind == "assisted":
            mode = "assisted"
        elif event.response_format == "single_choice" or event.options_exposed:
            mode = "choice"
        else:
            mode = "repeat" if event.prior_task_attempt else "independent"
        exercise = next((text for text, revision in _candidates(focus) if revision and revision not in seen), None)
        rows.append({
            "event_id": event.event_id, "cycle_id": event.cycle_id, "occurred_at": event.occurred_at,
            "category": category, "reason": reason, "mode": mode,
            "corrected_later": event.problem_revision in corrected, "next_problem": exercise,
        })
        if len(rows) == 8:
            break
    return rows
