"""Learning actions reuse assessed evidence; resources never establish mastery."""
from __future__ import annotations

import hashlib
import json
from importlib.resources import files

from mathtutor.application.exploration_evidence import safe_source_url
from mathtutor.application.learning_profile import profile_projection
from mathtutor.learning.knowledge_tracing.events import (
    attributed_skill_ids, has_verified_outcome, independent_skill_success_ids, valid_events,
)
from mathtutor.learning.skill_graph import GRAPH_VERSION, SKILLS

POLICY = "learning-actions-v1"
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
                observations[skill] = {"state": state, "event_id": event.event_id}
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


def plan_learning_actions(history, goal, catalog, *, language="zh"):
    validate_goal(goal)
    english = language == "en"
    profile = profile_projection(history)
    observed = _observations(history)
    target = goal
    if goal == "math_foundations":
        target = next((key for key in SKILLS if observed.get(key, {}).get("state") == "independent_difficulty"),
                      next((key for key in SKILLS if key not in observed), "linear_isolation"))
    reason = "unobserved"
    action = "explain"
    prerequisite_ids = _prerequisites(target) if target in SKILLS else list(GOALS[target][2])
    difficult = next((key for key in prerequisite_ids
                      if observed.get(key, {}).get("state") == "independent_difficulty"), None)
    if difficult:
        target, action, reason = difficult, "review_prerequisite", "prerequisite_difficulty"
    elif target in observed:
        reason = observed[target]["state"]
        action = {"independent_success": "continue", "independent_difficulty": "explain",
                  "assisted_observation": "check"}[reason]
    if target not in SKILLS:
        reason, action = "outside_assessment_scope", "explore"
    labels = {
        "unobserved": ("还没有这个知识点的独立作答记录，可以从概念与例子开始。", "There is no independent response for this topic yet. Start with its ideas and examples."),
        "independent_success": ("已有独立完成记录，可以换情境继续学习；这不代表所有相关知识已掌握。", "An independent success is recorded. Try a new setting; it does not establish mastery of every related skill."),
        "independent_difficulty": ("近期独立作答在这个知识点遇到困难，先回看概念和例子。", "An independent response showed difficulty with this skill. Revisit an explanation and example."),
        "prerequisite_difficulty": ("目标知识的一个前置知识点有独立作答困难记录，建议先回看它。", "An independently observed difficulty concerns a prerequisite. Revisit it first."),
        "assisted_observation": ("已有辅助后的作答记录，可以用一道新题检查独立理解。", "Assisted work is recorded. Use a new question to check independent understanding."),
        "outside_assessment_scope": ("这是你选择的学习方向；现有判题记录不能评定这一领域的掌握程度。", "This is your chosen direction. Existing assessments do not establish proficiency in this field."),
    }
    scored = []
    for resource in catalog["resources"]:
        points = resource["knowledge_points"]
        score = 4 * (target in points) + 2 * (goal in points)
        if score:
            score -= sum(observed.get(key, {}).get("state") == "independent_difficulty"
                         for key in resource["prerequisites"])
            scored.append((score, resource["resource_id"], resource))
    resources = [dict(row, selection_reason=labels[reason][english], review_status="reviewed_excerpt")
                 for _, _, row in sorted(scored, key=lambda item: (-item[0], item[1]))[:4]]
    evidence_ids = [observed[target]["event_id"]] if target in observed else []
    return {"policy": POLICY, "goal": goal, "goal_label": goal_label(goal, language), "target": target,
            "title": goal_label(target, language), "evidence_count": len(evidence_ids),
            "target_label": goal_label(target, language), "action": action, "reason_code": reason,
            "reason": labels[reason][english], "evidence_ids": evidence_ids,
            "profile_revision": profile_revision(history), "last_event_seq": profile["last_event_seq"],
            "graph_version": GRAPH_VERSION, "catalog_version": catalog["version"],
            "prerequisites": [{"id": key, "observed": key in observed} for key in prerequisite_ids],
            "resources": resources, "assessment_scope": "existing_algebra_skills",
            "query": goal_label(target, "zh") + " 学习 理解 例子"}
