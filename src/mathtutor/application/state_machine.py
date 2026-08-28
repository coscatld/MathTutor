"""Tutoring state machine (design doc §5).

One main problem owns one tutoring cycle. Every transition is versioned
(``new_version == prior_version + 1``), records the trigger command, the
chosen :class:`TutorAction` and policy versions, and is appended to the
cycle's transition log. Client commands carry an ``expected_cycle_version``
(CAS) — stale versions are rejected.

User commands drive the visible loop; internal outcomes (grounding /
verification / diagnosis results, prompt delivery) are emitted by the
application service stages and advance the machine deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4

from mathtutor.domain.tutoring import (
    CycleTransition,
    TutorAction,
    TutoringCycle,
)


class CycleState(StrEnum):
    PROBLEM_RECEIVED = "problem_received"
    GROUNDING = "grounding"
    AWAITING_CLARIFICATION = "awaiting_clarification"
    UNSUPPORTED = "unsupported"
    SOLUTION_VERIFYING = "solution_verifying"
    UNVERIFIED_BLOCKED = "unverified_blocked"
    AWAITING_ATTEMPT = "awaiting_attempt"
    HINTED = "hinted"
    EXPLAINING = "explaining"
    DIAGNOSING = "diagnosing"
    AWAITING_ATTEMPT_CLARIFICATION = "awaiting_attempt_clarification"
    AWAITING_RETRY = "awaiting_retry"
    SOLVED = "solved"
    REFLECTION = "reflection"
    SOLUTION_SHOWN = "solution_shown"
    PRACTICE_OFFERED = "practice_offered"
    CLOSED = "closed"


class CycleCommand(StrEnum):
    # User commands (client envelope §13.2).
    SUBMIT_PROBLEM = "submit_problem"
    CLARIFY_PROBLEM = "clarify_problem"
    SUBMIT_ATTEMPT = "submit_attempt"
    CLARIFY_ATTEMPT = "clarify_attempt"
    REQUEST_HINT = "request_hint"
    REQUEST_EXPLANATION = "request_explanation"
    REQUEST_EXAMPLE = "request_example"
    ACCEPT_PRACTICE_OFFER = "accept_practice_offer"
    DECLINE_PRACTICE_OFFER = "decline_practice_offer"
    CANCEL_TURN = "cancel_turn"
    # Internal outcomes driven by application service stages.
    GROUNDING_OK = "grounding_ok"
    GROUNDING_AMBIGUOUS = "grounding_ambiguous"
    GROUNDING_UNSUPPORTED = "grounding_unsupported"
    VERIFICATION_VERIFIED = "verification_verified"
    VERIFICATION_FAILED = "verification_failed"
    DIAGNOSIS_CORRECT = "diagnosis_correct"
    DIAGNOSIS_PARTIAL = "diagnosis_partial"
    DIAGNOSIS_INCORRECT = "diagnosis_incorrect"
    DIAGNOSIS_AMBIGUOUS = "diagnosis_ambiguous"
    HINT_DELIVERED = "hint_delivered"
    EXPLANATION_DELIVERED = "explanation_delivered"
    SOLUTION_SHOWN_PERMITTED = "solution_shown_permitted"
    REFLECTED = "reflected"
    PRACTICE_OFFERED = "practice_offered"


class InvalidTransitionError(Exception):
    def __init__(self, state: CycleState, command: CycleCommand) -> None:
        super().__init__(f"状态 {state.value} 不接受命令 {command.value}")
        self.state = state
        self.command = command


class VersionConflictError(Exception):
    def __init__(self, expected: int, actual: int) -> None:
        super().__init__(f"cycle 版本冲突：期望 {expected}，当前 {actual}")
        self.expected = expected
        self.actual = actual


# ---------------------------------------------------------------------------
# MVP deterministic action defaults (Phase 3 StagePolicy will replace these).
# ---------------------------------------------------------------------------


def _action(action: str, level: int, visibility: str = "none") -> TutorAction:
    return TutorAction(
        action=action,
        effective_assistance_level=level,
        solution_visibility=visibility,
    )


# Transition table: state -> command -> (next state, optional TutorAction).
_TRANSITIONS: dict[CycleState, dict[CycleCommand, tuple[CycleState, TutorAction | None]]] = {
    CycleState.PROBLEM_RECEIVED: {
        CycleCommand.SUBMIT_PROBLEM: (CycleState.GROUNDING, None),
    },
    CycleState.UNSUPPORTED: {},
    CycleState.UNVERIFIED_BLOCKED: {},
    CycleState.GROUNDING: {
        CycleCommand.GROUNDING_OK: (CycleState.SOLUTION_VERIFYING, None),
        CycleCommand.GROUNDING_AMBIGUOUS: (CycleState.AWAITING_CLARIFICATION, _action("ASK_STUDENT", 0)),
        CycleCommand.GROUNDING_UNSUPPORTED: (CycleState.UNSUPPORTED, None),
    },
    CycleState.AWAITING_CLARIFICATION: {
        CycleCommand.CLARIFY_PROBLEM: (CycleState.GROUNDING, _action("ASK_STUDENT", 0)),
    },
    CycleState.SOLUTION_VERIFYING: {
        CycleCommand.VERIFICATION_VERIFIED: (CycleState.AWAITING_ATTEMPT, None),
        CycleCommand.VERIFICATION_FAILED: (CycleState.UNVERIFIED_BLOCKED, None),
    },
    CycleState.AWAITING_ATTEMPT: {
        CycleCommand.SUBMIT_ATTEMPT: (CycleState.DIAGNOSING, None),
        CycleCommand.REQUEST_HINT: (CycleState.HINTED, _action("GIVE_HINT", 2, "hint")),
        CycleCommand.REQUEST_EXPLANATION: (CycleState.EXPLAINING, _action("EXPLAIN_CONCEPT", 1)),
        CycleCommand.REQUEST_EXAMPLE: (CycleState.EXPLAINING, _action("SHOW_EXAMPLE", 1)),
        CycleCommand.SOLUTION_SHOWN_PERMITTED: (CycleState.SOLUTION_SHOWN, _action("SHOW_SOLUTION", 5, "full")),
    },
    CycleState.HINTED: {
        CycleCommand.HINT_DELIVERED: (CycleState.AWAITING_ATTEMPT, None),
    },
    CycleState.EXPLAINING: {
        CycleCommand.EXPLANATION_DELIVERED: (CycleState.AWAITING_ATTEMPT, None),
    },
    CycleState.DIAGNOSING: {
        CycleCommand.DIAGNOSIS_CORRECT: (CycleState.SOLVED, _action("ASK_STUDENT", 0)),
        CycleCommand.DIAGNOSIS_PARTIAL: (CycleState.AWAITING_RETRY, _action("REQUEST_RETRY", 0)),
        CycleCommand.DIAGNOSIS_INCORRECT: (CycleState.AWAITING_RETRY, _action("REQUEST_RETRY", 0)),
        CycleCommand.DIAGNOSIS_AMBIGUOUS: (CycleState.AWAITING_ATTEMPT_CLARIFICATION, _action("ASK_STUDENT", 0)),
    },
    CycleState.AWAITING_ATTEMPT_CLARIFICATION: {
        CycleCommand.CLARIFY_ATTEMPT: (CycleState.DIAGNOSING, _action("ASK_STUDENT", 0)),
    },
    CycleState.AWAITING_RETRY: {
        CycleCommand.SUBMIT_ATTEMPT: (CycleState.DIAGNOSING, None),
        CycleCommand.REQUEST_HINT: (CycleState.HINTED, _action("GIVE_HINT", 2, "hint")),
        CycleCommand.REQUEST_EXPLANATION: (CycleState.EXPLAINING, _action("EXPLAIN_CONCEPT", 1)),
    },
    CycleState.SOLVED: {
        CycleCommand.REFLECTED: (CycleState.REFLECTION, None),
    },
    CycleState.SOLUTION_SHOWN: {
        CycleCommand.REFLECTED: (CycleState.REFLECTION, None),
    },
    CycleState.REFLECTION: {
        CycleCommand.PRACTICE_OFFERED: (CycleState.PRACTICE_OFFERED, _action("GENERATE_PRACTICE", 0)),
    },
    CycleState.PRACTICE_OFFERED: {
        CycleCommand.ACCEPT_PRACTICE_OFFER: (CycleState.CLOSED, _action("GENERATE_PRACTICE", 0)),
        CycleCommand.DECLINE_PRACTICE_OFFER: (CycleState.CLOSED, None),
    },
}

# cancel_turn closes the cycle from every non-terminal state.
for _state in list(_TRANSITIONS):
    _TRANSITIONS[_state][CycleCommand.CANCEL_TURN] = (CycleState.CLOSED, None)


def allowed_next_commands(state: CycleState) -> tuple[CycleCommand, ...]:
    return tuple(_TRANSITIONS.get(state, {}).keys())


@dataclass(slots=True)
class TutoringSession:
    """One in-memory tutoring cycle with versioned, append-only transitions."""

    session_id: UUID
    student_id: UUID
    problem_id: UUID | None = None
    practice_offer_id: UUID | None = None
    cycle: TutoringCycle = field(init=False)
    transitions: list[CycleTransition] = field(default_factory=list)
    _version: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.cycle = TutoringCycle(
            student_id=self.student_id,
            session_id=self.session_id,
            problem_id=self.problem_id,
            practice_offer_id=self.practice_offer_id,
            state=CycleState.PROBLEM_RECEIVED.value,
            state_version=0,
        )

    @property
    def state(self) -> CycleState:
        return CycleState(self.cycle.state)

    @property
    def version(self) -> int:
        return self._version

    @classmethod
    def restore(cls, *, cycle_id, student_id, session_id, state, state_version, problem_id=None, practice_offer_id=None) -> "TutoringSession":
        """Rebuild the in-memory working copy from a persisted snapshot.

        Phase 1B: the database is the authoritative cycle record; each turn
        loads a snapshot and works on it, then persists transitions with CAS.
        The state machine itself stays exactly the same.
        """
        session = cls.__new__(cls)  # bypass __post_init__ (we set everything)
        session.student_id = student_id
        session.session_id = session_id
        session.problem_id = problem_id
        session.practice_offer_id = practice_offer_id
        session.cycle = TutoringCycle(
            cycle_id=cycle_id,
            student_id=student_id,
            session_id=session_id,
            problem_id=problem_id,
            practice_offer_id=practice_offer_id,
            state=state,
            state_version=state_version,
        )
        session.transitions = []
        session._version = state_version
        return session

    def snapshot(self) -> dict:
        """Persistable cycle snapshot (state/version/problem binding)."""
        return {
            "cycle_id": str(self.cycle.cycle_id),
            "state": self.state.value,
            "state_version": self._version,
            "problem_id": str(self.problem_id) if self.problem_id else None,
            "practice_offer_id": str(self.practice_offer_id) if self.practice_offer_id else None,
        }

    def step(
        self,
        command: CycleCommand,
        *,
        expected_version: int | None = None,
        idempotency_key: str = "",
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
    ) -> CycleTransition:
        """Apply one command with CAS versioning; appends the transition."""
        if expected_version is not None and expected_version != self._version:
            raise VersionConflictError(expected_version, self._version)
        table = _TRANSITIONS.get(self.state)
        entry = (table or {}).get(command)
        if entry is None:
            raise InvalidTransitionError(self.state, command)
        next_state, action = entry
        prior = self._version
        self._version = prior + 1
        transition = CycleTransition(
            cycle_id=self.cycle.cycle_id,
            from_state=self.state.value,
            to_state=next_state.value,
            trigger_command=command.value,
            chosen_action=action,
            prior_version=prior,
            new_version=self._version,
            correlation_id=correlation_id,
            causation_id=causation_id,
            idempotency_key=idempotency_key,
        )
        self.transitions.append(transition)
        object.__setattr__(
            self.cycle,
            "state",
            next_state.value,
        )
        object.__setattr__(self.cycle, "state_version", self._version)
        return transition


__all__ = [
    "CycleCommand",
    "CycleState",
    "InvalidTransitionError",
    "TutoringSession",
    "VersionConflictError",
    "allowed_next_commands",
]
