"""MathTutor-owned controller — the single student-facing business entry.

Command envelope (§13.2) arrives as the user message. Free text enters an
intent boundary first; only concrete math input reaches ``submit_problem``:

.. code-block:: json

    {"command": "submit_problem", "payload": {"text": "2x + 3 = 7"},
     "expected_cycle_version": 3, "idempotency_key": "k1"}

The capability is a deterministic application shell: it routes the command
through the tutoring state machine, drives the shared application services
(parse → solve → verify → attestation), runs the Phase 4 learning loop on
submit_attempt (AttemptParser → AttemptVerifier → diagnosis → evidence →
mastery projection, committed in ONE short SQLite transaction), realizes
tutoring language through the pedagogy chain (planner → projector →
writer → guard), and emits §13.3-style typed public events. The LLM never
participates in judging, verification, mastery or control flow.

Identity (Phase 0): every turn receives a server-created
:class:`~mathtutor.security.scopes.StudentOwnerScope` on the narrow
request object.  There is no client ``student_id`` and no anonymous fallback.
The session store is keyed by ``(student_id, session_id)`` for owner
isolation.

The controller has no tool/capability/runtime surface.
"""

from __future__ import annotations
import re

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.state_machine import (
    CycleCommand,
    CycleState,
    InvalidTransitionError,
    TutoringSession,
    VersionConflictError,
    allowed_next_commands,
)
from mathtutor.domain.hashing import content_hash
from mathtutor.domain.problem import MathProblem
from mathtutor.learning.attempt_verifier import (
    Correctness,
)
from mathtutor.learning.skills import skill_for_problem
from mathtutor.pedagogy.disclosure import SolutionDisclosureProjector
from mathtutor.pedagogy.output_guard import TutorOutputGuard
from mathtutor.pedagogy.planner import CycleAssistance, PedagogyPlanner
from mathtutor.pedagogy.stage_policy import ADAPTIVE_POLICY, StagePolicy
from mathtutor.pedagogy.tutor_writer import (
    PublicProblemView,
    TemplateTutorWriter,
)
from mathtutor.application.constraint_layer import (
    ConstraintResult,
    ConstraintStatus,
    evaluate_constraints,
)
from mathtutor.application.message_projection import (
    project_assistant_message,
    project_turn_error,
)
from mathtutor.repositories.sqlite_store import SQLiteSessionStore
from mathtutor.repositories.session_store import SessionStoreProtocol


# Legacy protocol (no version / v1) only. Remove after v1 clients retire.
from mathtutor.application.attempt_evaluation import AttemptEvaluationService
from mathtutor.application.practice_workflow import PracticeWorkflowService
from mathtutor.application.tutor_intent_dispatcher import TutorIntentDispatcher
from mathtutor.application.tutor_contracts import LEGACY_COMMAND_ALIASES as LEGACY_COMMAND_ALIASES
from mathtutor.application.tutor_contracts import (
    USER_COMMANDS, SEND_MESSAGE_COMMAND, student_allowed_inputs, MathTutorRequest, MathTutorEventType, MathTutorEvent, MathTutorEventSink, MathTutorManifest, _parse_envelope
)

logger = logging.getLogger(__name__)


# Both durable and ephemeral runtimes use the same transactional SQLite store.


def _concept_hint_for(problem: MathProblem | None) -> str:
    """L1 concept hint: names/definitions only — never a target step."""
    if problem is None:
        return ""
    return {
        "arithmetic": "分数与整数的运算规则",
        "polynomial": "多项式与同类项的概念",
        "linear": "一元一次方程的概念",
        "quadratic": "一元二次方程的概念",
        "linear_inequality": "不等式的基本性质",
        "quadratic_inequality": "一元二次不等式与二次函数图像的关系",
        "linear_system": "方程组的解必须同时满足每一个方程",
    }.get(problem.problem_type, "")


def _strategy_hint_for(problem: MathProblem | None) -> str:
    """L2 strategy hint: method direction only — no concrete results."""
    if problem is None:
        return ""
    return {
        "arithmetic": "先确定括号和运算顺序；分数加减先通分，乘除按相应规则计算",
        "polynomial": "先展开或合并同类项，再比较系数",
        "linear": "先把含未知数的项移到一边，常数项移到另一边",
        "quadratic": "先尝试因式分解，或用求根公式",
        "linear_inequality": "先移项整理，两边同乘除负数时改变不等号方向",
        "quadratic_inequality": "先求对应方程的根，再结合抛物线开口方向确定解集",
        "linear_system": "选定一个未知数，通过两式整体倍乘相加减消元，或从一式表示它再代入另一式",
    }.get(problem.problem_type, "")


# ---------------------------------------------------------------------------
# Controller request/event boundary
# ---------------------------------------------------------------------------


