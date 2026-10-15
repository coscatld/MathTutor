"""Server-owned public capabilities and immutable problem binding.

Neither a UI command nor a classifier proposal grants solution access.
The stored verified chain is checked before advertising or executing actions.
"""
from mathtutor.application.state_machine import CycleState
from mathtutor.application.message_intent import _variables

TEACHING_COMMANDS = ("request_hint", "request_explanation", "request_example", "request_solution")
REVIEW_STATES = {CycleState.SOLVED, CycleState.SOLUTION_SHOWN, CycleState.REFLECTION, CycleState.PRACTICE_OFFERED}


def verified_binding(verified) -> bool:
    if verified is None:
        return False
    problem, candidate, ref = verified
    return (candidate.problem_id == problem.problem_id
            and ref.problem_id == problem.problem_id and ref.problem_content_hash == problem.content_hash
            and ref.solution_candidate_id == candidate.candidate_id and ref.solution_payload_hash == candidate.payload_hash)


def problem_variable(verified):
    names = _variables(verified[0].normalized_ast) if verified else set()
    return next(iter(names)) if len(names) == 1 else None


def binding_error(envelope, session, verified):
    cycle = str(session.cycle.cycle_id) if session else ""
    revision = verified[0].content_hash if verified else ""
    if "cycle_id" in envelope and envelope["cycle_id"] != cycle:
        return "PROBLEM_BINDING_STALE", "当前题目已经切换，请重新同步后再发送。"
    if "problem_revision" in envelope and envelope["problem_revision"] != revision:
        return "PROBLEM_REVISION_STALE", "题目内容已经更新，请重新同步后再发送。"
    expected = envelope.get("expected_state_version", envelope.get("expected_cycle_version"))
    if expected is not None and expected != (session.version if session else 0):
        return "STATE_VERSION_CONFLICT", "题目状态刚刚更新了，请重新同步后再试一次。"
    return None


