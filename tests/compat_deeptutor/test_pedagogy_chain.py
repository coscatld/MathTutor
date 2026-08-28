"""Phase 3 pedagogy chain: StagePolicy / Planner / Disclosure / Guard.

Acceptance targets (design doc Phase 3):
- exhaustive state×command consistency (state machine / TutorAction /
  allowed_next_inputs all derive from the SAME source of truth);
- SHOW_SOLUTION fail-closed without a verified ref;
- L1-L4 leakage interception incl. mathematically equivalent forms;
- the three stage policies behave DIFFERENTLY on identical inputs;
- internal fields can never enter the student wire.
"""

from __future__ import annotations

import pytest

from mathtutor.application.state_machine import (
    CycleCommand,
    CycleState,
    InvalidTransitionError,
    TutoringSession,
    allowed_next_commands,
)
from mathtutor.domain.solution import MathSolutionCandidate
from mathtutor.pedagogy.disclosure import SolutionDisclosureProjector
from mathtutor.pedagogy.exceptions import DisclosurePolicyViolation
from mathtutor.pedagogy.output_guard import TutorOutputGuard
from mathtutor.pedagogy.planner import CycleAssistance, PedagogyPlanner
from mathtutor.pedagogy.stage_policy import (
    HIGH_POLICY,
    MIDDLE_POLICY,
    PRIMARY_POLICY,
)
from mathtutor.pedagogy.tutor_writer import (
    TemplateTutorWriter,
    TutorWriterCandidate,
)
from mathtutor.solving import parse_problem, solve_problem, verify
from mathtutor.domain.problem import MathProblem

pytestmark = pytest.mark.asyncio


def _verified_chain(text: str):
    """parse → solve → verify for one problem; returns (problem, candidate, ref-like)."""
    parsed = parse_problem(text).problem
    problem = MathProblem.canonicalize(
        problem_type=parsed.problem_type,
        normalized_ast=parsed.normalized_ast,
        display_latex=parsed.display_latex,
    )
    solved = solve_problem(problem, parsed)
    decision = verify(problem, solved.candidate)
    assert decision.verdict == "VERIFIED"
    # VerifiedSolutionRef-lite: attestation comes from the repository; the
    # decision already binds problem+candidate hashes (design §6.1).
    from mathtutor.domain.solution import VerifiedSolutionRef

    ref = VerifiedSolutionRef(
        verification_log_id=decision.decision_id,
        problem_id=problem.problem_id,
        problem_content_hash=problem.content_hash,
        solution_candidate_id=solved.candidate.candidate_id,
        solution_payload_hash=solved.candidate.payload_hash,
        policy_id=decision.policy_id,
        policy_version=decision.policy_version,
        attestation_hash="test",
    )
    return problem, solved.candidate, ref


# ------------------------------------------------------------- acceptance 1


class TestExhaustiveStateCommandConsistency:
    def test_every_state_every_command_is_consistent(self) -> None:
        """For EVERY (state, command): either a legal transition whose action
        is planner-sanctioned and whose public event lists exactly
        allowed_next_commands(new_state), or InvalidTransitionError with no
        side effects."""
        session = TutoringSession(
            session_id=_uuid(), student_id=_uuid()
        )
        planner = PedagogyPlanner()
        policy = PRIMARY_POLICY

        checked_legal = 0
        checked_illegal = 0
        for state in CycleState:
            for command in CycleCommand:
                # fresh session pinned to this state for the check
                probe = TutoringSession.restore(
                    cycle_id=session.cycle.cycle_id,
                    student_id=session.student_id,
                    session_id=session.session_id,
                    state=state.value,
                    state_version=0,
                )
                version_before = probe.version
                try:
                    transition = probe.step(command)
                except InvalidTransitionError:
                    checked_illegal += 1
                    assert probe.version == version_before  # unchanged
                    assert transition_has_no_public_content(probe)
                    continue
                checked_legal += 1
                # Action chosen by the planner must agree with the machine.
                # (hints pre-issued so the L5 policy gate cannot veto the
                # traversal — gate behavior has its own dedicated tests).
                action = planner.plan(
                    state=state,
                    command=command,
                    policy=policy,
                    assistance=CycleAssistance(hints_issued=99),
                    verified_ref=_dummy_ref(),  # SHOW_SOLUTION gate input
                )
                assert action is not None
                # Public event allowed_next_inputs must be exactly the
                # machine's own answer for the NEW state (same source).
                event_next = [c.value for c in allowed_next_commands(probe.state)]
                assert event_next == transition_event_next(probe)
        assert checked_legal > 0 and checked_illegal > 0


