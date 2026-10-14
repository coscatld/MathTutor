"""Public item evidence counts; no internal prior is displayed as mastery."""
from mathtutor.learning.knowledge_tracing.events import valid_events


def public_evidence(events):
    counts = {"independent": 0, "assisted": 0, "post_solution": 0, "diagnostic": 0, "ungradable": 0}
    for event in valid_events(events):
        if event.event_type != "attempt_assessed" or getattr(event, "duplicate_response", False):
            continue
        if event.task_purpose in {"diagnostic", "error_analysis"}:
            key = "diagnostic"
        elif event.correctness in {None, "unknown"} or event.provenance_uncertain or event.evidence_kind == "unknown":
            key = "ungradable"
        elif event.completion_scope != "full_problem" or event.correctness == "partial":
            key = "diagnostic"
        else:
            key = event.evidence_kind
        if key == "independent" and event.prior_task_attempt:
            continue
        counts[key if key in counts else "ungradable"] += 1
    counts["status"] = "已有独立作答记录，仍需跨题验证" if counts["independent"] else "已看过解答，需换题独立检测" if counts["post_solution"] else "尚无整题独立作答证据"
    return counts


def teaching_evidence(events, skills):
    rows = [e for e in valid_events(events) if set(e.skill_ids) & set(skills)]
    independent = {e.problem_revision for e in rows if e.independent_target and e.correctness == "correct"}
    errors = {e.problem_revision for e in rows if e.independent_target and e.correctness == "incorrect"}
    # Count distinct first, independently attempted items, not retries, help,
    # self reports or an unverified explanation. A signal is an observed error
    # class; it does not establish the student's private reasoning.
    error_items = {}
    for event in rows:
        if event.independent_target and event.correctness == "incorrect":
            for code in event.misconception_codes:
                error_items.setdefault(code, set()).add(event.problem_revision)
    return {"independent_correct_items": len(independent), "independent_incorrect_items": len(errors),
            "verified_error_counts": {code: len(items) for code, items in error_items.items()},
            "evidence_ids": [e.assessment_id for e in rows if e.independent_target][-8:]}


def prerequisite_gap(context):
    """Only verified local signals (or a failed prerequisite diagnostic) qualify."""
    records = context.get("assessments", [])
    if records:
        signals = set(records[-1].get("misconception_candidates", []))
        if "sign_flip" in signals:
            return ("ARITHMETIC",)
        if "wrong_operation" in signals:
            return ("LINEAR_EQUATION",)
    for item in context.get("diagnosis", {}).get("results", []):
        if item["correctness"] == "incorrect" and set(item["skill_ids"]) & {"signed_operations", "fraction_operations"}:
            return ("ARITHMETIC",)
        if item["correctness"] == "incorrect" and set(item["skill_ids"]) & {"distributive_law", "combine_like_terms"}:
            return ("POLYNOMIAL_BASIC",)
    return ()


#: Verified error signal → (problem family → practice skill, guidance).
#: Ordered like the diagnosis rules: the first matching signal wins.
ERROR_PRACTICE = (
    ("sign_flip", {"arithmetic": "signed_operations", "linear": "signed_operations",
                   "linear_inequality": "signed_operations", "polynomial": "signed_operations"},
     "这次先练带符号的运算，检查结果的正负号。"),
    ("missing_root", {"quadratic": "quadratic_roots", "linear_system": "system_completeness"},
     "这次先练把所有解都求出来，最后逐个代回检查有没有漏掉。"),
    ("extraneous_root", {"quadratic": "substitution_check"},
     "这次先练把求出的解代回原式检验，去掉不满足的解。"),
    ("wrong_operation", {"linear": "equality_preservation", "linear_inequality": "equality_preservation",
                         "linear_system": "system_elimination", "polynomial": "combine_like_terms"},
     "这次先练等式两边同做运算，检查移项和常数处理。"),
    ("wrong_value", {"arithmetic": "signed_operations", "linear": "linear_isolation",
                     "polynomial": "combine_like_terms", "quadratic": "quadratic_roots",
                     "linear_system": "system_completeness"},
     "这次先练一步一步写出计算过程，每一步都能检查。"),
)
PRACTICE_ERROR_CODES = frozenset(code for code, _, _ in ERROR_PRACTICE)


def teaching_practice_focus(context):
    """Only independently verified error classes can constrain a new item."""
    counts = context.get("learner_evidence", {}).get("verified_error_counts", {})
    codes = {code for code, count in counts.items() if count >= 2}
    records = context.get("assessments", [])
    if records and records[-1].get("math_validity") == "invalid":
        codes.update(records[-1].get("misconception_candidates", []))
    family = context.get("problem_type")
    for code, skills, guidance in ERROR_PRACTICE:
        if code in codes and family in skills:
            return skills[family], guidance
    return "", ""


def review_due(events, skills, *, now=None):
    from datetime import datetime, timezone, timedelta
    now = now or datetime.now(timezone.utc)
    correct = [e for e in valid_events(events) if e.independent_target and e.correctness == "correct"
               and set(e.skill_ids) & set(skills)]
    if not correct:
        return False
    last = max(datetime.fromisoformat(e.occurred_at.replace("Z", "+00:00")) for e in correct)
    return now - last >= timedelta(days=3)