class MathTutorController:
    """Deterministic tutoring pipeline, independent of DeepTutor runtime."""

    manifest = MathTutorManifest(
        name="math_tutor",
        description=(
            "K12 数学辅导：支持整数/分数运算、多项式化简、一元一次/二次方程。"
            "普通对话走生成模型；具体题目走确定性解析-求解-验证管线。"
        ),
        stages=(
            "parse",
            "ground",
            "solve_and_verify",
            "plan",
            "realize",
            "commit",
            "stream",
        ),
    )

    def __init__(
        self,
        store: SessionStoreProtocol | None = None,
        service: MathTutorApplicationService | None = None,
        policy: StagePolicy | None = None,
        planner: PedagogyPlanner | None = None,
        projector: SolutionDisclosureProjector | None = None,
        writer: Any | None = None,  # TemplateTutorWriter | LLMTutorWriter
        guard: TutorOutputGuard | None = None,
        practice_repository: Any | None = None,
        practice_service: Any | None = None,  # AdaptivePracticeService | None
        chat_responder: Any | None = None,
        semantic_interpreter: Any | None = None,
    ) -> None:
        if store is None and practice_repository is not None:
            store = SQLiteSessionStore(practice_repository.uow.engine)
        self.sessions: SessionStoreProtocol = store or SQLiteSessionStore()
        self.service = service or MathTutorApplicationService(engine=self.sessions.uow.engine)
        # Phase 5 (§7.2): the verified-release catalog behind every offer.
        # Offers/accepts go through THIS repository only — the store's
        # accept transaction re-validates the offer with a CAS.
        from mathtutor.repositories.sqlite_practice import SQLitePracticeRepository

        self.practice: Any = practice_repository or SQLitePracticeRepository(self.sessions.uow)
        # Phase 5 (§7.5 E2E): server-driven practice offers after a solved
        # cycle. None → no offer is generated (cycles end at SOLVED; used by
        # capability-only tests). Product construction always wires the
        # AdaptivePracticeService here.
        self.practice_service: Any = practice_service
        if (
            hasattr(self.sessions, "practice_repository")
            and self.sessions.practice_repository is None
        ):
            self.sessions.practice_repository = self.practice
        # Phase 3 teaching control chain (defaults: deterministic, offline-safe).
        # No process-local pedagogy caches: the verified chain and the
        # assistance ledger live in the store (append-only tutor_actions +
        # attestation) and are restored at every turn start — restart-safe.
        self.policy: StagePolicy = policy or ADAPTIVE_POLICY
        self.planner = planner or PedagogyPlanner()
        self.projector = projector or SolutionDisclosureProjector()
        self.writer = writer or TemplateTutorWriter()
        self.guard = guard or TutorOutputGuard()
        self.chat_responder = chat_responder
        self.semantic_interpreter = semantic_interpreter
        # Gateway for model-proposed scene definitions (None: deterministic only).
        self.scene_gateway: Any = None
        self.community_plugins: Any = None

    def _intent_workflow(self) -> TutorIntentDispatcher:
        return TutorIntentDispatcher(
            begin_or_replace_problem=self._begin_or_replace_problem,
            continue_active_problem=self._continue_active_problem,
            dialogue=self._dialogue,
            emit=self._emit,
            emit_state=self._emit_state,
            offer_after_solved=self._offer_after_solved,
            personal_memory_context=self._personal_memory_context,
            realize_utterance=self._realize_utterance,
            redraw_on_canvas=self._redraw_on_canvas,
            remember_recovery=self._remember_recovery,
            run_explicit=self._run_explicit,
            start_understanding_check=self._start_understanding_check,
            submit_attempt=self._submit_attempt,
            teaching_context=self._teaching_context,
            chat_documents=getattr(self, 'chat_documents', None),
            chat_responder=self.chat_responder,
            image_repository=getattr(self, 'image_repository', None),
            learner_settings=getattr(self, 'learner_settings', None),
            planner=self.planner,
            policy=self.policy,
            practice_service=self.practice_service,
            semantic_interpreter=self.semantic_interpreter,
            service=self.service,
            sessions=self.sessions,
        )

    def _attempt_workflow(self) -> AttemptEvaluationService:
        return AttemptEvaluationService(
            advance_diagnostic=self._advance_diagnostic,
            dialogue=self._dialogue,
            emit=self._emit,
            offer_after_solved=self._offer_after_solved,
            step=self._step,
            teaching_context=self._teaching_context,
            service=self.service,
            sessions=self.sessions,
        )

    def _practice_workflow(self) -> PracticeWorkflowService:
        return PracticeWorkflowService(
            cycle_fact=self._cycle_fact,
            dialogue=self._dialogue,
            emit=self._emit,
            prepare_presentation=self._prepare_presentation,
            teaching_context=self._teaching_context,
            practice=self.practice,
            practice_service=self.practice_service,
            sessions=self.sessions,
        )

    async def _teaching_context(self, owner_id, session, verified):
        from mathtutor.pedagogy.teaching_plan import initial_context
        context = await self.sessions.teaching.load(owner_id, session.cycle.cycle_id)
        if verified and (context is None or context.get("schema_version") in {"mt-recovery-v1", "mt-discussion-v1"} or context.get("pending_diagnostic_initialization")):
            diagnostic_seed = {key: context[key] for key in (
                "diagnostic_item", "resume_parent_cycle_id", "diagnostic_remaining", "client_session_id", "diagnosis", "understanding_check")
                if context and key in context}
            assistance = await self.sessions.load_assistance(owner_id, session.cycle.cycle_id)
            legacy_auto = session.state in {CycleState.SOLUTION_SHOWN, CycleState.REFLECTION, CycleState.PRACTICE_OFFERED}
            context = initial_context(verified[0], verified[1], legacy_help=assistance.max_level_issued > 0 or legacy_auto,
                verified_solution_ref=verified[2], cycle_id=session.cycle.cycle_id)
            context["legacy_auto_transition"] = legacy_auto
            context.update(diagnostic_seed)
            from mathtutor.pedagogy.teaching_plan import TeachingPlan, current_subgoal
            goal = current_subgoal(context)
            context["last_plan"] = TeachingPlan("ASK_STUDENT", "focused_question", goal["prompt_target"], goal["id"],
                tuple(goal.get("skill_ids") or context["skill_ids"]), ("CURRENT_SUBGOAL",), "guided", ("request_solution", "end_problem")).public()
            await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        elif context is not None and verified and "task_context" not in context:
            from mathtutor.application.problem_context import build_problem_context
            from mathtutor.learning.skill_graph import skills_for_subgoal
            context["task_context"] = build_problem_context(verified[0], verified[1],
                cycle_id=session.cycle.cycle_id, verified_solution_ref=verified[2])
            for goal in context.get("subgoals", []):
                goal["skill_ids"] = list(skills_for_subgoal(verified[0], goal["id"], verified[1]))
            await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        # 0.4.4 contexts already have task_context, so the older migration
        # branch alone does not populate this new family selector.
        if context is not None and verified and context.get("problem_type") != verified[0].problem_type:
            context["problem_type"] = verified[0].problem_type
            await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        return context

    async def _prepare_presentation(self, owner_id, session, verified):
        """Must precede publishing a verified cycle to either HTTP or WebSocket."""
        tracking = getattr(self.sessions, "student_state", None)
        if tracking is None or not verified:
            return
        from mathtutor.learning.skill_graph import skills_for_problem
        problem = verified[0]
        await tracking.prepare_prediction(owner_id, prediction_id=f"presentation:{session.cycle.cycle_id}",
            session_id=session.session_id, cycle_id=session.cycle.cycle_id,
            problem_id=problem.problem_id, problem_revision=problem.content_hash,
            item_family_id=problem.problem_type, skill_ids=skills_for_problem(problem), at_presentation=True)

    async def _cycle_fact(self, owner_id, session, verified, event_type, *, lifecycle_status="active", task_purpose="practice"):
        tracking = getattr(self.sessions, "student_state", None)
        if tracking is None or not verified:
            return
        from mathtutor.learning.knowledge_tracing.events import LearningEvent
        from mathtutor.learning.skill_graph import skills_for_problem
        problem = verified[0]
        if event_type == "problem_started":
            await self._prepare_presentation(owner_id, session, verified)
        await tracking.append_event(LearningEvent(event_id=f"{event_type}:{session.cycle.cycle_id}",
            student_id=owner_id, session_id=str(session.session_id), cycle_id=str(session.cycle.cycle_id),
            event_type=event_type, problem_id=str(problem.problem_id), problem_revision=problem.content_hash,
            item_family_id=problem.problem_type, skill_ids=skills_for_problem(problem),
            eligible_cycle=task_purpose != "diagnostic", task_purpose=task_purpose, lifecycle_status=lifecycle_status,
            options_exposed=event_type == "options_exposed"))

    # ------------------------------------------------------------- run entry

    async def run(self, request: MathTutorRequest, stream: MathTutorEventSink) -> None:
        """Route one command envelope through the tutoring state machine.

        The auth layer has already resolved a trusted owner.  The controller
        never consults process-global auth context and never accepts identity
        fields from the client envelope. Free-text ``send_message`` is
        classified before any math parser or cycle command is applied.
        """
        owner = request.owner
        try:
            command, envelope = _parse_envelope(request.user_message)
        except ValueError as exc:
            await stream.error(project_turn_error(str(exc)), source=self.manifest.name)
            return

        session = await self.sessions.load(owner.student_id, request.session_id)
        from mathtutor.application.student_contract import binding_error
        bound_verified = await self.sessions.load_verified(owner.student_id, session.cycle.cycle_id) if session else None
        # An accepted offer is an immutable receipt, not a fresh operation on
        # whichever cycle is now active. Preserve owner-scoped accept replay.
        accepted_child = None
        if command == "accept_practice_offer":
            try:
                accepted_child = await self.sessions.load_child_cycle_for_offer(owner.student_id, UUID(str((envelope.get("payload") or {}).get("offer_id", ""))))
            except ValueError:
                pass
        conflict = binding_error(envelope, session, bound_verified) if accepted_child is None else None
        if conflict:
            await stream.error(conflict[1], source=self.manifest.name, metadata={"error_code": conflict[0]})
            return
        payload = envelope.get("payload") or {}
        if command == SEND_MESSAGE_COMMAND:
            from mathtutor.application.plugin_commands import parse_plugin_command
            slash = parse_plugin_command(str(payload.get("text", "")))
            if slash is not None:
                await self._plugin_command(request, session, bound_verified, envelope, slash, stream)
                return
        if payload.get("attachment_ids"):
            knowledge = getattr(self, "knowledge", None)
            if knowledge and (await knowledge.configuration(owner.student_id, request.session_id)).get("mode") == "knowledge":
                await self._dialogue(stream, session, "知识库问答只读取显式挂载的资料。请先在知识库导入文档；图片题目请切回辅导模式。", "TUTOR_CHAT")
                return
            # Images are expression input, never a verified math answer or a
            # permission to advance the bound teaching cycle.
            try:
                images = await self.image_repository.resolve(owner.student_id, payload["attachment_ids"])
                await self._chat_message(session, str(payload.get("text") or ""),
                    request.conversation_messages, stream, owner_id=owner.student_id, images=images,
                    unstructured_math=True, client_session_id=request.session_id)
            except ValueError as exc:
                await stream.error(str(exc), source=self.manifest.name)
            return
        if command == SEND_MESSAGE_COMMAND:
            from mathtutor.application.function_graph import resolve_graph_request
            graph_request = resolve_graph_request(str(payload.get("text", "")), request.conversation_messages)
            if graph_request is not None:
                await self._function_graph(owner.student_id, session, bound_verified, graph_request, stream)
                return
            from mathtutor.application.network_chat import NetworkFallbackSink, network_reply
            from mathtutor.application.message_intent import is_concrete_math_input
            online = (None if is_concrete_math_input(str(payload.get("text", "")))
                      else await network_reply(self, request, session, payload))
            if online is not None:
                if online.status in {"answered", "partial", "local_plan"} or online.calculation_receipts:
                    await self._dialogue(stream, session, online.text, "TUTOR_CHAT")
                    return
                stream = NetworkFallbackSink(stream, online.text)
            knowledge = getattr(self, "knowledge", None)
            if knowledge and (await knowledge.configuration(owner.student_id, request.session_id)).get("mode") == "knowledge":
                from mathtutor.application.student_contract import REVIEW_STATES, session_contract
                if bound_verified and session.state not in REVIEW_STATES and session.state != CycleState.CLOSED:
                    await self._dialogue(stream, session, "当前题目仍在练习中，知识库问答不能绕过答案披露限制。请先使用题目提示，或结束本题后再进入知识库问答。", "TUTOR_CHAT")
                    return
                text = str(payload.get("text", ""))
                practice = None
                import re
                if session and re.search(r"(?:给|来|做|要).*练习|练习(?:题|一下)", text) and not re.search(r"不要|不必|不用", text):
                    contract = await session_contract(self.sessions, owner.student_id, session)
                    if "request_practice" in contract.get("allowed_next_inputs", []):
                        async def practice():
                            await self._run_explicit(request, session, "request_practice", {}, envelope, stream)
                            offers = await self.practice.offers_for_student(owner.student_id)
                            return {"offers": [{"offer_id": str(x.offer_id), "status": x.status} for x in offers if x.status == "ACTIVE" and x.parent_cycle_id == session.cycle.cycle_id],
                                    "release_gate": "existing_verified_pipeline"}
                message = await self.knowledge_qa.respond(owner.student_id, request.session_id, text,
                    request.conversation_messages, practice=practice)
                if message:
                    # Retrieved sources and declared math tool receipts do not
                    # independently verify every generated explanatory sentence.
                    from mathtutor.application.math_claims import certify_and_annotate
                    from mathtutor.skills.canvas_drawing.enforce import sanitize_figures
                    from mathtutor.application.tutor_runtime import note_turn
                    message, removed = sanitize_figures(message)
                    if removed:
                        note_turn(figures={"removed": removed})

                    async def regenerate(feedback):
                        retry_history = (*request.conversation_messages, {"role": "student", "content": text},
                                         {"role": "tutor", "content": message})
                        return sanitize_figures(await self.knowledge_qa.respond(owner.student_id, request.session_id,
                            f"{text}\n\n{feedback}", retry_history, practice=None) or "")[0]
                    checked, _ = await certify_and_annotate(message, self.service.verification_backend,
                                                            regenerate=regenerate)
                    await self._dialogue(stream, session, checked, "TUTOR_CHAT")
                return
            await self._route_send_message(request, session, payload, envelope, stream)
            return
        from mathtutor.application.student_contract import REVIEW_STATES, TEACHING_COMMANDS
        if session is not None and bound_verified is None and session.state != CycleState.CLOSED and command in TEACHING_COMMANDS:
            from mathtutor.application.discussion_notebook import public_discussion
            notebook = await self.sessions.teaching.load(owner.student_id, session.cycle.cycle_id)
            if public_discussion(notebook):
                if command == "request_solution" and notebook.get("capability_boundary"):
                    await self._dialogue(stream, session, "原题尚无可核验的完整解答。可以点击解释讨论概念，或选择一题能够逐步核验的练习。", "ASK_STUDENT")
                    return
                # Explicit teaching requests for a saved discussion use the same
                # chat/verification path as typed questions. They do not enter
                # the verified exercise state machine or create learning evidence.
                prompts = {
                    "request_hint": "请围绕原题给我一个起步提示，暂不公布最终答案。",
                    "request_explanation": "请讲解原题涉及的关键概念和解题思路，暂不公布最终答案。",
                    "request_example": "请给一道同类示例并讲解它的解法，保留原题，不要公布原题的最终答案。",
                    "request_solution": "请给出原题的完整解答，写清推导与最终答案。",
                }
                await self._chat_message(session, prompts[command], request.conversation_messages, stream,
                    owner_id=owner.student_id, client_session_id=request.session_id,
                    unstructured_math=True, follow_up=True, agent_discussion=True)
                return
        if session is not None and session.state in REVIEW_STATES and command in TEACHING_COMMANDS:
            await self._run_explicit(request, session, command, payload, envelope, stream)
            return

        if session is None:
            session = await self.sessions.create(owner.student_id, request.session_id)
        verified = await self.sessions.load_verified(
            owner.student_id, session.cycle.cycle_id
        )
        assistance = await self.sessions.load_assistance(
            owner.student_id, session.cycle.cycle_id
        )

        expected_version = envelope.get("expected_state_version", envelope.get("expected_cycle_version"))
        idempotency_key = str(envelope.get("idempotency_key", ""))
        try:
            await self._dispatch(
                session,
                owner.student_id,
                request.session_id,
                command,
                payload,
                expected_version,
                idempotency_key,
                verified,
                assistance,
                stream,
            )
        except InvalidTransitionError as exc:
            logger.error(
                "InvalidTransition conversation_id=%s state=%s command=%s",
                request.session_id,
                exc.state.value,
                exc.command.value,
            )
            await stream.error(
                project_turn_error(exc.student_message),
                source=self.manifest.name,
                metadata={"cycle_state": session.state.value, "cycle_state_version": session.version},
            )
        except VersionConflictError as exc:
            logger.error(
                "VersionConflict conversation_id=%s expected=%s actual=%s",
                request.session_id,
                exc.expected,
                exc.actual,
            )
            await stream.error(
                "题目状态刚刚更新了，请重新同步后再试一次。",
                source=self.manifest.name,
                metadata={"cycle_state": session.state.value, "cycle_state_version": session.version},
            )
        except Exception:  # Surface a safe error; committed effects are journaled.
            logger.exception("tutor turn failed conversation_id=%s", request.session_id)
            await stream.error("这次没能处理完成，请重新同步对话后再试。", source=self.manifest.name)

    async def _plugin_command(self, request, session, verified, envelope, slash, stream):
        """One explicit host execution, then optional model expression only."""
        from mathtutor.application.plugin_commands import plugin_reference_context, slash_operation_id
        from mathtutor.application.tutor_runtime import current_turn
        from mathtutor.extensions.registry import ExtensionError
        service = self.community_plugins
        alias, argument = slash
        if service is None:
            await self._dialogue(stream, session, "当前环境尚未提供插件命令，请到‘我的插件’检查。", "TUTOR_CHAT")
            return
        try:
            record = service.resolve_command(request.owner.student_id, alias)
            if record is None:
                raise ExtensionError(f"未找到 /{alias} 命令。请到‘我的插件’查看已安装的命令。")
            if not record.get("enabled"):
                raise ExtensionError(f"/{alias} 所属插件尚未启用，请先查看权限并明确启用。")
            if not record.get("runtime_available", True):
                raise ExtensionError(f"/{alias} 所需的运行环境不可用，请到‘我的插件’检查。")
            turn = current_turn.get()
            stable_request = turn.turn_id if turn is not None else str(envelope.get("idempotency_key") or envelope.get("request_id") or "")
            operation_id = slash_operation_id(request.owner.student_id, request.session_id, stable_request)
            receipt = await service.run_slash(request.owner.student_id, alias, argument,
                operation_id=operation_id, conversation_id=request.session_id)
            context = plugin_reference_context(record, alias, receipt)
            if verified and session is not None:
                assistance = await self.sessions.load_assistance(request.owner.student_id, session.cycle.cycle_id)
                context["exercise_scope"] = {"cycle_state": session.state.value,
                    "assistance_level": assistance.max_level_issued,
                    "full_answer_authorized": assistance.max_level_issued >= 5,
                    "instruction": "只沿用已有教学帮助范围；插件执行不授权完整解答，不提交学生作答或推进题目。"}
        except ExtensionError as exc:
            await self._dialogue(stream, session, str(exc), "TUTOR_CHAT")
            return
        except Exception:
            logger.warning("Plugin slash command failed")
            await self._dialogue(stream, session, "插件命令未能完成；没有自动重试，请到‘我的插件’查看运行状态。", "TUTOR_CHAT")
            return
        await self._chat_message(session, str(envelope.get("payload", {}).get("text", "")),
            request.conversation_messages, stream, owner_id=request.owner.student_id,
            client_session_id=request.session_id, follow_up=bool(verified), plugin_context=context)

    async def _route_send_message(
        self,
        request: MathTutorRequest,
        session: TutoringSession | None,
        payload: dict[str, Any],
        envelope: dict[str, Any],
        stream: MathTutorEventSink,
    ) -> None:
        workflow = self._intent_workflow()
        return await workflow.route_send_message(request, session, payload, envelope, stream)

    async def _dialogue(self, stream, session, text, action, level=0):
        await stream.content(text, source=self.manifest.name, metadata={
            "event_type": "tutor_message", "action": action,
            "effective_assistance_level": level,
            "cycle_id": str(session.cycle.cycle_id) if session else "",
            "cycle_state": session.state.value if session else "",
            "cycle_state_version": session.version if session else 0,
            "allowed_next_inputs": student_allowed_inputs(session.state) if session else [],
        })

    async def _function_graph(self, owner_id, session, verified, text, stream):
        """Draw a server-computed graph or scene; the model never supplies points.

        Order: a typed single function (v1), the bound problem when nothing
        else was typed, a deterministic scene, then (with a model configured)
        a model-proposed scene definition, otherwise guidance. While the bound
        problem is open, answer points stay unmarked, and a graph of that
        problem is recorded as help.
        """
        from mathtutor.application.function_graph import (
            GRAPH_ACTION, GRAPHABLE_TYPES, GraphInputError, extract_function_text, graph_for_function, graph_for_problem)
        from mathtutor.application.scene import author_scene, example_scene_from_text, has_math_content, render_scene, scene_from_text
        from mathtutor.application.student_contract import REVIEW_STATES, verified_binding
        bound = bool(session and verified_binding(verified) and session.state != CycleState.CLOSED)
        open_problem = bound and session.state not in REVIEW_STATES
        source = extract_function_text(text)
        example = "可以这样写：画出 y = x^2 - 2x - 3 的图像，或 画出 x^2/4+y^2/3=1 和 y=kx+1。"
        # Only multi-object or parametrized requests become scenes; a single
        # plain y = f(x) stays on the v1 path.
        scene = scene_from_text(text, reveal=not open_problem) or example_scene_from_text(text, reveal=not open_problem)
        error = ""
        if scene is None and source:
            try:
                await self._dialogue(stream, session, graph_for_function(source, reveal=not open_problem), GRAPH_ACTION)
                return
            except GraphInputError as exc:
                error = str(exc)
        if scene is None and not source and bound and verified[0].problem_type in GRAPHABLE_TYPES and (
                not has_math_content(text) or re.search(r"这道题|这题|本题|题目|原题", text)):
            try:
                content = graph_for_problem(verified[0].problem_type, verified[0].normalized_ast, reveal=not open_problem)
            except GraphInputError as exc:
                await self._dialogue(stream, session, f"{exc}。{example}", "TUTOR_CHAT")
                return
            if open_problem:
                await self._record_graph_help(owner_id, session, verified)
            await self._dialogue(stream, session, content, GRAPH_ACTION)
            return
        gateway = getattr(self, "scene_gateway", None)
        scene_request = text
        if not source and session is not None:
            from mathtutor.application.discussion_notebook import model_context
            saved = model_context(await self.sessions.teaching.load(owner_id, session.cycle.cycle_id))
            if saved:
                scene_request = f"原题：{saved['original_question']}\n学生请求：{text}\n分段函数必须按各支定义域截取，不能把区间外的候选根画成原题零点。"
        if scene is None and gateway is not None and has_math_content(scene_request):
            scene = await author_scene(gateway, scene_request)
        if scene is not None:
            await self._dialogue(stream, session, render_scene(scene), GRAPH_ACTION)
            return
        await self._dialogue(stream, session, f"{error}。{example}" if error else f"请告诉我要画哪个函数或图形。{example}", "TUTOR_CHAT")

    async def _record_graph_help(self, owner_id, session, verified):
        # Same delivery ledger as hints: a later attempt counts as assisted
        # once the client acknowledges that the graph was shown.
        from mathtutor.application.tutor_runtime import current_turn
        from mathtutor.pedagogy.teaching_plan import current_subgoal
        teaching_context = await self._teaching_context(owner_id, session, verified)
        problem = verified[0]
        turn = current_turn.get()
        delivery_id = f"graph:{session.cycle.cycle_id}:{turn.turn_id if turn else uuid4()}"
        delivery = {"session_id": str(session.session_id), "problem_id": str(problem.problem_id),
            "problem_revision": problem.content_hash, "item_family_id": problem.problem_type,
            "skill_ids": teaching_context["skill_ids"], "subgoal_id": current_subgoal(teaching_context)["id"],
            "help_kind": "explanation", "target_answer_exposed": False, "delivery_id": delivery_id,
            "request_id": turn.turn_id if turn is not None else delivery_id, "target_answer_authorized": False}
        await self.sessions.teaching.delivery(owner_id, session.cycle.cycle_id, delivery_id, delivery)
        tracking = getattr(self.sessions, "student_state", None)
        if tracking is not None:
            for phase in ("help_requested", "help_committed"):
                await tracking.record_help(owner_id, event_id=f"{delivery_id}:{phase}",
                    cycle_id=str(session.cycle.cycle_id), event_type=phase, **delivery)
        await self.mark_delivery(owner_id, delivery_id, "possibly_exposed")
        if turn is not None:
            from mathtutor.application.network_chat import merge_continuation_context
            merge_continuation_context(turn, {"delivery_id": delivery_id})

    async def _continue_active_problem(
        self,
        request: MathTutorRequest,
        session: TutoringSession | None,
        text: str,
        envelope: dict[str, Any],
        stream: MathTutorEventSink,
    ) -> None:
        if session is None:
            await self._chat_message(
                None,
                text,
                request.conversation_messages,
                stream,
                owner_id=request.owner.student_id,
            )
            return
        allowed = set(student_allowed_inputs(session.state))
        from mathtutor.application.student_contract import REVIEW_STATES, TEACHING_COMMANDS
        if session.state in REVIEW_STATES:
            allowed.update(TEACHING_COMMANDS)
        if "request_explanation" in allowed:
            await self._run_explicit(
                request, session, "request_explanation", {"student_request": text}, envelope, stream
            )
            return
        if "request_hint" in allowed:
            await self._run_explicit(
                request, session, "request_hint", {"student_request": text}, envelope, stream
            )
            return
        await self._chat_message(
            session,
            text,
            request.conversation_messages,
            stream,
            owner_id=request.owner.student_id,
            follow_up=True,
        )

    async def _show_math_boundary(self, session, owner_id, text, constraint, stream, *, client_session_id=""):
        from mathtutor.application.constraint_layer import boundary_discussion_allowed, boundary_response
        from mathtutor.application.bounded_calculus import derivative_question_receipt
        from mathtutor.application.bounded_rational_equation import rational_equation_receipt, render_rational_receipt
        from mathtutor.application.discussion_notebook import SCHEMA
        from mathtutor.application.tutor_runtime import current_turn

        message = boundary_response(constraint)
        if not message:
            return False
        receipt = derivative_question_receipt(text)
        if receipt is None:
            receipt = await rational_equation_receipt(text, self.service.verification_backend)
        recovery = None
        if receipt is None:
            session, recovery = await self._remember_recovery(session, owner_id, text,
                client_session_id=client_session_id, mathematical=True)
        if receipt or boundary_discussion_allowed(constraint):
            if session is None and client_session_id:
                session = await self.sessions.create(owner_id, client_session_id)
            if session and not await self.sessions.load_verified(owner_id, session.cycle.cycle_id):
                notebook = {"schema_version": SCHEMA, "problem_id": f"discussion-{uuid4()}",
                    "display_text": text, "skill_ids": [], "lifecycle": "discussion", "student_focus": "",
                    "discussed": [], "assessments": [], "capability_boundary": constraint.reason}
                if recovery:
                    notebook.update(recovery_problem=recovery, recovery_original_text=text)
                if receipt:
                    notebook["math_receipt"] = receipt
                await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, notebook)
        if receipt:
            message = (render_rational_receipt(receipt) if receipt["scope"] == "bounded_rational_equation" else
                       f"已核验导数：\\(\\frac{{d}}{{d{receipt['variable']}}}({receipt['expression']})"
                       f"={receipt['display_latex']}\\)。可以点击解释，继续讨论求导规则。")
        turn = current_turn.get()
        if turn is not None:
            from mathtutor.application.network_chat import merge_continuation_context
            merge_continuation_context(turn, {"math_boundary": {
                "reason": constraint.reason, "original_question": text, "formula_receipt": receipt,
                "constraint_receipt": constraint.boundary_receipt}})
        if session and session.state == CycleState.GROUNDING:
            await self._step(owner_id, session, CycleCommand.GROUNDING_UNSUPPORTED)
        await self._dialogue(stream, session, message, "ASK_STUDENT")
        return True

    async def _begin_or_replace_problem(
        self,
        request: MathTutorRequest,
        session: TutoringSession | None,
        text: str,
        envelope: dict[str, Any],
        stream: MathTutorEventSink,
    ) -> None:
        constraint = evaluate_constraints(text)
        if await self._show_math_boundary(session, request.owner.student_id, text, constraint, stream,
                                         client_session_id=request.session_id):
            return
        if constraint.reason == "resource_limit":
            await stream.error("这道表达式超出计算预算，请缩短式子或减小数值后重试。",
                               source=self.manifest.name, metadata={"error_code": "RESOURCE_LIMIT"})
            return
        logger.info(
            "tutor_orchestration conversation_id=%s constraint=%s reason=%s",
            request.session_id,
            constraint.status.value,
            constraint.reason,
        )
        if constraint.status is ConstraintStatus.HARD_FAIL:
            await self._chat_message(
                session,
                text,
                request.conversation_messages,
                stream,
                owner_id=request.owner.student_id,
            )
            return
        if constraint.status is ConstraintStatus.SOFT_FAIL and constraint.reason != "unsupported_family":
            await self._chat_message(
                session,
                constraint.raw_text,
                request.conversation_messages,
                stream,
                owner_id=request.owner.student_id,
                unstructured_math=True,
                client_session_id=request.session_id,
                agent_discussion=constraint.reason == "unsupported_operation",
            )
            return
        owner_id = request.owner.student_id
        payload = {"text": constraint.solver_text}
        idempotency_key = str(envelope.get("idempotency_key", ""))
        if session is None:
            session = await self.sessions.create(owner_id, request.session_id)
            await self._submit_problem(
                session, owner_id, payload, None, idempotency_key, stream, constraint=constraint
            )
            return
        if session.state == CycleState.PROBLEM_RECEIVED:
            await self._submit_problem(
                session, owner_id, payload, None, idempotency_key, stream, constraint=constraint
            )
            return
        if session.state == CycleState.GROUNDING:
            logger.info(
                "tutor_orchestration conversation_id=%s recover_grounding command=problem_complete",
                request.session_id,
            )
            await self._ground_problem(session, owner_id, text, stream, constraint=constraint)
            return
        if session.state == CycleState.AWAITING_CLARIFICATION:
            await self._clarify_and_ground(
                session, owner_id, text, None, idempotency_key, stream, constraint=constraint
            )
            return
        session = await self._replace_cycle(session, owner_id, request.session_id)
        await self._submit_problem(
            session, owner_id, payload, None, idempotency_key, stream, constraint=constraint
        )

    async def _replace_cycle(
        self,
        session: TutoringSession,
        owner_id: str,
        client_session_id: str,
    ) -> TutoringSession:
        if CycleCommand.CANCEL_TURN in allowed_next_commands(session.state):
            try:
                await self._step(owner_id, session, CycleCommand.CANCEL_TURN)
            except (InvalidTransitionError, VersionConflictError):
                logger.warning(
                    "tutor_orchestration could not close prior cycle state=%s",
                    session.state.value,
                )
        starter = getattr(self.sessions, "start_new_cycle", None)
        if starter is not None:
            return await starter(owner_id, client_session_id)
        return await self.sessions.create(owner_id, client_session_id)

    async def _run_explicit(
        self,
        request: MathTutorRequest,
        session: TutoringSession,
        command: str,
        payload: dict[str, Any],
        envelope: dict[str, Any],
        stream: MathTutorEventSink,
    ) -> None:
        from mathtutor.application.student_contract import REVIEW_STATES, TEACHING_COMMANDS, verified_binding
        verified = await self.sessions.load_verified(
            request.owner.student_id, session.cycle.cycle_id
        )
        assistance = await self.sessions.load_assistance(
            request.owner.student_id, session.cycle.cycle_id
        )
        if command in TEACHING_COMMANDS and session.state in REVIEW_STATES and verified_binding(verified):
            await self._review_action(request, session, command, verified, assistance, stream,
                                      student_request=str(payload.get("student_request", "")))
            return
        try:
            await self._dispatch(
                session,
                request.owner.student_id,
                request.session_id,
                command,
                payload,
                envelope.get("expected_state_version", envelope.get("expected_cycle_version")),
                str(envelope.get("idempotency_key", "")),
                verified,
                assistance,
                stream,
            )
        except InvalidTransitionError as exc:
            logger.error(
                "InvalidTransition conversation_id=%s state=%s command=%s",
                request.session_id,
                exc.state.value,
                exc.command.value,
            )
            await stream.error(
                project_turn_error(exc.student_message),
                source=self.manifest.name,
                metadata={"cycle_state": session.state.value, "cycle_state_version": session.version},
            )

    async def _review_action(self, request, session, command, verified, assistance, stream, *, student_request="", resume_checkpoint=None):
        # Reviewing a solved problem must not reopen it or relabel evidence.
        reviewing_solution = command == "request_solution" and assistance.max_level_issued == 5
        if reviewing_solution:
            for message in reversed(request.conversation_messages):
                try:
                    context = json.loads(message.get("continuation_context") or "{}")
                except (TypeError, ValueError):
                    continue
                if not isinstance(context, dict):
                    continue
                approved = context.get("approved_solution_text")
                if (message.get("action") == "SHOW_SOLUTION" and message.get("status") == "COMPLETED"
                        and context.get("cycle_id") == str(session.cycle.cycle_id)
                        and isinstance(approved, str) and approved.strip()):
                    from mathtutor.application.tutor_runtime import current_turn
                    turn = current_turn.get()
                    if turn is not None:
                        turn.continuation_context = message["continuation_context"]
                    await self._dialogue(stream, session, approved, "SHOW_SOLUTION", 5)
                    return
        action = self.planner.plan(state=session.state, command=USER_COMMANDS[command],
                                   policy=self.policy, assistance=assistance, verified_ref=verified[2])
        from mathtutor.application.tutor_runtime import current_turn
        from mathtutor.domain.tutoring import TutorAction
        from mathtutor.pedagogy.output_guard import GuardedTutorUtterance
        turn = current_turn.get()
        teaching_context = await self._teaching_context(request.owner.student_id, session, verified)
        checkpoint = dict(resume_checkpoint or teaching_context.get("pending_expression") or {})
        request_id = turn.turn_id if turn else str(action.action_id)
        if checkpoint.get("request_id") != request_id:
            checkpoint = {}
        if resume_checkpoint and checkpoint.get("action"):
            action = TutorAction.model_validate(checkpoint["action"])
        checkpoint.update(request_id=request_id, command=command, student_request=student_request,
            problem_revision=verified[0].content_hash, cycle_version=session.version, action=action.model_dump(mode="json"))
        checkpoint.setdefault("phase", "planned")
        if not reviewing_solution:
            teaching_context["pending_expression"] = checkpoint
            await self.sessions.teaching.save(request.owner.student_id, session.cycle.cycle_id, teaching_context)
        # Legacy history may lack the approved body. Render the same stored,
        # verified solution deterministically, without a second exposure event.
        if checkpoint.get("approved_utterance") and not reviewing_solution:
            utterance = GuardedTutorUtterance.model_validate(checkpoint["approved_utterance"])
            if turn:
                turn.continuation_context = checkpoint.get("continuation_context", "")
        else:
            utterance = await self._realize_utterance(session, verified, action, restore_solution=reviewing_solution,
                                                    owner_id=request.owner.student_id,
                                                    student_request=student_request)
        if not reviewing_solution:
            teaching_context = await self.sessions.teaching.load(request.owner.student_id, session.cycle.cycle_id)
            teaching_context["pending_expression"].update(phase="action_committed", cycle_version=session.version)
            await self.sessions.commit_teaching_action(request.owner.student_id, session.cycle.cycle_id, [],
                action.model_copy(update={"action": utterance.action, "effective_assistance_level": utterance.assistance_level}), teaching_context)
        await self._dialogue(stream, session, utterance.text, utterance.action, utterance.assistance_level)

    async def _remember_recovery(self, session, owner_id, text, *, client_session_id="", mathematical=False):
        """Persist a separately verified scaffold; never accept it for the student."""
        from mathtutor.application.problem_recovery import recovery_candidate
        suggestion = recovery_candidate(text, mathematical=mathematical)
        if suggestion is None or not owner_id:
            return session, None
        exercise, relation = suggestion
        checked = await self.service.submit_problem(exercise)
        if checked.kind != "verified" or checked.problem is None:
            return session, None
        if session is None:
            if not client_session_id:
                return session, None
            session = await self.sessions.create(owner_id, client_session_id)
        context = await self.sessions.teaching.load(owner_id, session.cycle.cycle_id)
        if context is None:
            context = {"schema_version": "mt-recovery-v1", "problem_id": "", "display_text": text,
                "skill_ids": [], "lifecycle": "unsupported", "subgoals": [],
                "assessments": [], "diagnosis": {"status": "not_started", "can_skip": False, "question_count": 0}}
        recovery = {"text": exercise, "problem_type": checked.problem.problem_type, "relation": relation}
        context["recovery_problem"] = recovery
        context["recovery_original_text"] = text
        await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        return session, recovery

    async def _chat_message(
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
        workflow = self._intent_workflow()
        return await workflow.chat_message(session, text, history, stream, owner_id=owner_id, follow_up=follow_up, unstructured_math=unstructured_math, images=images, client_session_id=client_session_id, agent_discussion=agent_discussion, response_request=response_request, plugin_context=plugin_context)

    async def _redraw_on_canvas(self, responder, turn, text, history, first_answer, *, problem_context,
                                unstructured_math, images, math_verify, response_request=None,
                                learner_context=None, document_context=None, personal_memory=None,
                                execution_context=None) -> str:
        """One bounded repair: the answer drew a figure by itself; ask for draw_scene.

        Like the formula repair, the turn gets a fixed extra budget (one
        draw_scene call plus the answer). The new text is used only when a
        scene was actually drawn; otherwise the sanitized first answer stays.
        """
        from mathtutor.application.tutor_runtime import note_turn
        from mathtutor.skills.canvas_drawing.enforce import sanitize_figures
        saved = (turn.finish_reason, turn.status, turn.final_text, turn.error_code)
        turn.max_steps = max(turn.max_steps, turn.steps_used) + 2
        feedback = ("你上一条回答里用文字、代码或图片画了图，应用不会显示这些内容。"
                    "请调用 draw_scene 工具在画布上重新作图（只给定义），并重新完整回答原问题；"
                    "如果这张图无法用画布表示，就只用文字讲解。不要提到这次修改。")
        retry_history = (*history, {"role": "student", "content": text}, {"role": "tutor", "content": first_answer})
        try:
            import inspect
            supported = inspect.signature(responder.respond).parameters
            context_options = {key: value for key, value in {
                "response_request": response_request, "learner_context": learner_context,
                "authorization_request": text,
                "document_context": document_context, "personal_memory": personal_memory,
                "execution_context": execution_context,
            }.items() if key in supported and value is not None}
            again = project_assistant_message(await responder.respond(
                feedback, history=retry_history, problem_context=problem_context, unstructured_math=unstructured_math,
                math_verify=math_verify, draw_figures=True, **context_options,
                **({"images": images} if images else {}))) or ""
        except Exception:
            logger.warning("canvas redraw call failed")
            again = ""
        again, removed = sanitize_figures(again)
        drawn = bool(getattr(turn, "figures", None)) and bool(again.strip())
        note_turn(figure_repair={"attempted": 1, "succeeded": int(drawn)})
        if drawn:
            if removed:
                note_turn(figures={"removed": removed})
            return again
        turn.figures = []
        from mathtutor.domain.turn_result import FinishReason
        if turn.finish_reason == FinishReason.TOKEN_LIMIT:
            # The reliable first explanation survives a failed redraw, but a
            # budget stop must not become a completed answer again.
            turn.stop(FinishReason.TOKEN_LIMIT, first_answer)
        else:
            turn.finish_reason, turn.status, turn.final_text, turn.error_code = saved
        return first_answer

    # ------------------------------------------------------------- dispatch

    async def _step(
        self,
        owner_id: str,
        session: TutoringSession,
        command: CycleCommand,
        *,
        expected_version: int | None = None,
        idempotency_key: str = "",
        problem_id=None,
    ):
        """Apply one state-machine step and COMMIT it (short transaction).

        The state machine stays in memory; every transition is persisted
        with CAS (owner + version) so a stale command or replay aborts.
        ``problem_id`` (when given) is bound to the cycle in the same
        transaction — the verified problem becomes durable.
        """
        transition = session.step(
            command,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        await self.sessions.persist_transition(owner_id, transition, problem_id=problem_id)
        return transition

    async def _dispatch(
        self,
        session: TutoringSession,
        owner_id: str,
        client_session_id: str,
        command: str,
        payload: dict[str, Any],
        expected_version: int | None,
        idempotency_key: str,
        verified: tuple | None,
        assistance: CycleAssistance,
        stream: MathTutorEventSink,
    ) -> None:
        if command == "request_options":
            await self._request_options(session, owner_id, verified, stream)
        elif command in {"request_practice", "request_foundation", "request_review"}:
            if not verified:
                await stream.error("请先提供一道题，明确要练习的知识点。", source=self.manifest.name)
                return
            context = await self._teaching_context(owner_id, session, verified)
            from mathtutor.application.evidence_projection import prerequisite_gap, review_due
            gaps = prerequisite_gap(context) if command == "request_foundation" else ()
            tracking = getattr(self.sessions, "student_state", None)
            due = review_due(await tracking.events(owner_id), context["skill_ids"]) if tracking and command == "request_review" else False
            if command == "request_foundation" and not gaps:
                await stream.error("还没有定位具体的先修缺口，可以先做可跳过的相关知识诊断。", source=self.manifest.name)
                return
            if command == "request_review" and not due:
                await stream.error("当前没有到期复习记录，可以选择主动练习。", source=self.manifest.name)
                return
            await self._offer_after_solved(session, owner_id, skill_id=skill_for_problem(verified[0]),
                stream=stream, problem_text=verified[0].display_latex,
                purpose="C" if gaps else "E" if due else "D", prerequisite_skill_ids=gaps, review_due=due)
        elif command in {"resume_problem", "start_diagnostic", "skip_diagnostic", "end_problem"}:
            await self._learning_control(session, owner_id, client_session_id, command, verified, stream)
        elif command == "submit_problem":
            await self._submit_problem(session, owner_id, payload, expected_version, idempotency_key, stream)
        elif command in ("submit_attempt", "clarify_attempt"):
            await self._submit_attempt(
                session, owner_id, {**payload, "answer": payload.get("answer", payload.get("text", ""))}, expected_version, idempotency_key,
                verified, assistance, stream,
            )
        elif command == "request_hint":
            await self._prompt_command(
                session, owner_id, CycleCommand.REQUEST_HINT, "提示", expected_version, idempotency_key,
                verified, assistance, stream, student_request=str(payload.get("student_request", "")),
            )
        elif command == "request_explanation":
            await self._prompt_command(
                session, owner_id, CycleCommand.REQUEST_EXPLANATION, "讲解", expected_version, idempotency_key,
                verified, assistance, stream, student_request=str(payload.get("student_request", "")),
            )
        elif command == "request_example":
            await self._prompt_command(
                session, owner_id, CycleCommand.REQUEST_EXAMPLE, "示例", expected_version, idempotency_key,
                verified, assistance, stream, student_request=str(payload.get("student_request", "")),
            )
        elif command == "request_solution":
            # L5: the planner fails closed without a verified ref; the
            # projector/writer/guard only then see the full solution.
            await self._prompt_command(
                session, owner_id, CycleCommand.SOLUTION_SHOWN_PERMITTED, "完整解析", expected_version, idempotency_key,
                verified, assistance, stream, student_request=str(payload.get("student_request", "")),
            )
        elif command == "accept_practice_offer":
            await self._accept_practice_offer(
                session, owner_id, client_session_id, payload,
                expected_version, idempotency_key, stream,
            )
        elif command == "decline_practice_offer":
            await self._decline_practice_offer(
                session, owner_id, payload, expected_version, idempotency_key, stream,
            )
        elif command == "clarify_problem":
            await self._clarify_and_ground(
                session,
                owner_id,
                str(payload.get("text", "")),
                expected_version,
                idempotency_key,
                stream,
            )
        elif command in (
            "cancel_turn",
        ):
            await self._simple_step(session, owner_id, command, expected_version, idempotency_key, stream)
        else:
            try:
                rejected = CycleCommand(command)
            except ValueError:
                rejected = CycleCommand.SUBMIT_PROBLEM
            raise InvalidTransitionError(session.state, rejected)

    async def _submit_problem(
        self,
        session: TutoringSession,
        owner_id: str,
        payload: dict[str, Any],
        expected_version: int | None,
        idempotency_key: str,
        stream: MathTutorEventSink,
        constraint: ConstraintResult | None = None,
        task_purpose: str = "practice",
    ) -> None:
        text = str(payload.get("text", ""))
        constraint = constraint or evaluate_constraints(text)
        if await self._show_math_boundary(session, owner_id, text, constraint, stream):
            return
        if constraint.reason == "resource_limit":
            await stream.error("这道表达式超出计算预算，请缩短式子或减小数值后重试。",
                               source=self.manifest.name, metadata={"error_code": "RESOURCE_LIMIT"})
            return
        if (
            constraint.status is ConstraintStatus.SOFT_FAIL
            and constraint.reason != "unsupported_family"
            and session.state == CycleState.PROBLEM_RECEIVED
        ):
            await self._chat_message(
                session,
                constraint.raw_text,
                (),
                stream,
                owner_id=owner_id,
                unstructured_math=True,
            )
            return
        if session.state == CycleState.GROUNDING:
            await self._ground_problem(
                session, owner_id, text, stream, constraint=constraint
            )
            return
        if session.state == CycleState.AWAITING_CLARIFICATION:
            await self._clarify_and_ground(
                session,
                owner_id,
                text,
                expected_version,
                idempotency_key,
                stream,
                constraint=constraint,
            )
            return
        await self._step(
            owner_id,
            session,
            CycleCommand.SUBMIT_PROBLEM,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        await self._ground_problem(
            session, owner_id, text, stream, constraint=constraint, task_purpose=task_purpose
        )

    async def _clarify_and_ground(
        self,
        session: TutoringSession,
        owner_id: str,
        text: str,
        expected_version: int | None,
        idempotency_key: str,
        stream: MathTutorEventSink,
        constraint: ConstraintResult | None = None,
    ) -> None:
        await self._step(
            owner_id,
            session,
            CycleCommand.CLARIFY_PROBLEM,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        await self._ground_problem(
            session, owner_id, text, stream, constraint=constraint
        )

    async def _ground_problem(
        self,
        session: TutoringSession,
        owner_id: str,
        text: str,
        stream: MathTutorEventSink,
        constraint: ConstraintResult | None = None,
        task_purpose: str = "practice",
    ) -> None:
        """Complete GROUNDING in the same turn: parse is a tool, not a wait state."""
        if session.state != CycleState.GROUNDING:
            raise InvalidTransitionError(session.state, CycleCommand.GROUNDING_OK)
        constraint = constraint or evaluate_constraints(text)
        if await self._show_math_boundary(session, owner_id, text, constraint, stream):
            return
        if constraint.reason == "resource_limit":
            await self._step(owner_id, session, CycleCommand.GROUNDING_UNSUPPORTED)
            await stream.error("这道表达式超出计算预算，请缩短式子或减小数值后重试。",
                               source=self.manifest.name, metadata={"error_code": "RESOURCE_LIMIT"})
            return
        logger.info(
            "tutor_orchestration state=grounding constraint=%s reason=%s",
            constraint.status.value,
            constraint.reason,
        )
        if constraint.status is ConstraintStatus.NEED_CLARIFICATION:
            transition = await self._step(owner_id, session, CycleCommand.GROUNDING_AMBIGUOUS)
            await self._emit(
                stream,
                session,
                transition,
                constraint.clarification_prompt,
                extra={"action": "ambiguous"},
            )
            return
        if (
            constraint.status is ConstraintStatus.SOFT_FAIL
            and constraint.reason != "unsupported_family"
        ):
            if CycleCommand.CANCEL_TURN in allowed_next_commands(session.state):
                await self._step(owner_id, session, CycleCommand.CANCEL_TURN)
            await self._chat_message(
                session,
                constraint.raw_text,
                (),
                stream,
                owner_id=owner_id,
                unstructured_math=True,
            )
            return
        if (
            constraint.status is ConstraintStatus.SOFT_FAIL
            and constraint.reason == "unsupported_family"
        ) or (
            constraint.parse is not None and constraint.parse.kind == "unsupported"
        ):
            transition = await self._step(owner_id, session, CycleCommand.GROUNDING_UNSUPPORTED)
            _, recovery = await self._remember_recovery(session, owner_id, constraint.raw_text, mathematical=True)
            if self.chat_responder is not None and getattr(self.chat_responder, "is_configured", True):
                await self._chat_message(session, constraint.raw_text, (), stream,
                    owner_id=owner_id, unstructured_math=True)
                return
            message = "这道题还不能逐步核验。原题已保留；继续讨论原题时，讲解会标为未经核验。"
            if recovery:
                message += f"\n\n可以先练一道相关基础题：\\( {recovery['text']} \\)。{recovery['relation']}"
            await self._emit(
                stream,
                session,
                transition,
                message,
                extra={"action": "unsupported"},
            )
            return
        if constraint.status is ConstraintStatus.HARD_FAIL:
            transition = await self._step(owner_id, session, CycleCommand.GROUNDING_UNSUPPORTED)
            await self._emit(
                stream,
                session,
                transition,
                "请发一道题目，或问一个数学问题。",
                extra={"action": "unsupported"},
            )
            return
        result = await self.service.submit_problem(constraint.solver_text)
        logger.info(
            "tutor_orchestration state=grounding parser_kind=%s next_command=%s",
            result.kind,
            {
                "verified": "problem_complete",
                "ambiguous": "request_clarification",
                "unsupported": "grounding_unsupported",
                "unverified_blocked": "verification_failed",
                "unparseable": "soft_fail",
            }.get(result.kind, result.kind),
        )
        if result.kind in {"ambiguous", "unparseable"}:
            if CycleCommand.CANCEL_TURN in allowed_next_commands(session.state):
                await self._step(owner_id, session, CycleCommand.CANCEL_TURN)
            await self._chat_message(
                session,
                constraint.raw_text,
                (),
                stream,
                owner_id=owner_id,
                unstructured_math=True,
            )
            return
        if result.kind == "unsupported":
            logger.info("problem_grounding unsupported reason=%s", result.reason)
            transition = await self._step(owner_id, session, CycleCommand.GROUNDING_UNSUPPORTED)
            if result.code == "resource_limit":
                await stream.error("这道表达式超出计算预算，请缩短式子或减小数值后重试。",
                                   source=self.manifest.name, metadata={"error_code": "RESOURCE_LIMIT"})
                return
            _, recovery = await self._remember_recovery(session, owner_id, constraint.raw_text, mathematical=True)
            if self.chat_responder is not None and getattr(self.chat_responder, "is_configured", True):
                await self._chat_message(session, constraint.raw_text, (), stream,
                    owner_id=owner_id, unstructured_math=True)
                return
            message = "这道题还不能逐步核验。原题已保留；继续讨论原题时，讲解会标为未经核验。"
            if recovery:
                message += f"\n\n可以先练一道相关基础题：\\( {recovery['text']} \\)。{recovery['relation']}"
            await self._emit(
                stream,
                session,
                transition,
                message,
                extra={"action": "unsupported"},
            )
            return
        if result.kind == "unverified_blocked":
            logger.info("problem_grounding unverified reason=%s", result.reason)
            await self._step(owner_id, session, CycleCommand.GROUNDING_OK)
            transition = await self._step(owner_id, session, CycleCommand.VERIFICATION_FAILED)
            await self._emit(
                stream,
                session,
                transition,
                "这道题没有通过独立验证，暂时不能继续辅导。",
                extra={"action": "unverified"},
            )
            return
        await self._step(owner_id, session, CycleCommand.GROUNDING_OK)
        assert result.problem is not None
        # HTTP session restoration must not expose the new task either if
        # forecast persistence fails. Publish its binding only after this.
        await self._prepare_presentation(owner_id, session, (result.problem, result.candidate, result.verified_ref))
        session.problem_id = result.problem.problem_id
        transition = await self._step(
            owner_id,
            session,
            CycleCommand.VERIFICATION_VERIFIED,
            problem_id=result.problem.problem_id,
        )
        await self.sessions.store_verified(
            owner_id,
            session.cycle.cycle_id,
            (result.problem, result.candidate, result.verified_ref),
        )
        teaching = await self._teaching_context(owner_id, session, (result.problem, result.candidate, result.verified_ref))
        if teaching.get("diagnostic_item"):
            task_purpose = "diagnostic"  # also applies to interrupted grounding resumed after restart
        teaching["task_context"].update(original_statement=constraint.raw_text or text,
            full_statement=constraint.raw_text or text, statement_provenance="owner_source",
            source={"kind": "diagnostic" if task_purpose == "diagnostic" else "manual", "reference": None})
        await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, teaching)
        await self._cycle_fact(owner_id, session, (result.problem, result.candidate, result.verified_ref), "problem_started", task_purpose=task_purpose)
        await self._emit(
            stream,
            session,
            transition,
            f"题目已解析并验证：{result.problem.display_latex}",
            extra={
                "action": "verified",
                "problem_latex": result.problem.display_latex,
                "problem_type": result.problem.problem_type,
            },
        )

    async def _submit_attempt(
        self,
        session: TutoringSession,
        owner_id: str,
        payload: dict[str, Any],
        expected_version: int | None,
        idempotency_key: str,
        verified: tuple | None,
        assistance: CycleAssistance,
        stream: MathTutorEventSink,
        *,
        raw_text_override: str | None = None,
        offer_after: bool = True,
        followup_command: str = "",
        followup_request: str = "",
    ) -> None:
        workflow = self._attempt_workflow()
        return await workflow.submit_attempt(session, owner_id, payload, expected_version, idempotency_key, verified, assistance, stream, raw_text_override=raw_text_override, offer_after=offer_after, followup_command=followup_command, followup_request=followup_request)

    # ------------------------------------------------- practice offer flow

    async def _offer_after_solved(
        self,
        session: TutoringSession,
        owner_id: str,
        *,
        skill_id: str | None,
        stream: MathTutorEventSink,
        reflected: bool = False,
        problem_text: str = "",
        purpose: str | None = None,
        prerequisite_skill_ids: tuple[str, ...] = (),
        review_due: bool = False,
    ) -> None:
        workflow = self._practice_workflow()
        return await workflow.offer_after_solved(session, owner_id, skill_id=skill_id, stream=stream, reflected=reflected, problem_text=problem_text, purpose=purpose, prerequisite_skill_ids=prerequisite_skill_ids, review_due=review_due)

    async def _prompt_command(
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
        workflow = self._intent_workflow()
        return await workflow.prompt_command(session, owner_id, command, label, expected_version, idempotency_key, verified, assistance, stream, student_request=student_request, resume_checkpoint=resume_checkpoint)

    async def recover_expression(self, request, checkpoint, stream):
        """Resume only the persisted expression checkpoint, never re-assess input."""
        owner_id = request.owner.student_id
        session = await self.sessions.load(owner_id, request.session_id)
        verified = await self.sessions.load_verified(owner_id, session.cycle.cycle_id)
        if (not verified or verified[0].content_hash != checkpoint["problem_revision"]
                or session.version != checkpoint["cycle_version"]):
            await stream.error("原题状态已变化，未重放旧教学动作。", source=self.manifest.name)
            return
        if checkpoint["phase"] == "action_committed":
            from mathtutor.application.tutor_runtime import current_turn
            turn = current_turn.get()
            if turn:
                turn.continuation_context = checkpoint.get("continuation_context", "")
            approved = checkpoint["approved_utterance"]
            await self._dialogue(stream, session, approved["text"], approved["action"], approved["assistance_level"])
            if checkpoint["command"] == "request_solution" and approved["assistance_level"] == 5:
                await self._offer_after_solved(session, owner_id, skill_id=skill_for_problem(verified[0]),
                    problem_text=verified[0].display_latex, stream=stream, purpose="B")
            return
        assistance = await self.sessions.load_assistance(owner_id, session.cycle.cycle_id)
        from mathtutor.application.student_contract import REVIEW_STATES
        if session.state in REVIEW_STATES:
            await self._review_action(request, session, checkpoint["command"], verified, assistance, stream,
                student_request=checkpoint["student_request"], resume_checkpoint=checkpoint)
            return
        await self._prompt_command(session, owner_id, USER_COMMANDS[checkpoint["command"]], "恢复已请求的教学表达",
            session.version, f"expression:{checkpoint['request_id']}", verified, assistance, stream,
            student_request=checkpoint["student_request"], resume_checkpoint=checkpoint)

    async def _realize_utterance(
        self,
        session: TutoringSession,
        verified: tuple | None,
        action,
        *,
        restore_solution: bool = False,
        student_request: str = "",
        owner_id: str = "",
        continuing: bool = False,
    ):
        """DisclosureProjector → Writer → Guard (Phase 3A-D).

        The planner already chose and sanctioned ``action`` (BEFORE the
        state machine stepped). The writer only sees the projected context;
        the guard verifies the final text against the verified solution.
        Every level below L5 is structurally incapable of carrying answer
        content. ``verified`` comes from the STORE (restored at turn start).
        """
        problem, candidate, ref = verified if verified else (None, None, None)
        from mathtutor.pedagogy.teaching_plan import choose_plan, current_subgoal
        teaching_context = await self._teaching_context(owner_id, session, verified) if owner_id and verified else None
        plan = None
        if teaching_context:
            tracking = getattr(self.sessions, "student_state", None)
            if tracking is not None:
                from mathtutor.application.evidence_projection import teaching_evidence
                teaching_context["learner_evidence"] = teaching_evidence(await tracking.events(owner_id), teaching_context["skill_ids"])
                presentation = await tracking.presentation(owner_id, session.cycle.cycle_id)
                forecast = presentation.get("frozen_forecast") if presentation else None
                if forecast:
                    teaching_context["dkt_forecast"] = forecast
            if continuing and teaching_context.get("last_plan"):
                from mathtutor.pedagogy.teaching_plan import TeachingPlan
                plan = TeachingPlan(**teaching_context["last_plan"])
            else:
                teaching_context, plan = choose_plan(teaching_context, action, student_request)
            action = action.model_copy(update={"effective_assistance_level": plan.max_assistance_level,
                "target_step_index": min(teaching_context["current_subgoal_index"], max(0, len(candidate.steps) - 1))})
            await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, teaching_context)
        disclosure = self.projector.project(
            ref,
            candidate,
            action,
            concept_hint=_concept_hint_for(problem),
            strategy_hint=_strategy_hint_for(problem),
        )
        problem_view = (
            PublicProblemView.of(problem) if problem is not None else None
        )
        if problem_view is not None:
            problem_view = problem_view.model_copy(update={"student_request": student_request,
                "skill_id": skill_for_problem(problem),
                "personal_memory": await self._personal_memory_context(owner_id)})
            review_service = getattr(getattr(self, "knowledge", None), "state", None)
            review_service = getattr(review_service, "stage_review", None)
            if review_service and owner_id:
                from mathtutor.application.stage_review import STYLES
                stage = await review_service.read(str(owner_id))
                style = stage.get("preferences", {}).get("style", "default")
                problem_view = problem_view.model_copy(update={"review_style": STYLES.get(style, STYLES["default"])})
            if plan:
                from mathtutor.pedagogy.student_evidence_view import progress_view, assessment_view
                example = await self._verified_example(problem) if action.action == "SHOW_EXAMPLE" else None
                if action.action == "SHOW_EXAMPLE" and ("错" in student_request or teaching_context.get("stuck_count", 0) >= 2):
                    from mathtutor.pedagogy.error_example import build_teacher_error_example, TeacherErrorExampleUnavailable
                    try:
                        error_example = await build_teacher_error_example(skill_id=skill_for_problem(problem),
                            verification_backend=self.service.verification_backend,
                            release_service=getattr(self.practice_service, "_release_service", None))
                        teaching_context["teacher_error_example"] = {**error_example.model_dump(), "awaiting_response": True}
                        example = {"kind": "teacher_error_example", "problem": error_example.problem_text,
                                   "wrong_step": error_example.wrong_step, "instruction": error_example.instruction}
                        from dataclasses import replace
                        plan = replace(plan, strategy="teacher_error_example", question_goal="指出教师故意设置的错误，并写出修正步骤", response_kind="error_analysis")
                    except TeacherErrorExampleUnavailable:
                        pass
                problem_view = problem_view.model_copy(update={"teaching_plan": plan.public(),
                    "task_context": {key: teaching_context.get("task_context", {}).get(key, "unknown") for key in
                        ("full_statement", "task_kind", "task_objective", "domain", "units", "precision", "expected_answer_shape", "verification_capability")},
                    "language_understanding": ({key: teaching_context.get("language_understanding", {}).get(key) for key in
                        ("intent", "confusion", "resolved", "scope", "source")} if student_request and
                        teaching_context.get("language_input_hash") == content_hash({"text": student_request}) else {}),
                    "current_subgoal": current_subgoal(teaching_context),
                    "verified_progress": progress_view(teaching_context["progress"][-4:]),
                    "recent_assessments": assessment_view(teaching_context["assessments"][-3:]), "approved_example": example})
        document_context = await self._document_context_for_action(
            session, action, problem
        )
        from mathtutor.application.tutor_runtime import current_turn
        turn = current_turn.get()
        if turn is not None:
            turn.continuation_context = json.dumps({"cycle_id": str(session.cycle.cycle_id),
                                                   "action": action.model_dump(mode="json"),
                                                   "student_request": student_request})
        writer = self.writer
        from mathtutor.pedagogy.tutor_writer import TemplateTutorWriter
        if restore_solution:
            writer = TemplateTutorWriter()
        candidate_text = await writer.write(
            problem_view=problem_view,
            disclosure=disclosure,
            policy=self.policy,
            action=action,
            document_context=document_context,
        )
        if candidate_text.writer_version not in {TemplateTutorWriter.writer_version, "mt-grounded-template-v2"}:
            # Model prose never carries its own figures (canvas drawing skill).
            from mathtutor.skills.canvas_drawing.enforce import sanitize_figures
            clean, removed = sanitize_figures(candidate_text.text)
            if removed:
                from mathtutor.application.tutor_runtime import note_turn
                note_turn(figures={"removed": removed})
                candidate_text = candidate_text.model_copy(update={"text": clean})
        if turn is not None and turn.conversation_id and owner_id:
            live = await self.sessions.load(owner_id, turn.conversation_id)
            if (live is None or live.cycle.cycle_id != session.cycle.cycle_id or live.version != session.version):
                # Recheck after model latency, before committing any approved
                # delivery. A response for an old focus cannot enter a new task.
                raise RuntimeError("teaching binding changed before delivery")
        utterance = self.guard.guard_or_fallback(
            candidate=candidate_text,
            candidate_solution=candidate,
            disclosure=disclosure,
            action=action,
        )
        math_check = None
        if candidate_text.writer_version not in {TemplateTutorWriter.writer_version, "mt-grounded-template-v2"} and not utterance.fallback_used:
            # Model formulas must pass verify_math against the bound problem.
            # A refuted step never reaches the student: use the verified template.
            from mathtutor.application.math_claims import anchor_for, certify
            math_check = await certify(utterance.text, self.service.verification_backend, anchor=anchor_for(problem))
            checked_text = utterance.text
            from mathtutor.application.tutor_runtime import note_turn
            note_turn(formulas=math_check.counts(), template_fallback=bool(math_check.refuted))
            if math_check.refuted:
                candidate_text = await TemplateTutorWriter().write(problem_view=problem_view, disclosure=disclosure,
                    policy=self.policy, action=action, document_context=document_context)
                utterance = self.guard.guard_or_fallback(candidate=candidate_text, candidate_solution=candidate,
                    disclosure=disclosure, action=action)
                math_check = None
        if plan:
            from mathtutor.pedagogy.quality_guard import enforce_teaching_quality
            utterance = await enforce_teaching_quality(utterance, candidate_text, problem_view, disclosure, action, self.policy)
            from mathtutor.application.teaching_intent import negates_solution
            if negates_solution(student_request) and self.guard._detect_leak(utterance.text, candidate, target_answer_only=True) is not None:
                # Even a verified one-step demonstration may be the final
                # answer. An explicit "no answer" request narrows disclosure.
                safe_action = action.model_copy(update={"action": "ASK_STUDENT", "effective_assistance_level": 1,
                    "solution_visibility": "hint", "target_step_index": None})
                safe_disclosure = self.projector.project(ref, candidate, safe_action,
                    concept_hint=_concept_hint_for(problem), strategy_hint=_strategy_hint_for(problem))
                from mathtutor.pedagogy.tutor_writer import TemplateTutorWriter
                safe_view = problem_view.model_copy(update={"teaching_plan": {**plan.public(), "support_mode": "guided"}, "approved_example": None})
                safe_text = await TemplateTutorWriter().write(problem_view=safe_view, disclosure=safe_disclosure,
                    policy=self.policy, action=safe_action)
                candidate_text = safe_text
                utterance = self.guard.guard_or_fallback(candidate=safe_text, candidate_solution=candidate,
                    disclosure=safe_disclosure, action=safe_action)
            if not restore_solution:
                if not continuing:
                    teaching_context["help_without_progress"] += int(utterance.assistance_level > 0)
                    from dataclasses import replace
                    teaching_context["help_fingerprints"].append(
                        replace(plan, max_assistance_level=utterance.assistance_level).fingerprint)
                teaching_context["last_plan"] = {**plan.public(), "max_assistance_level": utterance.assistance_level}
                delivery_id = str(action.action_id)
                if continuing:
                    delivery_id += f":continuation:{turn.turn_id if turn else uuid4()}"
                target_exposed = self.guard._detect_leak(utterance.text, candidate, target_answer_only=True) is not None
                delivery = {"session_id": str(session.session_id), "problem_id": str(problem.problem_id),
                    "problem_revision": problem.content_hash, "item_family_id": problem.problem_type,
                    "skill_ids": teaching_context["skill_ids"], "subgoal_id": current_subgoal(teaching_context)["id"],
                    "help_kind": {"SHOW_SOLUTION": "solution", "EXPLAIN_CONCEPT": "explanation", "SHOW_EXAMPLE": "example"}.get(utterance.action, "hint"),
                    "target_answer_exposed": target_exposed, "delivery_id": delivery_id,
                    "request_id": turn.turn_id if turn is not None else delivery_id,
                    "target_answer_authorized": action.action == "SHOW_SOLUTION"}
                await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, teaching_context)
                if utterance.assistance_level > 0:
                    await self.sessions.teaching.delivery(owner_id, session.cycle.cycle_id, delivery_id, delivery)
                tracking = getattr(self.sessions, "student_state", None)
                if tracking is not None and utterance.assistance_level > 0:
                    for phase in ("help_requested", "help_committed"):
                        await tracking.record_help(owner_id, event_id=f"{delivery_id}:{phase}",
                            cycle_id=str(session.cycle.cycle_id), event_type=phase, **delivery)
                # Publishing begins immediately after this checkpoint. If an
                # ACK is lost, conservatively treat these approved bytes as seen.
                if utterance.assistance_level > 0:
                    await self.mark_delivery(owner_id, delivery_id, "possibly_exposed")
                if turn is not None and utterance.assistance_level > 0:
                    from mathtutor.application.network_chat import merge_continuation_context
                    merge_continuation_context(turn, {"delivery_id": delivery_id})
        if candidate_text.writer_version not in {TemplateTutorWriter.writer_version, "mt-grounded-template-v2"} and not utterance.fallback_used:
            # Disclosure and equation guards do not verify every prose claim.
            # Persist this notice with approved bytes so history and continuation
            # retain the same mathematical certainty boundary as live delivery.
            from mathtutor.application.math_claims import anchor_for, annotate, certify
            if math_check is None or checked_text != utterance.text:
                # Later guards rewrote the text: count what is actually shown.
                math_check = await certify(utterance.text, self.service.verification_backend, anchor=anchor_for(problem))
            utterance = utterance.model_copy(update={"text": annotate(utterance.text, math_check)})
        if turn is not None and utterance.action == "SHOW_SOLUTION" and utterance.assistance_level == 5:
            # The turn can also contain an assessment or an invitation. Store
            # the guarded answer separately; reviewing it must not replay those.
            from mathtutor.application.network_chat import merge_continuation_context
            merge_continuation_context(turn, {"approved_solution_text": utterance.text})
        if (teaching_context and teaching_context.get("pending_expression") and not restore_solution and not continuing
                and (turn is None or teaching_context["pending_expression"]["request_id"] == turn.turn_id)):
            # Approved bytes form a durable outbox. A crash before action commit
            # resumes these exact bytes, with the original action/delivery IDs.
            teaching_context["pending_expression"].update(phase="expression_approved",
                approved_utterance=utterance.model_dump(),
                continuation_context=getattr(turn, "continuation_context", ""))
            await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, teaching_context)
        return utterance

    async def mark_delivery(self, owner_id, delivery_id, status):
        row = await self.sessions.teaching.mark_delivery(owner_id, delivery_id, status)
        tracking = getattr(self.sessions, "student_state", None)
        if row is not None and tracking is not None:
            phase = f"help_{status}"
            await tracking.record_help(owner_id, event_id=f"{delivery_id}:{phase}", event_type=phase,
                **{k: v for k, v in row.items() if k != "status"})

    async def _verified_example(self, problem):
        from mathtutor.pedagogy.tutor_writer import _render_full_solution
        from mathtutor.domain.tutoring import TutorAction
        text = {"arithmetic": "17/5 + 3/10", "polynomial": "3a+2(a+4)",
                "linear": "5z+4=39", "quadratic": "z^2-12z+35=0",
                "linear_system": "2u+v=19;u-v=2", "linear_inequality": "3y-2>7",
                "quadratic_inequality": "y^2-7y+12<0"}.get(problem.problem_type)
        if not text:
            return None
        result = await self.service.submit_problem(text)
        if result.kind != "verified":
            return None
        full = self.projector.project(result.verified_ref, result.candidate,
            TutorAction(action="SHOW_SOLUTION", effective_assistance_level=5, solution_visibility="full"))
        return {"problem": result.problem.display_latex, "solution": _render_full_solution(full.full_solution)}

    async def _learning_control(self, session, owner_id, client_id, command, verified, stream):
        from datetime import datetime, timezone
        context = await self._teaching_context(owner_id, session, verified)
        if command == "end_problem":
            await self._step(owner_id, session, CycleCommand.CANCEL_TURN)
            if context:
                context["lifecycle"] = "ended"
                await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
                await self._cycle_fact(owner_id, session, verified, "problem_ended", lifecycle_status="exited")
            await self._dialogue(stream, session, "已结束当前题目的辅导，记录会保留。", "END_PROBLEM")
            return
        if not context:
            await stream.error("请先提供要辅导的题目。", source=self.manifest.name)
            return
        if command in {"resume_problem", "skip_diagnostic"}:
            parent_id = context.get("resume_parent_cycle_id")
            if not parent_id:
                await stream.error("当前没有待返回的原题。", source=self.manifest.name)
                return
            if command == "skip_diagnostic":
                context["diagnosis"]["status"] = "skipped"
                context["lifecycle"] = "skipped"
                await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
                parent_context = await self.sessions.teaching.load(owner_id, parent_id)
                if context.get("understanding_check"):
                    for row in reversed(parent_context.get("understanding_checks", [])):
                        if row.get("status") == "started":
                            row.update(status="skipped", check_cycle_id=str(session.cycle.cycle_id))
                            break
                else:
                    parent_context["diagnosis"] = context["diagnosis"]
                await self.sessions.teaching.save(owner_id, parent_id, parent_context)
            parent = await self.sessions.focus_cycle(owner_id, client_id, parent_id)
            await self._dialogue(stream, parent,
                ("已返回原题。检查题跳过不会算作答错。" if context.get("understanding_check") else "已返回原题。诊断跳过不计为答错。")
                if command == "skip_diagnostic" else "已返回原题，继续之前的小目标。", "RESUME_PROBLEM")
            return
        if context.get("diagnostic_item") or context["diagnosis"]["status"] == "running":
            await stream.error("相关知识诊断已经开始。你可以继续作答，也可以随时跳过。", source=self.manifest.name)
            return
        # Short, optional cold start tied to the actual problem family.
        # Each item goes through the same independent verifier as a normal problem.
        family = verified[0].problem_type
        prerequisites = ["8-(-3)", "3(a+2)-2a"]
        targets = {"arithmetic": ["3/4+1/2"], "polynomial": ["2(a+3)+a"],
                   "linear": ["3z+2=17"], "quadratic": ["z^2-7z+12=0"],
                   "linear_system": ["u+v=9;u-v=3"]}.get(family, [])
        context["diagnosis"] = {"status": "running", "can_skip": True, "question_count": len(prerequisites + targets),
            "started_at": datetime.now(timezone.utc).isoformat(), "answered": 0, "results": []}
        await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        await self._start_diagnostic_item(owner_id, client_id, str(session.cycle.cycle_id),
            prerequisites + targets, context["diagnosis"], stream)

    async def _assess_teacher_error(self, session, owner_id, context, answer, expected_version, request_id, stream):
        workflow = self._attempt_workflow()
        return await workflow.assess_teacher_error(session, owner_id, context, answer, expected_version, request_id, stream)

    async def _start_understanding_check(self, owner_id, client_id, session, verified, stream):
        """Move to one fresh, verified check, keeping the original task intact."""
        from datetime import datetime, timezone
        context = await self._teaching_context(owner_id, session, verified)
        if context.get("understanding_check") or context.get("diagnostic_item"):
            await self._dialogue(stream, session, "继续这道检查题就好。先写出你能确定的一步。", "UNDERSTANDING_CHECK")
            return
        from mathtutor.application.understanding_check import check_statement
        from mathtutor.application.llm_candidate_generator import candidate_is_distinct
        excluded = [verified[0].display_latex, *(row["statement"] for row in context.get("understanding_checks", []))]
        ordinal = context.get("understanding_checks_started", 0)
        tracking = getattr(self.sessions, "student_state", None)
        history = await tracking.events(owner_id) if tracking else []
        used_revisions = {event.problem_revision for event in history}
        # Every parent has its own counter. Advance beyond earlier diagnostic
        # items in this family too, so a bounded search remains useful after
        # the student has completed more than five checks across parent tasks.
        previous_diagnostic_revisions = {event.problem_revision for event in history
            if event.item_family_id == verified[0].problem_type and event.task_purpose == "diagnostic"}
        ordinal = max(ordinal, len(previous_diagnostic_revisions))
        selected = None
        selected_verified = None
        for offset in range(5):
            statement = check_statement(verified[0].problem_type, ordinal + offset)
            if not candidate_is_distinct(statement, excluded):
                continue
            result = await self.service.submit_problem(statement)
            if result.kind == "verified" and result.problem.content_hash not in used_revisions:
                selected = statement
                selected_verified = (result.problem, result.candidate, result.verified_ref)
                ordinal += offset
                break
        if selected is None:
            await self._dialogue(stream, session, "理解反馈已记下。暂时没有准备好新的可核验检查题，先把原题的一步写出来，我来检查。", "SELF_REPORT")
            return
        context["understanding_checks_started"] = ordinal + 1
        context.setdefault("understanding_checks", []).append({"statement": selected, "status": "started"})
        await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        diagnosis = {"status": "running", "can_skip": True, "question_count": 1,
                     "started_at": datetime.now(timezone.utc).isoformat(), "answered": 0, "results": [],
                     "kind": "understanding_check"}
        await self._start_diagnostic_item(owner_id, client_id, str(session.cycle.cycle_id),
            [selected], diagnosis, stream, understanding_check=True, verified_seed=selected_verified)

    async def _start_diagnostic_item(self, owner_id, client_id, parent_id, items, diagnosis, stream, *, understanding_check=False, verified_seed=None):
        from mathtutor.pedagogy.teaching_plan import initial_context
        if verified_seed is None:
            result = await self.service.submit_problem(items[0])
            if result.kind != "verified":
                await stream.error("本次诊断题暂时不可用，已保留原题。", source=self.manifest.name)
                return
            verified_seed = (result.problem, result.candidate, result.verified_ref)
        seed = initial_context(verified_seed[0], verified_seed[1], verified_solution_ref=verified_seed[2])
        seed.update(pending_diagnostic_initialization=True, diagnostic_item=True,
            resume_parent_cycle_id=parent_id, diagnostic_remaining=items[1:],
            client_session_id=client_id, diagnosis=diagnosis)
        if understanding_check:
            seed["understanding_check"] = True
        item = await self.sessions.start_new_cycle(owner_id, client_id, teaching_context=seed)
        await self._submit_problem(item, owner_id, {"text": items[0]}, None, "", stream, task_purpose="diagnostic")
        verified = await self.sessions.load_verified(owner_id, item.cycle.cycle_id)
        context = await self._teaching_context(owner_id, item, verified)
        if context is None:
            await self.sessions.focus_cycle(owner_id, client_id, parent_id)
            await stream.error("本次诊断题暂时不可用，已保留原题。", source=self.manifest.name)
            return
        await self._dialogue(stream, item,
            "好，用一道需要两步的检查题试试。原题会保留，做完就回去。先写出你能确定的一步。" if understanding_check
            else "这是可跳过的相关知识诊断，不计为考试。请写出你的答案或一步思路。",
            "UNDERSTANDING_CHECK" if understanding_check else "DIAGNOSTIC")

    async def _advance_diagnostic(self, session, owner_id, context, assessment, stream):
        if context.get("understanding_check"):
            if assessment.correctness is not Correctness.CORRECT:
                return  # partial progress and a verified error stay on this check
            diagnosis = context["diagnosis"]
            diagnosis.update(status="completed", can_skip=False, answered=1)
            diagnosis["results"] = [{"problem_id": context["problem_id"], "skill_ids": context["skill_ids"],
                                     "correctness": "correct"}]
            parent_id = context["resume_parent_cycle_id"]
            parent_context = await self.sessions.teaching.load(owner_id, parent_id)
            for row in reversed(parent_context.get("understanding_checks", [])):
                if row.get("status") == "started":
                    row.update(status="completed", check_cycle_id=str(session.cycle.cycle_id),
                               assessment_id=str(assessment.attempt_id))
                    break
            await self.sessions.teaching.save(owner_id, parent_id, parent_context)
            await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
            parent = await self.sessions.focus_cycle(owner_id, context["client_session_id"], parent_id)
            await self._dialogue(stream, parent,
                "检查题的作答已通过验证，回到原题。你可以继续追问，或再练一道。" if parent_context.get("lifecycle") == "completed"
                else "检查题的作答已通过验证，回到原题。原题还要单独作答，先写出下一步。", "UNDERSTANDING_CHECK_COMPLETE")
            return
        if assessment.correctness in {Correctness.UNDETERMINED, Correctness.PARTIAL}:
            return
        diagnosis = context["diagnosis"]
        diagnosis["answered"] += 1
        diagnosis["results"].append({"problem_id": context["problem_id"],
            "skill_ids": context["skill_ids"], "correctness": assessment.correctness.value})
        items = list(context["diagnostic_remaining"])
        # One verified error triggers one smaller prerequisite check, bounded
        # to five total items; no global grade/ability label is inferred.
        if assessment.correctness is Correctness.INCORRECT and not diagnosis.get("branched"):
            items.insert(0, "5-(-2)")
            diagnosis["branched"] = True
            diagnosis["question_count"] += 1
        parent_id = context["resume_parent_cycle_id"]
        parent_context = await self.sessions.teaching.load(owner_id, parent_id)
        if not items:
            diagnosis["status"] = "completed"
            diagnosis["can_skip"] = False
        parent_context["diagnosis"] = diagnosis
        await self.sessions.teaching.save(owner_id, parent_id, parent_context)
        await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        if items:
            await self._start_diagnostic_item(owner_id, context["client_session_id"], parent_id, items, diagnosis, stream)
        else:
            parent = await self.sessions.focus_cycle(owner_id, context["client_session_id"], parent_id)
            await self._dialogue(stream, parent, "这组诊断已完成。已记录诊断作答，回到原题继续。", "DIAGNOSTIC_COMPLETE")

    async def _personal_memory_context(self, owner_id):
        """Fresh per-answer projection; management changes affect the next turn.

        Only the shared source provider touches persistence. This output
        context cannot append evidence or change the student model.
        """
        source = getattr(self, "personal_memory_source", None)
        if source is None or not owner_id:
            return None
        from mathtutor.application.tutor_runtime import note_turn
        try:
            result = await source.load_for_tutor(student_id=str(owner_id))
        except Exception:
            logger.warning("Personal memory retrieval unavailable")
            note_turn(memory={"status": "unavailable", "included_count": 0})
            return None
        context = result.payload
        note_turn(memory={
            "status": "disabled_by_user" if result.disabled_by_user else "loaded" if context and context.entries else "empty",
            "included_count": len(context.entries) if context else 0,
            "memory_ids": [str(entry.memory_id) for entry in context.entries] if context else [],
            "detail": result.detail,
        })
        return context

    async def _document_context_for_action(self, session, action, problem):
        """Assemble USER_DOCUMENTS for hint/explain when the policy allows it.

        REQUEST_HINT / EXPLAIN_CONCEPT already list documents as OPTIONAL in
        RetrievalPolicy. Practice generation already goes through the
        assembler; this reuses the same Chinese query pack so tutoring
        language can cite the student's notes too.
        """
        if self.practice_service is None:
            return None
        action_name = getattr(action, "action", "")
        if action_name not in {"GIVE_HINT", "EXPLAIN_CONCEPT"}:
            return None
        from mathtutor.domain.retrieval_policy import RetrievalIntent

        intent = (
            RetrievalIntent.REQUEST_HINT
            if action_name == "GIVE_HINT"
            else RetrievalIntent.EXPLAIN_CONCEPT
        )
        skill_ids = ()
        problem_text = ""
        if problem is not None:
            try:
                skill_ids = (skill_for_problem(problem),)
            except ValueError:
                skill_ids = ()
            problem_text = getattr(problem, "display_latex", "") or ""
        try:
            assembled = await self.practice_service.assemble_for_intent(
                str(session.student_id),
                intent=intent,
                skill_ids=skill_ids,
                problem_text=problem_text,
            )
        except Exception:
            return None
        docs = assembled.user_documents
        if not docs:
            return None
        return docs if len(docs) > 1 else docs[0]

    async def _simple_step(
        self,
        session: TutoringSession,
        owner_id: str,
        command: str,
        expected_version: int | None,
        idempotency_key: str,
        stream: MathTutorEventSink,
    ) -> None:
        transition = await self._step(
            owner_id,
            session,
            USER_COMMANDS[command],
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        student_text = {
            "cancel_turn": "本题先停在这里。你可以直接发新题目，或继续提问。",
            "clarify_attempt": "你的作答我还没看懂，可以再写清楚一点吗？",
        }.get(command, "好的，我们继续。")
        await self._emit(
            stream,
            session,
            transition,
            student_text,
            extra={"action": "ASK_STUDENT" if command == "clarify_attempt" else "TUTOR_CHAT"},
        )

    # --------------------------------------------- practice offer (§7.7/§7.8)

    async def _accept_practice_offer(
        self,
        session: TutoringSession,
        owner_id: str,
        client_session_id: str,
        payload: dict[str, Any],
        expected_version: int | None,
        idempotency_key: str,
        stream: MathTutorEventSink,
    ) -> None:
        workflow = self._practice_workflow()
        return await workflow.accept_practice_offer(session, owner_id, client_session_id, payload, expected_version, idempotency_key, stream)

    async def _request_options(self, session, owner_id, verified, stream):
        """Persist exposure before returning options; typed answers cannot undo it."""
        from mathtutor.application.student_contract import session_contract
        contract = await session_contract(self.sessions, owner_id, session)
        context = await self.sessions.teaching.load(owner_id, session.cycle.cycle_id)
        if not verified or not context or context.get("response_mode") != "free_response":
            await stream.error("当前题目没有可切换的选项。", source=self.manifest.name)
            return
        if "submit_attempt" not in contract["allowed_next_inputs"]:
            await stream.error("当前阶段不能查看选项。", source=self.manifest.name)
            return
        if not context.get("choices"):
            from mathtutor.application.multiple_choice import make_choices
            try:
                choices = make_choices(verified[0], verified[1], salt=str(session.cycle.cycle_id))
            except ValueError:
                await stream.error("这道题暂不支持选项，可以继续自由作答或请求提示。", source=self.manifest.name)
                return
            # An exposure fact is conservative if delivery is interrupted.
            await self._cycle_fact(owner_id, session, verified, "options_exposed")
            context.update(choices=choices, options_exposed=True, observation_kind="diagnostic")
            await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
        await self._dialogue(stream, session, "已显示选项，本题后续作答记为诊断观察。要检查独立迁移，可以再做一道未见新题。", "SHOW_OPTIONS")

    async def _decline_practice_offer(
        self,
        session: TutoringSession,
        owner_id: str,
        payload: dict[str, Any],
        expected_version: int | None,
        idempotency_key: str,
        stream: MathTutorEventSink,
    ) -> None:
        workflow = self._practice_workflow()
        return await workflow.decline_practice_offer(session, owner_id, payload, expected_version, idempotency_key, stream)

    # ---------------------------------------------------------------- events

    async def _emit(
        self,
        stream: MathTutorEventSink,
        session: TutoringSession,
        transition: Any,
        message: str,
        detail: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """§13.3-style public event: student message + machine authority.

        Student-facing metadata ONLY — no candidate/verification/trace
        fields exist on this wire shape (see pedagogy.events)."""
        metadata = {
            "event_type": "tutor_action_committed",
            "cycle_id": str(session.cycle.cycle_id),
            "from_state": transition.from_state,
            "to_state": transition.to_state,
            "cycle_state": session.state.value,
            "cycle_state_version": session.version,
            "allowed_next_inputs": student_allowed_inputs(session.state),
            "trigger_command": transition.trigger_command,
            "detail": detail,
        }
        if extra:
            metadata.update(extra)
        visible = project_assistant_message(message)
        if visible is None:
            await self._emit_state(stream, session)
            return
        await stream.content(
            visible,
            source=self.manifest.name,
            stage=transition.to_state,
            metadata=metadata,
        )

    async def _emit_state(
        self, stream: MathTutorEventSink, session: TutoringSession
    ) -> None:
        """State-only event: the server's authority on what's next."""
        await stream.emit(
            MathTutorEvent(
                type=MathTutorEventType.CONTENT,
                source=self.manifest.name,
                content="",
                metadata={
                    "event_type": "cycle_state_committed",
                    "cycle_id": str(session.cycle.cycle_id),
                    "cycle_state": session.state.value,
                    "cycle_state_version": session.version,
                    "allowed_next_inputs": student_allowed_inputs(session.state),
                },
            )
        )


__all__ = [
    "MathTutorController",
    "MathTutorEvent",
    "MathTutorEventSink",
    "MathTutorEventType",
    "MathTutorManifest",
    "MathTutorRequest",
]
