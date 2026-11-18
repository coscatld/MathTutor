"""Learning actions reuse assessed evidence; resources never establish mastery."""
from __future__ import annotations

import hashlib
import json
import re
from importlib.resources import files

from mathtutor.application.exploration_evidence import safe_source_url
from mathtutor.application.learning_profile import profile_projection
from mathtutor.learning.knowledge_tracing.events import (
    attributed_skill_ids, has_verified_outcome, independent_skill_success_ids, valid_events,
)
from mathtutor.learning.skill_graph import GRAPH_VERSION, SKILLS

POLICY = "learning-actions-v3"
GOALS = {
    "math_foundations": ("数学基础", "Mathematical foundations", ("signed_operations", "fraction_operations", "linear_isolation")),
    "calculus": ("微积分", "Calculus", ("functions", "limits")),
    "linear_algebra": ("线性代数", "Linear algebra", ("system_elimination", "vectors")),
    "probability": ("概率与统计", "Probability and statistics", ("fraction_operations", "functions")),
    "machine_learning": ("机器学习", "Machine learning", ("linear_algebra", "calculus", "probability")),
    "algorithms": ("算法与数据结构", "Algorithms and data structures", ("algebra", "logic")),
    "research_methods": ("科研与论文阅读", "Research and paper reading", ()),
}
_EN_SKILLS = {
    "signed_operations": "Signed arithmetic", "fraction_operations": "Fractions",
    "distributive_law": "The distributive law", "combine_like_terms": "Combining like terms",
    "equality_preservation": "Preserving equality", "linear_isolation": "Linear equations",
    "substitution_check": "Checking by substitution", "factorisation": "Factorisation",
    "quadratic_discriminant": "The quadratic discriminant", "quadratic_roots": "Quadratic roots",
    "system_elimination": "Elimination", "system_substitution": "Substitution",
    "system_completeness": "Checking systems of equations",
}


def goal_label(goal, language="zh"):
    if goal in SKILLS:
        return _EN_SKILLS[goal] if language == "en" else SKILLS[goal].label
    return GOALS[goal][language == "en"]


def validate_goal(goal):
    if goal not in GOALS and goal not in SKILLS:
        raise ValueError("Unknown learning goal")
    return goal


def goal_options(language="zh"):
    return [{"id": key, "label": goal_label(key, language)} for key in (*GOALS, *SKILLS)]


