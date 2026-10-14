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

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.verification_backend import (
    VerificationBackendError,
)
from mathtutor.application.state_machine import (
    CycleCommand,
    CycleState,
    InvalidTransitionError,
    STUDENT_TRANSITION_FAILURE,
    TutoringSession,
    VersionConflictError,
    allowed_next_commands,
)
from mathtutor.domain.hashing import content_hash
from mathtutor.domain.problem import MathProblem
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import (
    AttemptAssessment,
    Correctness,
)
from mathtutor.learning.diagnosis import diagnose
from mathtutor.learning.evidence import EvidenceFactory
from mathtutor.learning.projection import project_student_state
from mathtutor.learning.skills import skill_for_problem
from mathtutor.pedagogy.disclosure import SolutionDisclosureProjector
from mathtutor.pedagogy.exceptions import DisclosurePolicyViolation
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
from mathtutor.application.message_intent import (
    ConversationIntent,
    classify_user_message,
    fallback_tutor_reply,
)
from mathtutor.application.message_projection import (
    project_assistant_message,
    project_turn_error,
)
from mathtutor.repositories.session_store import (
    InMemorySessionStore,
    LearningCommit,
    SessionStoreProtocol,
)
from mathtutor.security.scopes import (
    StudentOwnerScope,
)
from mathtutor.solving import nodes as n
from mathtutor.solving import parse_problem
from mathtutor.solving.parser import ParsedProblem
from mathtutor.solving.strategies import _common as common
from mathtutor.solving.strategies import quadratic as q

USER_COMMANDS: dict[str, CycleCommand] = {
    "submit_problem": CycleCommand.SUBMIT_PROBLEM,
    "clarify_problem": CycleCommand.CLARIFY_PROBLEM,
    "submit_attempt": CycleCommand.SUBMIT_ATTEMPT,
    "clarify_attempt": CycleCommand.CLARIFY_ATTEMPT,
    "request_hint": CycleCommand.REQUEST_HINT,
    "request_explanation": CycleCommand.REQUEST_EXPLANATION,
    "request_example": CycleCommand.REQUEST_EXAMPLE,
    "request_solution": CycleCommand.SOLUTION_SHOWN_PERMITTED,  # L5 (design §2.1 请求完整解析)
    "accept_practice_offer": CycleCommand.ACCEPT_PRACTICE_OFFER,
    "decline_practice_offer": CycleCommand.DECLINE_PRACTICE_OFFER,
    "cancel_turn": CycleCommand.CANCEL_TURN,
    "request_practice": CycleCommand.REQUEST_HINT,
    "request_foundation": CycleCommand.REQUEST_HINT,
    "request_review": CycleCommand.REQUEST_HINT,
    "resume_problem": CycleCommand.REQUEST_HINT,
    "end_problem": CycleCommand.CANCEL_TURN,
    "start_diagnostic": CycleCommand.REQUEST_HINT,
    "skip_diagnostic": CycleCommand.REQUEST_HINT,
}

# Legacy protocol (no version / v1) only. Remove after v1 clients retire.
LEGACY_COMMAND_ALIASES = {"solution_shown_permitted": "request_solution"}
SEND_MESSAGE_COMMAND = "send_message"
logger = logging.getLogger(__name__)


def student_allowed_inputs(state: CycleState) -> list[str]:
    """Student-channel commands only: internal outcomes (e.g.
    ``solution_shown_permitted``) never appear in the UI contract — the
    client can only ever send what it is shown (design doc §13.3)."""
    allowed = set(allowed_next_commands(state))
    return [name for name, command in USER_COMMANDS.items() if command in allowed]


# The capability persists cycles through the SessionStoreProtocol: the
# in-memory implementation (repositories/session_store.py) keeps dev/test
# free of files; SQLiteSessionStore (Phase 1B) makes the database the
# authoritative record with CAS + owner isolation. The capability logic is
# identical for both — only the storage implementation changes.


# ---------------------------------------------------------------------------
# Attempt judging (MVP exact-match stub; replaced by AttemptVerifier in Phase 4)
# ---------------------------------------------------------------------------


def _assessment_attestation_hash(
    attempt, *, reference_log_id=None, verdict: str = ""
) -> str:
    """Deterministic assessment attestation bound to attempt payload, the
    reference solution log and the verdict (matches solution-attestation
    binding strength)."""
    return content_hash(
        {
            "attempt_id": str(attempt.attempt_id),
            "payload_hash": attempt.payload_hash,
            "reference_solution_log_id": str(reference_log_id) if reference_log_id else "",
            "verdict": verdict,
        }
    )


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
    }.get(problem.problem_type, "")


def _strategy_hint_for(problem: MathProblem | None) -> str:
    """L2 strategy hint: method direction only — no concrete results."""
    if problem is None:
        return ""
    return {
        "arithmetic": "先统一分数的分母，再合并计算",
        "polynomial": "先展开或合并同类项，再比较系数",
        "linear": "先把含未知数的项移到一边，常数项移到另一边",
        "quadratic": "先尝试因式分解，或用求根公式",
        "linear_inequality": "先移项整理，两边同乘除负数时改变不等号方向",
        "quadratic_inequality": "先求对应方程的根，再结合抛物线开口方向确定解集",
    }.get(problem.problem_type, "")


# ---------------------------------------------------------------------------
# Controller request/event boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MathTutorRequest:
    """Trusted request accepted by the product controller.

    ``owner`` is constructed by the server auth boundary and cannot be
    deserialized from an HTTP/WS payload.
    """

    session_id: str
    user_message: str
    owner: StudentOwnerScope
    conversation_messages: tuple[dict[str, Any], ...] = ()


