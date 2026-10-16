"""Pure teaching decisions over verified progress, not a hint-count curriculum.

The solution graph is a set of goals, not a mandatory reference step sequence.
An independently verified alternative step is progress; a full answer can jump
to completion. No self report or help delivery completes a goal.
"""
from __future__ import annotations

import re
from copy import deepcopy
from hashlib import sha256
from dataclasses import dataclass, asdict, replace

from mathtutor.learning.skill_graph import GRAPH_VERSION, SKILLS, skills_for_problem, skills_for_subgoal
from mathtutor.domain.dual_channel_gate import evidence_kind, math_state_from_correctness

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
    student_guidance: str = ""
    model_guidance: str = ""

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
    "linear_inequality": (("balance", "整理含未知数的项，并注意不等号方向"), ("isolate", "写出未知数的取值范围")),
    "quadratic_inequality": (("roots", "先求出对应方程的根"), ("sign", "根据开口方向和不等号写出解集")),
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
        "display_text": problem.display_latex, "problem_type": problem.problem_type, "skill_ids": list(skill_ids),
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
        "evidence_kind": evidence_kind(math_state_from_correctness(verdict),
                                       max_assistance_level=assistance.max_level_issued, diagnostic=diagnostic),
    }


def apply_assessment(context, assessment, raw_text, assistance):
    context = deepcopy(context)
    record = assessment_record(assessment, raw_text, assistance,
                               diagnostic=context.get("diagnostic_item", False))
    if context.get("problem_type") in {"linear_inequality", "quadratic_inequality"} and assessment.reason:
        # Inequality errors are about direction and boundaries; the verifier's
        # own reason is more precise than the generic signal guidance.
        record["verifier_reason"] = assessment.reason
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
            elif "equivalent_equation" in claims and _isolated_coefficient_step(context, raw_text):
                # Recognize a verified result such as 3z=15, regardless of the
                # student's chosen route. An unchanged restatement stays at
                # the earlier goal; equivalence alone does not prove progress.
                goals[0]["status"] = "verified"
                context["current_subgoal_index"] = min(1, len(goals) - 1)
    return context, record


def _isolated_coefficient_step(context, raw_text):
    if context.get("problem_type") != "linear":
        return False
    from mathtutor.solving.parser import parse_problem
    from mathtutor.solving import nodes as n
    parsed = parse_problem(raw_text)
    if parsed.kind != "parsed" or parsed.problem.problem_type != "linear":
        return False
    original = parse_problem(context.get("display_text", ""))
    if original.kind == "parsed" and original.problem.normalized_ast == parsed.problem.normalized_ast:
        return False
    equation = parsed.problem.ast
    variables = n.variables(equation)
    if len(variables) != 1:
        return False
    variable = next(iter(variables))
    left, right = n.poly_coeffs(equation.lhs, variable), n.poly_coeffs(equation.rhs, variable)
    if left is None or right is None:
        return False
    return bool((left.get(1) and not left.get(0) and not right.get(1))
                or (right.get(1) and not right.get(0) and not left.get(1)))


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
    guidance = ""
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
        codes = context["assessments"][-1].get("misconception_candidates", [])
        repeated = any(context.get("learner_evidence", {}).get("verified_error_counts", {}).get(code, 0) >= 2 for code in codes)
        guidance = error_guidance(codes, repeated=repeated)
        if repeated:
            reason.append("REPEATED_VERIFIED_ERROR")
            level = min(4, max(level, 2))
    elif any(context.get("learner_evidence", {}).get("verified_error_counts", {}).get(code, 0) >= 2
             for code in GUIDED_ERROR_CODES):
        strategy, mode = "repeated_error_step", "scaffold"
        reason.append("REPEATED_VERIFIED_ERROR")
        codes = [code for code, count in context["learner_evidence"]["verified_error_counts"].items() if count >= 2]
        guidance = error_guidance(codes, repeated=True)
        level = min(4, max(level, 2))
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
                        evidence_refs=tuple(dict.fromkeys([*(p["assessment_id"] for p in context["progress"][-3:]),
                                                         *context.get("learner_evidence", {}).get("evidence_ids", [])])),
                        student_guidance=guidance)
    if plan.fingerprint in context["help_fingerprints"] and action.action != "SHOW_SOLUTION":
        plan = TeachingPlan(**{**asdict(plan), "strategy": "offer_alternative", "support_mode": "choice",
                               "reason_codes": (*plan.reason_codes, "REPEATED_TEACHING_OPERATION"),
                               "exit_options": ("request_example", "request_solution", "request_practice", "end_problem")})
    plan = apply_trained_dkt(plan, context.get("dkt_forecast") or {},
                             context=context, student_request=student_request)
    context["last_plan"] = plan.public()
    return context, plan


