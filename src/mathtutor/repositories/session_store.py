"""Session store contract + in-memory implementation (Phase 1B + 3).

The capability depends ONLY on this Protocol: the in-memory implementation
keeps tests and the dev loop free of files, and ``SQLiteSessionStore``
(repositories/sqlite_store.py) provides durability + CAS + owner isolation
with the same interface. The database is authoritative when it is in use;
the in-memory store is authoritative only for its own process.

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
from uuid import UUID, uuid4

from mathtutor.application.state_machine import TutoringSession
from mathtutor.domain.problem import MathProblem
from mathtutor.domain.solution import (
    MathSolutionCandidate,
    VerifiedSolutionRef,
)
from mathtutor.domain.tutoring import CycleTransition, TutorAction
from mathtutor.pedagogy.planner import CycleAssistance
from mathtutor.security.scopes import student_uuid


class PracticeOfferAcceptError(Exception):
    """Offer accept refused: not ACTIVE, expired, wrong owner, or replay."""


@dataclass(frozen=True, slots=True)
class LearningCommit:
    """Everything one attempt turn writes atomically (Phase 4, C14).

    The SQLite implementation commits ALL rows (submission/attempt/
    assessment/observation/evidence/student-state CAS/transition/outbox) in
    ONE short transaction; the in-memory implementation appends to its
    per-process history. Either way the caller (capability) computes first
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
    verified_claims: tuple[dict[str, Any], ...] = ()
    invalid_claims: tuple[dict[str, Any], ...] = ()
    remaining_requirements: tuple[dict[str, Any], ...] = ()
    observation: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    projection: dict[str, Any] | None = None
    outbox_events: list[dict[str, Any]] = field(default_factory=list)


class SessionStoreProtocol(Protocol):
    """Async persistence contract the capability drives each turn."""

    async def load(self, student_id: str, client_session_id: str) -> TutoringSession | None: ...

    async def create(self, student_id: str, client_session_id: str) -> TutoringSession: ...

    async def start_new_cycle(self, student_id: str, client_session_id: str) -> TutoringSession: ...

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

    async def load_assistance(self, student_id: str, cycle_id: UUID) -> CycleAssistance: ...

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

    async def iter_for_student(self, student_id: str) -> list[tuple[str, TutoringSession]]: ...

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


class InMemorySessionStore:
    """Process-local store keyed by owner (Phase 0 behavior, async surface).

    Phase 3: tutor actions and the verified chain are held HERE (per cycle)
    instead of inside the capability — the capability only ever talks to the
    store, so in-memory and SQLite backends behave identically.
    """

    def __init__(
        self,
        practice_repository: "Any | None" = None,
    ) -> None:
        self._sessions: dict[tuple[str, str], TutoringSession] = {}
        self._actions: dict[UUID, list[TutorAction]] = {}
        self._verified: dict[UUID, tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef]] = {}
        self._attempt_counts: dict[UUID, int] = {}
        self._evidence_history: dict[str, list[Any]] = {}
        self._observation_history: dict[str, list[Any]] = {}
        # Phase 5: exact-snapshot fallback for child cycles (mirror of the
        # SQLite path); the capability also store_verified()s at accept.
        self.practice_repository = practice_repository

    async def load(self, student_id: str, client_session_id: str) -> TutoringSession | None:
        return self._sessions.get((student_id, client_session_id))

    async def create(self, student_id: str, client_session_id: str) -> TutoringSession:
        session = TutoringSession(session_id=uuid4(), student_id=student_uuid(student_id))
        self._sessions[(student_id, client_session_id)] = session
        return session

    async def start_new_cycle(self, student_id: str, client_session_id: str) -> TutoringSession:
        return await self.create(student_id, client_session_id)

    async def persist_transition(
        self,
        student_id: str,
        transition: CycleTransition,
        problem_id: "UUID | None" = None,
    ) -> None:
        # The in-memory session object IS the record: mutation already
        # happened inside the state machine; nothing further to persist.
        pass

    async def persist_tutor_action(
        self,
        student_id: str,
        cycle_id: UUID,
        action: TutorAction,
    ) -> None:
        self._actions.setdefault(cycle_id, []).append(action)

    async def load_assistance(self, student_id: str, cycle_id: UUID) -> CycleAssistance:
        return _assistance_from_actions(self._actions.get(cycle_id, []))

    async def load_verified(
        self, student_id: str, cycle_id: UUID
    ) -> tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef] | None:
        stored = self._verified.get(cycle_id)
        if stored is not None:
            return stored
        # Child cycle (practice_offer_id, no problem_id — XOR): resolve the
        # release's EXACT snapshot from the practice catalog, mirroring the
        # SQLite path (exact-snapshot invariant §11.3).
        if self.practice_repository is not None:
            for (owner, _client_id), session in self._sessions.items():
                if (
                    owner == student_id
                    and session.cycle.cycle_id == cycle_id
                    and session.cycle.practice_offer_id is not None
                ):
                    offer = await self.practice_repository.load_offer(
                        session.cycle.practice_offer_id
                    )
                    if offer is None:
                        return None
                    release = await self.practice_repository.load_release(
                        offer.exercise_release_id
                    )
                    if release is None:
                        return None
                    return await self.practice_repository.load_exact_verified(release)
        return None

    async def store_verified(
        self,
        student_id: str,
        cycle_id: UUID,
        verified: tuple[MathProblem, MathSolutionCandidate, VerifiedSolutionRef],
    ) -> None:
        self._verified[cycle_id] = verified

    async def commit_learning_transaction(
        self,
        student_id: str,
        commit: LearningCommit,
    ) -> None:
        # In-memory: the session object already mutated; append the learning
        # facts to the per-process history so projections can replay.
        cycle_id = commit.transitions[0].cycle_id
        self._attempt_counts[cycle_id] = self._attempt_counts.get(cycle_id, 0) + 1
        if commit.evidence is not None:
            self._evidence_history.setdefault(student_id, []).append(
                _evidence_from_commit(student_id, commit)
            )
        if commit.observation is not None:
            self._observation_history.setdefault(student_id, []).append(
                _observation_from_commit(student_id, commit)
            )

    async def load_learning_history(
        self, student_id: str
    ) -> tuple[list[Any], list[Any]]:
        return (
            list(self._evidence_history.get(student_id, [])),
            list(self._observation_history.get(student_id, [])),
        )

    async def load_attempt_index(self, student_id: str, cycle_id: UUID) -> int:
        # Next index for this cycle (count of committed attempts + 1).
        return self._attempt_counts.get(cycle_id, 0) + 1

    async def iter_for_student(self, student_id: str) -> list[tuple[str, TutoringSession]]:
        return [
            (client_session_id, session)
            for (owner_id, client_session_id), session in self._sessions.items()
            if owner_id == student_id
        ]

    async def accept_practice_offer(
        self,
        student_id: str,
        client_session_id: str,
        offer_id: UUID,
        parent_transition: CycleTransition,
        child: TutoringSession,
        outbox_events: list[dict[str, Any]] = (),
    ) -> None:
        """Register the accepted offer + child cycle (in-memory).

        The parent session object already mutated in place (CLOSED) and the
        child carries its 3 transitions; the offer CAS lives in the practice
        repository. This makes the in-memory path behave like the SQLite
        accept transaction: after accept, the client session's current
        cycle IS the child (mirror of load_cycle's newest-first order).
        """
        if self.practice_repository is None:
            raise PracticeOfferAcceptError("practice repository 未配置")
        accepted = await self.practice_repository.accept_offer(student_id, offer_id)
        if not accepted:
            raise PracticeOfferAcceptError("offer 不是 ACTIVE 或已过期")
        self._sessions[(student_id, client_session_id)] = child

    async def load_child_cycle_for_offer(
        self, student_id: str, offer_id: UUID
    ) -> TutoringSession | None:
        for (owner, _client_id), session in self._sessions.items():
            if owner == student_id and session.cycle.practice_offer_id == offer_id:
                return session
        return None

    async def clear(self) -> None:
        self._sessions.clear()
        self._actions.clear()
        self._verified.clear()
        self._attempt_counts.clear()
        self._evidence_history.clear()
        self._observation_history.clear()

    def clear_sync(self) -> None:
        """Sync convenience for test fixtures (in-memory store only)."""
        self._sessions.clear()
        self._actions.clear()
        self._verified.clear()
        self._attempt_counts.clear()
        self._evidence_history.clear()
        self._observation_history.clear()