class MathTutorEventType(str, Enum):
    CONTENT = "content"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class MathTutorEvent:
    """Narrow internal event; only student-public content/error can exist."""

    type: MathTutorEventType
    content: str = ""
    source: str = "math_tutor"
    stage: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class MathTutorEventSink(Protocol):
    async def emit(self, event: MathTutorEvent) -> None: ...

    async def content(
        self,
        text: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def error(
        self,
        message: str,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class MathTutorManifest:
    name: str
    description: str
    stages: tuple[str, ...]
    tools_used: tuple[()] = ()


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
        self.service = service or MathTutorApplicationService()
        self.sessions: SessionStoreProtocol = store or InMemorySessionStore()
        # Phase 5 (§7.2): the verified-release catalog behind every offer.
        # Offers/accepts go through THIS repository only — the store's
        # accept transaction re-validates the offer with a CAS.
        from mathtutor.repositories.practice_repository import (
            InMemoryPracticeRepository,
        )

        self.practice: Any = practice_repository or InMemoryPracticeRepository()
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

    async def _teaching_context(self, owner_id, session, verified):
        from mathtutor.pedagogy.teaching_plan import initial_context
        context = await self.sessions.teaching.load(owner_id, session.cycle.cycle_id)
        if verified and (context is None or context.get("schema_version") == "mt-recovery-v1" or context.get("pending_diagnostic_initialization")):
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
            eligible_cycle=task_purpose != "diagnostic", task_purpose=task_purpose, lifecycle_status=lifecycle_status))

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
                    request.conversation_messages, stream, owner_id=owner.student_id, images=images)
            except ValueError as exc:
                await stream.error(str(exc), source=self.manifest.name)
            return
        if command == SEND_MESSAGE_COMMAND:
            from mathtutor.application.function_graph import is_graph_request
            if is_graph_request(str(payload.get("text", ""))):
                await self._function_graph(owner.student_id, session, bound_verified, str(payload.get("text", "")), stream)
                return
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

    async def _route_send_message(
        self,
        request: MathTutorRequest,
        session: TutoringSession | None,
        payload: dict[str, Any],
        envelope: dict[str, Any],
        stream: MathTutorEventSink,
    ) -> None:
        text = str(payload.get("text", ""))
        previous = next((m for m in reversed(request.conversation_messages) if m.get("role") == "tutor"), None)
        if text.strip() == "继续" and previous and previous.get("status") == "PARTIAL":
            if previous.get("action") in {"TUTOR_CHAT", "TUTOR_CHAT_FIGURE"}:
                chat_context = json.loads(previous.get("continuation_context") or "{}")
                history = request.conversation_messages
                if chat_context.get("raw_text"):
                    # App labels and a nearby exercise do not close a truncated
                    # model sentence. Resume from its actual saved boundary.
                    history = tuple({**item, "content": chat_context["raw_text"]} if item is previous else item
                                    for item in history)
                if chat_context.get("boundary_unverified"):
                    from mathtutor.application.tutor_runtime import current_turn
                    continuation_turn = current_turn.get()
                    if continuation_turn is not None:
                        continuation_turn.error_code = "CONTINUATION_BOUNDARY_UNVERIFIED"
                await self._chat_message(session, text, history, stream,
                    owner_id=request.owner.student_id,
                    follow_up=bool(chat_context.get("follow_up")),
                    unstructured_math=bool(chat_context.get("unstructured_math")))
                return
            context = json.loads(previous.get("continuation_context") or "{}")
            if session is not None and context.get("cycle_id") == str(session.cycle.cycle_id) and context.get("action"):
                from mathtutor.domain.tutoring import TutorAction
                from mathtutor.application.tutor_runtime import continuation_text
                action = TutorAction.model_validate(context["action"])
                verified = await self.sessions.load_verified(request.owner.student_id, session.cycle.cycle_id)
                token = continuation_text.set(str(previous.get("content") or ""))
                try:
                    utterance = await self._realize_utterance(session, verified, action,
                        owner_id=request.owner.student_id,
                        student_request=str(context.get("student_request", "")), continuing=True)
                finally:
                    continuation_text.reset(token)
                await stream.emit(MathTutorEvent(type=MathTutorEventType.CONTENT, content=utterance.text,
                    source=self.manifest.name, metadata={"event_type": "tutor_message", "action": utterance.action,
                    "effective_assistance_level": utterance.assistance_level,
                    "cycle_state": session.state.value, "cycle_state_version": session.version}))
                return
        from mathtutor.application.student_contract import problem_variable, verified_binding
        verified = await self.sessions.load_verified(request.owner.student_id, session.cycle.cycle_id) if session else None
        import re
        if not verified and re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text.strip()):
            await self._dialogue(stream, session, f"你希望对 {text.strip()} 做什么任务？请补充题目要求，例如计算、分解或检验某个结论。", "ASK_STUDENT")
            return
        perception = None
        if verified and re.search(r"[\u4e00-\u9fff]|\b(?:understand|explain|confused|hint)\b", text, re.I):
            from mathtutor.application.teaching_intent import rule_teaching_intent
            from mathtutor.pedagogy.teaching_plan import current_subgoal
            context = await self._teaching_context(request.owner.student_id, session, verified)
            visible_context = {"problem_id": context["problem_id"], "display_text": context["display_text"],
                "skill_ids": context["skill_ids"], "current_subgoal": current_subgoal(context),
                "recent_teaching": context.get("last_plan"), "stuck_count": context["stuck_count"],
                "help_without_progress": context["help_without_progress"],
                "recent_messages": [{"role": m.get("role"), "content": str(m.get("content", ""))[-600:]}
                                    for m in request.conversation_messages[-4:]]}
            if self.semantic_interpreter is not None:
                perception = await self.semantic_interpreter.interpret(text, context=visible_context)
            else:
                perception = rule_teaching_intent(text, context=visible_context)
            context["language_understanding"] = perception.model_dump()
            context["language_input_hash"] = content_hash({"text": text})
            context["language_request_id"] = str(envelope.get("idempotency_key", ""))
            await self.sessions.teaching.save(request.owner.student_id, session.cycle.cycle_id, context)
        if verified and perception and perception.intent == "self_report" and perception.confusion == "none":
            if perception.resolved:
                context = await self.sessions.teaching.load(request.owner.student_id, session.cycle.cycle_id)
                context["stuck_count"] = 0
                context["language_signal_consumed_request"] = context.get("language_request_id")
                await self.sessions.teaching.save(request.owner.student_id, session.cycle.cycle_id, context)
            tracking = getattr(self.sessions, "student_state", None)
            if tracking:
                from mathtutor.learning.knowledge_tracing.events import LearningEvent
                from mathtutor.learning.skill_graph import skills_for_problem
                await tracking.append_event(LearningEvent(event_id=f"self-report:{envelope.get('idempotency_key') or uuid4()}",
                    student_id=request.owner.student_id, session_id=str(session.session_id), cycle_id=str(session.cycle.cycle_id),
                    event_type="self_explanation", problem_id=str(verified[0].problem_id), problem_revision=verified[0].content_hash,
                    item_family_id=verified[0].problem_type, skill_ids=skills_for_problem(verified[0]), completion_scope="reflection"))
            if (perception.resolved and perception.scope in {"current_goal", "current_problem", "same_skill"}
                    and session.state != CycleState.CLOSED):
                await self._start_understanding_check(request.owner.student_id, request.session_id, session, verified, stream)
            else:
                await self._dialogue(stream, session, "已记下你的理解反馈。先写出你能确定的一步，我来检查。", "SELF_REPORT")
            return
        pending = ""
        if previous and previous.get("action") == "CLARIFY_INTENT":
            prior = list(request.conversation_messages)
            previous_index = next((i for i, m in reversed(list(enumerate(prior))) if m is previous), -1)
            pending = next((m.get("content", "") for m in reversed(prior[:previous_index]) if m.get("role") == "student"), "")
        from mathtutor.solving.parser import stored_math_ast
        routed = classify_user_message(text, cycle_state=session.state if session else None,
                                       variable=problem_variable(verified),
                                       skill_id=skill_for_problem(verified[0]) if verified else "",
                                       pending_math_text=pending,
                                       variables=tuple(n.variables(n.from_dict(stored_math_ast(verified[0].normalized_ast)))) if verified else (),
                                       related_to_active=__import__("mathtutor.learning.skill_graph", fromlist=["related_question"]).related_question(text, verified[0]) if verified else False)
        if (perception and perception.confidence >= 0.7 and perception.scope == "other"
                and routed.intent in {ConversationIntent.GENERAL_CHAT, ConversationIntent.PROBLEM_CONTINUATION,
                                      ConversationIntent.TEACHING_REQUEST}):
            from dataclasses import replace
            # A discussion of a quoted phrase or a different subject isn't
            # evidence that the student is stuck on this mathematical goal.
            routed = replace(routed, intent=ConversationIntent.GENERAL_CHAT, command="")
        if perception and perception.confidence >= 0.7 and perception.scope in {"current_goal", "current_problem", "same_skill"}:
            from dataclasses import replace
            semantic_command = {"explanation": "request_explanation", "confusion": "request_explanation",
                "hint": "request_hint", "example": "request_example", "solution": "request_solution",
                "practice": "request_practice", "followup": "request_explanation"}.get(perception.intent)
            # Only the structural route may create/replace a problem or submit
            # a candidate answer. The model selects support, never correctness.
            if semantic_command and routed.intent is ConversationIntent.ATTEMPT:
                routed = replace(routed, command=semantic_command)
            elif semantic_command and routed.intent in {ConversationIntent.GENERAL_CHAT,
                    ConversationIntent.PROBLEM_CONTINUATION, ConversationIntent.TEACHING_REQUEST}:
                routed = replace(routed, intent=ConversationIntent.TEACHING_REQUEST, command=semantic_command)
            elif perception.intent == "ambiguous" and routed.intent is ConversationIntent.GENERAL_CHAT:
                await self._dialogue(stream, session, "你想让我重讲刚才的小目标，还是换一个例子演示？我们可以继续围绕当前题目。", "ASK_STUDENT")
                return
        if session and routed.intent is ConversationIntent.CLARIFY_INTENT:
            context = await self.sessions.teaching.load(request.owner.student_id, session.cycle.cycle_id)
            if context and context.get("teacher_error_example", {}).get("awaiting_response"):
                from dataclasses import replace
                routed = replace(routed, intent=ConversationIntent.ATTEMPT, answer_text=text)
        logger.info(
            "tutor_orchestration conversation_id=%s intent=%s mode=%s state=%s",
            request.session_id,
            routed.intent.value,
            routed.mode.value,
            session.state.value if session is not None else "",
        )
        if routed.intent is ConversationIntent.GENERAL_CHAT:
            await self._chat_message(
                session,
                text,
                request.conversation_messages,
                stream,
                owner_id=request.owner.student_id,
                client_session_id=request.session_id,
            )
            return
        if routed.intent is ConversationIntent.CLARIFY_INTENT:
            await self._dialogue(stream, session, "这是你推到的下一步，还是一道新题？请回复“这是步骤”或“这是新题”。", "CLARIFY_INTENT")
            return
        if routed.intent is ConversationIntent.TEACHING_REQUEST:
            if session is None:
                await self._dialogue(stream, session, "请先发来要辅导的题目。", "ASK_STUDENT")
            else:
                await self._run_explicit(request, session, routed.command, {"student_request": text}, envelope, stream)
            return
        if routed.intent is ConversationIntent.ATTEMPT:
            if session is None or not verified_binding(verified):
                await self._dialogue(stream, session, "当前题目还没有可用的验证记录，请先补充完整题目。", "ASK_STUDENT")
                return
            if session.state not in {CycleState.AWAITING_ATTEMPT, CycleState.AWAITING_RETRY, CycleState.AWAITING_ATTEMPT_CLARIFICATION, CycleState.SOLUTION_SHOWN}:
                await self._dialogue(stream, session, "本题已经完成。你可以继续追问原题，或用“换题：…”开始另一道题。", "ASK_STUDENT")
                return
            assistance = await self.sessions.load_assistance(request.owner.student_id, session.cycle.cycle_id)
            await self._submit_attempt(session, request.owner.student_id, {"answer": routed.answer_text},
                envelope.get("expected_state_version", envelope.get("expected_cycle_version")),
                str(envelope.get("idempotency_key", "")), verified, assistance, stream,
                raw_text_override=f"{pending}\n{text}" if pending and routed.answer_text == pending else text,
                offer_after=not bool(routed.command), followup_command=routed.command or "",
                followup_request=text)
            if routed.command:
                followup = {**envelope, "expected_state_version": session.version, "expected_cycle_version": session.version}
                await self._run_explicit(request, session, routed.command, {"student_request": text}, followup, stream)
            return
        if routed.intent is ConversationIntent.PROBLEM_CONTINUATION:
            await self._continue_active_problem(request, session, text, envelope, stream)
            return
        await self._begin_or_replace_problem(request, session, routed.problem_text or text, envelope, stream)

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
        import re
        from mathtutor.application.scene import author_scene, has_math_content, render_scene, scene_from_text
        from mathtutor.application.student_contract import REVIEW_STATES, verified_binding
        bound = bool(session and verified_binding(verified) and session.state != CycleState.CLOSED)
        open_problem = bound and session.state not in REVIEW_STATES
        source = extract_function_text(text)
        example = "可以这样写：画出 y = x^2 - 2x - 3 的图像，或 画出 x^2/4+y^2/3=1 和 y=kx+1。"
        # Only multi-object or parametrized requests become scenes; a single
        # plain y = f(x) stays on the v1 path.
        scene = scene_from_text(text, reveal=not open_problem)
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
        if scene is None and gateway is not None and has_math_content(text):
            scene = await author_scene(gateway, text)
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
            data = json.loads(getattr(turn, "continuation_context", "") or "{}")
            data["delivery_id"] = delivery_id
            turn.continuation_context = json.dumps(data, ensure_ascii=False)

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

    async def _begin_or_replace_problem(
        self,
        request: MathTutorRequest,
        session: TutoringSession | None,
        text: str,
        envelope: dict[str, Any],
        stream: MathTutorEventSink,
    ) -> None:
        constraint = evaluate_constraints(text)
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
    ) -> None:
        recovery = None
        if not images and text.strip() != "继续":
            session, recovery = await self._remember_recovery(session, owner_id, text,
                client_session_id=client_session_id, mathematical=unstructured_math)
        responder = self.chat_responder
        document_context = None
        document_source = getattr(self, "chat_documents", None)
        if document_source is not None:
            try:
                document_context = await document_source.build(owner_id, text, history)
            except Exception:
                logger.warning("Chat document retrieval unavailable")
                document_context = {"status": "retrieval_failed", "files": [], "chunks": []}
        if images is None and getattr(self, "image_repository", None) is not None:
            # Reattach the latest image turn for conversational follow-ups and
            # continuation. A new structured math task still uses its own route.
            previous = next((m for m in reversed(history[-20:]) if m.get("role") == "student" and m.get("attachments")), None)
            if previous:
                try:
                    images = await self.image_repository.resolve(owner_id, [a["id"] for a in previous["attachments"]])
                except ValueError:
                    await stream.error("之前的图片已删除或不可用，请重新上传。", source=self.manifest.name)
                    return
        problem_context = ""
        if follow_up and session is not None and owner_id:
            verified = await self.sessions.load_verified(
                owner_id, session.cycle.cycle_id
            )
            if verified is not None:
                problem_context = getattr(verified[0], "display_latex", "") or ""
        provider_result = "fallback"
        math_verify = None
        draw_offered = False
        if responder is None:
            if images:
                raise ValueError("当前模型不支持图片输入，请切换到支持视觉输入的模型。")
            message = fallback_tutor_reply(text)
        else:
            try:
                extra = {"images": images} if images else {}
                if document_context is not None:
                    extra["document_context"] = document_context
                # Free chat streams: verified sentences are previewed as they arrive.
                from mathtutor.application.math_claims import VerifiedPreview, anchor_for
                from mathtutor.application.tutor_runtime import stream_preview
                bound_for_preview = await self.sessions.load_verified(owner_id, session.cycle.cycle_id) if session and owner_id else None

                async def emit_preview(verified_text):
                    # The preview never shows a figure: those come only with the final message.
                    from mathtutor.skills.canvas_drawing.enforce import sanitize_figures
                    verified_text = sanitize_figures(verified_text)[0]
                    if verified_text:
                        await stream.content(verified_text, source=self.manifest.name, metadata={"event_type": "tutor_preview"})
                preview_token = stream_preview.set(VerifiedPreview(
                    self.service.verification_backend, emit_preview,
                    anchor=anchor_for(bound_for_preview[0]) if bound_for_preview else None))
                from mathtutor.application.message_intent import is_concrete_math_input
                import inspect
                accepts = inspect.signature(responder.respond).parameters
                takes_tools = "math_verify" in accepts or any(p.kind is p.VAR_KEYWORD for p in accepts.values())
                takes_figures = "draw_figures" in accepts or any(p.kind is p.VAR_KEYWORD for p in accepts.values())
                from mathtutor.skills.canvas_drawing import wants_figure
                figure_asked = wants_figure(text)
                if takes_tools and (unstructured_math or follow_up or figure_asked or is_concrete_math_input(text)):
                    # Maths questions: the model may verify its own claims first,
                    # and show a figure only through the canvas (draw_scene).
                    from mathtutor.application.math_verification import verify_math

                    async def math_verify(expression, answer):
                        return await verify_math(self.service.verification_backend, expression, answer)
                    extra = {**extra, "math_verify": math_verify}
                    if takes_figures:
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
            except TypeError:
                if images:
                    raise ValueError("当前模型不支持图片输入，请切换到支持视觉输入的模型。") from None
                message = await responder.respond(text, history=history)
                provider_result = "success"
            except ValueError as exc:
                if not images:
                    raise
                await stream.error(str(exc), source=self.manifest.name)
                return
        logger.info(
            "tutor_orchestration intent=general_chat provider_result=%s state=%s",
            provider_result,
            session.state.value if session is not None else "",
        )
        visible = project_assistant_message(message) or fallback_tutor_reply(text)
        if recovery and visible == fallback_tutor_reply(text):
            visible = "这道题的完整过程还不能逐步核验。你可以写出下一步的想法，或先练下面的相关基础题。"
        # Canvas drawing skill: a figure the model drew by itself never reaches the student.
        from mathtutor.application.tutor_runtime import current_turn, note_turn
        from mathtutor.skills.canvas_drawing.enforce import sanitize_figures
        turn = current_turn.get()
        visible, removed = sanitize_figures(visible)
        visible = visible or fallback_tutor_reply(text)
        if removed:
            note_turn(figures={"removed": removed})
        if (removed and draw_offered and turn is not None and not getattr(turn, "figures", None)
                and provider_result == "success" and not recovery):
            visible = await self._redraw_on_canvas(responder, turn, text, history, visible, problem_context=problem_context,
                unstructured_math=unstructured_math, images=images, math_verify=math_verify)
        raw_visible = visible
        from mathtutor.application.problem_recovery import simple_greeting
        from mathtutor.application.math_claims import strip_notice
        if not simple_greeting(text, visible):
            # Each formula goes through verify_math; prose stays unverified.
            from mathtutor.application.math_claims import anchor_for, certify_and_annotate
            bound = await self.sessions.load_verified(owner_id, session.cycle.cycle_id) if session and owner_id else None
            regenerate = None
            if responder is not None and provider_result == "success" and not recovery:
                first_answer = raw_visible

                async def regenerate(feedback):
                    retry_history = (*history, {"role": "student", "content": text}, {"role": "tutor", "content": first_answer})
                    return sanitize_figures(project_assistant_message(await responder.respond(
                        feedback, history=retry_history, problem_context=problem_context,
                        unstructured_math=unstructured_math, **({"images": images} if images else {}))) or "")[0]
            visible, checked = await certify_and_annotate(visible, self.service.verification_backend,
                                                          anchor=anchor_for(bound[0]) if bound else None,
                                                          regenerate=regenerate)
            raw_visible = strip_notice(visible) if not checked.refuted else raw_visible
        action = "TUTOR_CHAT"
        figures = list(getattr(turn, "figures", None) or []) if turn is not None else []
        if figures:
            # Scenes the application built from draw_scene calls, appended only
            # to the final message (never to the streamed preview).
            from mathtutor.application.scene import render_scene
            visible += "".join("\n\n" + render_scene(scene) for scene in figures)
            action = "TUTOR_CHAT_FIGURE"
            note_turn(figures={"delivered": len(figures)})
        if recovery:
            visible += f"\n\n原题还保留在对话里。可以先练一道相关基础题：\\( {recovery['text']} \\)。{recovery['relation']}"
        if turn is not None:
            turn.continuation_context = json.dumps({"kind": "chat", "unstructured_math": unstructured_math,
                "follow_up": follow_up, "raw_text": raw_visible,
                "boundary_unverified": turn.error_code == "CONTINUATION_BOUNDARY_UNVERIFIED"}, ensure_ascii=False)
        await stream.emit(
            MathTutorEvent(
                type=MathTutorEventType.CONTENT,
                content=visible,
                source=self.manifest.name,
                metadata={
                    "event_type": "tutor_message",
                    "action": action,
                    "cycle_state": session.state.value if session is not None else "",
                    "cycle_state_version": session.version if session is not None else 0,
                    "allowed_next_inputs": student_allowed_inputs(session.state) if session is not None else [],
                },
            )
        )

    async def _redraw_on_canvas(self, responder, turn, text, history, first_answer, *, problem_context,
                                unstructured_math, images, math_verify) -> str:
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
            again = project_assistant_message(await responder.respond(
                feedback, history=retry_history, problem_context=problem_context, unstructured_math=unstructured_math,
                math_verify=math_verify, draw_figures=True, **({"images": images} if images else {}))) or ""
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
        if command in {"request_practice", "request_foundation", "request_review"}:
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
            _, recovery = await self._remember_recovery(session, owner_id, constraint.raw_text, mathematical=True)
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
        submit_command = CycleCommand.CLARIFY_ATTEMPT if session.state == CycleState.AWAITING_ATTEMPT_CLARIFICATION else CycleCommand.SUBMIT_ATTEMPT
        # ---- READ is done by run(): cycle/verified/assistance restored. ----
        # A child practice cycle (practice_offer_id set, problem_id NULL —
        # ck_cycle_source_xor) judges against the offer→release EXACT
        # snapshot restored by load_verified; the verified chain must exist
        # either way or the attempt cannot be judged (fail closed).
        if verified is None or (
            session.problem_id is None and session.practice_offer_id is None
        ):
            transition = await self._step(
                owner_id, session, submit_command,
                expected_version=expected_version, idempotency_key=idempotency_key,
            )
            transition = await self._step(owner_id, session, CycleCommand.DIAGNOSIS_AMBIGUOUS)
            await self._emit(stream, session, transition, "没有已验证的题目可供判题")
            return

        problem, candidate, ref = verified
        if (
            ref.problem_id != problem.problem_id
            or ref.problem_content_hash != problem.content_hash
            or ref.solution_candidate_id != candidate.candidate_id
            or ref.solution_payload_hash != candidate.payload_hash
        ):
            transition = await self._step(
                owner_id, session, submit_command,
                expected_version=expected_version, idempotency_key=idempotency_key,
            )
            transition = await self._step(
                owner_id, session, CycleCommand.DIAGNOSIS_AMBIGUOUS
            )
            await self._emit(
                stream, session, transition,
                "已保存的验证记录无法通过绑定校验，请重新提交题目。",
                detail="verification_binding_invalid",
            )
            return
        answer = str(payload.get("answer", ""))
        from mathtutor.learning.skill_graph import skills_for_problem
        from mathtutor.pedagogy.teaching_plan import apply_assessment, assessment_feedback, current_subgoal
        context = await self._teaching_context(owner_id, session, verified)
        if "choice_id" in payload:
            from mathtutor.application.multiple_choice import resolve_choice
            try:
                answer = resolve_choice(context.get("choices"), payload["choice_id"], payload.get("choice_version"))
            except ValueError as exc:
                await stream.error(str(exc), source=self.manifest.name)
                return
            raw_text_override = f"{payload['choice_id']}. {answer}"
        if context.get("teacher_error_example", {}).get("awaiting_response"):
            await self._assess_teacher_error(session, owner_id, context, answer, expected_version, idempotency_key, stream)
            return
        deliveries = await self.sessions.teaching.for_cycle(owner_id, session.cycle.cycle_id)
        shown = [row for row in deliveries if row["status"] in {"possibly_exposed", "presented"}]
        factual_level = 5 if any(row.get("target_answer_exposed") for row in shown) else 1 if shown else 0
        # Old actions without delivery provenance cannot certify independence.
        actual_assistance = CycleAssistance(max_level_issued=factual_level)
        tracking = getattr(self.sessions, "student_state", None)
        if tracking is not None:
            exposure = await tracking.exposure_context(owner_id, problem.content_hash)
            factual_level = max(factual_level, exposure["assistance_level"])
            actual_assistance = CycleAssistance(max_level_issued=factual_level)
            context["legacy_provenance_uncertain"] |= exposure["provenance_uncertain"]
        prediction_id = f"prediction:{session.cycle.cycle_id}:{idempotency_key or uuid4()}"
        submission_event_id = ""
        if tracking is not None:
            presentation = await tracking.presentation(owner_id, session.cycle.cycle_id)
            if presentation is not None:
                prediction_id = presentation["prediction_id"]
            else:
                # Pre-upgrade open cycles have no trustworthy presentation record.
                context["legacy_provenance_uncertain"] = True
            submission_event_id = f"submission:{session.cycle.cycle_id}:{idempotency_key or uuid4()}"
            await tracking.record_submission(owner_id, event_id=submission_event_id,
                session_id=session.session_id, cycle_id=session.cycle.cycle_id,
                problem_id=problem.problem_id, problem_revision=problem.content_hash,
                item_family_id=problem.problem_type, skill_ids=skills_for_problem(problem),
                response_fingerprint=content_hash({"raw_response": raw_text_override if raw_text_override is not None else answer}),
                prediction_id=prediction_id, task_purpose="diagnostic" if context.get("diagnostic_item") else "practice")

        # ---- COMPUTE: Phase 4 learning loop, pure and deterministic. ----
        attempt_index = await self.sessions.load_attempt_index(
            owner_id, session.cycle.cycle_id
        )
        submission_id = uuid4()
        student_attempt = parse_student_attempt(
            attempt_submission_id=submission_id,
            student_id=session.student_id,
            cycle_id=session.cycle.cycle_id,
            raw_text=answer,
            attempt_index=attempt_index,
        )
        try:
            assessment = await self.service.verification_backend.verify_attempt(
                student_attempt, problem, candidate
            )
            if problem.problem_type == "linear_system" and assessment.correctness is Correctness.PARTIAL:
                # Accumulate only independently verified coordinate claims,
                # then reverify the combined answer against BOTH original equations.
                coordinates = {}
                for prior in context["progress"]:
                    for claim in prior["verified_claims"]:
                        if claim.get("claim") == "variable_value":
                            coordinates[claim["variable"]] = claim["value"]
                for claim in assessment.verified_claims:
                    if claim.get("claim") == "variable_value":
                        coordinates[claim["variable"]] = claim["value"]
                if len(coordinates) == 2:
                    merged = ";".join(f"{name}={value['n']}/{value['d']}" for name, value in coordinates.items())
                    joint_attempt = parse_student_attempt(attempt_submission_id=submission_id,
                        student_id=session.student_id, cycle_id=session.cycle.cycle_id,
                        raw_text=merged, attempt_index=attempt_index)
                    joint = await self.service.verification_backend.verify_attempt(joint_attempt, problem, candidate)
                    if joint.correctness is Correctness.CORRECT:
                        student_attempt, assessment = joint_attempt, joint
        except VerificationBackendError as exc:
            # Infrastructure failure is not a mathematical assessment.  We
            # preserve the legal cycle transition but persist no attempt
            # assessment, evidence, misconception, mastery, or attestation.
            transition = await self._step(
                owner_id, session, submit_command,
                expected_version=expected_version, idempotency_key=idempotency_key,
            )
            transition = await self._step(
                owner_id, session, CycleCommand.DIAGNOSIS_AMBIGUOUS
            )
            await self._emit(
                stream, session, transition,
                "数学验证服务暂时不可用，请稍后重试。",
                detail=f"verification_unavailable:{type(exc).__name__}",
            )
            return

        # State machine transitions in memory (persisted in ONE transaction
        # together with the education rows below — READ→COMPUTE→COMMIT).
        submit_transition = session.step(
            submit_command,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        if assessment.correctness is Correctness.UNDETERMINED:
            diag_command = CycleCommand.DIAGNOSIS_AMBIGUOUS
            message, detail = "作答无法理解，请澄清", "undetermined"
        elif assessment.correctness is Correctness.CORRECT:
            diag_command = CycleCommand.DIAGNOSIS_CORRECT
            message, detail = "回答正确！", "correct"
        elif assessment.correctness is Correctness.PARTIAL:
            diag_command = CycleCommand.DIAGNOSIS_PARTIAL
            message, detail = "方向对了，但还没做完，继续！", "partial"
        else:
            diag_command = CycleCommand.DIAGNOSIS_INCORRECT
            message, detail = "回答不正确，再试一次", "incorrect"
        diag_transition = session.step(diag_command)
        context, scoped_assessment = apply_assessment(context, assessment,
            raw_text_override if raw_text_override is not None else answer, actual_assistance)
        if context.get("legacy_provenance_uncertain") and scoped_assessment["evidence_kind"] == "independent":
            scoped_assessment["evidence_kind"] = "ungradable"
        if shown and any(row["status"] != "presented" for row in shown) and scoped_assessment["evidence_kind"] == "assisted":
            scoped_assessment["evidence_kind"] = "ungradable"
        message = assessment_feedback(scoped_assessment)
        if followup_command:
            from mathtutor.application.tutor_runtime import current_turn
            active_turn = current_turn.get()
            context["pending_expression"] = {
                "phase": "assessment_committed", "request_id": active_turn.turn_id if active_turn else idempotency_key,
                "command": followup_command, "student_request": followup_request,
                "cycle_version": session.version, "problem_revision": problem.content_hash,
                "feedback": message, "assessment_id": scoped_assessment["assessment_id"],
            }

        observation = diagnose(
            assessment=assessment, problem=problem, attempt=student_attempt
        )
        # An understanding check has its own diagnostic assessment ledger.
        # It must not create a legacy mastery or misconception projection for
        # the original task, nor turn a self report into independent success.
        if context.get("understanding_check"):
            observation = None
        evidence_obj = None
        projection_obj = None
        if assessment.correctness is not Correctness.UNDETERMINED and not context.get("understanding_check"):
            factory = EvidenceFactory()
            evidence_obj = factory.build_evidence(
                assessment=assessment,
                verified_ref=ref,
                skill_id=skill_for_problem(problem),
                assistance=assistance,
                attempt_index=attempt_index,
                observation=observation,
                idempotency_key=idempotency_key,
            )
            history_evidence, history_observations = await self.sessions.load_learning_history(
                owner_id
            )
            projection_obj = project_student_state(
                student_id=session.student_id,
                evidence=[*history_evidence, evidence_obj] if evidence_obj else history_evidence,
                observations=[*history_observations, observation]
                if observation is not None
                else history_observations,
            )

        # ---- SHORT COMMIT: one atomic transaction (§C14). ----
        evidence_row = None
        if evidence_obj is not None:
            evidence_row = {
                "skill_id": skill_for_problem(problem),
                "difficulty": 1,
                "effective_assistance_level": evidence_obj.effective_assistance_level,
                "evidence_version": evidence_obj.evidence_version,
                "idempotency_key": evidence_obj.idempotency_key,
            }
        projection_row = None
        if projection_obj is not None:
            projection_row = {
                "estimator_version": projection_obj.estimator_version,
                "projection_version": projection_obj.projection_version,
                "concept_mastery": projection_obj.concept_mastery,
                "skill_mastery": projection_obj.skill_mastery,
                "active_misconceptions": [
                    m["rule_id"] if isinstance(m, dict) else getattr(m, "rule_id")
                    for m in projection_obj.active_misconceptions
                ],
            }
        commit = LearningCommit(
            transitions=[submit_transition, diag_transition],
            problem_id=problem.problem_id,
            attempt_submission_id=submission_id,
            attempt_id=student_attempt.attempt_id,
            raw_text=raw_text_override if raw_text_override is not None else answer,
            parsed_steps=list(student_attempt.parsed_steps),
            attempt_index=attempt_index,
            payload_hash=student_attempt.payload_hash,
            reference_solution_log_id=ref.verification_log_id,
            correctness=assessment.correctness.value,
            score=assessment.score,
            assessment_attestation_hash=_assessment_attestation_hash(
                student_attempt,
                reference_log_id=ref.verification_log_id,
                verdict=assessment.correctness.value,
            ),
            assessment_policy_version=assessment.policy_version,
            idempotency_key=idempotency_key,
            verified_claims=assessment.verified_claims,
            teaching_context=context,
            tracking_attempt={
                "session_id": str(session.session_id), "cycle_id": str(session.cycle.cycle_id),
                "problem_id": str(problem.problem_id), "problem_revision": problem.content_hash,
                "item_family_id": problem.problem_type, "skill_ids": skills_for_problem(problem),
                "assessment_id": str(student_attempt.attempt_id), "attempt_id": str(student_attempt.attempt_id),
                "correctness": assessment.correctness.value, "prediction_id": prediction_id,
                "submission_event_id": submission_event_id,
                "response_format": "single_choice" if context.get("choices") else "free_response",
                "completion_scope": "full_problem" if assessment.correctness is Correctness.CORRECT else "subgoal" if assessment.correctness is Correctness.PARTIAL else "full_problem",
                "subgoal_id": current_subgoal(context)["id"],
                "provenance_uncertain": context.get("legacy_provenance_uncertain", False),
                "task_purpose": "diagnostic" if context.get("diagnostic_item") else "practice",
                "misconception_codes": assessment.signals,
                "response_fingerprint": content_hash({"parsed_steps": list(student_attempt.parsed_steps)}),
            } if tracking is not None else None,
            invalid_claims=assessment.invalid_claims,
            remaining_requirements=assessment.remaining_requirements,
            observation=(
                {
                    "rule_id": observation.rule_id,
                    "confidence": observation.confidence,
                    "detail": observation.detail,
                }
                if observation is not None
                else None
            ),
            evidence=evidence_row,
            projection=projection_row,
            outbox_events=[
                {
                    "aggregate_type": "attempt",
                    "aggregate_id": str(student_attempt.attempt_id),
                    "aggregate_version": attempt_index,
                    "event_sequence": 1,
                    "event_type": "attempt_assessed",
                    "audience": "student",
                    "payload": {"correctness": assessment.correctness.value},
                }
            ],
        )
        await self.sessions.commit_learning_transaction(owner_id, commit)

        await self._emit(stream, session, diag_transition, message, detail=detail)

        # Phase 5 (§7.5 E2E): a solved cycle is followed by a server-driven
        # practice offer — SOLVED →(REFLECTED)→ REFLECTION →(PRACTICE_OFFERED).
        if context.get("diagnostic_item"):
            await self._advance_diagnostic(session, owner_id, context, assessment, stream)
        elif assessment.correctness is Correctness.CORRECT and offer_after:
            await self._offer_after_solved(
                session,
                owner_id,
                skill_id=skill_for_problem(problem),
                stream=stream,
                problem_text=problem.display_latex,
            )

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
        """Server-driven practice offer after a solved cycle (§7.5 E2E).

        ``prepare_offer`` runs the FULL release gate (candidate → parser →
        solver → verifier → attestation → ExerciseRelease → PracticeOffer)
        inside the adaptive-practice service — this helper never touches the
        verifier, releases or the student model itself (Invariant A), and it
        persists each state step as its own short transaction (restart-safe).

        The offer is a recommendation: when no candidate passes the gate (or
        the service is unavailable) the cycle STILL advances to
        PRACTICE_OFFERED and a degraded message is emitted — the student
        exits via decline/cancel. The emitted projection is the same public
        shape as GET /offers (offer id, curriculum labels, difficulty,
        timestamps) — never a solution, answer key, verification log,
        attestation or mastery value.
        """
        if self.practice_service is None:
            return
        verified = await self.sessions.load_verified(owner_id, session.cycle.cycle_id)
        assistance = await self.sessions.load_assistance(owner_id, session.cycle.cycle_id)
        deliveries = await self.sessions.teaching.for_cycle(owner_id, session.cycle.cycle_id)
        exposure = 5 if any(x.get("target_answer_exposed") for x in deliveries
                            if x["status"] in {"possibly_exposed", "presented"}) else assistance.max_level_issued
        tracking = getattr(self.sessions, "student_state", None)
        if tracking is not None and verified:
            exposure = max(exposure, (await tracking.exposure_context(owner_id, verified[0].content_hash))["assistance_level"])
        purpose = purpose or ("B" if exposure >= 5 else "A2" if exposure else "A1")
        from mathtutor.learning.knowledge_tracing.events import valid_events
        history = await tracking.events(owner_id) if tracking else []
        from mathtutor.application.evidence_projection import teaching_evidence, teaching_practice_focus
        context = await self._teaching_context(owner_id, session, verified) if verified else None
        focus, practice_guidance = "", ""
        if context:
            context["learner_evidence"] = teaching_evidence(history, context["skill_ids"])
            focus, practice_guidance = teaching_practice_focus(context)
        basis_events = [e for e in valid_events(history)
            if e.cycle_id == str(session.cycle.cycle_id) and e.event_type == "attempt_assessed"]
        from mathtutor.application.evidence_projection import PRACTICE_ERROR_CODES
        if focus and context:
            basis_events.extend(e for e in valid_events(history)
                if e.independent_target and e.correctness == "incorrect"
                and set(e.skill_ids) & set(context["skill_ids"])
                and set(e.misconception_codes) & PRACTICE_ERROR_CODES)
        offer = None
        try:
            offer = await self.practice_service.prepare_offer(
                owner_id,
                parent_cycle_id=session.cycle.cycle_id,
                target_skill_ids=(skill_id,) if skill_id else (),
                problem_text=problem_text,
                purpose=purpose,
                target_revision=verified[0].content_hash if verified else "",
                exposure_level=exposure,
                full_task_completed=session.state == CycleState.SOLVED,
                prerequisite_skill_ids=prerequisite_skill_ids,
                review_due=review_due,
                history_cutoff_seq=max((e.event_seq for e in history), default=0) if tracking else None,
                evidence_ids=tuple(e.event_id for e in basis_events),
                foundation_focus=focus,
            )
        except Exception:
            offer = None
        from types import SimpleNamespace
        transition = SimpleNamespace(from_state=session.state.value, to_state=session.state.value,
                                     trigger_command="request_practice")
        if offer is None:
            await self._emit(
                stream,
                session,
                transition,
                "这次没有生成通过验证的练习题。当前题目和作答记录保留，你可以继续辅导或稍后重试。",
                detail="practice_unavailable",
            )
            return
        from mathtutor.application.practice_release import (
            labels_for_mapping_ids,
        )

        labels = labels_for_mapping_ids(offer.target_mapping_ids)
        release = await self.practice.load_release(offer.exercise_release_id)
        exercise = (
            await self.practice.load_exercise(release.exercise_id)
            if release is not None
            else None
        )
        await self._emit(
            stream,
            session,
            transition,
            practice_guidance + {"A1": "这道题已经独立完成，可以换一道题检验迁移。",
             "A2": "这道题在帮助后完成了，可以换一道题独立巩固。",
             "B": "已展示解答；这不等于已经掌握。可以换一道题独立检测。",
             "D": "练习题已经通过验证。你可以开始，原题会保留。"}.get(purpose, "练习题已经准备好。"),
            detail="practice_offered",
            extra={
                "offer_id": str(offer.offer_id),
                "status": offer.status,
                "skill_labels": labels["skill_labels"],
                "concept_labels": labels["concept_labels"],
                "difficulty": exercise.difficulty if exercise is not None else None,
                "offered_at": offer.offered_at.isoformat(),
                "expires_at": offer.expires_at.isoformat(),
                "parent_cycle_id": str(offer.parent_cycle_id),
                "purpose": purpose,
            },
        )

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
        from mathtutor.application.student_contract import verified_binding
        if not verified_binding(verified):
            await stream.error("当前题目还没有可用的验证解答，请先补充题目。", source=self.manifest.name,
                               metadata={"error_code": "NO_VERIFIED_SOLUTION"})
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
            context = await self.sessions.teaching.load(owner_id, session.cycle.cycle_id)
            pending = (context or {}).get("pending_expression") or {}
            if pending.get("request_id") in {turn.turn_id if turn else None, idempotency_key}:
                context.pop("pending_expression")
                await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, context)
            code = getattr(exc, "error_code", "")
            await stream.error(
                str(exc) if code else f"当前策略不允许这个操作：{exc}",
                source=self.manifest.name,
                metadata={"cycle_state": session.state.value, **({"error_code": code} if code else {})},
            )
            return
        from mathtutor.domain.tutoring import TutorAction
        from mathtutor.application.tutor_runtime import current_turn
        from mathtutor.pedagogy.output_guard import GuardedTutorUtterance
        teaching_context = await self._teaching_context(owner_id, session, verified)
        turn = current_turn.get()
        request_id = turn.turn_id if turn else idempotency_key
        if resume_checkpoint and resume_checkpoint.get("action"):
            action = TutorAction.model_validate(resume_checkpoint["action"])
        checkpoint = dict(resume_checkpoint or teaching_context.get("pending_expression") or {})
        if checkpoint.get("request_id") != request_id:
            checkpoint = {}
        checkpoint.update(request_id=request_id, command={
            CycleCommand.REQUEST_HINT: "request_hint", CycleCommand.REQUEST_EXPLANATION: "request_explanation",
            CycleCommand.REQUEST_EXAMPLE: "request_example", CycleCommand.SOLUTION_SHOWN_PERMITTED: "request_solution",
        }[command], student_request=student_request, problem_revision=problem.content_hash,
            cycle_version=session.version, action=action.model_dump(mode="json"))
        checkpoint.setdefault("phase", "planned")
        teaching_context["pending_expression"] = checkpoint
        await self.sessions.teaching.save(owner_id, session.cycle.cycle_id, teaching_context)
        # Phase 3 teaching control chain: projector → writer → guard (the
        # action is already planner-sanctioned).
        if checkpoint.get("approved_utterance"):
            utterance = GuardedTutorUtterance.model_validate(checkpoint["approved_utterance"])
            if turn:
                turn.continuation_context = checkpoint.get("continuation_context", "")
        else:
            utterance = await self._realize_utterance(session, verified, action, student_request=student_request, owner_id=owner_id)
        # Keep the previous actionable state while the writer runs. Commit
        # the request + delivery transition together, never strand a restart
        # in HINTED/EXPLAINING after a provider failure or cancellation.
        actual_command = command
        return_state = session.state
        if command == CycleCommand.SOLUTION_SHOWN_PERMITTED and utterance.assistance_level < 5:
            actual_command = CycleCommand.REQUEST_HINT
        transition = session.step(actual_command, expected_version=expected_version, idempotency_key=idempotency_key)
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
        teaching_context = await self.sessions.teaching.load(owner_id, session.cycle.cycle_id)
        teaching_context["pending_expression"].update(phase="action_committed", cycle_version=session.version)
        actual_action = action.model_copy(update={"action": utterance.action,
            "effective_assistance_level": utterance.assistance_level,
            "solution_visibility": {0: "none", 1: "hint", 2: "hint", 3: "step", 4: "partial", 5: "full"}[utterance.assistance_level]})
        await self.sessions.commit_teaching_action(owner_id, session.cycle.cycle_id, transitions, actual_action, teaching_context)
        await self._emit(
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
            await self._offer_after_solved(
                session,
                owner_id,
                skill_id=skill_for_problem(problem) if problem is not None else None,
                stream=stream,
                reflected=True,
                problem_text=problem.display_latex if problem is not None else "",
                purpose="B",
            )
        else:
            await self._emit_state(stream, session)

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
                                                           "skill_id": skill_for_problem(problem)})
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
                    teaching_context["help_fingerprints"].append(plan.fingerprint)
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
                    data = json.loads(turn.continuation_context)
                    data["delivery_id"] = delivery_id
                    turn.continuation_context = json.dumps(data, ensure_ascii=False)
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
            context = json.loads(turn.continuation_context)
            context["approved_solution_text"] = utterance.text
            turn.continuation_context = json.dumps(context, ensure_ascii=False)
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
        example = context["teacher_error_example"]
        result = await self.service.submit_problem(example["problem_text"])
        if result.kind != "verified":
            await stream.error("这个教师示例暂时无法验证，原题记录没有改变。", source=self.manifest.name)
            return
        problem, candidate, ref = result.problem, result.candidate, result.verified_ref
        attempt_index = await self.sessions.load_attempt_index(owner_id, session.cycle.cycle_id)
        submission_id = uuid4()
        attempt = parse_student_attempt(attempt_submission_id=submission_id, student_id=session.student_id,
            cycle_id=session.cycle.cycle_id, raw_text=answer, attempt_index=attempt_index)
        prediction_id = f"error-analysis:{session.cycle.cycle_id}:{request_id or submission_id}"
        tracking = getattr(self.sessions, "student_state", None)
        from mathtutor.learning.skill_graph import skills_for_problem
        item = {"session_id": str(session.session_id), "cycle_id": str(session.cycle.cycle_id),
                "problem_id": str(problem.problem_id), "problem_revision": problem.content_hash,
                "item_family_id": problem.problem_type, "skill_ids": skills_for_problem(problem)}
        if tracking:
            await tracking.prepare_prediction(owner_id, prediction_id=prediction_id, **item)
        assessment = await self.service.verification_backend.verify_attempt(attempt, problem, candidate)
        from mathtutor.pedagogy.error_example import assess_teacher_error_repair
        assessment = assess_teacher_error_repair(example=example, raw_text=answer, assessment=assessment)
        transition = session.step(CycleCommand.TEACHER_ERROR_ANALYZED, expected_version=expected_version)
        valid = assessment.correctness in {Correctness.CORRECT, Correctness.PARTIAL}
        if valid:
            context["teacher_error_example"]["awaiting_response"] = False
        context.setdefault("error_analyses", []).append({"assessment_id": str(attempt.attempt_id),
            "correctness": assessment.correctness.value, "student_text": answer, "teacher_authored": True})
        commit = LearningCommit(transitions=[transition], problem_id=problem.problem_id,
            attempt_submission_id=submission_id, attempt_id=attempt.attempt_id, raw_text=answer,
            parsed_steps=list(attempt.parsed_steps), attempt_index=attempt_index, payload_hash=attempt.payload_hash,
            reference_solution_log_id=ref.verification_log_id, correctness=assessment.correctness.value,
            score=assessment.score, assessment_attestation_hash=_assessment_attestation_hash(attempt,
                reference_log_id=ref.verification_log_id, verdict=assessment.correctness.value),
            assessment_policy_version=assessment.policy_version, idempotency_key=request_id,
            verified_claims=assessment.verified_claims, invalid_claims=assessment.invalid_claims,
            remaining_requirements=assessment.remaining_requirements, teaching_context=context,
            tracking_attempt={**item, "attempt_id": str(attempt.attempt_id), "assessment_id": str(attempt.attempt_id),
                "correctness": assessment.correctness.value, "prediction_id": prediction_id,
                "task_purpose": "error_analysis", "completion_scope": "error_analysis",
                "response_fingerprint": content_hash({"parsed_steps": list(attempt.parsed_steps)})} if tracking else None)
        await self.sessions.commit_learning_transaction(owner_id, commit)
        await self._dialogue(stream, session,
            "已验证这一步修正成立。这是教师错误示例的分析证据，不代表原题已经完成；现在回到原题。" if valid
            else "这次修正还没有通过验证；示例中的错误是老师故意设置的，不会算作你原题做错。请继续检查等式两边的运算。",
            "ERROR_ANALYSIS")

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
        """Accept one practice offer — the client sends ONLY ``offer_id``.

        Nine steps (§7.7), all READ→COMPUTE, ONE short SHORT COMMIT:
        1. owner check; 2. offer ACTIVE; 3. release active; 4. exact
        snapshot (fail closed without VERIFIED bytes); 5. idempotency
        (already ACCEPTED → replay the SAME child cycle); 6. create the
        child cycle (SAME state machine, §7.8 — PROBLEM_RECEIVED v0
        auto-advanced to AWAITING_ATTEMPT); 7. parent relation
        (child.practice_offer_id = offer; parent closed); 8. outbox;
        9. atomic commit (offer CAS + parent transition + child cycle +
        child transitions + outbox in ONE transaction).
        """
        from datetime import datetime, timezone
        from uuid import UUID

        from mathtutor.domain.tutoring import CycleTransition

        raw_offer_id = payload.get("offer_id")
        try:
            offer_id = UUID(str(raw_offer_id))
        except (ValueError, TypeError):
            await stream.error("offer_id 无效", source=self.manifest.name)
            return
        offer = await self.practice.load_offer(offer_id)
        # 1. Owner isolation: the offer must belong to THIS student.
        if offer is None or str(offer.student_id) != str(session.student_id):
            await stream.error("offer 不存在", source=self.manifest.name)
            return
        # 5. Idempotent replay: an accepted offer returns the SAME child.
        if offer.status == "ACCEPTED":
            child = await self.sessions.load_child_cycle_for_offer(owner_id, offer_id)
            if child is None:
                await stream.error(
                    "offer 已接受，但子周期不可恢复", source=self.manifest.name
                )
                return
            replay = CycleTransition(
                cycle_id=session.cycle.cycle_id,
                from_state="practice_offered",
                to_state="closed",
                trigger_command="accept_practice_offer",
                prior_version=session.version,
                new_version=session.version,
            )
            await self._emit(
                stream,
                session,
                replay,
                "已接受练习",
                detail="practice_started",
                extra={
                    "child_cycle_id": str(child.cycle.cycle_id),
                    "idempotent_replay": True,
                },
            )
            return
        # 2/3. ACTIVE offer bound to a RELEASED (not revoked/superseded) release.
        if offer.status != "ACTIVE":
            await stream.error("offer 已失效（已撤销或已过期）", source=self.manifest.name)
            return
        if offer.expires_at <= datetime.now(timezone.utc):
            await stream.error("offer 已过期", source=self.manifest.name)
            return
        if offer.parent_cycle_id != session.cycle.cycle_id:
            await stream.error("offer 不属于当前周期", source=self.manifest.name)
            return
        release = await self.practice.load_release(offer.exercise_release_id)
        if release is None or release.status != "released":
            await stream.error("练习题已下架（发布被撤销或已替换）", source=self.manifest.name)
            return
        # 4. Exact snapshot — no VERIFIED bytes ⇒ no child cycle (fail closed).
        exact = await self.practice.load_exact_verified(release)
        if exact is None:
            await stream.error(
                "练习题未通过独立验证，无法开始练习", source=self.manifest.name
            )
            return
        problem, _candidate, _ref = exact
        from mathtutor.application.multiple_choice import make_choices
        try:
            choices = make_choices(problem, _candidate, salt=str(release.release_id))
        except ValueError:
            await stream.error("这道旧练习暂不支持选择题，请重新邀请练习。", source=self.manifest.name)
            return

        # 6/7. Parent closes (in memory); the child is a NEW TutoringCycle in
        # the SAME session + SAME state machine (§7.8), practice-bound only
        # (problem_id NULL — the XOR invariant; the problem binding lives in
        # the offer→release exact snapshot resolved by load_verified).
        child = TutoringSession(
            session_id=session.session_id,
            student_id=session.student_id,
            practice_offer_id=offer_id,
        )
        child.step(CycleCommand.SUBMIT_PROBLEM)
        child.step(CycleCommand.GROUNDING_OK)
        child.step(CycleCommand.VERIFICATION_VERIFIED)
        await self._prepare_presentation(owner_id, child, exact)
        parent_transition = session.step(
            CycleCommand.ACCEPT_PRACTICE_OFFER,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )

        # 8. Outbox events (written in the same transaction, §7.10).
        outbox_events = [
            {
                "aggregate_type": "cycle",
                "aggregate_id": str(session.cycle.cycle_id),
                "aggregate_version": session.version,
                "event_sequence": 1,
                "event_type": "cycle_state_committed",
                "audience": "student",
                "payload": {
                    "from_state": parent_transition.from_state,
                    "to_state": parent_transition.to_state,
                    "trigger_command": parent_transition.trigger_command,
                },
            },
            {
                "aggregate_type": "practice_offer",
                "aggregate_id": str(offer_id),
                "aggregate_version": 1,
                "event_sequence": 2,  # seq 1 is practice_offer_issued
                "event_type": "practice_offer_accepted",
                "audience": "student",
                "payload": {"child_cycle_id": str(child.cycle.cycle_id)},
            },
        ]
        # 9. ONE short transaction: offer CAS + parent transition + child
        #    cycle + child transitions + outbox (§7.7 step 9, §7.10).
        await self.sessions.accept_practice_offer(
            owner_id,
            client_session_id,
            offer_id,
            parent_transition,
            child,
            outbox_events,
        )
        # Restart-safe verified chain for the child (SQLite: no-op — the DB
        # resolves the exact snapshot; in-memory: cached per cycle).
        await self.sessions.store_verified(
            owner_id, child.cycle.cycle_id, exact
        )
        child_context = await self._teaching_context(owner_id, child, exact)
        child_context["resume_parent_cycle_id"] = str(session.cycle.cycle_id)
        child_context["choices"] = choices
        await self.sessions.teaching.save(owner_id, child.cycle.cycle_id, child_context)
        recommendation = await self.practice.recommendation_for_offer(owner_id, offer_id)
        await self._cycle_fact(owner_id, child, exact, "problem_started",
            task_purpose="transfer" if recommendation and recommendation.purpose in {"A1", "A2", "B"} else "practice")
        await self._emit(
            stream,
            session,
            parent_transition,
            "开始练习！",
            detail="practice_started",
            extra={
                "child_cycle_id": str(child.cycle.cycle_id),
                # Student-facing problem surface ONLY — no answer key.
                "problem_latex": problem.display_latex,
                "problem_type": problem.problem_type,
            },
        )

    async def _decline_practice_offer(
        self,
        session: TutoringSession,
        owner_id: str,
        payload: dict[str, Any],
        expected_version: int | None,
        idempotency_key: str,
        stream: MathTutorEventSink,
    ) -> None:
        """Decline the session's pending offer (owner + parent cycle scoped).

        Payload ``offer_id`` is optional — the ACTIVE offer of the current
        parent cycle is used when omitted.
        """
        from uuid import UUID

        offer_id = payload.get("offer_id")
        offer = None
        if offer_id:
            try:
                candidate_offer = await self.practice.load_offer(UUID(str(offer_id)))
            except (ValueError, TypeError):
                candidate_offer = None
            if (
                candidate_offer is not None
                and str(candidate_offer.student_id) == str(session.student_id)
                and candidate_offer.parent_cycle_id == session.cycle.cycle_id
            ):
                offer = candidate_offer
        if offer is None or offer.status != "ACTIVE":
            offers = await self.practice.offers_for_student(owner_id)
            offer = next(
                (
                    o
                    for o in offers
                    if o.status == "ACTIVE"
                    and o.parent_cycle_id == session.cycle.cycle_id
                ),
                None,
            )
        if offer is None:
            await stream.error("没有可拒绝的练习 offer", source=self.manifest.name)
            return
        await self.practice.mark_offer_declined(owner_id, offer.offer_id)
        await self._dialogue(stream, session, "已略过这次练习邀请，原题保持不变。", "PRACTICE_DECLINED")

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


def _parse_envelope(user_message: str) -> tuple[str, dict[str, Any]]:
    """Parse the command envelope; plain text enters the intent router."""
    text = user_message.strip()
    if not text:
        return (SEND_MESSAGE_COMMAND, {"payload": {"text": ""}})
    if text.startswith("{"):
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"命令 envelope 不是合法 JSON: {exc}") from exc
        command = str(envelope.get("command") or SEND_MESSAGE_COMMAND)
        if envelope.get("protocol_version", 1) == 1:
            command = LEGACY_COMMAND_ALIASES.get(command, command)
        if command not in USER_COMMANDS and command != SEND_MESSAGE_COMMAND:
            raise ValueError(f"未知命令: {command}")
        return (command, envelope)
    return (SEND_MESSAGE_COMMAND, {"payload": {"text": text}})


__all__ = [
    "MathTutorController",
    "MathTutorEvent",
    "MathTutorEventSink",
    "MathTutorEventType",
    "MathTutorManifest",
    "MathTutorRequest",
]
