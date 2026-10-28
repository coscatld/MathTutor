"""SQLite session store (Phase 1B) — durable cycles with CAS + owner isolation.

Implements :class:`SessionStoreProtocol` over short UoW transactions
(READ → COMPUTE → COMMIT): each load/create/persist is its own transaction,
never a transaction spanning solver/verifier/LLM work.

The database is the authoritative cycle record between turns; a restart or
reconnect resumes from the last committed state/version.
"""

from __future__ import annotations

import hashlib
from typing import Any
from uuid import UUID

from mathtutor.application.state_machine import TutoringSession
from mathtutor.domain.tutoring import CycleTransition
from mathtutor.repositories import sqlite_runtime as rt
from mathtutor.repositories.uow import MathTutorUow


def _hash_uuid(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _restore(snapshot: rt.CycleSnapshot, student_id: str) -> TutoringSession:
    # Non-UUID student ids (e.g. "local-dev-student") map deterministically.
    student_uuid = UUID(hex=hashlib.sha256(student_id.encode("utf-8")).hexdigest()[:32])
    return TutoringSession.restore(
        cycle_id=snapshot.cycle_id,
        student_id=student_uuid,
        session_id=snapshot.session_id,
        state=snapshot.state,
        state_version=snapshot.state_version,
        problem_id=snapshot.problem_id,
        practice_offer_id=snapshot.practice_offer_id,
    )


class SQLiteSessionStore:
    """Durable owner-keyed cycle store over the product database."""

    def __init__(self, engine: Any) -> None:
        self.uow = MathTutorUow(engine)
        from mathtutor.repositories.teaching_repository import TeachingRepository
        self.teaching = TeachingRepository(engine)
        self.student_state = None

    async def focus_cycle(self, student_id, client_session_id, cycle_id):
        async with self.uow.transaction() as conn:
            await rt.set_cycle_focus(conn, student_id=student_id,
                client_session_id=client_session_id, cycle_id=cycle_id)
            snapshot = await rt.load_cycle(conn, student_id=student_id, client_session_id=client_session_id)
        return _restore(snapshot, student_id)

    async def load(self, student_id: str, client_session_id: str) -> TutoringSession | None:
        async with self.uow.transaction() as conn:
            snapshot = await rt.load_cycle(
                conn, student_id=student_id, client_session_id=client_session_id
            )
        if snapshot is None:
            return None
        return _restore(snapshot, student_id)

    async def create(self, student_id: str, client_session_id: str) -> TutoringSession:
        async with self.uow.transaction() as conn:
            await rt.ensure_student(conn, student_id=student_id)
            snapshot = await rt.create_cycle(
                conn, student_id=student_id, client_session_id=client_session_id
            )
        return _restore(snapshot, student_id)

    async def start_new_cycle(self, student_id: str, client_session_id: str, *, teaching_context=None) -> TutoringSession:
        async with self.uow.transaction() as conn:
            await rt.ensure_student(conn, student_id=student_id)
            existing = await rt.load_cycle(
                conn, student_id=student_id, client_session_id=client_session_id
            )
            if existing is None:
                snapshot = await rt.create_cycle(
                    conn, student_id=student_id, client_session_id=client_session_id
                )
            else:
                snapshot = await rt.create_successor_cycle(
                    conn, student_id=student_id, parent=existing
                )
            await rt.set_cycle_focus(conn, student_id=student_id,
                client_session_id=client_session_id, cycle_id=snapshot.cycle_id)
            if teaching_context is not None:
                from copy import deepcopy
                context = deepcopy(teaching_context)
                context["task_context"]["cycle_id"] = str(snapshot.cycle_id)
                # Focus and diagnostic provenance are one durable operation.
                # No interruption can expose a child as ordinary practice.
                await self.teaching.save(student_id, snapshot.cycle_id, context, conn=conn)
        return _restore(snapshot, student_id)

    async def persist_transition(
        self,
        student_id: str,
        transition: CycleTransition,
        problem_id: UUID | None = None,
    ) -> None:
        """CAS commit: WHERE cycle_id + student_id + state_version = prior."""
        async with self.uow.transaction() as conn:
            await rt.persist_transition(
                conn,
                student_id=student_id,
                cycle_id=transition.cycle_id,
                transition=transition,
                problem_id=problem_id,
            )

    async def persist_tutor_action(
        self,
        student_id: str,
        cycle_id: UUID,
        action: Any,
    ) -> None:
        """Append the issued TutorAction (append-only fact, §7.1 ledger)."""
        from mathtutor.repositories.sqlite_education import insert_tutor_action

        async with self.uow.transaction() as conn:
            await insert_tutor_action(
                conn,
                student_id=student_id,
                cycle_id=cycle_id,
                action=action.action,
                effective_assistance_level=action.effective_assistance_level,
                solution_visibility=action.solution_visibility,
                target_step_index=action.target_step_index,
                action_id=action.action_id,
            )

    async def commit_teaching_action(self, student_id, cycle_id, transitions, action, context):
        """One checkpoint for state, actual disclosure action, and resumable text."""
        from mathtutor.repositories.sqlite_education import insert_tutor_action
        async with self.uow.transaction() as conn:
            for transition in transitions:
                await rt.persist_transition(conn, student_id=student_id,
                    cycle_id=cycle_id, transition=transition)
            await insert_tutor_action(conn, student_id=student_id, cycle_id=cycle_id,
                action_id=action.action_id, action=action.action,
                effective_assistance_level=action.effective_assistance_level,
                solution_visibility=action.solution_visibility, target_step_index=action.target_step_index)
            await self.teaching.save(student_id, cycle_id, context, conn=conn)

    async def persist_transitions(self, student_id, transitions):
        async with self.uow.transaction() as conn:
            for transition in transitions:
                await rt.persist_transition(conn, student_id=student_id,
                    cycle_id=transition.cycle_id, transition=transition)

    async def load_assistance(self, student_id: str, cycle_id: UUID) -> Any:
        """Rebuild the ledger from persisted tutor_actions (projection)."""
        from sqlalchemy import select

        from mathtutor.infrastructure.schema import tutor_actions
        from mathtutor.repositories.session_store import _assistance_from_actions
        from mathtutor.domain.tutoring import TutorAction

        async with self.uow.transaction() as conn:
            rows = (
                await conn.execute(
                    select(tutor_actions)
                    .where(tutor_actions.c.cycle_id == str(cycle_id))
                    .where(tutor_actions.c.student_id == student_id)
                    .order_by(tutor_actions.c.created_at)
                )
            ).all()
        actions = [
            TutorAction(
                action=row.action,
                effective_assistance_level=row.effective_assistance_level,
                solution_visibility=row.solution_visibility,
            )
            for row in rows
        ]
        return _assistance_from_actions(actions)

    async def load_verified(self, student_id: str, cycle_id: UUID) -> Any:
        """Restore the verified chain for the cycle.

        Two paths (design doc §11.3, exact-snapshot invariant):

        - problem-bound cycle (parent): the problem's persisted attestation;
        - practice-bound cycle (child, ``practice_offer_id`` set, problem_id
          NULL — the ``ck_cycle_source_xor`` invariant): the OFFER → RELEASE
          exact snapshot — the release's OWN solution_candidate_id +
          verification_log_id, never "the newest attestation".

        Owner-scoped either way; None → the caller fails closed.
        """
        from sqlalchemy import select

        from mathtutor.infrastructure.schema import (
            practice_offers,
            tutoring_cycles,
        )
        from mathtutor.repositories.sqlite_math_facts import (
            load_verified_for_problem,
        )
        from mathtutor.repositories.sqlite_practice import (
            load_exact_verified_by_release,
        )

        async with self.uow.transaction() as conn:
            row = (
                await conn.execute(
                    select(tutoring_cycles)
                    .where(tutoring_cycles.c.cycle_id == str(cycle_id))
                    .where(tutoring_cycles.c.student_id == student_id)
                )
            ).first()
            if row is None:
                return None
            if row.practice_offer_id:
                offer = (
                    await conn.execute(
                        select(practice_offers).where(
                            practice_offers.c.offer_id == row.practice_offer_id
                        )
                    )
                ).first()
                if offer is None:
                    return None
                return await load_exact_verified_by_release(
                    conn, UUID(offer.exercise_release_id)
                )
            if not row.problem_id:
                return None
            return await load_verified_for_problem(conn, UUID(row.problem_id))

    async def store_verified(self, student_id: str, cycle_id: UUID, verified: Any) -> None:
        # The attestation is already persisted by the service (Phase 1C);
        # the store's job is restore, not cache.
        pass

    async def commit_learning_transaction(self, student_id: str, commit: Any) -> None:
        """Phase 4 C14: ONE short transaction writes transition + submission
        + attempt + assessment + observation + evidence + student-state CAS
        + outbox events. Any exception rolls EVERYTHING back."""
        from mathtutor.repositories import sqlite_education as edu
        from mathtutor.repositories.uow import append_outbox_events

        cycle_id = commit.transitions[0].cycle_id
        async with self.uow.transaction() as conn:
            # 1. CAS cycle transitions (owner + version checked, in order).
            for transition in commit.transitions:
                await rt.persist_transition(
                    conn,
                    student_id=student_id,
                    cycle_id=transition.cycle_id,
                    transition=transition,
                )
            # 2. Attempt chain (append-only). The submission row is created
            # here and its issued id binds the attempt row (FK consistency).
            await edu.insert_attempt_submission(
                conn,
                student_id=student_id,
                cycle_id=cycle_id,
                raw_text=commit.raw_text,
                idempotency_key=commit.idempotency_key or str((commit.evidence or {}).get("idempotency_key") or ""),
                submission_id=commit.attempt_submission_id,
            )
            await edu.insert_attempt(
                conn,
                student_id=student_id,
                cycle_id=cycle_id,
                attempt_submission_id=commit.attempt_submission_id,
                parsed_steps=commit.parsed_steps,
                attempt_index=commit.attempt_index,
                payload_hash=commit.payload_hash,
                attempt_id=commit.attempt_id,
            )
            # 3. Assessment (verification log XOR subject = attempt).
            assessment_log_id = await edu.insert_attempt_assessment(
                conn,
                student_id=student_id,
                attempt_id=commit.attempt_id,
                cycle_id=cycle_id,
                problem_id=commit.problem_id,
                reference_solution_log_id=commit.reference_solution_log_id,
                correctness=commit.correctness,
                score=commit.score,
                attestation_hash=commit.assessment_attestation_hash,
                policy_version=commit.assessment_policy_version,
                verified_claims=commit.verified_claims,
                invalid_claims=commit.invalid_claims,
                remaining_requirements=commit.remaining_requirements,
            )
            # 4. Misconception observation (append-only; deterministic id).
            if commit.observation is not None:
                await edu.insert_misconception_observation(
                    conn,
                    student_id=student_id,
                    attempt_id=commit.attempt_id,
                    rule_id=str(commit.observation.get("rule_id") or ""),
                    confidence=float(commit.observation.get("confidence") or 0.0),
                    detail=dict(commit.observation.get("detail") or {}),
                )
            # 5. Evidence (only when the attempt is determinate) + state CAS.
            if commit.evidence is not None:
                await edu.insert_mastery_evidence(
                    conn,
                    student_id=student_id,
                    attempt_id=commit.attempt_id,
                    skill_id=str(commit.evidence.get("skill_id") or ""),
                    attempt_assessment_log_id=assessment_log_id,
                    correctness=commit.correctness,
                    score=float(commit.score if commit.score is not None else 0.0),
                    difficulty=int(commit.evidence.get("difficulty") or 1),
                    effective_assistance_level=int(
                        commit.evidence.get("effective_assistance_level") or 0
                    ),
                    evidence_version=str(commit.evidence.get("evidence_version") or "mt-evidence-v1"),
                    idempotency_key=str(commit.evidence.get("idempotency_key") or ""),
                )
            if commit.projection is not None:
                await edu.upsert_student_state(
                    conn,
                    student_id=student_id,
                    estimator_version=str(commit.projection.get("estimator_version") or ""),
                    projection_version=int(commit.projection.get("projection_version") or 1),
                    concept_mastery=list(commit.projection.get("concept_mastery") or []),
                    skill_mastery=list(commit.projection.get("skill_mastery") or []),
                    active_misconceptions=list(commit.projection.get("active_misconceptions") or []),
                )
            # 6. Outbox in the SAME transaction.
            if commit.teaching_context is not None:
                await self.teaching.save(student_id, commit.transitions[0].cycle_id, commit.teaching_context, conn=conn)
            if self.student_state is not None and commit.tracking_attempt is not None:
                await self.student_state.record_attempt(student_id, **commit.tracking_attempt, conn=conn)
            if commit.outbox_events:
                await append_outbox_events(conn, list(commit.outbox_events))

    async def load_learning_history(self, student_id: str) -> tuple[list, list]:
        """Replay evidence + observations (deterministic order) for projection."""
        from sqlalchemy import select

        from mathtutor.infrastructure.schema import (
            misconception_observations,
        )
        from mathtutor.learning.diagnosis import MisconceptionObservation
        from mathtutor.repositories.sqlite_education import (
            load_evidence_for_student,
        )

        async with self.uow.transaction() as conn:
            evidence = await load_evidence_for_student(conn, student_id)
            rows = (
                await conn.execute(
                    select(misconception_observations)
                    .where(misconception_observations.c.student_id == student_id)
                    .order_by(misconception_observations.c.created_at)
                )
            ).all()
        observations = [
            MisconceptionObservation(
                observation_id=UUID(row.observation_id),
                student_id=UUID(hex=_hash_uuid(student_id)),
                attempt_id=UUID(row.attempt_id),
                rule_id=row.rule_id,
                confidence=row.confidence,
                detail=row.detail,
                created_at=row.created_at,
            )
            for row in rows
        ]
        return evidence, observations

    async def load_attempt_index(self, student_id: str, cycle_id: UUID) -> int:
        """Next attempt index for this cycle (owner-scoped count + 1)."""
        from sqlalchemy import func, select

        from mathtutor.infrastructure.schema import attempts

        async with self.uow.transaction() as conn:
            count = (
                await conn.execute(
                    select(func.count())
                    .select_from(attempts)
                    .where(attempts.c.cycle_id == str(cycle_id))
                    .where(attempts.c.student_id == student_id)
                )
            ).scalar_one()
        return int(count) + 1

    async def accept_practice_offer(
        self,
        student_id: str,
        client_session_id: str,
        offer_id: UUID,
        parent_transition: Any,
        child: Any,
        outbox_events: list[dict[str, Any]] = (),
        *, teaching_context: dict[str, Any] | None = None,
        learning_events: tuple[Any, ...] = (),
    ) -> None:
        """Accept ONE practice offer in ONE short transaction (§7.7/§7.10):

        1. offer CAS: ACTIVE → ACCEPTED (owner + not expired; rowcount 0 ⇒
           stale/revoked/expired/already-consumed — never a silent no-op);
        2. the parent's ACCEPT transition (CAS on its state_version);
        3. the child cycle row (problem_received v0, practice_offer_id set,
           same session as the parent — the unique (student, client session)
           constraint forbids a second session row) + its 3 transitions
           (SUBMIT_PROBLEM → GROUNDING_OK → VERIFICATION_VERIFIED, CAS v0→v3);
        4. the accept outbox events in the SAME transaction.

        Any failure rolls EVERYTHING back — no offer consumed without its
        child cycle, no child cycle without its consumed offer.
        """
        from mathtutor.repositories import sqlite_runtime as rt
        from mathtutor.repositories.session_store import (
            PracticeOfferAcceptError,
        )
        from mathtutor.repositories.sqlite_practice import (
            accept_offer_cas,
        )
        from mathtutor.repositories.uow import append_outbox_events

        async with self.uow.transaction() as conn:
            accepted = await accept_offer_cas(
                conn, student_id=student_id, offer_id=offer_id
            )
            if not accepted:
                raise PracticeOfferAcceptError(
                    "offer 不是 ACTIVE（已消费/已撤销/已过期）或不属于该学生"
                )
            await rt.persist_transition(
                conn,
                student_id=student_id,
                cycle_id=parent_transition.cycle_id,
                transition=parent_transition,
            )
            await rt.create_practice_child_cycle(
                conn,
                student_id=student_id,
                session_id=child.session_id,
                cycle_id=child.cycle.cycle_id,
                offer_id=offer_id,
            )
            for transition in child.transitions:
                await rt.persist_transition(
                    conn,
                    student_id=student_id,
                    cycle_id=child.cycle.cycle_id,
                    transition=transition,
                )
            await rt.set_cycle_focus(conn, student_id=student_id,
                client_session_id=client_session_id, cycle_id=child.cycle.cycle_id)
            if teaching_context is not None:
                await self.teaching.save(student_id, child.cycle.cycle_id, teaching_context, conn=conn)
            for event in learning_events:
                await self.student_state.append_event(event, conn=conn)
            if outbox_events:
                await append_outbox_events(conn, list(outbox_events))

    async def load_child_cycle_for_offer(
        self, student_id: str, offer_id: UUID
    ) -> Any:
        """Owner-scoped child cycle of an accepted offer (idempotent replay)."""
        from mathtutor.repositories import sqlite_runtime as rt

        async with self.uow.transaction() as conn:
            snapshot = await rt.load_cycle_by_offer(
                conn, student_id=student_id, offer_id=offer_id
            )
        if snapshot is None:
            return None
        return _restore(snapshot, student_id)

    async def iter_for_student(self, student_id: str) -> list[tuple[str, TutoringSession]]:
        async with self.uow.transaction() as conn:
            rows = await rt.list_cycles_for_student(conn, student_id=student_id)
        return [(client_id, _restore(snapshot, student_id)) for client_id, snapshot in rows]

    async def clear(self) -> None:
        """Test/dev only: wipe all product rows (schema stays)."""
        from mathtutor.infrastructure.schema import metadata

        async with self.uow.engine.begin() as conn:
            for table in reversed(metadata.sorted_tables):
                await conn.execute(table.delete())


__all__ = ["SQLiteSessionStore"]