def _assistance_from_actions(actions: list[TutorAction]) -> CycleAssistance:
    """Rebuild the assistance ledger from append-only tutor actions (§7.1).

    The ledger is a PROJECTION over facts — never stored itself, so it can
    always be rebuilt after a restart.
    """
    hints = sum(1 for a in actions if a.action == "GIVE_HINT")
    explanations = sum(1 for a in actions if a.action in ("EXPLAIN_CONCEPT", "SHOW_EXAMPLE"))
    max_level = max((a.effective_assistance_level for a in actions), default=0)
    return CycleAssistance(
        hints_issued=hints,
        explanations_issued=explanations,
        max_level_issued=max_level,
    )


def _evidence_from_commit(student_id: str, commit: LearningCommit):
    """Rebuild a LearningEvidence from an in-memory commit (history replay)."""
    from uuid import uuid4

    from mathtutor.learning.evidence import LearningEvidence

    row = commit.evidence or {}
    return LearningEvidence(
        evidence_id=uuid4(),
        student_id=student_uuid(student_id),
        attempt_id=commit.attempt_id,
        skill_id=str(row.get("skill_id") or "UNKNOWN_SKILL"),
        correctness=commit.correctness,
        score=float(commit.score if commit.score is not None else 0.0),
        difficulty=int(row.get("difficulty") or 1),
        effective_assistance_level=int(row.get("effective_assistance_level") or 0),
        attempt_index=commit.attempt_index,
        evidence_version=str(row.get("evidence_version") or "mt-evidence-v1"),
        idempotency_key=str(row.get("idempotency_key") or ""),
    )


def _observation_from_commit(student_id: str, commit: LearningCommit):
    """Rebuild a MisconceptionObservation from an in-memory commit."""
    from uuid import uuid4

    from mathtutor.learning.diagnosis import MisconceptionObservation

    row = commit.observation or {}
    return MisconceptionObservation(
        observation_id=uuid4(),
        student_id=student_uuid(student_id),
        attempt_id=commit.attempt_id,
        rule_id=str(row.get("rule_id") or ""),
        confidence=float(row.get("confidence") or 0.0),
        detail=dict(row.get("detail") or {}),
    )


__all__ = [
    "InMemorySessionStore",
    "LearningCommit",
    "PracticeOfferAcceptError",
    "SessionStoreProtocol",
]