_DKT_PHRASE = {
    "linear_isolation": "等式隔离这一步",
    "signed_operations": "符号运算这一步",
    "fraction_operations": "分数运算这一步",
    "distributive_law": "分配律这一步",
    "quadratic_roots": "求根这一步",
    "system_completeness": "方程组检验这一步",
}


def apply_trained_dkt(plan: TeachingPlan, forecast: dict, *, context=None, student_request="") -> TeachingPlan:
    """Let a mapped trained probability move the next step by one notch.

    Only with a product skill mapping and the student's own attempts (see
    ``dkt_policy``); a foreign prior alone changes nothing. Never print the number.
    """
    from mathtutor.pedagogy.dkt_policy import dkt_may_adjust, note_dkt
    from mathtutor.application.teaching_intent import explicit_solution_request, rule_teaching_intent
    if (plan.action == "SHOW_SOLUTION" or explicit_solution_request(student_request)
            or not dkt_may_adjust(forecast, skill_ids=plan.target_skill_ids)):
        return plan
    probability = forecast["probability"]
    from mathtutor.learning.knowledge_tracing.mapped_dkt import expand
    _sources, current, _unmapped = expand(plan.target_skill_ids)
    skills = [skill for skill in current if forecast["target_history_by_skill"].get(skill, 0) > 0]
    phrase = _DKT_PHRASE.get(skills[0], "这一步")

    def guidance(sentence):
        # A concrete misconception explanation remains first. The trained
        # support instruction is composed with it, not swallowed by ``or``.
        old = plan.student_guidance.strip()
        return old if sentence in old else (old.rstrip("。") + "。" if old else "") + sentence

    context = context or {}
    signal = rule_teaching_intent(student_request, context=context) if student_request else None
    protected_action = (plan.action in {"EXPLAIN_CONCEPT", "SHOW_EXAMPLE", "GIVE_HINT"}
                        or bool(signal and signal.intent in {"explanation", "example", "hint"}))
    if probability < 0.45:
        note_dkt("teaching", "more_support")
        sentence = (f"保留学生请求的讲解或示例，围绕{phrase}先解释一个关键联系，再衔接所需步骤。"
                    if protected_action else f"先只写{phrase}的一步，并说明这一步所用的条件，不用一次算完。")
        return replace(
            plan,
            strategy=plan.strategy if protected_action or plan.student_guidance else "smaller_step",
            support_mode=plan.support_mode if protected_action else "scaffold",
            max_assistance_level=(plan.max_assistance_level if protected_action or plan.max_assistance_level >= 2
                                  else plan.max_assistance_level + 1),
            student_guidance=guidance(sentence),
            model_guidance=sentence,
            reason_codes=(*plan.reason_codes, "DKT_UNSTEADY"),
        )
    if probability > 0.75:
        # A source-domain forecast cannot cancel a current request or stronger
        # direct evidence that the student needs help now.
        needs_help = (protected_action or context.get("stuck_count", 0) > 0
                      or context.get("help_without_progress", 0) >= 2
                      or bool(set(plan.reason_codes).intersection({
                          "LANGUAGE_CONFUSION", "REPEATED_EXPLICIT_STUCK", "HELP_WITHOUT_VERIFIED_PROGRESS",
                          "VERIFIED_ERROR", "REPEATED_VERIFIED_ERROR", "REPEATED_INDEPENDENT_DIFFICULTY"}))
                      or bool(signal and (signal.confusion != "none" or signal.intent in {"explanation", "example", "hint"})))
        if needs_help:
            return plan
        note_dkt("teaching", "less_support")
        sentence = f"让学生自主写出{phrase}的下一步及理由，再核对；保留求助入口，不追加未请求的整题解答。"
        return replace(
            plan,
            max_assistance_level=max(0, plan.max_assistance_level - 1),
            student_guidance=guidance(sentence),
            model_guidance=sentence,
            reason_codes=(*plan.reason_codes, "DKT_STEADY"),
        )
    sentence = (f"保留所请求的提示、解释或示例，先围绕{phrase}核对一个关键联系。"
                if protected_action else f"先围绕{phrase}核对当前一步，再决定是否增加帮助。")
    return replace(plan, student_guidance=guidance(sentence), model_guidance=sentence,
                   reason_codes=(*plan.reason_codes, "DKT_GUIDE"))


