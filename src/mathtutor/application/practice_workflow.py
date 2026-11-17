"""PracticeWorkflowService — isolated tutoring workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from uuid import UUID

from mathtutor.application.state_machine import (
    CycleCommand,
    CycleState,
    TutoringSession,
)
from mathtutor.application.tutor_contracts import MathTutorEventSink
from mathtutor.repositories.session_store import SessionStoreProtocol


@dataclass(slots=True)
class PracticeWorkflowService:
    """Own this workflow; storage and cross-workflow effects are explicit dependencies."""

    cycle_fact: Callable[..., Awaitable[Any]]
    dialogue: Callable[..., Awaitable[Any]]
    emit: Callable[..., Awaitable[Any]]
    prepare_presentation: Callable[..., Awaitable[Any]]
    teaching_context: Callable[..., Awaitable[Any]]
    practice: Any
    practice_service: Any
    sessions: SessionStoreProtocol

    async def offer_after_solved(
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
        assistance = await self.sessions.load_assistance(
            owner_id, session.cycle.cycle_id
        )
        deliveries = await self.sessions.teaching.for_cycle(
            owner_id, session.cycle.cycle_id
        )
        exposure = (
            5
            if any(
                x.get("target_answer_exposed")
                for x in deliveries
                if x["status"] in {"possibly_exposed", "presented"}
            )
            else assistance.max_level_issued
        )
        tracking = getattr(self.sessions, "student_state", None)
        if tracking is not None and verified:
            exposure = max(
                exposure,
                (await tracking.exposure_context(owner_id, verified[0].content_hash))[
                    "assistance_level"
                ],
            )
        purpose = purpose or ("B" if exposure >= 5 else "A2" if exposure else "A1")
        from mathtutor.learning.knowledge_tracing.events import valid_events

        history = await tracking.events(owner_id) if tracking else []
        from mathtutor.application.evidence_projection import (
            teaching_evidence,
            teaching_practice_focus,
        )

        context = (
            await self.teaching_context(owner_id, session, verified)
            if verified
            else None
        )
        focus, practice_guidance = "", ""
        if context:
            context["learner_evidence"] = teaching_evidence(
                history, context["skill_ids"]
            )
            focus, practice_guidance = teaching_practice_focus(context)
        basis_events = [
            e
            for e in valid_events(history)
            if e.cycle_id == str(session.cycle.cycle_id)
            and e.event_type == "attempt_assessed"
        ]
        from mathtutor.application.evidence_projection import PRACTICE_ERROR_CODES

        if focus and context:
            basis_events.extend(
                e
                for e in valid_events(history)
                if e.independent_target
                and e.correctness == "incorrect"
                and set(e.skill_ids) & set(context["skill_ids"])
                and set(e.misconception_codes) & PRACTICE_ERROR_CODES
            )
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
                history_cutoff_seq=max((e.event_seq for e in history), default=0)
                if tracking
                else None,
                evidence_ids=tuple(e.event_id for e in basis_events),
                foundation_focus=focus,
            )
        except Exception:
            offer = None
        from types import SimpleNamespace

        transition = SimpleNamespace(
            from_state=session.state.value,
            to_state=session.state.value,
            trigger_command="request_practice",
        )
        if offer is None:
            await self.emit(
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
        await self.emit(
            stream,
            session,
            transition,
            practice_guidance
            + {
                "A1": "这道题已经独立完成，可以换一道题检验迁移。",
                "A2": "这道题在帮助后完成了，可以换一道题独立巩固。",
                "B": "已展示解答；这不等于已经掌握。可以换一道题独立检测。",
                "D": "练习题已经通过验证。你可以开始，原题会保留。",
            }.get(purpose, "练习题已经准备好。"),
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

    async def accept_practice_offer(
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

        from mathtutor.domain.tutoring import CycleTransition

        raw_offer_id = payload.get("offer_id")
        try:
            offer_id = UUID(str(raw_offer_id))
        except (ValueError, TypeError):
            await stream.error("offer_id 无效", source="math_tutor")
            return
        offer = await self.practice.load_offer(offer_id)
        # 1. Owner isolation: the offer must belong to THIS student.
        if offer is None or str(offer.student_id) != str(session.student_id):
            await stream.error("offer 不存在", source="math_tutor")
            return
        # 5. Idempotent replay: an accepted offer returns the SAME child.
        if offer.status == "ACCEPTED":
            child = await self.sessions.load_child_cycle_for_offer(owner_id, offer_id)
            if child is None:
                await stream.error(
                    "offer 已接受，但子周期不可恢复", source="math_tutor"
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
            await self.emit(
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
            await stream.error("offer 已失效（已撤销或已过期）", source="math_tutor")
            return
        if offer.expires_at <= datetime.now(timezone.utc):
            await stream.error("offer 已过期", source="math_tutor")
            return
        if offer.parent_cycle_id != session.cycle.cycle_id:
            await stream.error("offer 不属于当前周期", source="math_tutor")
            return
        release = await self.practice.load_release(offer.exercise_release_id)
        if release is None or release.status != "released":
            await stream.error(
                "练习题已下架（发布被撤销或已替换）", source="math_tutor"
            )
            return
        # 4. Exact snapshot — no VERIFIED bytes ⇒ no child cycle (fail closed).
        exact = await self.practice.load_exact_verified(release)
        if exact is None:
            await stream.error(
                "练习题未通过独立验证，无法开始练习", source="math_tutor"
            )
            return
        problem, _candidate, _ref = exact
        recommendation = await self.practice.recommendation_for_offer(
            owner_id, offer_id
        )
        response_mode = (
            recommendation.response_mode if recommendation else "single_choice"
        )
        choices = None
        if response_mode == "single_choice":
            from mathtutor.application.multiple_choice import make_choices

            try:
                choices = make_choices(
                    problem, _candidate, salt=str(release.release_id)
                )
            except ValueError:
                await stream.error(
                    "这道旧练习暂不支持选择题，请重新邀请练习。", source="math_tutor"
                )
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
        from mathtutor.pedagogy.teaching_plan import initial_context

        child_context = initial_context(
            problem,
            _candidate,
            verified_solution_ref=_ref,
            cycle_id=child.cycle.cycle_id,
        )
        child_context.update(
            resume_parent_cycle_id=str(session.cycle.cycle_id),
            client_session_id=client_session_id,
            choices=choices,
            response_mode=response_mode,
            observation_kind=recommendation.observation_kind
            if recommendation
            else "diagnostic",
            options_exposed=choices is not None,
        )
        choice_events = ()
        if choices and getattr(self.sessions, "student_state", None) is not None:
            from mathtutor.learning.knowledge_tracing.events import LearningEvent
            from mathtutor.learning.skill_graph import skills_for_problem

            choice_events = (
                LearningEvent(
                    event_id=f"options_exposed:{child.cycle.cycle_id}",
                    student_id=owner_id,
                    session_id=str(child.session_id),
                    cycle_id=str(child.cycle.cycle_id),
                    event_type="options_exposed",
                    problem_id=str(problem.problem_id),
                    problem_revision=problem.content_hash,
                    item_family_id=problem.problem_type,
                    skill_ids=skills_for_problem(problem),
                    options_exposed=True,
                ),
            )
        await self.prepare_presentation(owner_id, child, exact)
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
            teaching_context=child_context,
            learning_events=choice_events,
        )
        # Restart-safe verified chain for the child (SQLite: no-op — the DB
        # resolves the exact snapshot; in-memory: cached per cycle).
        await self.sessions.store_verified(owner_id, child.cycle.cycle_id, exact)
        await self.cycle_fact(
            owner_id,
            child,
            exact,
            "problem_started",
            task_purpose="transfer"
            if recommendation and recommendation.purpose in {"A1", "A2", "B"}
            else "practice",
        )
        await self.emit(
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

    async def decline_practice_offer(
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
            await stream.error("没有可拒绝的练习 offer", source="math_tutor")
            return
        await self.practice.mark_offer_declined(owner_id, offer.offer_id)
        await self.dialogue(
            stream, session, "已略过这次练习邀请，原题保持不变。", "PRACTICE_DECLINED"
        )