def load_catalog(path=None):
    resource = path or files("mathtutor").joinpath("community_assets/zhihu_catalog.json")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("version"), str) or not isinstance(value.get("resources"), list):
        raise ValueError("Invalid reviewed resource catalog")
    ids, urls = set(), set()
    for row in value["resources"]:
        if not isinstance(row, dict) or row.get("review", {}).get("status") != "accepted":
            raise ValueError("Catalog entries must have an accepted review")
        for key in ("resource_id", "title", "summary", "recommendation_reason"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError("Missing reviewed resource field: " + key)
        if not safe_source_url(row.get("url")) or not row.get("knowledge_points"):
            raise ValueError("Resource needs a safe original URL and knowledge points")
        for key in ("knowledge_points", "prerequisites", "tags"):
            if not isinstance(row.get(key), list) or not all(isinstance(x, str) for x in row[key]):
                raise ValueError("Invalid resource tags")
        proof = row.get("provenance", {})
        excerpt = proof.get("excerpt")
        if (not isinstance(excerpt, str) or not excerpt.strip() or
                hashlib.sha256(excerpt.encode()).hexdigest() != proof.get("excerpt_sha256") or
                not proof.get("retrieved_at") or row["review"].get("scope") != "search_excerpt"):
            raise ValueError("Resource review lacks a verifiable excerpt")
        gates = row["review"].get("gates", {})
        if len(gates) < 6 or any(v not in ("pass", "not_applicable") for v in gates.values()):
            raise ValueError("Resource has not passed all admission gates")
        canonical = row["url"].split("?")[0].rstrip("/")
        if row["resource_id"] in ids or canonical in urls:
            raise ValueError("Duplicate reviewed resource")
        ids.add(row["resource_id"])
        urls.add(canonical)
    return value


def profile_revision(history):
    # Includes invalidations and provenance corrections, without storing answers.
    return hashlib.sha256(json.dumps([event.model_dump(mode="json") for event in history],
        ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _observations(history):
    observations = {}
    for event in valid_events(history):
        if event.duplicate_response or not has_verified_outcome(event):
            continue
        successes = independent_skill_success_ids(event)
        for skill in attributed_skill_ids(event):
            if skill not in SKILLS:
                continue
            state = None
            if skill in successes:
                state = "independent_success"
            elif event.independent_target and event.correctness == "incorrect":
                state = "independent_difficulty"
            elif event.evidence_kind in ("assisted", "post_solution"):
                state = "assisted_observation"
            if state:
                previous = observations.get(skill)
                # Assistance cannot erase an independently observed difficulty.
                if state == "assisted_observation" and previous and previous["state"].startswith("independent_"):
                    continue
                observations[skill] = {"state": state, "event_id": event.event_id, "event_seq": event.event_seq}
    return observations


def _prerequisites(skill):
    result = []
    def visit(key):
        for prerequisite in SKILLS[key].prerequisites:
            if prerequisite not in result:
                visit(prerequisite)
                result.append(prerequisite)
    visit(skill)
    return result


def requested_goal(request):
    """Current positive topic requests outrank old goals; a self-report is not mastery."""
    aliases = {key: (names[0], names[1], key.replace("_", " ")) for key, names in GOALS.items()}
    aliases.update({key: (skill.label, _EN_SKILLS[key], *skill.aliases) for key, skill in SKILLS.items()})
    aliases["calculus"] += ("导数", "极限", "derivative", "limits")
    aliases["probability"] += ("概率", "统计", "贝叶斯")
    aliases["algorithms"] += ("算法", "数据结构")
    aliases["research_methods"] += ("论文阅读", "读论文", "科研方法", "reading papers")
    candidates = []
    generic = {"符号", "两边", "平衡", "系数", "隔离", "代入", "检验", "验算", "成立", "合并", "展开"}
    for clause in re.split(r"[，,。；;\n]|但是|但|而是|\bbut\b", request[:2000], flags=re.I):
        for key, terms in aliases.items():
            for term in terms:
                if term in generic:
                    continue
                for match in re.finditer(re.escape(term), clause, re.I):
                    prefix = clause[max(0, match.start() - 25):match.start()]
                    if re.search(r"不要|不想|不学|不是|跳过|先不|\b(?:not|skip|instead of)\b", prefix, re.I):
                        continue
                    priority = bool(re.search(r"目标|想学|先学|练习|资料|推荐|分不清|不会|\b(?:learn|study|focus|practice|confused)\b", clause, re.I))
                    candidates.append((priority, len(term), match.start(), key))
    return max(candidates)[-1] if candidates else None


def _request_state(request):
    viewed = bool(re.search(r"看懂|看过|观看|读过|\b(?:read|watched|seen)\b", request, re.I))
    unanswered = bool(re.search(r"(?:还没(?:有)?|尚未|没有|未)[^。.!?\n]{0,12}(?:作答|做题|练习)|"
                               r"\b(?:not|haven't|have not|didn't)\b[^.!?\n]{0,25}\b(?:answer\w*|attempt\w*|practi[cs]\w*)\b", request, re.I))
    review = bool(re.search(r"复习|回顾|重看|再看|\b(?:review|revisit)\b", request, re.I))
    match = re.search(r"(\d{1,3}|[一二三四五六七八九十两]{1,3}|one|two|five|ten|fifteen|twenty|thirty)\s*(?:分钟|minutes?|mins?)", request, re.I)
    minutes = None
    if match:
        word = match[1].lower()
        numbers = dict(zip("一二三四五六七八九", range(1, 10))) | {"两": 2, "": 0}
        english = {"one": 1, "two": 2, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30}
        if word.isdigit():
            minutes = int(word)
        elif word in english:
            minutes = english[word]
        elif "十" in word:
            left, right = word.split("十", 1)
            minutes = (numbers.get(left) or 1) * 10 + numbers.get(right, 0)
        else:
            minutes = numbers.get(word)
    return viewed and unanswered, review, minutes if minutes and 0 < minutes <= 120 else None


def _session_steps(target, action, *, viewed, minutes, unchecked, language):
    en = language == "en"
    label = goal_label(target, language)
    definition = SKILLS[target].definition if target in SKILLS and not en else label
    detail = (f"独立完成一道未做过的{label}题，写出过程后再提交检查。" if not en else
              f"Attempt a new {label} question independently, show your working, then submit it for checking.")
    if unchecked:
        prerequisite = goal_label(unchecked[0], language)
        detail = (f"可选检查目标：独立完成一道{label}新题并写出过程。涉及{prerequisite}时先检查该步；若卡住，就停在前置步骤，不升级任务。"
                  if not en else f"Optional check: attempt a new {label} task and show your working. Check {prerequisite} when needed; stop there if stuck before advancing.")
    if target not in SKILLS:
        detail = (f"用自己的话整理{label}的一个核心概念，并写下一个仍不清楚的问题。" if not en else
                  f"Explain one core idea in {label} in your own words and record one unresolved question.")
    steps = []
    if not viewed and action != "continue":
        steps.append({"kind": "read", "title": "看" if not en else "Read",
                      "detail": f"阅读{label}的定义与一个例子：{definition}" if not en else f"Read the definition and one example of {label}."})
    check = ("提交后核对过程与结果，记录卡住的步骤；看懂例子或一次正确都不等于整章掌握。" if not en else
             "After submission, check the reasoning and result and note the sticking point. Viewing an example or one success does not establish mastery of a chapter.")
    if target in SKILLS and not en:
        check = f"对照核对目标：{SKILLS[target].definition} 留意易错点：{'；'.join(SKILLS[target].common_errors)}。" + check
    steps.extend([{"kind": "practice", "title": "做" if not en else "Attempt", "detail": detail},
                  {"kind": "check", "title": "查" if not en else "Check", "detail": check}])
    if minutes:
        read = minutes // 5 if len(steps) == 3 else 0
        check = max(1, minutes * 3 // 10)
        amounts = ([read] if len(steps) == 3 else []) + [max(0, minutes - read - check), min(check, minutes)]
        steps = [dict(step, minutes=amount) for step, amount in zip(steps, amounts) if amount]
    return steps


def plan_learning_actions(history, goal, catalog, *, language="zh", request="", goal_source="current_goal", resolve_goal=True):
    explicit = requested_goal(request) if resolve_goal else None
    if explicit:
        goal, goal_source = explicit, "current_request"
    validate_goal(goal)
    english = language == "en"
    profile = profile_projection(history)
    observed = _observations(history)
    viewed, review_requested, minutes = _request_state(request)
    accepted = valid_events(history)
    finished = {event.cycle_id for event in accepted if event.event_type == "problem_ended"
                or (event.event_type == "attempt_assessed" and event.completion_scope == "full_problem"
                    and event.correctness == "correct" and has_verified_outcome(event))}
    latest_started = next((event for event in reversed(accepted) if event.event_type == "problem_started"), None)
    current_skill = next((key for key in latest_started.skill_ids if key in SKILLS), None) if latest_started else None
    active = latest_started if current_skill and latest_started.cycle_id not in finished else None
    target = goal
    if goal == "math_foundations":
        target = next((key for key in SKILLS if observed.get(key, {}).get("state") == "independent_difficulty"),
                      next((key for key in SKILLS if observed.get(key, {}).get("state") != "independent_success"), "linear_isolation"))
        if current_skill:
            target = current_skill
    reason = "unobserved"
    action = "explain"
    prerequisite_ids = _prerequisites(target) if target in SKILLS else list(GOALS[target][2])
    difficult = next((key for key in prerequisite_ids
                      if observed.get(key, {}).get("state") == "independent_difficulty"
                      and not (observed.get(target, {}).get("state") == "independent_success"
                               and observed[target]["event_seq"] > observed[key]["event_seq"])), None)
    if difficult:
        target, action, reason = difficult, "review_prerequisite", "prerequisite_difficulty"
    elif target in observed:
        reason = observed[target]["state"]
        action = {"independent_success": "continue", "independent_difficulty": "explain",
                  "assisted_observation": "check"}[reason]
    if target not in SKILLS:
        reason, action = "outside_assessment_scope", "explore"
    unchecked = [key for key in (SKILLS[target].prerequisites if target in SKILLS else ())
                 if observed.get(key, {}).get("state") != "independent_success"]
    if reason == "unobserved" and unchecked:
        reason, action = "prerequisite_unconfirmed", "check"
    presented = [event for event in accepted if target in event.skill_ids
                 and event.event_type == "help_presented" and event.help_kind in {"example", "explanation", "solution"}]
    latest = presented[-1] if presented else None
    relevant = [event for event in accepted if target in event.skill_ids]
    outcome = next((event for event in reversed(relevant) if has_verified_outcome(event)
                    and event.completion_scope == "full_problem"), None)
    # Whole-task progress is useful even when it cannot diagnose a component skill.
    later_stage = max((event.event_seq for event in relevant if event.event_type in
                       {"problem_started", "problem_ended", "attempt_submitted", "attempt_assessed"}), default=-1)
    pending_example = bool(latest and latest.event_seq > later_stage)
    active_target = bool(active and target in active.skill_ids)
    if outcome and not difficult and (not latest or outcome.event_seq > latest.event_seq):
        if outcome.correctness == "correct" and reason not in {"independent_success", "assisted_observation"}:
            action, reason = "continue", "task_completed"
        elif outcome.correctness != "correct" and reason not in {"independent_difficulty", "assisted_observation"}:
            action, reason = "check", "task_needs_review"
    if active_target and (not outcome or active.event_seq > outcome.event_seq) and not difficult:
        action, reason = "check", "task_in_progress"
    if (viewed or pending_example) and not difficult:
        action, reason = "check", "viewed_unchecked" if viewed else "presented_unchecked"
    if review_requested and not difficult:
        action, reason = "explain", "requested_review"
    if target in observed and observed[target]["state"] == "independent_success":
        unchecked = []
    labels = {
        "unobserved": ("还没有这个知识点的独立作答记录，可以从概念与例子开始。", "There is no independent response for this topic yet. Start with its ideas and examples."),
        "independent_success": ("已有独立完成记录，可以换情境继续学习；这不代表所有相关知识已掌握。", "An independent success is recorded. Try a new setting; it does not establish mastery of every related skill."),
        "independent_difficulty": ("近期独立作答在这个知识点遇到困难，先回看概念和例子。", "An independent response showed difficulty with this skill. Revisit an explanation and example."),
        "prerequisite_difficulty": ("目标知识的一个前置知识点有独立作答困难记录，建议先回看它。", "An independently observed difficulty concerns a prerequisite. Revisit it first."),
        "assisted_observation": ("已有辅助后的作答记录，可以用一道新题检查独立理解。", "Assisted work is recorded. Use a new question to check independent understanding."),
        "outside_assessment_scope": ("这是你选择的学习方向；现有判题记录不能评定这一领域的掌握程度。", "This is your chosen direction. Existing assessments do not establish proficiency in this field."),
        "prerequisite_unconfirmed": ("前置知识尚无可确认的独立记录，不代表不会；可先用一个小题确定起点，通过后继续当前目标。", "Prerequisite evidence is missing, which does not mean inability. Use a short check to choose a starting point, then continue your goal."),
        "viewed_unchecked": ("按你本条说明，已看懂示例但还未独立作答；下次从可选的独立检查继续，不重复观看，也不据此认定掌握。", "You report viewing the example without an independent attempt. Continue with an optional independent check; viewing does not establish mastery."),
        "presented_unchecked": ("记录显示已展示示例，此后尚无该题作答记录；下次从可选的独立检查继续，展示示例不算掌握。", "An example was presented with no subsequent recorded attempt. Continue with an optional independent check; presentation is not mastery."),
        "requested_review": ("按你当前的复习请求安排；已有独立完成记录继续保留，不把复习当成进度退回。", "Follow your current review request while keeping existing independent-completion evidence."),
        "task_in_progress": ("当前还有正在进行的题目，先继续原题的当前步骤；不另开重复任务，也不把开始练习当成掌握。", "A task is already in progress. Resume its current step rather than starting a duplicate; starting a task is not mastery."),
        "task_completed": ("最近一道相关题目已经完成，可以换一道同类题独立检查；整题结果不能单独证明其中每个知识点已掌握。", "A recent related task is complete. Try another similar task independently; its result does not establish mastery of every component skill."),
        "task_needs_review": ("最近一道相关题目已有作答，但尚未完成；先核对原题的条件与过程，不能据此把某个知识点判为薄弱。", "A recent related task has an assessed response but is unfinished. Check its conditions and working; this alone does not identify a weak component skill."),
    }
    scored = []
    for resource in catalog["resources"]:
        points = resource["knowledge_points"]
        score = 4 * (target in points)
        ready = all(key == target or key not in SKILLS or observed.get(key, {}).get("state") == "independent_success"
                    for key in resource["prerequisites"])
        if score and ready and action != "continue" and (review_requested or not (viewed or pending_example or active_target)):
            scored.append((score, resource["resource_id"], resource))
    resources = [dict(row, selection_reason=labels[reason][english], review_status="reviewed_excerpt")
                 for _, _, row in sorted(scored, key=lambda item: (-item[0], item[1]))[:4]]
    evidence_ids = list(dict.fromkeys(([observed[target]["event_id"]] if target in observed else [])
                                     + ([outcome.event_id] if outcome else [])))
    steps = _session_steps(target, action, viewed=(viewed or pending_example or active_target) and not review_requested, minutes=minutes,
                           unchecked=unchecked, language=language)
    resume_active = active_target and not (viewed or pending_example or review_requested)
    if resume_active:
        for step in steps:
            if step["kind"] == "practice":
                step["detail"] = ("继续已经打开的题目，写出当前步骤后再提交；需要帮助时从当前卡住处开始。" if not english else
                                  "Resume the open task and submit your current step. Ask for help at the point where you are stuck.")
    return {"policy": POLICY, "goal": goal, "goal_label": goal_label(goal, language), "target": target,
            "title": goal_label(target, language), "evidence_count": len(evidence_ids),
            "target_label": goal_label(target, language), "action": action, "reason_code": reason,
            "reason": labels[reason][english], "evidence_ids": evidence_ids,
            "profile_revision": profile_revision(history), "last_event_seq": profile["last_event_seq"],
            "graph_version": GRAPH_VERSION, "catalog_version": catalog["version"],
            "prerequisites": [{"id": key, "observed": key in observed} for key in prerequisite_ids],
            "resources": resources, "assessment_scope": "existing_algebra_skills",
            "goal_source": goal_source, "progress": labels[reason][english], "steps": steps,
            "time_budget_minutes": minutes, "check_goal": next((step["detail"] for step in steps if step["kind"] == "practice"), ""),
            "state_event_ids": ([active.event_id] if resume_active else []) + ([latest.event_id] if pending_example else []),
            "query": goal_label(target, "zh") + " 学习 理解 例子"}