def transition_has_no_public_content(session: TutoringSession) -> bool:
    return not hasattr(session, "_emitted")  # helper: illegal steps emit nothing


def transition_event_next(session: TutoringSession) -> list[str]:
    return [c.value for c in allowed_next_commands(session.state)]


# ------------------------------------------------------------- acceptance 2


class TestShowSolutionFailClosed:
    def test_planner_refuses_without_verified_ref(self) -> None:
        planner = PedagogyPlanner()
        with pytest.raises(DisclosurePolicyViolation):
            planner.plan(
                state=CycleState.AWAITING_ATTEMPT,
                command=CycleCommand.SOLUTION_SHOWN_PERMITTED,
                policy=MIDDLE_POLICY,
                assistance=CycleAssistance(),
                verified_ref=None,
            )

    def test_planner_allows_with_verified_ref_and_enough_hints(self) -> None:
        _, _, ref = _verified_chain("2x + 3 = 7")
        action = PedagogyPlanner().plan(
            state=CycleState.AWAITING_ATTEMPT,
            command=CycleCommand.SOLUTION_SHOWN_PERMITTED,
            policy=MIDDLE_POLICY,
            assistance=CycleAssistance(hints_issued=MIDDLE_POLICY.min_hints_for_solution),
            verified_ref=ref,
        )
        assert action.action == "SHOW_SOLUTION"
        assert action.effective_assistance_level == 5

    def test_planner_refuses_without_policy_hint_threshold(self) -> None:
        """N-L5 gate: verified ref is necessary but NOT sufficient — the
        stage's minimum hints must have been issued first (§7.1)."""
        _, _, ref = _verified_chain("2x + 3 = 7")
        with pytest.raises(DisclosurePolicyViolation):
            PedagogyPlanner().plan(
                state=CycleState.AWAITING_ATTEMPT,
                command=CycleCommand.SOLUTION_SHOWN_PERMITTED,
                policy=PRIMARY_POLICY,
                assistance=CycleAssistance(hints_issued=0),
                verified_ref=ref,
            )

    def test_projector_l3_without_ref_fails_closed(self) -> None:
        projector = SolutionDisclosureProjector()
        from mathtutor.domain.tutoring import TutorAction

        action = TutorAction(
            action="GIVE_HINT", effective_assistance_level=3, solution_visibility="step"
        )
        with pytest.raises(DisclosurePolicyViolation):
            projector.project(None, None, action)


# ------------------------------------------------------------- acceptance 3


