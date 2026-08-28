"""MathTutor-owned controller — the single student-facing business entry.

Command envelope (§13.2) arrives as the user message (JSON; plain text is
accepted as a ``submit_problem`` shorthand):

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
from dataclasses import dataclass, field
from enum import Enum
from fractions import Fraction
from typing import Any, Literal, Protocol
from uuid import uuid4

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.verification_backend import (
    VerificationBackendError,
)
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
from mathtutor.pedagogy.stage_policy import PRIMARY_POLICY, StagePolicy
from mathtutor.pedagogy.tutor_writer import (
    PublicProblemView,
    TemplateTutorWriter,
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
}

_STUDENT_COMMAND_VALUES = frozenset(c.value for c in USER_COMMANDS.values())


def student_allowed_inputs(state: CycleState) -> list[str]:
    """Student-channel commands only: internal outcomes (e.g.
    ``solution_shown_permitted``) never appear in the UI contract — the
    client can only ever send what it is shown (design doc §13.3)."""
    return [
        command.value
        for command in allowed_next_commands(state)
        if command.value in _STUDENT_COMMAND_VALUES
    ]


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
            "确定性解析-求解-验证管线，不支持通用聊天。"
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
        self.policy: StagePolicy = policy or PRIMARY_POLICY
        self.planner = planner or PedagogyPlanner()
        self.projector = projector or SolutionDisclosureProjector()
        self.writer = writer or TemplateTutorWriter()
        self.guard = guard or TutorOutputGuard()

    # ------------------------------------------------------------- run entry

    async def run(self, request: MathTutorRequest, stream: MathTutorEventSink) -> None:
        """Route one command envelope through the tutoring state machine.

        The auth layer has already resolved a trusted owner.  The controller
        never consults process-global auth context and never accepts identity
        fields from the client envelope.
        """
        owner = request.owner
        # READ phase: load the persisted cycle snapshot (or create the
        # initial row) — one short transaction, then compute in memory.
        session = await self.sessions.load(owner.student_id, request.session_id)
        if session is None:
            session = await self.sessions.create(owner.student_id, request.session_id)
        # Phase 3 restart-safety: restore the pedagogy state (verified chain
        # + assistance ledger) from the store — never from process memory.
        verified = await self.sessions.load_verified(
            owner.student_id, session.cycle.cycle_id
        )
        assistance = await self.sessions.load_assistance(
            owner.student_id, session.cycle.cycle_id
        )
        try:
            command, envelope = _parse_envelope(request.user_message)
        except ValueError as exc:
            await stream.error(str(exc), source=self.manifest.name)
            return

        expected_version = envelope.get("expected_cycle_version")
        idempotency_key = str(envelope.get("idempotency_key", ""))
        payload = envelope.get("payload") or {}
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
        except (InvalidTransitionError, VersionConflictError) as exc:
            await stream.error(
                str(exc),
                source=self.manifest.name,
                metadata={"cycle_state": session.state.value, "cycle_state_version": session.version},
            )
        except Exception as exc:  # fail closed: no state mutation, clear error
            await stream.error(f"内部错误: {exc}", source=self.manifest.name)

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
        if command == "submit_problem":
            await self._submit_problem(session, owner_id, payload, expected_version, idempotency_key, stream)
        elif command == "submit_attempt":
            await self._submit_attempt(
                session, owner_id, payload, expected_version, idempotency_key,
                verified, assistance, stream,
            )
        elif command == "request_hint":
            await self._prompt_command(
                session, owner_id, CycleCommand.REQUEST_HINT, "提示", expected_version, idempotency_key,
                verified, assistance, stream,
            )
        elif command == "request_explanation":
            await self._prompt_command(
                session, owner_id, CycleCommand.REQUEST_EXPLANATION, "讲解", expected_version, idempotency_key,
                verified, assistance, stream,
            )
        elif command == "request_example":
            await self._prompt_command(
                session, owner_id, CycleCommand.REQUEST_EXAMPLE, "示例", expected_version, idempotency_key,
                verified, assistance, stream,
            )
        elif command == "request_solution":
            # L5: the planner fails closed without a verified ref; the
            # projector/writer/guard only then see the full solution.
            await self._prompt_command(
                session, owner_id, CycleCommand.SOLUTION_SHOWN_PERMITTED, "完整解析", expected_version, idempotency_key,
                verified, assistance, stream,
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
        elif command in (
            "clarify_problem",
            "clarify_attempt",
            "cancel_turn",
        ):
            await self._simple_step(session, owner_id, command, expected_version, idempotency_key, stream)
        else:
            raise InvalidTransitionError(session.state, CycleCommand.SUBMIT_PROBLEM)

    async def _submit_problem(
        self,
        session: TutoringSession,
        owner_id: str,
        payload: dict[str, Any],
        expected_version: int | None,
        idempotency_key: str,
        stream: MathTutorEventSink,
    ) -> None:
        await self._step(
            owner_id,
            session,
            CycleCommand.SUBMIT_PROBLEM,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        # COMPUTE phase: deterministic parse → solve → verify (no DB work).
        result = await self.service.submit_problem(str(payload.get("text", "")))
        if result.kind == "ambiguous":
            transition = await self._step(owner_id, session, CycleCommand.GROUNDING_AMBIGUOUS)
            await self._emit(stream, session, transition, "题目有歧义，请澄清", detail=result.reason)
        elif result.kind == "unsupported":
            transition = await self._step(owner_id, session, CycleCommand.GROUNDING_UNSUPPORTED)
            await self._emit(stream, session, transition, "暂不支持这类题目", detail=result.reason)
        elif result.kind == "unverified_blocked":
            transition = await self._step(owner_id, session, CycleCommand.VERIFICATION_FAILED)
            await self._emit(stream, session, transition, "题目未通过独立验证", detail=result.reason)
        else:
            await self._step(owner_id, session, CycleCommand.GROUNDING_OK)
            assert result.problem is not None
            session.problem_id = result.problem.problem_id
            transition = await self._step(
                owner_id,
                session,
                CycleCommand.VERIFICATION_VERIFIED,
                problem_id=result.problem.problem_id,
            )
            # Persist the verified chain for restart-safe teaching control
            # (SQLite already holds the attestation from the service commit;
            # the in-memory store caches it per cycle).
            await self.sessions.store_verified(
                owner_id,
                session.cycle.cycle_id,
                (result.problem, result.candidate, result.verified_ref),
            )
            await self._emit(
                stream,
                session,
                transition,
                f"题目已解析并验证：{result.problem.display_latex}",
                detail="verified",
                extra={
                    # Structured problem surface for the UI (contract gap #1
                    # fixed): no string-prefix parsing of tutor text.
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
    ) -> None:
        # ---- READ is done by run(): cycle/verified/assistance restored. ----
        # A child practice cycle (practice_offer_id set, problem_id NULL —
        # ck_cycle_source_xor) judges against the offer→release EXACT
        # snapshot restored by load_verified; the verified chain must exist
        # either way or the attempt cannot be judged (fail closed).
        if verified is None or (
            session.problem_id is None and session.practice_offer_id is None
        ):
            transition = await self._step(
                owner_id, session, CycleCommand.SUBMIT_ATTEMPT,
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
                owner_id, session, CycleCommand.SUBMIT_ATTEMPT,
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
        except VerificationBackendError as exc:
            # Infrastructure failure is not a mathematical assessment.  We
            # preserve the legal cycle transition but persist no attempt
            # assessment, evidence, misconception, mastery, or attestation.
            transition = await self._step(
                owner_id, session, CycleCommand.SUBMIT_ATTEMPT,
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
            CycleCommand.SUBMIT_ATTEMPT,
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

        observation = diagnose(
            assessment=assessment, problem=problem, attempt=student_attempt
        )
        evidence_obj = None
        projection_obj = None
        if assessment.correctness is not Correctness.UNDETERMINED:
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
            raw_text=answer,
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
            verified_claims=assessment.verified_claims,
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
        if assessment.correctness is Correctness.CORRECT:
            await self._offer_after_solved(
                session,
                owner_id,
                skill_id=skill_for_problem(problem),
                stream=stream,
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
        if not reflected:
            await self._step(owner_id, session, CycleCommand.REFLECTED)
        offer = None
        try:
            offer = await self.practice_service.prepare_offer(
                owner_id,
                parent_cycle_id=session.cycle.cycle_id,
                target_skill_ids=(skill_id,) if skill_id else (),
            )
        except Exception:  # practice is best-effort; the cycle must advance
            offer = None
        transition = await self._step(
            owner_id, session, CycleCommand.PRACTICE_OFFERED
        )
        if offer is None:
            await self._emit(
                stream,
                session,
                transition,
                "练习推荐暂时不可用 — 你已经完成了这一步，随时可以进入下一环节",
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
            "做得很棒！为你准备了一道同类练习题，想挑战一下吗？",
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
    ) -> None:
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
            await stream.error(
                f"当前策略不允许这个操作：{exc}",
                source=self.manifest.name,
                metadata={"cycle_state": session.state.value},
            )
            return
        transition = await self._step(
            owner_id, session, command, expected_version=expected_version, idempotency_key=idempotency_key
        )
        # Phase 3 teaching control chain: projector → writer → guard (the
        # action is already planner-sanctioned).
        utterance = await self._realize_utterance(session, verified, action)
        # Append the issued action to the store (append-only fact) so the
        # ledger survives restarts (Phase 3 restart-safety).
        await self.sessions.persist_tutor_action(
            owner_id, session.cycle.cycle_id, action
        )
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
        if command == CycleCommand.REQUEST_HINT:
            delivered = CycleCommand.HINT_DELIVERED
        elif command == CycleCommand.SOLUTION_SHOWN_PERMITTED:
            delivered = CycleCommand.REFLECTED  # L5 shown → reflection
        else:
            delivered = CycleCommand.EXPLANATION_DELIVERED
        await self._step(owner_id, session, delivered)
        if delivered == CycleCommand.REFLECTED and self.practice_service is not None:
            # L5 shown → REFLECTION → server-driven practice offer (§7.5 E2E).
            # The helper emits the final event (offer projection / degraded),
            # so no state-only emit follows.
            await self._offer_after_solved(
                session,
                owner_id,
                skill_id=skill_for_problem(problem) if problem is not None else None,
                stream=stream,
                reflected=True,
            )
        else:
            await self._emit_state(stream, session)

    async def _realize_utterance(
        self,
        session: TutoringSession,
        verified: tuple | None,
        action,
    ):
        """DisclosureProjector → Writer → Guard (Phase 3A-D).

        The planner already chose and sanctioned ``action`` (BEFORE the
        state machine stepped). The writer only sees the projected context;
        the guard verifies the final text against the verified solution.
        Every level below L5 is structurally incapable of carrying answer
        content. ``verified`` comes from the STORE (restored at turn start).
        """
        problem, candidate, ref = verified if verified else (None, None, None)
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
        candidate_text = await self.writer.write(
            problem_view=problem_view,
            disclosure=disclosure,
            policy=self.policy,
            action=action,
        )
        utterance = self.guard.guard_or_fallback(
            candidate=candidate_text,
            candidate_solution=candidate,
            disclosure=disclosure,
            action=action,
        )
        return utterance

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
        await self._emit(stream, session, transition, f"命令 {command} 已确认")

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

        # 6/7. Parent closes (in memory); the child is a NEW TutoringCycle in
        # the SAME session + SAME state machine (§7.8), practice-bound only
        # (problem_id NULL — the XOR invariant; the problem binding lives in
        # the offer→release exact snapshot resolved by load_verified).
        parent_transition = session.step(
            CycleCommand.ACCEPT_PRACTICE_OFFER,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        child = TutoringSession(
            session_id=session.session_id,
            student_id=session.student_id,
            practice_offer_id=offer_id,
        )
        child.step(CycleCommand.SUBMIT_PROBLEM)
        child.step(CycleCommand.GROUNDING_OK)
        child.step(CycleCommand.VERIFICATION_VERIFIED)

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
        transition = await self._step(
            owner_id,
            session,
            CycleCommand.DECLINE_PRACTICE_OFFER,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
        )
        await self.practice.mark_offer_declined(owner_id, offer.offer_id)
        await self._emit(
            stream, session, transition, "已拒绝练习", detail="practice_declined"
        )

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
        await stream.content(
            message,
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
                    "cycle_state": session.state.value,
                    "cycle_state_version": session.version,
                    "allowed_next_inputs": student_allowed_inputs(session.state),
                },
            )
        )


def _parse_envelope(user_message: str) -> tuple[str, dict[str, Any]]:
    """Parse the command envelope; plain text defaults to submit_problem."""
    text = user_message.strip()
    if not text:
        return ("submit_problem", {"payload": {"text": ""}})
    if text.startswith("{"):
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"命令 envelope 不是合法 JSON: {exc}") from exc
        command = str(envelope.get("command") or "submit_problem")
        if command not in USER_COMMANDS:
            raise ValueError(f"未知命令: {command}")
        return (command, envelope)
    return ("submit_problem", {"payload": {"text": text}})


__all__ = [
    "MathTutorController",
    "MathTutorEvent",
    "MathTutorEventSink",
    "MathTutorEventType",
    "MathTutorManifest",
    "MathTutorRequest",
]
