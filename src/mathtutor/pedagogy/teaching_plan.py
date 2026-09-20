"""Pure teaching decisions over verified progress, not a hint-count curriculum.

The solution graph is a set of goals, not a mandatory reference step sequence.
An independently verified alternative step is progress; a full answer can jump
to completion. No self report or help delivery completes a goal.
"""
from __future__ import annotations

import re
from copy import deepcopy
from hashlib import sha256
from dataclasses import dataclass, asdict

from mathtutor.learning.skill_graph import GRAPH_VERSION, SKILLS, skills_for_problem, skills_for_subgoal

_STUCK = re.compile(r"不会|没懂|不懂|不明白|看不懂|还是不|没思路|卡住")


@dataclass(frozen=True)
class TeachingPlan:
    action: str
    strategy: str
    question_goal: str
    target_subgoal_id: str
    target_skill_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    support_mode: str
    exit_options: tuple[str, ...]
    response_kind: str = "question"
    max_assistance_level: int = 1
    allow_target_answer: bool = False
    expected_response: str = "写出你能确定的一步，或说明卡在哪里"
    material_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    def public(self):
        return asdict(self)

    @property
    def fingerprint(self):
        # A paraphrase does not count as another instructional operation.
        return sha256(repr((self.target_subgoal_id, self.strategy,
                            self.material_refs, self.support_mode)).encode()).hexdigest()


_GOALS = {
    "arithmetic": (("plan", "选择运算顺序或共同分母"), ("answer", "算出结果并检查符号")),
    "polynomial": (("expand", "先检查括号与分配律"), ("combine", "辨认并合并同类项")),
    "linear": (("balance", "保持等式两边相等，整理含未知数的项"), ("isolate", "得到未知数的值并代回原式")),
    "quadratic": (("method", "选择分解或求根方法"), ("roots", "找齐所有实数根并排除增根")),
    "linear_system": (("eliminate", "选择代入或消元，先求一个未知数"), ("remaining", "再求另一未知数并检验两条原式")),
}


def initial_context(problem, candidate, *, legacy_help=False, verified_solution_ref=None, cycle_id=None):
    from mathtutor.application.problem_context import build_problem_context
    skill_ids = skills_for_problem(problem)
    goals = _GOALS.get(problem.problem_type, (("reason", "说明题目条件和要解决的问题"),))
    return {
        "schema_version": "mt-teaching-v2", "skill_graph_version": GRAPH_VERSION,
        "problem_id": str(problem.problem_id), "problem_revision": problem.content_hash,
        "display_text": problem.display_latex, "skill_ids": list(skill_ids),
        "task_context": build_problem_context(problem, candidate, cycle_id=cycle_id, verified_solution_ref=verified_solution_ref),
        "lifecycle": "active", "current_subgoal_index": 0,
        "subgoals": [{"id": key, "prompt_target": label, "status": "pending",
                      "skill_ids": list(skills_for_subgoal(problem, key, candidate))} for key, label in goals],
        "progress": [], "assessments": [], "stuck_count": 0, "help_without_progress": 0,
        "help_fingerprints": [], "last_plan": None, "deliveries": [],
        "legacy_provenance_uncertain": legacy_help, "diagnosis": {"status": "not_started", "can_skip": True, "question_count": 0},
    }


def current_subgoal(context):
    goals = context.get("subgoals") or []
    index = min(context.get("current_subgoal_index", 0), len(goals) - 1)
    return goals[index] if goals else {"id": "reason", "prompt_target": "说明要解决的问题", "status": "pending"}


def assessment_record(assessment, raw_text, assistance, *, diagnostic=False):
    verdict = assessment.correctness.value
    complete = verdict == "correct"
    return {
        "assessment_id": str(assessment.attempt_id), "raw_text": raw_text,
        "assessment_scope": "full_problem" if complete else "subgoal" if verdict == "partial" else "attempt",
        "math_validity": "valid" if verdict in {"correct", "partial"} else "invalid" if verdict == "incorrect" else "unknown",
        "task_completion": "complete" if complete else "incomplete" if verdict != "undetermined" else "unknown",
        "verified_steps": list(assessment.verified_claims), "invalid_claims": list(assessment.invalid_claims),
        "remaining_requirements": list(assessment.remaining_requirements),
        "misconception_candidates": list(assessment.signals),
        "help_before_attempt": assistance.max_level_issued,
        "evidence_kind": "diagnostic" if diagnostic else "ungradable" if verdict == "undetermined" else "post_solution" if assistance.max_level_issued >= 5 else "assisted" if assistance.max_level_issued else "independent",
    }


