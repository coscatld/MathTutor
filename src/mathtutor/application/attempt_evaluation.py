"""AttemptEvaluationService — isolated tutoring workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import uuid4

from mathtutor.application.math_tutor_service import MathTutorApplicationService
from mathtutor.application.state_machine import (
    CycleCommand,
    CycleState,
    TutoringSession,
)
from mathtutor.application.tutor_contracts import MathTutorEventSink
from mathtutor.application.verification_backend import VerificationBackendError
from mathtutor.domain.hashing import content_hash
from mathtutor.learning.attempt_parser import parse_student_attempt
from mathtutor.learning.attempt_verifier import Correctness
from mathtutor.learning.diagnosis import diagnose
from mathtutor.learning.evidence import EvidenceFactory
from mathtutor.learning.projection import project_student_state
from mathtutor.learning.skills import skill_for_problem
from mathtutor.pedagogy.planner import CycleAssistance
from mathtutor.repositories.session_store import LearningCommit, SessionStoreProtocol


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
            "reference_solution_log_id": str(reference_log_id)
            if reference_log_id
            else "",
            "verdict": verdict,
        }
    )


@dataclass(slots=True)
class AttemptEvaluationService:
    """Own this workflow; storage and cross-workflow effects are explicit dependencies."""

    advance_diagnostic: Callable[..., Awaitable[Any]]
    dialogue: Callable[..., Awaitable[Any]]
    emit: Callable[..., Awaitable[Any]]
    offer_after_solved: Callable[..., Awaitable[Any]]
    step: Callable[..., Awaitable[Any]]
    teaching_context: Callable[..., Awaitable[Any]]
    service: MathTutorApplicationService
    sessions: SessionStoreProtocol

    async def submit_attempt(
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
        submit_command = (
            CycleCommand.CLARIFY_ATTEMPT
            if session.state == CycleState.AWAITING_ATTEMPT_CLARIFICATION
            else CycleCommand.SUBMIT_ATTEMPT
        )
        # ---- READ is done by run(): cycle/verified/assistance restored. ----
        # A child practice cycle (practice_offer_id set, problem_id NULL —
        # ck_cycle_source_xor) judges against the offer→release EXACT
        # snapshot restored by load_verified; the verified chain must exist
        # either way or the attempt cannot be judged (fail closed).
        if verified is None or (
            session.problem_id is None and session.practice_offer_id is None
        ):
            transition = await self.step(
                owner_id,
                session,
                submit_command,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
            transition = await self.step(
                owner_id, session, CycleCommand.DIAGNOSIS_AMBIGUOUS
            )
            await self.emit(stream, session, transition, "没有已验证的题目可供判题")
            return

        problem, candidate, ref = verified
        if (
            ref.problem_id != problem.problem_id
            or ref.problem_content_hash != problem.content_hash
            or ref.solution_candidate_id != candidate.candidate_id
            or ref.solution_payload_hash != candidate.payload_hash
        ):
            transition = await self.step(
                owner_id,
                session,
                submit_command,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
            transition = await self.step(
                owner_id, session, CycleCommand.DIAGNOSIS_AMBIGUOUS
            )
            await self.emit(
                stream,
                session,
                transition,
                "已保存的验证记录无法通过绑定校验，请重新提交题目。",
                detail="verification_binding_invalid",
            )
            return
        answer = str(payload.get("answer", ""))
        from mathtutor.learning.skill_graph import skills_for_problem
        from mathtutor.pedagogy.teaching_plan import (
            apply_assessment,
            assessment_feedback,
            current_subgoal,
        )

        context = await self.teaching_context(owner_id, session, verified)
        if "choice_id" in payload:
            from mathtutor.application.multiple_choice import resolve_choice

            try:
                answer = resolve_choice(
                    context.get("choices"),
                    payload["choice_id"],
                    payload.get("choice_version"),
                )
            except ValueError as exc:
                await stream.error(str(exc), source="math_tutor")
                return
            raw_text_override = f"{payload['choice_id']}. {answer}"
        if context.get("teacher_error_example", {}).get("awaiting_response"):
            await self.assess_teacher_error(
                session,
                owner_id,
                context,
                answer,
                expected_version,
                idempotency_key,
                stream,
            )
            return
        deliveries = await self.sessions.teaching.for_cycle(
            owner_id, session.cycle.cycle_id
        )
        shown = [
            row
            for row in deliveries
            if row["status"] in {"possibly_exposed", "presented"}
        ]
        factual_level = (
            5
            if any(row.get("target_answer_exposed") for row in shown)
            else 1
            if shown
            else 0
        )
        # Old actions without delivery provenance cannot certify independence.
        actual_assistance = CycleAssistance(max_level_issued=factual_level)
        tracking = getattr(self.sessions, "student_state", None)
        if tracking is not None:
            exposure = await tracking.exposure_context(owner_id, problem.content_hash)
            factual_level = max(factual_level, exposure["assistance_level"])
            actual_assistance = CycleAssistance(max_level_issued=factual_level)
            context["legacy_provenance_uncertain"] |= exposure["provenance_uncertain"]
            context["options_exposed"] = (
                context.get("options_exposed", False) or exposure["options_exposed"]
            )
        prediction_id = (
            f"prediction:{session.cycle.cycle_id}:{idempotency_key or uuid4()}"
        )
        submission_event_id = ""
        if tracking is not None:
            presentation = await tracking.presentation(owner_id, session.cycle.cycle_id)
            if presentation is not None:
                prediction_id = presentation["prediction_id"]
            else:
                # Pre-upgrade open cycles have no trustworthy presentation record.
                context["legacy_provenance_uncertain"] = True
            submission_event_id = (
                f"submission:{session.cycle.cycle_id}:{idempotency_key or uuid4()}"
            )
            await tracking.record_submission(
                owner_id,
                event_id=submission_event_id,
                session_id=session.session_id,
                cycle_id=session.cycle.cycle_id,
                problem_id=problem.problem_id,
                problem_revision=problem.content_hash,
                item_family_id=problem.problem_type,
                skill_ids=skills_for_problem(problem),
                response_fingerprint=content_hash(
                    {
                        "raw_response": raw_text_override
                        if raw_text_override is not None
                        else answer
                    }
                ),
                prediction_id=prediction_id,
                task_purpose="diagnostic"
                if context.get("diagnostic_item")
                else "practice",
            )

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
            if (
                problem.problem_type == "linear_system"
                and assessment.correctness is Correctness.PARTIAL
            ):
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
                    merged = ";".join(
                        f"{name}={value['n']}/{value['d']}"
                        for name, value in coordinates.items()
                    )
                    joint_attempt = parse_student_attempt(
                        attempt_submission_id=submission_id,
                        student_id=session.student_id,
                        cycle_id=session.cycle.cycle_id,
                        raw_text=merged,
                        attempt_index=attempt_index,
                    )
                    joint = await self.service.verification_backend.verify_attempt(
                        joint_attempt, problem, candidate
                    )
                    if joint.correctness is Correctness.CORRECT:
                        student_attempt, assessment = joint_attempt, joint
        except VerificationBackendError as exc:
            # Infrastructure failure is not a mathematical assessment.  We
            # preserve the legal cycle transition but persist no attempt
            # assessment, evidence, misconception, mastery, or attestation.
            transition = await self.step(
                owner_id,
                session,
                submit_command,
                expected_version=expected_version,
                idempotency_key=idempotency_key,
            )
            transition = await self.step(
                owner_id, session, CycleCommand.DIAGNOSIS_AMBIGUOUS
            )
            await self.emit(
                stream,
                session,
                transition,
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
        context, scoped_assessment = apply_assessment(
            context,
            assessment,
            raw_text_override if raw_text_override is not None else answer,
            actual_assistance,
        )
        if (
            context.get("legacy_provenance_uncertain")
            and scoped_assessment["evidence_kind"] == "independent"
        ):
            scoped_assessment["evidence_kind"] = "ungradable"
        if (
            shown
            and any(row["status"] != "presented" for row in shown)
            and scoped_assessment["evidence_kind"] == "assisted"
        ):
            scoped_assessment["evidence_kind"] = "ungradable"
        message = assessment_feedback(scoped_assessment)
        if followup_command:
            from mathtutor.application.tutor_runtime import current_turn

            active_turn = current_turn.get()
            context["pending_expression"] = {
                "phase": "assessment_committed",
                "request_id": active_turn.turn_id if active_turn else idempotency_key,
                "command": followup_command,
                "student_request": followup_request,
                "cycle_version": session.version,
                "problem_revision": problem.content_hash,
                "feedback": message,
                "assessment_id": scoped_assessment["assessment_id"],
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
        if assessment.correctness is not Correctness.UNDETERMINED and not context.get(
            "understanding_check"
        ):
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
            (
                history_evidence,
                history_observations,
            ) = await self.sessions.load_learning_history(owner_id)
            projection_obj = project_student_state(
                student_id=session.student_id,
                evidence=[*history_evidence, evidence_obj]
                if evidence_obj
                else history_evidence,
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
                "session_id": str(session.session_id),
                "cycle_id": str(session.cycle.cycle_id),
                "problem_id": str(problem.problem_id),
                "problem_revision": problem.content_hash,
                "item_family_id": problem.problem_type,
                "skill_ids": skills_for_problem(problem),
                "assessment_id": str(student_attempt.attempt_id),
                "attempt_id": str(student_attempt.attempt_id),
                "correctness": assessment.correctness.value,
                "prediction_id": prediction_id,
                "submission_event_id": submission_event_id,
                "response_format": "single_choice"
                if context.get("choices") or context.get("options_exposed")
                else "free_response",
                "completion_scope": "full_problem"
                if assessment.correctness is Correctness.CORRECT
                else "subgoal"
                if assessment.correctness is Correctness.PARTIAL
                else "full_problem",
                "subgoal_id": current_subgoal(context)["id"],
                "provenance_uncertain": context.get(
                    "legacy_provenance_uncertain", False
                ),
                "task_purpose": "diagnostic"
                if context.get("diagnostic_item")
                else "practice",
                "misconception_codes": assessment.signals,
                "response_fingerprint": content_hash(
                    {"parsed_steps": list(student_attempt.parsed_steps)}
                ),
            }
            if tracking is not None
            else None,
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

        await self.emit(stream, session, diag_transition, message, detail=detail)

        # Phase 5 (§7.5 E2E): a solved cycle is followed by a server-driven
        # practice offer — SOLVED →(REFLECTED)→ REFLECTION →(PRACTICE_OFFERED).
        if context.get("diagnostic_item"):
            await self.advance_diagnostic(
                session, owner_id, context, assessment, stream
            )
        elif assessment.correctness is Correctness.CORRECT and offer_after:
            await self.offer_after_solved(
                session,
                owner_id,
                skill_id=skill_for_problem(problem),
                stream=stream,
                problem_text=problem.display_latex,
            )

    async def assess_teacher_error(
        self, session, owner_id, context, answer, expected_version, request_id, stream
    ):
        example = context["teacher_error_example"]
        result = await self.service.submit_problem(example["problem_text"])
        if result.kind != "verified":
            await stream.error(
                "这个教师示例暂时无法验证，原题记录没有改变。", source="math_tutor"
            )
            return
        problem, candidate, ref = result.problem, result.candidate, result.verified_ref
        attempt_index = await self.sessions.load_attempt_index(
            owner_id, session.cycle.cycle_id
        )
        submission_id = uuid4()
        attempt = parse_student_attempt(
            attempt_submission_id=submission_id,
            student_id=session.student_id,
            cycle_id=session.cycle.cycle_id,
            raw_text=answer,
            attempt_index=attempt_index,
        )
        prediction_id = (
            f"error-analysis:{session.cycle.cycle_id}:{request_id or submission_id}"
        )
        tracking = getattr(self.sessions, "student_state", None)
        from mathtutor.learning.skill_graph import skills_for_problem

        item = {
            "session_id": str(session.session_id),
            "cycle_id": str(session.cycle.cycle_id),
            "problem_id": str(problem.problem_id),
            "problem_revision": problem.content_hash,
            "item_family_id": problem.problem_type,
            "skill_ids": skills_for_problem(problem),
        }
        if tracking:
            await tracking.prepare_prediction(
                owner_id, prediction_id=prediction_id, **item
            )
        assessment = await self.service.verification_backend.verify_attempt(
            attempt, problem, candidate
        )
        from mathtutor.pedagogy.error_example import assess_teacher_error_repair

        assessment = assess_teacher_error_repair(
            example=example, raw_text=answer, assessment=assessment
        )
        transition = session.step(
            CycleCommand.TEACHER_ERROR_ANALYZED, expected_version=expected_version
        )
        valid = assessment.correctness in {Correctness.CORRECT, Correctness.PARTIAL}
        if valid:
            context["teacher_error_example"]["awaiting_response"] = False
        context.setdefault("error_analyses", []).append(
            {
                "assessment_id": str(attempt.attempt_id),
                "correctness": assessment.correctness.value,
                "student_text": answer,
                "teacher_authored": True,
            }
        )
        commit = LearningCommit(
            transitions=[transition],
            problem_id=problem.problem_id,
            attempt_submission_id=submission_id,
            attempt_id=attempt.attempt_id,
            raw_text=answer,
            parsed_steps=list(attempt.parsed_steps),
            attempt_index=attempt_index,
            payload_hash=attempt.payload_hash,
            reference_solution_log_id=ref.verification_log_id,
            correctness=assessment.correctness.value,
            score=assessment.score,
            assessment_attestation_hash=_assessment_attestation_hash(
                attempt,
                reference_log_id=ref.verification_log_id,
                verdict=assessment.correctness.value,
            ),
            assessment_policy_version=assessment.policy_version,
            idempotency_key=request_id,
            verified_claims=assessment.verified_claims,
            invalid_claims=assessment.invalid_claims,
            remaining_requirements=assessment.remaining_requirements,
            teaching_context=context,
            tracking_attempt={
                **item,
                "attempt_id": str(attempt.attempt_id),
                "assessment_id": str(attempt.attempt_id),
                "correctness": assessment.correctness.value,
                "prediction_id": prediction_id,
                "task_purpose": "error_analysis",
                "completion_scope": "error_analysis",
                "response_fingerprint": content_hash(
                    {"parsed_steps": list(attempt.parsed_steps)}
                ),
            }
            if tracking
            else None,
        )
        await self.sessions.commit_learning_transaction(owner_id, commit)
        await self.dialogue(
            stream,
            session,
            "已验证这一步修正成立。这是教师错误示例的分析证据，不代表原题已经完成；现在回到原题。"
            if valid
            else "这次修正还没有通过验证；示例中的错误是老师故意设置的，不会算作你原题做错。请继续检查等式两边的运算。",
            "ERROR_ANALYSIS",
        )