async def session_contract(store, owner_id, session, *, processing=False):
    from mathtutor.application.controller import student_allowed_inputs
    verified = await store.load_verified(owner_id, session.cycle.cycle_id) if session else None
    valid = verified_binding(verified)
    allowed = student_allowed_inputs(session.state) if session else []
    if session and session.state in REVIEW_STATES:
        allowed = list(dict.fromkeys([*allowed, *TEACHING_COMMANDS]))
    # Offer lifecycle is independent: buttons require a real ACTIVE resource.
    allowed = [x for x in allowed if x not in {"accept_practice_offer", "decline_practice_offer",
        "request_practice", "request_foundation", "request_review", "resume_problem", "start_diagnostic", "skip_diagnostic", "end_problem"}]
    if not processing:
        allowed = [x for x in allowed if x != "cancel_turn"]
    active_offer = None
    practice = getattr(store, "practice_repository", None)
    if session and practice:
        from datetime import datetime, timezone
        offers = await practice.offers_for_student(owner_id)
        offer = next((o for o in offers if o.status == "ACTIVE" and o.expires_at > datetime.now(timezone.utc)
                      and o.parent_cycle_id == session.cycle.cycle_id), None)
        if offer:
            recommendation = await practice.recommendation_for_offer(owner_id, offer.offer_id)
            from mathtutor.domain.practice_recommendation import PURPOSE_LABELS
            purpose = recommendation.purpose if recommendation else "D"
            active_offer = {"offer_id": str(offer.offer_id), "title": PURPOSE_LABELS[purpose], "purpose": purpose, "status": "ACTIVE"}
            allowed.extend(["accept_practice_offer", "decline_practice_offer"])
    context = await store.teaching.load(owner_id, session.cycle.cycle_id) if session else None
    if context and valid and session.state != CycleState.CLOSED:
        allowed.extend(["request_practice", "end_problem"])
        from mathtutor.application.evidence_projection import prerequisite_gap, review_due
        if prerequisite_gap(context):
            allowed.append("request_foundation")
        tracking = getattr(store, "student_state", None)
        if tracking and review_due(await tracking.events(owner_id), context["skill_ids"]):
            allowed.append("request_review")
        if context.get("resume_parent_cycle_id"):
            allowed.append("resume_problem")
        if context.get("diagnostic_item") and context["diagnosis"]["status"] == "running":
            allowed.append("skip_diagnostic")
        elif context["diagnosis"]["status"] == "not_started":
            allowed.append("start_diagnostic")
    elif (context and session and session.state != CycleState.CLOSED
          and context.get("resume_parent_cycle_id") and context.get("diagnostic_item")):
        # An interrupted child presentation must still have an escape route.
        # Navigation does not authorize teaching or grade an unverified item.
        allowed.append("resume_problem")
        if context.get("diagnosis", {}).get("status") == "running":
            allowed.append("skip_diagnostic")
    assistance = await store.load_assistance(owner_id, session.cycle.cycle_id) if session else None
    from mathtutor.pedagogy.planner import solution_needs_hint
    from mathtutor.pedagogy.stage_policy import ADAPTIVE_POLICY
    needs_hint = bool(session) and solution_needs_hint(session.state, ADAPTIVE_POLICY, assistance)
    actions = []
    for command in dict.fromkeys([*TEACHING_COMMANDS, *allowed]):
        gated = command == "request_solution" and needs_hint
        enabled = not processing and command in allowed and (valid or command not in TEACHING_COMMANDS) and not gated
        reason = "AVAILABLE" if enabled else "REQUEST_IN_PROGRESS" if processing else "NO_CURRENT_PROBLEM" if not session else "NO_VERIFIED_SOLUTION" if not valid else "HINT_REQUIRED" if gated and command in allowed else "ACTION_NOT_APPLICABLE"
        actions.append({"command": command, "enabled": enabled, "reason_code": reason,
                        "description": {"AVAILABLE": "", "NO_CURRENT_PROBLEM": "请先发来要辅导的题目。",
                                        "NO_VERIFIED_SOLUTION": "当前题目还没有可用的验证解答，请补充题目。",
                                        "ACTION_NOT_APPLICABLE": "当前阶段暂不能使用这个操作。",
                                        "HINT_REQUIRED": "先看一次提示再试试，之后可以查看完整答案。",
                                        "REQUEST_IN_PROGRESS": "正在处理上一条请求，请稍候。"}[reason],
                        "label": "重新查看答案" if command == "request_solution" and assistance and assistance.max_level_issued == 5 else ""})
    from mathtutor.pedagogy.teaching_plan import public_context
    from mathtutor.application.function_graph import GRAPHABLE_TYPES
    from mathtutor.application.discussion_notebook import public_discussion
    if public_discussion(context):
        for action in actions:
            if action["reason_code"] == "NO_VERIFIED_SOLUTION":
                action["description"] = "本题已保存，可以直接在对话中追问；尚未启用本地自动判题。"
    evidence = {"independent": 0, "assisted": 0, "post_solution": 0, "diagnostic": 0, "ungradable": 0, "status": "尚无独立检测证据"}
    tracking = getattr(store, "student_state", None)
    if tracking:
        from mathtutor.application.evidence_projection import public_evidence
        history = await tracking.events(owner_id)
        evidence = public_evidence([event for event in history if verified and event.problem_revision == verified[0].content_hash])
    elif context:
        for record in context.get("assessments", []):
            evidence[record["evidence_kind"]] += 1
    return {"cycle_id": str(session.cycle.cycle_id) if session else "",
            "problem_revision": verified[0].content_hash if verified else "",
            "state": session.state.value if session else "", "state_version": session.version if session else 0,
            "effective_assistance_level": assistance.max_level_issued if assistance else 0,
            "allowed_actions": actions, "allowed_next_inputs": [a["command"] for a in actions if a["enabled"]],
            "teaching_plan": context.get("last_plan") if context else None,
            "problem_context": {**public_context(context), "graphable": verified[0].problem_type in GRAPHABLE_TYPES} if context and valid else public_discussion(context),
            "evidence_summary": evidence, "active_offer": active_offer,
            "diagnosis": context.get("diagnosis") if context else None,
            "recovery_problem": context.get("recovery_problem") if context else None}
