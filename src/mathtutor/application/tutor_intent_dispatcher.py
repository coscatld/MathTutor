"""TutorIntentDispatcher — isolated tutoring workflow."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.message_intent import (
    ConversationIntent,
    classify_user_message,
    fallback_tutor_reply,
)
from mathtutor.application.message_projection import project_assistant_message
from mathtutor.application.state_machine import (
    CycleCommand,
    CycleState,
    TutoringSession,
)
from mathtutor.application.tutor_contracts import (
    MathTutorEvent,
    MathTutorEventSink,
    MathTutorEventType,
    MathTutorRequest,
    student_allowed_inputs,
)
from mathtutor.domain.hashing import content_hash
from mathtutor.learning.skills import skill_for_problem
from mathtutor.pedagogy.exceptions import DisclosurePolicyViolation
from mathtutor.pedagogy.planner import CycleAssistance, PedagogyPlanner
from mathtutor.pedagogy.stage_policy import StagePolicy
from mathtutor.repositories.session_store import SessionStoreProtocol
from mathtutor.solving import nodes as n

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TutorIntentDispatcher:
    """Own this workflow; storage and cross-workflow effects are explicit dependencies."""

    begin_or_replace_problem: Callable[..., Awaitable[Any]]
    continue_active_problem: Callable[..., Awaitable[Any]]
    dialogue: Callable[..., Awaitable[Any]]
    emit: Callable[..., Awaitable[Any]]
    emit_state: Callable[..., Awaitable[Any]]
    offer_after_solved: Callable[..., Awaitable[Any]]
    personal_memory_context: Callable[..., Awaitable[Any]]
    realize_utterance: Callable[..., Awaitable[Any]]
    redraw_on_canvas: Callable[..., Awaitable[Any]]
    remember_recovery: Callable[..., Awaitable[Any]]
    run_explicit: Callable[..., Awaitable[Any]]
    start_understanding_check: Callable[..., Awaitable[Any]]
    submit_attempt: Callable[..., Awaitable[Any]]
    teaching_context: Callable[..., Awaitable[Any]]
    chat_documents: Any
    chat_responder: Any
    image_repository: Any
    learner_settings: Any
    planner: PedagogyPlanner
    policy: StagePolicy
    practice_service: Any
    semantic_interpreter: Any
    service: MathTutorApplicationService
    sessions: SessionStoreProtocol

    async def route_send_message(
        self,
        request: MathTutorRequest,
        session: TutoringSession | None,
        payload: dict[str, Any],
        envelope: dict[str, Any],
        stream: MathTutorEventSink,
    ) -> None:
        text = str(payload.get("text", ""))
        previous = next(
            (
                m
                for m in reversed(request.conversation_messages)
                if m.get("role") == "tutor"
            ),
            None,
        )
        if text.strip() == "继续" and previous and previous.get("status") == "PARTIAL":
            if previous.get("action") in {"TUTOR_CHAT", "TUTOR_CHAT_FIGURE"}:
                chat_context = json.loads(previous.get("continuation_context") or "{}")
                history = request.conversation_messages
                if chat_context.get("raw_text"):
                    # App labels and a nearby exercise do not close a truncated
                    # model sentence. Resume from its actual saved boundary.
                    history = tuple(
                        {**item, "content": chat_context["raw_text"]}
                        if item is previous
                        else item
                        for item in history
                    )
                if chat_context.get("boundary_unverified"):
                    from mathtutor.application.tutor_runtime import current_turn

                    continuation_turn = current_turn.get()
                    if continuation_turn is not None:
                        continuation_turn.error_code = (
                            "CONTINUATION_BOUNDARY_UNVERIFIED"
                        )
                await self.chat_message(
                    session,
                    text,
                    history,
                    stream,
                    owner_id=request.owner.student_id,
                    client_session_id=request.session_id,
                    follow_up=bool(chat_context.get("follow_up")),
                    response_request=chat_context.get("response_request"),
                    plugin_context=chat_context.get("plugin_context"),
                    unstructured_math=bool(chat_context.get("unstructured_math")),
                )
                return
            context = json.loads(previous.get("continuation_context") or "{}")
            if (
                session is not None
                and context.get("cycle_id") == str(session.cycle.cycle_id)
                and context.get("action")
            ):
                from mathtutor.application.tutor_runtime import continuation_text
                from mathtutor.domain.tutoring import TutorAction

                action = TutorAction.model_validate(context["action"])
                verified = await self.sessions.load_verified(
                    request.owner.student_id, session.cycle.cycle_id
                )
                token = continuation_text.set(str(previous.get("content") or ""))
                try:
                    utterance = await self.realize_utterance(
                        session,
                        verified,
                        action,
                        owner_id=request.owner.student_id,
                        student_request=str(context.get("student_request", "")),
                        continuing=True,
                    )
                finally:
                    continuation_text.reset(token)
                await stream.emit(
                    MathTutorEvent(
                        type=MathTutorEventType.CONTENT,
                        content=utterance.text,
                        source="math_tutor",
                        metadata={
                            "event_type": "tutor_message",
                            "action": utterance.action,
                            "effective_assistance_level": utterance.assistance_level,
                            "cycle_state": session.state.value,
                            "cycle_state_version": session.version,
                        },
                    )
                )
                return
        from mathtutor.application.student_contract import (
            problem_variable,
            verified_binding,
        )

        verified = (
            await self.sessions.load_verified(
                request.owner.student_id, session.cycle.cycle_id
            )
            if session
            else None
        )
        if session and not verified:
            from mathtutor.application.discussion_notebook import FOLLOWUP, public_discussion, starts_new_question
            from mathtutor.application.message_intent import is_concrete_math_input, _requested_action

            notebook = await self.sessions.teaching.load(request.owner.student_id, session.cycle.cycle_id)
            if public_discussion(notebook) and notebook.get("capability_boundary") and not starts_new_question(text):
                action = _requested_action(text)
                if action == "request_solution":
                    await self.dialogue(stream, session, "原题尚无可核验的完整解答。可以点击解释讨论概念，或选择一题能够逐步核验的练习。", "ASK_STUDENT")
                    return
                if action or FOLLOWUP.match(text.strip()) or is_concrete_math_input(text):
                    await self.chat_message(session, text, request.conversation_messages, stream,
                        owner_id=request.owner.student_id, client_session_id=request.session_id,
                        unstructured_math=True, follow_up=True, agent_discussion=True)
                    return
        if not verified and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text.strip()):
            await self.dialogue(
                stream,
                session,
                f"你希望对 {text.strip()} 做什么任务？请补充题目要求，例如计算、分解或检验某个结论。",
                "ASK_STUDENT",
            )
            return
        perception = None
        if verified and re.search(
            r"[\u4e00-\u9fff]|\b(?:understand|explain|confused|hint)\b", text, re.I
        ):
            from mathtutor.application.teaching_intent import rule_teaching_intent
            from mathtutor.pedagogy.teaching_plan import current_subgoal

            context = await self.teaching_context(
                request.owner.student_id, session, verified
            )
            visible_context = {
                "problem_id": context["problem_id"],
                "display_text": context["display_text"],
                "skill_ids": context["skill_ids"],
                "current_subgoal": current_subgoal(context),
                "recent_teaching": context.get("last_plan"),
                "stuck_count": context["stuck_count"],
                "help_without_progress": context["help_without_progress"],
                "recent_messages": [
                    {"role": m.get("role"), "content": str(m.get("content", ""))[-600:]}
                    for m in request.conversation_messages[-4:]
                ],
            }
            if self.semantic_interpreter is not None:
                perception = await self.semantic_interpreter.interpret(
                    text, context=visible_context
                )
            else:
                perception = rule_teaching_intent(text, context=visible_context)
            context["language_understanding"] = perception.model_dump()
            context["language_input_hash"] = content_hash({"text": text})
            context["language_request_id"] = str(envelope.get("idempotency_key", ""))
            await self.sessions.teaching.save(
                request.owner.student_id, session.cycle.cycle_id, context
            )
        if (
            verified
            and perception
            and perception.intent == "self_report"
            and perception.confusion == "none"
        ):
            if perception.resolved:
                context = await self.sessions.teaching.load(
                    request.owner.student_id, session.cycle.cycle_id
                )
                context["stuck_count"] = 0
                context["language_signal_consumed_request"] = context.get(
                    "language_request_id"
                )
                await self.sessions.teaching.save(
                    request.owner.student_id, session.cycle.cycle_id, context
                )
            tracking = getattr(self.sessions, "student_state", None)
            if tracking:
                from mathtutor.learning.knowledge_tracing.events import LearningEvent
                from mathtutor.learning.skill_graph import skills_for_problem

                await tracking.append_event(
                    LearningEvent(
                        event_id=f"self-report:{envelope.get('idempotency_key') or uuid4()}",
                        student_id=request.owner.student_id,
                        session_id=str(session.session_id),
                        cycle_id=str(session.cycle.cycle_id),
                        event_type="self_explanation",
                        problem_id=str(verified[0].problem_id),
                        problem_revision=verified[0].content_hash,
                        item_family_id=verified[0].problem_type,
                        skill_ids=skills_for_problem(verified[0]),
                        completion_scope="reflection",
                    )
                )
            if (
                perception.resolved
                and perception.scope
                in {"current_goal", "current_problem", "same_skill"}
                and session.state != CycleState.CLOSED
            ):
                await self.start_understanding_check(
                    request.owner.student_id,
                    request.session_id,
                    session,
                    verified,
                    stream,
                )
            else:
                await self.dialogue(
                    stream,
                    session,
                    "已记下你的理解反馈。先写出你能确定的一步，我来检查。",
                    "SELF_REPORT",
                )
            return
        pending = ""
        if previous and previous.get("action") == "CLARIFY_INTENT":
            prior = list(request.conversation_messages)
            previous_index = next(
                (i for i, m in reversed(list(enumerate(prior))) if m is previous), -1
            )
            pending = next(
                (
                    m.get("content", "")
                    for m in reversed(prior[:previous_index])
                    if m.get("role") == "student"
                ),
                "",
            )
        from mathtutor.solving.parser import stored_math_ast

        routed = classify_user_message(
            text,
            cycle_state=session.state if session else None,
            variable=problem_variable(verified),
            skill_id=skill_for_problem(verified[0]) if verified else "",
            pending_math_text=pending,
            variables=tuple(
                n.variables(n.from_dict(stored_math_ast(verified[0].normalized_ast)))
            )
            if verified
            else (),
            related_to_active=__import__(
                "mathtutor.learning.skill_graph", fromlist=["related_question"]
            ).related_question(text, verified[0])
            if verified
            else False,
        )
        if (
            perception
            and perception.confidence >= 0.7
            and perception.scope == "other"
            and routed.intent
            in {
                ConversationIntent.GENERAL_CHAT,
                ConversationIntent.PROBLEM_CONTINUATION,
                ConversationIntent.TEACHING_REQUEST,
            }
        ):
            from dataclasses import replace

            # A discussion of a quoted phrase or a different subject isn't
            # evidence that the student is stuck on this mathematical goal.
            routed = replace(routed, intent=ConversationIntent.GENERAL_CHAT, command="")
        if (
            perception
            and perception.confidence >= 0.7
            and perception.scope in {"current_goal", "current_problem", "same_skill"}
        ):
            from dataclasses import replace

            semantic_command = {
                "explanation": "request_explanation",
                "confusion": "request_explanation",
                "hint": "request_hint",
                "example": "request_example",
                "solution": "request_solution",
                "practice": "request_practice",
                "followup": "request_explanation",
            }.get(perception.intent)
            # Only the structural route may create/replace a problem or submit
            # a candidate answer. The model selects support, never correctness.
            if semantic_command and routed.intent is ConversationIntent.ATTEMPT:
                routed = replace(routed, command=semantic_command)
            elif semantic_command and routed.intent in {
                ConversationIntent.GENERAL_CHAT,
                ConversationIntent.PROBLEM_CONTINUATION,
                ConversationIntent.TEACHING_REQUEST,
            }:
                routed = replace(
                    routed,
                    intent=ConversationIntent.TEACHING_REQUEST,
                    command=semantic_command,
                )
            elif (
                perception.intent == "ambiguous"
                and routed.intent is ConversationIntent.GENERAL_CHAT
            ):
                await self.dialogue(
                    stream,
                    session,
                    "你想让我重讲刚才的小目标，还是换一个例子演示？我们可以继续围绕当前题目。",
                    "ASK_STUDENT",
                )
                return
        if session and routed.intent is ConversationIntent.CLARIFY_INTENT:
            context = await self.sessions.teaching.load(
                request.owner.student_id, session.cycle.cycle_id
            )
            if context and context.get("teacher_error_example", {}).get(
                "awaiting_response"
            ):
                from dataclasses import replace

                routed = replace(
                    routed, intent=ConversationIntent.ATTEMPT, answer_text=text
                )
        logger.info(
            "tutor_orchestration conversation_id=%s intent=%s mode=%s state=%s",
            request.session_id,
            routed.intent.value,
            routed.mode.value,
            session.state.value if session is not None else "",
        )
        if routed.intent is ConversationIntent.GENERAL_CHAT:
            from mathtutor.application.math_operation_scope import requires_unstructured_math
            from mathtutor.application.message_intent import _command_quotation

            await self.chat_message(
                session,
                text,
                request.conversation_messages,
                stream,
                owner_id=request.owner.student_id,
                client_session_id=request.session_id,
                unstructured_math=not _command_quotation(text) and bool(
                    re.search(r"[=+*/^√∫]|\\(?:frac|sqrt)\b", text) or requires_unstructured_math(text)),
            )
            return
        if routed.intent is ConversationIntent.CLARIFY_INTENT:
            await self.dialogue(
                stream,
                session,
                "这是你推到的下一步，还是一道新题？请回复“这是步骤”或“这是新题”。",
                "CLARIFY_INTENT",
            )
            return
        if routed.intent is ConversationIntent.TEACHING_REQUEST:
            if not verified_binding(verified):
                # A conceptual follow-up does not require a structured algebra
                # binding. Keep the actual high-school question in its history.
                await self.chat_message(
                    session,
                    text,
                    request.conversation_messages,
                    stream,
                    owner_id=request.owner.student_id,
                    client_session_id=request.session_id,
                    follow_up=True,
                    unstructured_math=True,
                )
            else:
                await self.run_explicit(
                    request,
                    session,
                    routed.command,
                    {"student_request": text},
                    envelope,
                    stream,
                )
            return
        if routed.intent is ConversationIntent.ATTEMPT:
            if session is None or not verified_binding(verified):
                await self.dialogue(
                    stream,
                    session,
                    "当前题目还没有可用的验证记录，请先补充完整题目。",
                    "ASK_STUDENT",
                )
                return
            if session.state not in {
                CycleState.AWAITING_ATTEMPT,
                CycleState.AWAITING_RETRY,
                CycleState.AWAITING_ATTEMPT_CLARIFICATION,
                CycleState.SOLUTION_SHOWN,
            }:
                await self.dialogue(
                    stream,
                    session,
                    "本题已经完成。你可以继续追问原题，或用“换题：…”开始另一道题。",
                    "ASK_STUDENT",
                )
                return
            assistance = await self.sessions.load_assistance(
                request.owner.student_id, session.cycle.cycle_id
            )
            await self.submit_attempt(
                session,
                request.owner.student_id,
                {"answer": routed.answer_text},
                envelope.get(
                    "expected_state_version", envelope.get("expected_cycle_version")
                ),
                str(envelope.get("idempotency_key", "")),
                verified,
                assistance,
                stream,
                raw_text_override=f"{pending}\n{text}"
                if pending and routed.answer_text == pending
                else text,
                offer_after=not bool(routed.command),
                followup_command=routed.command or "",
                followup_request=text,
            )
            if routed.command:
                followup = {
                    **envelope,
                    "expected_state_version": session.version,
                    "expected_cycle_version": session.version,
                }
                await self.run_explicit(
                    request,
                    session,
                    routed.command,
                    {"student_request": text},
                    followup,
                    stream,
                )
            return
        if routed.intent is ConversationIntent.PROBLEM_CONTINUATION:
            await self.continue_active_problem(request, session, text, envelope, stream)
            return
        await self.begin_or_replace_problem(
            request, session, routed.problem_text or text, envelope, stream
        )

    async def chat_message(
        self,
        session: TutoringSession | None,
        text: str,
        history: tuple[dict[str, Any], ...],
        stream: MathTutorEventSink,
        *,
        owner_id: str | None = None,
        follow_up: bool = False,
        unstructured_math: bool = False,
        images: list | None = None,
        client_session_id: str = "",
        agent_discussion: bool = False,
        response_request: str | None = None,
        plugin_context: dict | None = None,
    ) -> None:
        request_text = text if response_request is None else response_request
        recovery = None
        if (
            plugin_context is None
            and not images
            and text.strip() != "继续"
            and not follow_up
            and not agent_discussion
        ):
            session, recovery = await self.remember_recovery(
                session,
                owner_id,
                text,
                client_session_id=client_session_id,
                mathematical=unstructured_math,
            )
        from mathtutor.application.discussion_notebook import (
            SCHEMA,
            model_context,
            starts_new_question,
        )

        notebook = (
            await self.sessions.teaching.load(owner_id, session.cycle.cycle_id)
            if plugin_context is None and session and owner_id
            else None
        )
        saved_discussion = model_context(notebook)
        if (
            unstructured_math
            and not follow_up
            and owner_id
            and not recovery
            and (images or not saved_discussion or starts_new_question(text))
        ):
            if session is None and client_session_id:
                session = await self.sessions.create(owner_id, client_session_id)
            if session is not None:
                bound = await self.sessions.load_verified(
                    owner_id, session.cycle.cycle_id
                )
                if bound is None:
                    notebook = {
                        "schema_version": SCHEMA,
                        "problem_id": f"discussion-{uuid4()}",
                        "display_text": text or "图片中的数学题（原图已保存在本会话）",
                        "skill_ids": [],
                        "lifecycle": "discussion",
                        "original_image_ids": [image["id"] for image in images or []],
                        "student_focus": "",
                        "discussed": [],
                        "assessments": [],
                    }
                    await self.sessions.teaching.save(
                        owner_id, session.cycle.cycle_id, notebook
                    )
                    saved_discussion = model_context(notebook)
        if saved_discussion and text != saved_discussion["original_question"]:
            notebook["student_focus"] = text
            await self.sessions.teaching.save(
                owner_id, session.cycle.cycle_id, notebook
            )
            saved_discussion = model_context(notebook)
        responder = self.chat_responder
        document_context = None
        document_source = getattr(self, "chat_documents", None)
        if document_source is not None and plugin_context is None:
            try:
                document_context = await document_source.build(owner_id, text, history)
            except Exception:
                logger.warning("Chat document retrieval unavailable")
                document_context = {
                    "status": "retrieval_failed",
                    "files": [],
                    "chunks": [],
                }
        if (
            plugin_context is None
            and images is None
            and getattr(self, "image_repository", None) is not None
        ):
            if saved_discussion and notebook.get("original_image_ids"):
                try:
                    images = await self.image_repository.resolve(
                        owner_id, notebook["original_image_ids"]
                    )
                except ValueError:
                    await stream.error(
                        "原题图片已删除或不可用，请重新上传。", source="math_tutor"
                    )
                    return
            # Reattach the latest image turn for conversational follow-ups and
            # continuation. A new structured math task still uses its own route.
            previous = next(
                (
                    m
                    for m in reversed(history[-20:])
                    if m.get("role") == "student" and m.get("attachments")
                ),
                None,
            )
            if previous and images is None:
                try:
                    images = await self.image_repository.resolve(
                        owner_id, [a["id"] for a in previous["attachments"]]
                    )
                except ValueError:
                    await stream.error(
                        "之前的图片已删除或不可用，请重新上传。", source="math_tutor"
                    )
                    return
        problem_context = ""
        if saved_discussion:
            problem_context = json.dumps(saved_discussion, ensure_ascii=False)
        if follow_up and session is not None and owner_id:
            verified = await self.sessions.load_verified(
                owner_id, session.cycle.cycle_id
            )
            if verified is not None:
                problem_context = getattr(verified[0], "display_latex", "") or ""
        provider_result = "fallback"
        math_verify = None
        draw_offered = False
        verification_notice = ""
        learner_context = None
        personal_memory = None
        execution_context = None
        if responder is None:
            if images:
                raise ValueError("当前模型不支持图片输入，请切换到支持视觉输入的模型。")
            if plugin_context is not None:
                from mathtutor.application.plugin_commands import format_plugin_receipt

                message = format_plugin_receipt(plugin_context)
            else:
                message = fallback_tutor_reply(text)
        else:
            from mathtutor.application.tutor_runtime import TutorResponseUnavailable

            try:
                extra = {"images": images} if images else {}
                if document_context is not None:
                    extra["document_context"] = document_context
                # Free chat streams: verified sentences are previewed as they arrive.
                from mathtutor.application.math_claims import (
                    VerifiedPreview,
                    anchor_for,
                )
                from mathtutor.application.tutor_runtime import stream_preview

                bound_for_preview = (
                    await self.sessions.load_verified(owner_id, session.cycle.cycle_id)
                    if session and owner_id
                    else None
                )

                async def emit_preview(verified_text):
                    # The preview never shows a figure: those come only with the final message.
                    from mathtutor.skills.canvas_drawing.enforce import sanitize_figures

                    verified_text = sanitize_figures(verified_text)[0]
                    if verified_text:
                        await stream.content(
                            verified_text,
                            source="math_tutor",
                            metadata={"event_type": "tutor_preview"},
                        )

                preview_token = stream_preview.set(
                    VerifiedPreview(
                        self.service.verification_backend,
                        emit_preview,
                        anchor=anchor_for(bound_for_preview[0])
                        if bound_for_preview
                        else None,
                    )
                )
                import inspect

                from mathtutor.application.message_intent import is_concrete_math_input

                accepts = inspect.signature(responder.respond).parameters
                if plugin_context is not None and "plugin_context" in accepts:
                    extra["plugin_context"] = plugin_context
                if "execution_context" in accepts and owner_id and client_session_id:
                    from mathtutor.application.tutor_runtime import current_turn
                    from mathtutor.extensions import ExecutionContext

                    active_turn = current_turn.get()
                    execution_context = ExecutionContext(
                        owner_id=owner_id,
                        conversation_id=client_session_id,
                        request_id=active_turn.turn_id
                        if active_turn and active_turn.turn_id
                        else str(uuid4()),
                    )
                    extra["execution_context"] = execution_context
                if "authorization_request" in accepts:
                    # Authorization belongs to this authenticated turn, whereas
                    # response_request may retain a historical explanation goal.
                    extra["authorization_request"] = text
                personal_memory = await self.personal_memory_context(owner_id)
                if personal_memory is not None and "personal_memory" in accepts:
                    extra["personal_memory"] = personal_memory
                if response_request is not None and "response_request" in accepts:
                    extra["response_request"] = request_text
                if "learner_context" in accepts:
                    from mathtutor.pedagogy.adaptive_dialogue import (
                        build_adaptive_context,
                        resolve_dialogue_skills,
                    )

                    # One owner-scoped, read-only snapshot per answer. Repairs
                    # reuse it; generating advice never manufactures a student
                    # observation or rewrites a presentation-time prediction.
                    skills = resolve_dialogue_skills(
                        request_text,
                        problem=bound_for_preview[0]
                        if bound_for_preview and follow_up
                        else None,
                        original_question=saved_discussion["original_question"]
                        if saved_discussion
                        else "",
                    )
                    learner_context = await build_adaptive_context(
                        getattr(self.sessions, "student_state", None),
                        owner_id or "",
                        skills,
                    )
                    extra["learner_context"] = learner_context
                    from mathtutor.application.tutor_runtime import note_turn

                    strategy = learner_context["strategy"]
                    note_turn(
                        adaptation={
                            "strategy": strategy,
                            "evidence_count": learner_context["evidence_count"],
                            "skill_ids": learner_context["skill_ids"],
                            "reason_codes": learner_context["reason_codes"],
                            "model_sha256": learner_context["forecast"]
                            .get("source_model", {})
                            .get("model_sha256"),
                            "forecast_status": learner_context["forecast"]["status"],
                        }
                    )
                    if strategy != "neutral":
                        from mathtutor.pedagogy.dkt_policy import note_dkt

                        note_dkt("dialogue", strategy)
                takes_tools = "math_verify" in accepts or any(
                    p.kind is p.VAR_KEYWORD for p in accepts.values()
                )
                takes_figures = "draw_figures" in accepts or any(
                    p.kind is p.VAR_KEYWORD for p in accepts.values()
                )
                from mathtutor.skills.canvas_drawing import can_offer_drawing

                drawing_relevant = can_offer_drawing(text, history)
                math_history = any(
                    is_concrete_math_input(str(item.get("content", "")))
                    for item in history[-6:]
                )
                if (
                    plugin_context is None
                    and takes_tools
                    and (
                        unstructured_math
                        or follow_up
                        or drawing_relevant
                        or math_history
                        or is_concrete_math_input(text)
                    )
                ):
                    # Maths questions: the model may verify its own claims first,
                    # and show a figure only through the canvas (draw_scene).
                    from mathtutor.application.math_verification import verify_math

                    async def math_verify(expression, answer):
                        return await verify_math(
                            self.service.verification_backend, expression, answer
                        )

                    extra = {**extra, "math_verify": math_verify}
                    if takes_figures and drawing_relevant:
                        draw_offered = True
                        extra["draw_figures"] = True
                try:
                    message = await responder.respond(
                        text,
                        history=history,
                        problem_context=problem_context,
                        unstructured_math=unstructured_math,
                        **extra,
                    )
                finally:
                    stream_preview.reset(preview_token)
                provider_result = "success"
            except TutorResponseUnavailable as exc:
                await stream.error(
                    str(exc), source="math_tutor", metadata={"error_code": exc.code}
                )
                return
            except TypeError:
                if images:
                    raise ValueError(
                        "当前模型不支持图片输入，请切换到支持视觉输入的模型。"
                    ) from None
                message = await responder.respond(text, history=history)
                provider_result = "success"
            except ValueError as exc:
                if not images:
                    raise
                await stream.error(str(exc), source="math_tutor")
                return
        logger.info(
            "tutor_orchestration intent=general_chat provider_result=%s state=%s",
            provider_result,
            session.state.value if session is not None else "",
        )
        visible = project_assistant_message(message) or fallback_tutor_reply(text)
        using_fallback = visible == fallback_tutor_reply(text)
        if recovery and using_fallback:
            visible = "这道题的完整过程还不能逐步核验。你可以写出下一步的想法，或先练下面的相关基础题。"
        # Canvas drawing skill: a figure the model drew by itself never reaches the student.
        from mathtutor.application.tutor_runtime import current_turn, note_turn
        from mathtutor.skills.canvas_drawing.enforce import sanitize_figures

        turn = current_turn.get()
        visible, removed = sanitize_figures(visible)
        visible = visible or fallback_tutor_reply(text)
        if removed:
            note_turn(figures={"removed": removed})
        if (
            removed
            and draw_offered
            and turn is not None
            and not getattr(turn, "figures", None)
            and provider_result == "success"
            and not recovery
        ):
            visible = await self.redraw_on_canvas(
                responder,
                turn,
                text,
                history,
                visible,
                problem_context=problem_context,
                unstructured_math=unstructured_math,
                images=images,
                math_verify=math_verify,
                response_request=request_text,
                learner_context=learner_context,
                document_context=document_context,
                personal_memory=personal_memory,
                execution_context=execution_context,
            )
        raw_visible = visible
        from mathtutor.application.math_claims import strip_notice
        from mathtutor.application.problem_recovery import simple_greeting

        if not simple_greeting(text, visible):
            # Each formula goes through verify_math; prose stays unverified.
            from mathtutor.application.math_claims import (
                anchor_for,
                certify_and_annotate,
            )

            bound = (
                await self.sessions.load_verified(owner_id, session.cycle.cycle_id)
                if session and owner_id
                else None
            )
            regenerate = None
            if responder is not None and provider_result == "success" and not recovery:
                first_answer = raw_visible

                async def regenerate(feedback):
                    retry_history = (
                        *history,
                        {"role": "student", "content": text},
                        {"role": "tutor", "content": first_answer},
                    )
                    # Internal repair feedback must not replace the student's
                    # language, answer-disclosure or presentation constraints.
                    repair_options = {"images": images} if images else {}
                    repair_parameters = inspect.signature(responder.respond).parameters
                    if "response_request" in repair_parameters:
                        repair_options["response_request"] = request_text
                    if "authorization_request" in repair_parameters:
                        repair_options["authorization_request"] = text
                    if (
                        document_context is not None
                        and "document_context" in repair_parameters
                    ):
                        repair_options["document_context"] = document_context
                    if math_verify is not None and "math_verify" in repair_parameters:
                        repair_options["math_verify"] = math_verify
                    if learner_context is not None:
                        repair_options["learner_context"] = learner_context
                    if (
                        personal_memory is not None
                        and "personal_memory" in repair_parameters
                    ):
                        repair_options["personal_memory"] = personal_memory
                    if (
                        execution_context is not None
                        and "execution_context" in repair_parameters
                    ):
                        repair_options["execution_context"] = execution_context
                    if (
                        plugin_context is not None
                        and "plugin_context" in repair_parameters
                    ):
                        repair_options["plugin_context"] = plugin_context
                    return sanitize_figures(
                        project_assistant_message(
                            await responder.respond(
                                feedback,
                                history=retry_history,
                                problem_context=problem_context,
                                unstructured_math=unstructured_math,
                                **repair_options,
                            )
                        )
                        or ""
                    )[0]

            visible, checked = await certify_and_annotate(
                visible,
                self.service.verification_backend,
                anchor=anchor_for(bound[0]) if bound else None,
                regenerate=regenerate,
            )
            raw_visible = strip_notice(visible) if not checked.refuted else raw_visible
            if not checked.refuted:
                # The same public receipt remains visible in the UI, replay
                # and restored history, without becoming an unsolicited
                # Chinese sentence in a student's requested answer format.
                from mathtutor.application.math_claims import notice_for

                verification_notice = notice_for(checked).removeprefix("> ")
                visible = strip_notice(visible)
        from mathtutor.application.response_contract import extract_response_contract

        violations = extract_response_contract(request_text).violations(raw_visible)
        if violations:
            # Observe failures honestly. Never truncate a proof or select a
            # yes/no label just to make the answer look compliant.
            note_turn(
                response_contract={
                    "violations": len(violations),
                    "codes": list(violations),
                }
            )
        action = "TUTOR_CHAT"
        figures = list(getattr(turn, "figures", None) or []) if turn is not None else []
        if figures:
            # Scenes the application built from draw_scene calls, appended only
            # to the final message (never to the streamed preview).
            from mathtutor.application.scene import render_scene

            visible += "".join("\n\n" + render_scene(scene) for scene in figures)
            action = "TUTOR_CHAT_FIGURE"
            note_turn(figures={"delivered": len(figures)})
        if recovery and using_fallback:
            visible += f"\n\n原题还保留在对话里。可以先练一道相关基础题：\\( {recovery['text']} \\)。{recovery['relation']}"
        if saved_discussion and session is not None and provider_result == "success":
            notebook["discussed"] = [
                *notebook.get("discussed", []),
                raw_visible[:1200],
            ][-6:]
            await self.sessions.teaching.save(
                owner_id, session.cycle.cycle_id, notebook
            )
        if turn is not None:
            from mathtutor.application.network_chat import merge_continuation_context
            from mathtutor.application.offline_foundations import offline_concept_reply

            merge_continuation_context(turn,
                {
                    "kind": "chat",
                    "unstructured_math": unstructured_math,
                    "follow_up": follow_up,
                    "raw_text": raw_visible,
                    "response_request": request_text,
                    "plugin_context": plugin_context,
                    "verification_notice": verification_notice,
                    "boundary_unverified": turn.error_code
                    == "CONTINUATION_BOUNDARY_UNVERIFIED",
                },
            )
            if using_fallback and not recovery:
                local = offline_concept_reply(text)
                if local is not None and local.text == raw_visible:
                    merge_continuation_context(turn, {"offline_foundations": local.receipt()})
        await stream.emit(
            MathTutorEvent(
                type=MathTutorEventType.CONTENT,
                content=visible,
                source="math_tutor",
                metadata={
                    "event_type": "tutor_message",
                    "action": action,
                    "verification_notice": verification_notice,
                    "cycle_state": session.state.value if session is not None else "",
                    "cycle_state_version": session.version
                    if session is not None
                    else 0,
                    "allowed_next_inputs": student_allowed_inputs(session.state)
                    if session is not None
                    else [],
                },
            )
        )

    async def prompt_command(
        self,
        session: TutoringSession,
        owner_id: str,
        command: CycleCommand,
        label: str,
        expected_version: int | None,
        idempotency_key: str,
        verified: tuple | None,
        assistance: CycleAssistance,
        stream: MathTutorEventSink,
        *,
        student_request: str = "",
        resume_checkpoint: dict | None = None,
    ) -> None:
        from mathtutor.application.student_contract import verified_binding

        if not verified_binding(verified):
            await stream.error(
                "当前题目还没有可用的验证解答，请先补充题目。",
                source="math_tutor",
                metadata={"error_code": "NO_VERIFIED_SOLUTION"},
            )
            return
        # PLAN FIRST: a policy refusal must never advance the state machine
        # (e.g. request_solution before the stage's hint threshold).
        problem, candidate, ref = verified if verified else (None, None, None)
        try:
            action = self.planner.plan(
                state=session.state,
                command=command,
                policy=self.policy,
                assistance=assistance,
                verified_ref=ref,
            )
        except DisclosurePolicyViolation as exc:
            # A refusal leaves the cycle version unchanged, so an open
            # checkpoint would make a replay rerun only this refused half.
            from mathtutor.application.tutor_runtime import current_turn

            turn = current_turn.get()
            context = await self.sessions.teaching.load(
                owner_id, session.cycle.cycle_id
            )
            pending = (context or {}).get("pending_expression") or {}
            if pending.get("request_id") in {
                turn.turn_id if turn else None,
                idempotency_key,
            }:
                context.pop("pending_expression")
                await self.sessions.teaching.save(
                    owner_id, session.cycle.cycle_id, context
                )
            code = getattr(exc, "error_code", "")
            await stream.error(
                str(exc) if code else f"当前策略不允许这个操作：{exc}",
                source="math_tutor",
                metadata={
                    "cycle_state": session.state.value,
                    **({"error_code": code} if code else {}),
                },
            )
            return
        from mathtutor.application.tutor_runtime import current_turn
        from mathtutor.domain.tutoring import TutorAction
        from mathtutor.pedagogy.output_guard import GuardedTutorUtterance

        teaching_context = await self.teaching_context(owner_id, session, verified)
        turn = current_turn.get()
        request_id = turn.turn_id if turn else idempotency_key
        if resume_checkpoint and resume_checkpoint.get("action"):
            action = TutorAction.model_validate(resume_checkpoint["action"])
        checkpoint = dict(
            resume_checkpoint or teaching_context.get("pending_expression") or {}
        )
        if checkpoint.get("request_id") != request_id:
            checkpoint = {}
        checkpoint.update(
            request_id=request_id,
            command={
                CycleCommand.REQUEST_HINT: "request_hint",
                CycleCommand.REQUEST_EXPLANATION: "request_explanation",
                CycleCommand.REQUEST_EXAMPLE: "request_example",
                CycleCommand.SOLUTION_SHOWN_PERMITTED: "request_solution",
            }[command],
            student_request=student_request,
            problem_revision=problem.content_hash,
            cycle_version=session.version,
            action=action.model_dump(mode="json"),
        )
        checkpoint.setdefault("phase", "planned")
        teaching_context["pending_expression"] = checkpoint
        await self.sessions.teaching.save(
            owner_id, session.cycle.cycle_id, teaching_context
        )
        # Phase 3 teaching control chain: projector → writer → guard (the
        # action is already planner-sanctioned).
        if checkpoint.get("approved_utterance"):
            utterance = GuardedTutorUtterance.model_validate(
                checkpoint["approved_utterance"]
            )
            if turn:
                turn.continuation_context = checkpoint.get("continuation_context", "")
        else:
            utterance = await self.realize_utterance(
                session,
                verified,
                action,
                student_request=student_request,
                owner_id=owner_id,
            )
        # Keep the previous actionable state while the writer runs. Commit
        # the request + delivery transition together, never strand a restart
        # in HINTED/EXPLAINING after a provider failure or cancellation.
        actual_command = command
        return_state = session.state
        if (
            command == CycleCommand.SOLUTION_SHOWN_PERMITTED
            and utterance.assistance_level < 5
        ):
            actual_command = CycleCommand.REQUEST_HINT
        transition = session.step(
            actual_command,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        if actual_command == CycleCommand.REQUEST_HINT:
            delivered = CycleCommand.HINT_DELIVERED
        elif actual_command == CycleCommand.SOLUTION_SHOWN_PERMITTED:
            delivered = None
        else:
            delivered = CycleCommand.EXPLANATION_DELIVERED
        if delivered is not None and return_state == CycleState.AWAITING_RETRY:
            delivered = CycleCommand.SUPPORT_RETURNED_TO_RETRY
        transitions = [transition]
        if delivered is not None:
            transitions.append(session.step(delivered))
        teaching_context = await self.sessions.teaching.load(
            owner_id, session.cycle.cycle_id
        )
        teaching_context["pending_expression"].update(
            phase="action_committed", cycle_version=session.version
        )
        actual_action = action.model_copy(
            update={
                "action": utterance.action,
                "effective_assistance_level": utterance.assistance_level,
                "solution_visibility": {
                    0: "none",
                    1: "hint",
                    2: "hint",
                    3: "step",
                    4: "partial",
                    5: "full",
                }[utterance.assistance_level],
            }
        )
        await self.sessions.commit_teaching_action(
            owner_id,
            session.cycle.cycle_id,
            transitions,
            actual_action,
            teaching_context,
        )
        await self.emit(
            stream,
            session,
            transition,
            utterance.text,
            detail=utterance.action,
            extra={
                "action": utterance.action,
                "effective_assistance_level": utterance.assistance_level,
            },
        )
        if delivered is None and self.practice_service is not None:
            # L5 shown → REFLECTION → server-driven practice offer (§7.5 E2E).
            # The helper emits the final event (offer projection / degraded),
            # so no state-only emit follows.
            await self.offer_after_solved(
                session,
                owner_id,
                skill_id=skill_for_problem(problem) if problem is not None else None,
                stream=stream,
                reflected=True,
                problem_text=problem.display_latex if problem is not None else "",
                purpose="B",
            )
        else:
            await self.emit_state(stream, session)