def apply_assessment(context, assessment, raw_text, assistance):
    context = deepcopy(context)
    record = assessment_record(assessment, raw_text, assistance,
                               diagnostic=context.get("diagnostic_item", False))
    context["assessments"].append(record)
    if record["math_validity"] == "valid":
        context["progress"].append({"assessment_id": record["assessment_id"], "text": raw_text,
                                    "verified_claims": record["verified_steps"]})
        context["stuck_count"] = 0
        context["help_without_progress"] = 0
        goals = context["subgoals"]
        if record["task_completion"] == "complete":
            for goal in goals:
                goal["status"] = "verified"
            context["current_subgoal_index"] = len(goals) - 1
            context["lifecycle"] = "completed"
        else:
            # A restatement is mathematically valid but not a new completed goal.
            claims = {c.get("claim") for c in record["verified_steps"]}
            # An equivalent restatement, including +0 or another valid route,
            # remains evidence without pretending it completed a named goal.
            if claims & {"variable_value", "root_subset"}:
                goals[0]["status"] = "verified_partial"
                context["current_subgoal_index"] = min(1, len(goals) - 1)
    return context, record


def choose_plan(context, action, student_request=""):
    context = deepcopy(context)
    from mathtutor.application.teaching_intent import rule_teaching_intent
    from mathtutor.domain.hashing import content_hash
    signal = context.get("language_understanding", {})
    signal_matches = bool(student_request) and context.get("language_input_hash") == content_hash({"text": student_request})
    if not signal_matches:
        signal = rule_teaching_intent(student_request, context=context).model_dump() if student_request else {}
    request_key = context.get("language_request_id") if signal_matches else None
    apply_signal = not request_key or context.get("language_signal_consumed_request") != request_key
    if apply_signal and signal.get("scope") in {"current_goal", "current_problem", "same_skill"}:
        if signal.get("resolved"):
            context["stuck_count"] = 0  # reported confidence, never task completion
        elif signal.get("confusion", "none") != "none":
            context["stuck_count"] += 1
            if signal["confusion"] == "persistent":
                context["stuck_count"] = max(2, context["stuck_count"])
        if request_key:
            context["language_signal_consumed_request"] = request_key
    goal = current_subgoal(context)
    stuck = context["stuck_count"]
    no_progress = context["help_without_progress"]
    strategy, mode, reason = "focused_question", "guided", ["CURRENT_SUBGOAL"]
    if signal.get("confusion", "none") != "none":
        reason.append("LANGUAGE_CONFUSION")
        if signal.get("source") == "llm":
            reason.append("SEMANTIC_INTENT")
    level = action.effective_assistance_level
    if action.action == "SHOW_SOLUTION":
        strategy, mode = "worked_solution", "demonstration"
        reason.append("EXPLICIT_SOLUTION_REQUEST")
    elif action.action == "SHOW_EXAMPLE":
        strategy, mode = "verified_analogy", "demonstration"
    elif stuck >= 2:
        strategy, mode = "smaller_step", "scaffold"
        reason.append("REPEATED_EXPLICIT_STUCK")
        level = min(4, max(level, 3))
    elif no_progress >= 2:
        strategy, mode = "worked_prefix", "demonstration"
        reason.append("HELP_WITHOUT_VERIFIED_PROGRESS")
        level = min(4, max(level, 3))
    elif action.action == "EXPLAIN_CONCEPT":
        strategy, mode = "definition_to_problem", "explanation"
    elif context["assessments"] and context["assessments"][-1]["invalid_claims"]:
        strategy, mode = "locate_verified_error", "scaffold"
        reason.append("VERIFIED_ERROR")
    elif context.get("learner_evidence", {}).get("independent_correct_items", 0) >= 3:
        strategy, mode = "compare_methods", "light_scaffold"
        reason.append("MULTIPLE_INDEPENDENT_ITEMS")
        level = min(level, 2)
    elif context.get("learner_evidence", {}).get("independent_incorrect_items", 0) >= 2:
        strategy, mode = "prerequisite_check", "scaffold"
        reason.append("REPEATED_INDEPENDENT_DIFFICULTY")
    exits = ("request_example", "request_solution", "request_practice", "end_problem") if stuck >= 2 or no_progress >= 2 else ("request_solution", "end_problem")
    plan = TeachingPlan(action.action, strategy, goal["prompt_target"], goal["id"],
                        tuple(goal.get("skill_ids") or context["skill_ids"]), tuple(reason), mode, exits,
                        "demonstration" if mode == "demonstration" else "question",
                        level, action.action == "SHOW_SOLUTION",
                        evidence_refs=tuple(p["assessment_id"] for p in context["progress"][-3:]))
    if plan.fingerprint in context["help_fingerprints"] and action.action != "SHOW_SOLUTION":
        plan = TeachingPlan(**{**asdict(plan), "strategy": "offer_alternative", "support_mode": "choice",
                               "reason_codes": (*plan.reason_codes, "REPEATED_TEACHING_OPERATION"),
                               "exit_options": ("request_example", "request_solution", "request_practice", "end_problem")})
    context["last_plan"] = plan.public()
    return context, plan


