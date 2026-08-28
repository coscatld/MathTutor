"""Tutoring state machine: transitions, versioning/CAS, failure paths."""

from __future__ import annotations

from uuid import uuid4

import pytest

from mathtutor.application.state_machine import (
    CycleCommand as Cmd,
    CycleState as S,
    InvalidTransitionError,
    TutoringSession,
    VersionConflictError,
    allowed_next_commands,
)


def session() -> TutoringSession:
    return TutoringSession(session_id=uuid4(), student_id=uuid4())


class TestHappyPath:
    def test_full_solve_flow(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        assert s.state == S.GROUNDING
        s.step(Cmd.GROUNDING_OK)
        assert s.state == S.SOLUTION_VERIFYING
        s.step(Cmd.VERIFICATION_VERIFIED)
        assert s.state == S.AWAITING_ATTEMPT

        s.step(Cmd.SUBMIT_ATTEMPT)
        assert s.state == S.DIAGNOSING
        s.step(Cmd.DIAGNOSIS_CORRECT)
        assert s.state == S.SOLVED
        s.step(Cmd.REFLECTED)
        assert s.state == S.REFLECTION
        s.step(Cmd.PRACTICE_OFFERED)
        assert s.state == S.PRACTICE_OFFERED
        s.step(Cmd.ACCEPT_PRACTICE_OFFER)
        assert s.state == S.CLOSED

    def test_hint_and_explanation_cycle(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        s.step(Cmd.GROUNDING_OK)
        s.step(Cmd.VERIFICATION_VERIFIED)
        assert s.state == S.AWAITING_ATTEMPT

        transition = s.step(Cmd.REQUEST_HINT)
        assert s.state == S.HINTED
        assert transition.chosen_action is not None
        assert transition.chosen_action.action == "GIVE_HINT"
        assert transition.chosen_action.effective_assistance_level == 2
        s.step(Cmd.HINT_DELIVERED)
        assert s.state == S.AWAITING_ATTEMPT

        s.step(Cmd.REQUEST_EXPLANATION)
        assert s.state == S.EXPLAINING
        s.step(Cmd.EXPLANATION_DELIVERED)
        assert s.state == S.AWAITING_ATTEMPT

        s.step(Cmd.REQUEST_EXAMPLE)
        assert s.state == S.EXPLAINING
        s.step(Cmd.EXPLANATION_DELIVERED)
        assert s.state == S.AWAITING_ATTEMPT

    def test_show_solution_ladder_top(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        s.step(Cmd.GROUNDING_OK)
        s.step(Cmd.VERIFICATION_VERIFIED)
        transition = s.step(Cmd.SOLUTION_SHOWN_PERMITTED)
        assert s.state == S.SOLUTION_SHOWN
        assert transition.chosen_action is not None
        assert transition.chosen_action.action == "SHOW_SOLUTION"
        assert transition.chosen_action.effective_assistance_level == 5
        s.step(Cmd.REFLECTED)
        assert s.state == S.REFLECTION

    def test_retry_loop(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        s.step(Cmd.GROUNDING_OK)
        s.step(Cmd.VERIFICATION_VERIFIED)
        for correctness in (Cmd.DIAGNOSIS_INCORRECT, Cmd.DIAGNOSIS_PARTIAL):
            s.step(Cmd.SUBMIT_ATTEMPT)
            assert s.state == S.DIAGNOSING
            transition = s.step(correctness)
            assert s.state == S.AWAITING_RETRY
            assert transition.chosen_action is not None
            assert transition.chosen_action.action == "REQUEST_RETRY"
        s.step(Cmd.SUBMIT_ATTEMPT)
        s.step(Cmd.DIAGNOSIS_CORRECT)
        assert s.state == S.SOLVED

    def test_ambiguous_flows(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        s.step(Cmd.GROUNDING_AMBIGUOUS)
        assert s.state == S.AWAITING_CLARIFICATION
        s.step(Cmd.CLARIFY_PROBLEM)
        assert s.state == S.GROUNDING
        s.step(Cmd.GROUNDING_OK)
        s.step(Cmd.VERIFICATION_VERIFIED)

        s.step(Cmd.SUBMIT_ATTEMPT)
        s.step(Cmd.DIAGNOSIS_AMBIGUOUS)
        assert s.state == S.AWAITING_ATTEMPT_CLARIFICATION
        s.step(Cmd.CLARIFY_ATTEMPT)
        assert s.state == S.DIAGNOSING
        s.step(Cmd.DIAGNOSIS_CORRECT)

    def test_fail_closed_paths(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        s.step(Cmd.GROUNDING_UNSUPPORTED)
        assert s.state == S.UNSUPPORTED
        s.step(Cmd.CANCEL_TURN)
        assert s.state == S.CLOSED

        s2 = session()
        s2.step(Cmd.SUBMIT_PROBLEM)
        s2.step(Cmd.GROUNDING_OK)
        s2.step(Cmd.VERIFICATION_FAILED)
        assert s2.state == S.UNVERIFIED_BLOCKED
        s2.step(Cmd.CANCEL_TURN)
        assert s2.state == S.CLOSED


class TestVersioning:
    def test_versions_monotonic(self) -> None:
        s = session()
        transitions = [
            s.step(Cmd.SUBMIT_PROBLEM),
            s.step(Cmd.GROUNDING_OK),
            s.step(Cmd.VERIFICATION_VERIFIED),
            s.step(Cmd.SUBMIT_ATTEMPT),
            s.step(Cmd.DIAGNOSIS_CORRECT),
        ]
        versions = [t.new_version for t in transitions]
        assert versions == [1, 2, 3, 4, 5]
        assert all(t.new_version == t.prior_version + 1 for t in transitions)
        assert s.version == 5
        assert s.cycle.state_version == 5

    def test_expected_version_cas(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)  # version 1
        s.step(Cmd.GROUNDING_OK, expected_version=1)  # version 2 — matches
        s.step(Cmd.VERIFICATION_VERIFIED, expected_version=2)  # version 3 — matches
        assert s.version == 3

    def test_stale_version_rejected(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        s.step(Cmd.GROUNDING_OK)  # version 2
        with pytest.raises(VersionConflictError):
            s.step(Cmd.VERIFICATION_VERIFIED, expected_version=1)  # stale

    def test_transition_records_trigger_and_ids(self) -> None:
        s = session()
        correlation = uuid4()
        transition = s.step(Cmd.SUBMIT_PROBLEM, idempotency_key="k1", correlation_id=correlation)
        assert transition.trigger_command == Cmd.SUBMIT_PROBLEM.value
        assert transition.idempotency_key == "k1"
        assert transition.correlation_id == correlation
        assert transition.from_state == S.PROBLEM_RECEIVED.value
        assert transition.to_state == S.GROUNDING.value
        assert len(s.transitions) == 1


class TestInvalid:
    def test_invalid_command_raises(self) -> None:
        s = session()
        with pytest.raises(InvalidTransitionError):
            s.step(Cmd.REQUEST_HINT)  # hints are not available before AWAITING_ATTEMPT

    def test_closed_is_terminal(self) -> None:
        s = session()
        s.step(Cmd.SUBMIT_PROBLEM)
        s.step(Cmd.CANCEL_TURN)
        assert s.state == S.CLOSED
        with pytest.raises(InvalidTransitionError):
            s.step(Cmd.SUBMIT_PROBLEM)

    def test_allowed_next_commands(self) -> None:
        assert Cmd.SUBMIT_PROBLEM in allowed_next_commands(S.PROBLEM_RECEIVED)
        assert Cmd.REQUEST_HINT in allowed_next_commands(S.AWAITING_ATTEMPT)
        assert Cmd.SUBMIT_ATTEMPT in allowed_next_commands(S.AWAITING_RETRY)
        assert Cmd.CANCEL_TURN in allowed_next_commands(S.SOLUTION_VERIFYING)
        assert allowed_next_commands(S.CLOSED) == ()