def assessment_feedback(record):
    raw = record["raw_text"]
    if record["task_completion"] == "complete":
        return f"已验证你提交的「{raw}」满足这道题的完整要求。"
    if record["math_validity"] == "valid":
        return f"已验证「{raw}」是有效的部分结果；整题还没有完成，请继续补齐剩余要求。"
    if record["math_validity"] == "invalid":
        guidance = record.get("verifier_reason") or error_guidance(record.get("misconception_candidates", []))
        return f"你提交的「{raw}」未通过原题检验。" + (guidance or "先把你刚才的运算写成一步，我来检查。")
    return "这次作答暂时无法可靠判定，不会记作答错。请补充这一步的等式或说明要检验的结论。"


def public_context(context):
    result = {key: deepcopy(context[key]) for key in ("problem_id", "display_text", "skill_ids", "lifecycle")} | {"current_subgoal": current_subgoal(context), "choices": deepcopy(context.get("choices"))}
    if context.get("understanding_check"):
        result["understanding_check"] = True
    return result


_ERROR_GUIDANCE = (
    ("wrong_operation", "前面不同题目的移项或常数处理还不稳定。", "这一步的移项或常数处理没有保持等式相等。",
     "先写出等式两边同时做的运算。"),
    ("sign_flip", "前面不同题目的结果符号还不稳定。", "这个结果的符号没有通过原题检验。", "先把带符号的运算单独写成一步。"),
    ("missing_root", "前面不同题目都出现了漏解。", "这个答案还缺少满足原题的解。", "先确认一共应有几个解，再逐个求出。"),
    ("extraneous_root", "前面不同题目都混入了不满足原题的解。", "这个答案里有不满足原题的解。", "先把每个解代回原式检验。"),
)
GUIDED_ERROR_CODES = tuple(code for code, *_ in _ERROR_GUIDANCE)


def error_guidance(codes, *, repeated=False):
    """State only the verifier's coarse error class; never invent a cause."""
    for code, repeated_text, single_text, step in _ERROR_GUIDANCE:
        if code in codes:
            return (repeated_text if repeated else single_text) + step
    return ""


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
        "arithmetic": "先写出最先要做的一个运算。",
        "polynomial": "找出能合并的一组同类项；它们的字母和次数分别是什么？",
        "linear": "先指出要消去哪个常数项，再写出等式两边同时做的运算。",
        "linear_inequality": "先整理含未知数的项，再写明不等号的方向。",
        "quadratic_inequality": "先把不等号换成等号，求出对应方程的根，再看抛物线开口方向。",
        "quadratic": "你准备先用哪一种方法：因式分解还是求根公式？",
        "linear_system": "先选一个要消去的未知数。",
    }.get(problem_view.problem_type, "指出已知条件和要证明或计算的结论。")
    if plan.get("strategy") == "compare_methods":
        operation = "你已经在不同题目中提供过独立作答证据。这次先比较两种可行方法，你会选哪一种？"
    elif plan.get("strategy") == "prerequisite_check":
        operation = "先检查这一步依赖的基础运算：" + operation
    if plan.get("strategy") == "smaller_step":
        operation = "先不用算完整答案：" + operation
    if plan.get("student_guidance"):
        operation = plan["student_guidance"]
    return prefix + (disclosure.concept_hint or disclosure.strategy_hint or "") + "。" + operation