def assessment_feedback(record):
    raw = record["raw_text"]
    if record["task_completion"] == "complete":
        return f"已验证你提交的「{raw}」满足这道题的完整要求。"
    if record["math_validity"] == "valid":
        return f"已验证「{raw}」是有效的部分结果；整题还没有完成，请继续补齐剩余要求。"
    if record["math_validity"] == "invalid":
        return f"你提交的「{raw}」未通过原题检验。请检查这一步的运算，或选择演示一个例子。"
    return "这次作答暂时无法可靠判定，不会记作答错。请补充这一步的等式或说明要检验的结论。"


def public_context(context):
    return {key: deepcopy(context[key]) for key in ("problem_id", "display_text", "skill_ids", "lifecycle")} | {"current_subgoal": current_subgoal(context), "choices": deepcopy(context.get("choices"))}


def grounded_template(problem_view, disclosure, action):
    """Every fallback binds an answerable operation to the current problem."""
    from mathtutor.pedagogy.disclosure import _display_step
    plan = problem_view.teaching_plan or {}
    prefix = f"仍看这道题：\\( {problem_view.display_latex} \\)。"
    if plan.get("support_mode") == "choice":
        return prefix + "刚才的帮助还没有推进到可验证的一步。你可以看一个示例、查看完整解析、做一道基础练习，或先暂停；你想选哪一种？"
    if action.action == "SHOW_EXAMPLE" and problem_view.approved_example:
        example = problem_view.approved_example
        if example.get("kind") == "teacher_error_example":
            return f"{example['instruction']}\n示例题：\\( {example['problem']} \\)\n教师故意写错的步骤：\\( {example['wrong_step']} \\)\n请写出你认为正确的这一步等式。"
        return f"方法示例（不是你这道题的答案）：\\( {example['problem']} \\)。\n{example['solution']}\n" + prefix + "比较两题中需要保持不变的条件，再写你的一步。"
    steps = list(disclosure.approved_prefix) or ([disclosure.approved_step] if disclosure.approved_step else [])
    if steps:
        import re
        variable = next(iter(re.findall(r"[a-zA-Z]", problem_view.display_latex)), "x")
        rendered = [_display_step(dict(s), i + 1, variable) for i, s in enumerate(steps)]
        body = "\n".join(s["display_text"] + (f"：\\( {s['display_latex']} \\)" if s["display_latex"] else "") for s in rendered)
        return prefix + "下面演示已验证的一小段：\n" + body + "\n请接着完成剩余要求，或说出这一步仍不清楚的地方。"
    operation = {
        "arithmetic": "先指出要先做哪一个运算；有分数时，哪些分母需要统一？",
        "polynomial": "找出能合并的一组同类项；它们的字母和次数分别是什么？",
        "linear": "先指出要消去哪个常数项，再写出等式两边同时做的运算。",
        "quadratic": "先指出二次项、一次项和常数项；你打算因式分解还是用求根公式？",
        "linear_system": "先选要消去的未知数；两条等式的哪个系数可以对齐？",
    }.get(problem_view.problem_type, "指出已知条件和要证明或计算的结论。")
    if plan.get("strategy") == "compare_methods":
        operation = "你已经在不同题目中提供过独立作答证据。这次先比较两种可行方法：你会选哪一种，为什么？"
    elif plan.get("strategy") == "prerequisite_check":
        operation = "先检查这一步依赖的基础运算：" + operation
    if plan.get("strategy") == "smaller_step":
        operation = "先不用算完整答案：" + operation
    return prefix + (disclosure.concept_hint or disclosure.strategy_hint or "") + "。" + operation