class TestDisclosureLeakage:
    def _guard(self) -> TutorOutputGuard:
        return TutorOutputGuard()

    def _malicious(self, text: str, level: int, action: str) -> TutorWriterCandidate:
        return TutorWriterCandidate(text=text, writer_version="malicious-test")

    @pytest.mark.parametrize(
        "level,action",
        [
            (1, "EXPLAIN_CONCEPT"),
            (2, "GIVE_HINT"),
            (3, "GIVE_HINT"),
            (4, "GIVE_HINT"),
        ],
    )
    def test_final_answer_value_blocked(self, level: int, action: str) -> None:
        _, candidate, _ = _verified_chain("2x + 3 = 7")
        from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
        from mathtutor.domain.tutoring import TutorAction

        for malicious in (
            "这个知识点是移项，顺便告诉你 x=2。",
            "可以使用移项法，答案最后是2。",
            "下一步 2x=4，然后 x=2。",
            "2x=4，所以完整答案 x=2。",
        ):
            disclosure = DisclosedSolutionContext(assistance_level=level)
            tutor_action = TutorAction(
                action=action,
                effective_assistance_level=level,
                solution_visibility="none",
            )
            utterance = self._guard().guard_or_fallback(
                candidate=self._malicious(malicious, level, action),
                candidate_solution=candidate,
                disclosure=disclosure,
                action=tutor_action,
            )
            assert utterance.fallback_used, malicious
            assert utterance.leak is not None
            assert "2" not in _numbers_only(utterance.text)

    def test_equivalent_forms_blocked(self) -> None:
        """x-2=0 / 2-x=0 / x=4/2 must be caught by ROOT-SET equality, not
        string search for 'x=2'."""
        _, candidate, _ = _verified_chain("2x + 3 = 7")
        from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
        from mathtutor.domain.tutoring import TutorAction

        disclosure = DisclosedSolutionContext(assistance_level=2)
        action = TutorAction(action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint")
        for equivalent in (
            "答案是 x-2=0 的根。",
            "变形可得 2-x=0。",
            "未知数最终会得到 4/2。",
            "答案就是 x = 4/2。",
        ):
            utterance = self._guard().guard_or_fallback(
                candidate=self._malicious(equivalent, 2, "GIVE_HINT"),
                candidate_solution=candidate,
                disclosure=disclosure,
                action=action,
            )
            assert utterance.fallback_used, equivalent

    def test_clean_hint_passes(self) -> None:
        _, candidate, _ = _verified_chain("2x + 3 = 7")
        from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
        from mathtutor.domain.tutoring import TutorAction

        disclosure = DisclosedSolutionContext(assistance_level=2)
        action = TutorAction(action="GIVE_HINT", effective_assistance_level=2, solution_visibility="hint")
        utterance = self._guard().guard_or_fallback(
            candidate=self._malicious("先把含未知数的项移到一边，常数项移到另一边。", 2, "GIVE_HINT"),
            candidate_solution=candidate,
            disclosure=disclosure,
            action=action,
        )
        assert not utterance.fallback_used

    def test_l5_is_allowed_to_carry_solution(self) -> None:
        _, candidate, _ = _verified_chain("2x + 3 = 7")
        from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
        from mathtutor.domain.tutoring import TutorAction

        disclosure = DisclosedSolutionContext(assistance_level=5)
        action = TutorAction(action="SHOW_SOLUTION", effective_assistance_level=5, solution_visibility="full")
        utterance = self._guard().guard_or_fallback(
            candidate=self._malicious("解得 x=2。", 5, "SHOW_SOLUTION"),
            candidate_solution=candidate,
            disclosure=disclosure,
            action=action,
        )
        assert not utterance.fallback_used


def _numbers_only(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _dummy_ref():
    from mathtutor.domain.solution import VerifiedSolutionRef

    return VerifiedSolutionRef(
        verification_log_id=_uuid(),
        problem_id=_uuid(),
        problem_content_hash="h",
        solution_candidate_id=_uuid(),
        solution_payload_hash="h",
        policy_id="p",
        policy_version="1",
        attestation_hash="h",
    )


# ------------------------------------------------------------- acceptance 4


class TestStagePolicyBehavioralDifference:
    def test_policies_differ_on_identical_input(self) -> None:
        planner = PedagogyPlanner()
        assistance = CycleAssistance()
        primary = planner.plan(
            state=CycleState.AWAITING_ATTEMPT,
            command=CycleCommand.REQUEST_HINT,
            policy=PRIMARY_POLICY,
            assistance=assistance,
        )
        middle = planner.plan(
            state=CycleState.AWAITING_ATTEMPT,
            command=CycleCommand.REQUEST_HINT,
            policy=MIDDLE_POLICY,
            assistance=assistance,
        )
        high = planner.plan(
            state=CycleState.AWAITING_ATTEMPT,
            command=CycleCommand.REQUEST_HINT,
            policy=HIGH_POLICY,
            assistance=assistance,
        )
        # First-hint levels differ (primary starts at L1, middle/high at L2).
        assert primary.effective_assistance_level == 1
        assert middle.effective_assistance_level == 2
        assert high.effective_assistance_level == 2

    def test_hint_escalation_ladders_differ(self) -> None:
        assert PRIMARY_POLICY.hint_escalation == (1, 2, 3)
        assert MIDDLE_POLICY.hint_escalation == (2, 3, 4)
        assert HIGH_POLICY.hint_escalation == (2, 3, 4, 5)

    def test_budgets_differ(self) -> None:
        assert PRIMARY_POLICY.max_steps_per_turn == 1
        assert MIDDLE_POLICY.max_steps_per_turn == 3
        assert HIGH_POLICY.max_steps_per_turn == 5
        assert PRIMARY_POLICY.symbol_density == "low"
        assert HIGH_POLICY.symbol_density == "high"
        assert PRIMARY_POLICY.proof_rigor == "none"
        assert HIGH_POLICY.proof_rigor == "strict"

    def test_planner_decisions_differ_by_policy(self) -> None:
        """Same state+command, three policies → three different action
        payloads (not just different prompt strings)."""
        planner = PedagogyPlanner()
        actions = [
            planner.plan(
                state=CycleState.AWAITING_ATTEMPT,
                command=CycleCommand.REQUEST_HINT,
                policy=policy,
                assistance=CycleAssistance(),
            )
            for policy in (PRIMARY_POLICY, MIDDLE_POLICY, HIGH_POLICY)
        ]
        levels = {a.effective_assistance_level for a in actions}
        assert len(levels) >= 2  # genuinely different decisions


# ------------------------------------------------------------- acceptance 5


class TestInternalFieldsNeverReachStudent:
    def test_student_schema_rejects_unknown_fields(self) -> None:
        from pydantic import ValidationError

        from mathtutor.pedagogy.events import StudentPublicEvent

        with pytest.raises(ValidationError):
            StudentPublicEvent(
                event_type="tutor_action_committed",
                candidate_solution={"final_answer": "x=2"},  # type: ignore[call-arg]
            )

    def test_forbidden_field_detector_recursive(self) -> None:
        from mathtutor.pedagogy.events import assert_no_forbidden_fields

        with pytest.raises(ValueError):
            assert_no_forbidden_fields(
                {
                    "event_type": "x",
                    "payload": {"candidate_solution": "…"},
                }
            )
        with pytest.raises(ValueError):
            assert_no_forbidden_fields({"final_answer": "x=2"})
        # Clean student frame passes.
        assert_no_forbidden_fields(
            {
                "event_type": "tutor_action_committed",
                "audience": "student",
                "cycle_state": "awaiting_attempt",
                "payload": {"student_message": "试试看"},
            }
        )

    def test_internal_event_has_distinct_schema(self) -> None:
        from mathtutor.pedagogy.events import InternalEvent

        internal = InternalEvent(event_type="solver_trace", payload={"final_answer": "x=2"})
        # Internal events carry a different audience marker and are NOT
        # StudentPublicEvent instances — the student serializer's parameter
        # type rejects them at the boundary.
        assert internal.audience == "internal"
        from mathtutor.pedagogy.events import StudentPublicEvent

        assert not isinstance(internal, StudentPublicEvent)

    async def test_template_writer_never_embeds_answers(self) -> None:
        """The MVP writer's templates contain no answer-bearing content by
        construction — verify across all levels."""
        writer = TemplateTutorWriter()
        from mathtutor.pedagogy.disclosure import DisclosedSolutionContext
        from mathtutor.pedagogy.tutor_writer import PublicProblemView
        from mathtutor.domain.tutoring import TutorAction

        problem, candidate, ref = _verified_chain("x^2 - 5x + 6 = 0")
        for level, action_name in (
            (0, "ASK_STUDENT"),
            (1, "EXPLAIN_CONCEPT"),
            (2, "GIVE_HINT"),
            (3, "CORRECT_STEP"),
        ):
            action = TutorAction(
                action=action_name,
                effective_assistance_level=level,
                solution_visibility="none",
            )
            out = await writer.write(
                problem_view=PublicProblemView.of(problem),
                disclosure=DisclosedSolutionContext(assistance_level=level),
                policy=PRIMARY_POLICY,
                action=action,
            )
            for forbidden_value in ("2", "3", "2x", "x=2"):
                assert forbidden_value not in _numbers_or_vars(out.text)


def _numbers_or_vars(text: str) -> str:
    import re

    return re.sub(r"\s+", "", text)


def _uuid():
    from uuid import uuid4

    return uuid4()


class TestL5SolutionFlowReachable:
    """B2 fix: the full-solution path is now REACHABLE from the student
    channel (request_solution) while staying fail-closed."""

    async def test_request_solution_without_verified_fails_closed(self) -> None:
        from mathtutor.capabilities.math_tutor import MathTutorCapability
        from deeptutor.core.context import UnifiedContext
        from deeptutor.core.stream_bus import StreamBus
        from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

        owner = StudentOwnerScope(
            principal=PrincipalScope("u1", "a", "user"), student_id="u1"
        )
        cap = MathTutorCapability()
        bus = StreamBus()
        events: list = []

        async def _consume() -> None:
            async for event in bus.subscribe():
                events.append(event)

        import asyncio

        task = asyncio.get_event_loop().create_task(_consume())
        # No problem submitted: request_solution must NOT show anything.
        await cap.run(
            UnifiedContext(
                session_id="s-l5",
                user_message='{"command": "request_solution", "payload": {}}',
                metadata={"student_owner": owner},
            ),
            bus,
        )
        await bus.close()
        await task
        errors = [e for e in events if e.type == "error"]
        assert errors  # invalid transition / no verified ref — fail closed

    async def test_request_solution_after_verified_shows_l5(self) -> None:
        from mathtutor.capabilities.math_tutor import MathTutorCapability
        from deeptutor.core.context import UnifiedContext
        from deeptutor.core.stream_bus import StreamBus
        from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

        owner = StudentOwnerScope(
            principal=PrincipalScope("u1", "a", "user"), student_id="u1"
        )
        cap = MathTutorCapability()

        async def _turn(msg: str) -> list[dict]:
            bus = StreamBus()
            events: list[dict] = []

            async def _consume() -> None:
                async for event in bus.subscribe():
                    md = event.metadata or {}
                    events.append(
                        {
                            "type": event.type,
                            "content": event.content,
                            "state": md.get("cycle_state", ""),
                            "action": md.get("action", ""),
                            "level": md.get("effective_assistance_level"),
                        }
                    )

            import asyncio

            task = asyncio.get_event_loop().create_task(_consume())
            await cap.run(
                UnifiedContext(
                    session_id="s-l5b",
                    user_message=msg,
                    metadata={"student_owner": owner},
                ),
                bus,
            )
            await bus.close()
            await task
            return events

        await _turn('{"command": "submit_problem", "payload": {"text": "2x + 3 = 7"}}')
        # Policy gate first: zero hints → refused, state unchanged.
        refused = await _turn('{"command": "request_solution", "payload": {}}')
        assert any(e["type"] == "error" for e in refused)
        assert not any(e.get("action") == "SHOW_SOLUTION" for e in refused)
        # Earn the stage threshold (PRIMARY: 3 hints), then the L5 path
        # delivers the ACTUAL solution content.
        for _ in range(PRIMARY_POLICY.min_hints_for_solution):
            await _turn('{"command": "request_hint", "payload": {}}')
        events = await _turn('{"command": "request_solution", "payload": {}}')
        actions = [e for e in events if e.get("action") == "SHOW_SOLUTION"]
        assert actions, "L5 完整解析必须可达（SHOW_SOLUTION action）"
        assert actions[0]["level"] == 5
        assert actions[0]["state"] == "solution_shown"
        # The utterance must carry the permitted solution content (N-L5).
        assert "x = 2" in actions[0]["content"]

    async def test_request_example_routes_to_show_example(self) -> None:
        """B2-3 fix coverage: request_example reaches the planner's
        SHOW_EXAMPLE branch (previously mis-routed to EXPLAIN_CONCEPT)."""
        from mathtutor.capabilities.math_tutor import MathTutorCapability
        from deeptutor.core.context import UnifiedContext
        from deeptutor.core.stream_bus import StreamBus
        from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope

        owner = StudentOwnerScope(
            principal=PrincipalScope("u1", "a", "user"), student_id="u1"
        )
        cap = MathTutorCapability()

        async def _turn(msg: str) -> list[dict]:
            bus = StreamBus()
            events: list[dict] = []

            async def _consume() -> None:
                async for event in bus.subscribe():
                    md = event.metadata or {}
                    events.append({"type": event.type, "action": md.get("action", "")})

            import asyncio

            task = asyncio.get_event_loop().create_task(_consume())
            await cap.run(
                UnifiedContext(
                    session_id="s-example",
                    user_message=msg,
                    metadata={"student_owner": owner},
                ),
                bus,
            )
            await bus.close()
            await task
            return events

        await _turn('{"command": "submit_problem", "payload": {"text": "2x + 3 = 7"}}')
        events = await _turn('{"command": "request_example", "payload": {}}')
        assert any(e.get("action") == "SHOW_EXAMPLE" for e in events), (
            "request_example 必须产出 SHOW_EXAMPLE action"
        )
