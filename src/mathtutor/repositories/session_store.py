"""Session store contract (Phase 1B + 3).

The controller depends on this Protocol. ``SQLiteSessionStore`` supplies
transactional storage, CAS and owner isolation in both durable and ephemeral
SQLite databases.

Ownership: keys are ``(student_id, client_session_id)`` — the client session
name is a namespace, never an identity; the owner half always comes from the
server-side StudentOwnerScope.

Phase 3 restart-safety: tutor actions are append-only facts; the assistance
ledger (CycleAssistance) and the verified chain (problem/candidate/ref) are
RESTORED from the store at turn start — the capability holds no process
state that outlives a restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from mathtutor.application.state_machine import TutoringSession
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerifiedSolutionRef,
)
from mathtutor.domain.tutoring import CycleTransition, TutorAction
from mathtutor.pedagogy.planner import CycleAssistance


class PracticeOfferAcceptError(Exception):
    """Offer accept refused: not ACTIVE, expired, wrong owner, or replay."""


@dataclass(frozen=True, slots=True)
class LearningCommit:
    """Everything one attempt turn writes atomically (Phase 4, C14).

    The SQLite implementation commits ALL rows (submission/attempt/
    assessment/observation/evidence/student-state CAS/transition/outbox) in
    ONE short transaction. The caller (controller) computes first
    and commits last — READ → COMPUTE → SHORT COMMIT.
    """

    transitions: list[CycleTransition]
    problem_id: UUID
    attempt_submission_id: UUID
    attempt_id: UUID
    raw_text: str
    parsed_steps: list[dict[str, Any]]
    attempt_index: int
    payload_hash: str
    reference_solution_log_id: UUID
    correctness: str
    score: float | None
    assessment_attestation_hash: str
    assessment_policy_version: str = ""
    idempotency_key: str = ""
    verified_claims: tuple[dict[str, Any], ...] = ()
    invalid_claims: tuple[dict[str, Any], ...] = ()
    remaining_requirements: tuple[dict[str, Any], ...] = ()
    observation: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    projection: dict[str, Any] | None = None
    outbox_events: list[dict[str, Any]] = field(default_factory=list)
    teaching_context: dict[str, Any] | None = None
    tracking_attempt: dict[str, Any] | None = None


class SessionStoreProtocol(Protocol):
    """Async persistence contract the capability drives each turn."""

    async def load(
        self, student_id: str, client_session_id: str
    ) -> TutoringSession | None: ...

    async def create(
        self, student_id: str, client_session_id: str
    ) -> TutoringSession: ...

    async def start_new_cycle(
        self, student_id: str, client_session_id: str, *, teaching_context=None
    ) -> TutoringSession: ...

    async def persist_transition(
        self,
        student_id: str,
        transition: CycleTransition,
        problem_id: "UUID | None" = None,
    ) -> None: ...

    async def persist_tutor_action(
        self,
        student_id: str,
        cycle_id: UUID,
        action: TutorAction,
    ) -> None: ...

    async def load_assistance(
        self, student_id: str, cycle_id: UUID
    ) -> CycleAssistance: ...

    async def load_verified(
        self, student_id: str, cycle_id: UUID
    ) -> tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef] | None: ...

    async def store_verified(
        self,
        student_id: str,
        cycle_id: UUID,
        verified: tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef],
    ) -> None: ...

    async def commit_learning_transaction(
        self,
        student_id: str,
        commit: LearningCommit,
    ) -> None: ...

    async def load_learning_history(
        self, student_id: str
    ) -> tuple[list[Any], list[Any]]: ...

    async def load_attempt_index(self, student_id: str, cycle_id: UUID) -> int: ...

    async def iter_for_student(
        self, student_id: str
    ) -> list[tuple[str, TutoringSession]]: ...

    async def clear(self) -> None: ...

    # ---- Phase 5: practice-offer accept (ONE short transaction, §7.10) ----

    async def accept_practice_offer(
        self,
        student_id: str,
        client_session_id: str,
        offer_id: UUID,
        parent_transition: CycleTransition,
        child: TutoringSession,
        outbox_events: list[dict[str, Any]] = (),
        *,
        teaching_context: dict[str, Any] | None = None,
        learning_events: tuple[Any, ...] = (),
    ) -> None:
        """Consume the offer + close the parent + create the child cycle.

        SQLite: ONE transaction (offer CAS → parent transition → child
        cycle row + its 3 transitions → outbox). In-memory: the session
        objects already mutated; this registers the child as the current
        cycle of the client session.
        """
        ...

    async def load_child_cycle_for_offer(
        self, student_id: str, offer_id: UUID
    ) -> TutoringSession | None:
        """The child cycle created by accepting ``offer_id`` (idempotent
        replay of an already-accepted offer), owner-scoped."""
        ...


def _assistance_from_actions(actions: list[TutorAction]) -> CycleAssistance:
    """Rebuild the assistance ledger from append-only tutor actions (§7.1).

    The ledger is a PROJECTION over facts — never stored itself, so it can
    always be rebuilt after a restart.
    """
    hints = sum(1 for a in actions if a.action == "GIVE_HINT")
    explanations = sum(
        1 for a in actions if a.action in ("EXPLAIN_CONCEPT", "SHOW_EXAMPLE")
    )
    max_level = max((a.effective_assistance_level for a in actions), default=0)
    return CycleAssistance(
        hints_issued=hints,
        explanations_issued=explanations,
        max_level_issued=max_level,
    )


__all__ = [
    "LearningCommit",
    "PracticeOfferAcceptError",
    "SessionStoreProtocol",
]
