"""PedagogyPlanner — the single server-side TutorAction chooser (Phase 3A).

Inputs: current state, the student's command, the StagePolicy, the number of
hints already issued this cycle, and (for SHOW_SOLUTION) the verified
solution ref. Output: exactly ONE TutorAction with an effective assistance
level.

The planner never chooses on the basis of LLM output; SHOW_SOLUTION is
fail-closed: without a VERIFIED solution ref it raises instead of degrading
to an unverified view.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID, uuid4

from mathtutor.application.state_machine import CycleCommand, CycleState
from mathtutor.domain.solution import VerifiedSolutionRef
from mathtutor.domain.tutoring import TutorAction
from mathtutor.pedagogy.exceptions import DisclosurePolicyViolation, HintRequiredForSolution
from mathtutor.pedagogy.stage_policy import StagePolicy

SOLUTION_REVIEW_STATES = frozenset({
    CycleState.SOLVED, CycleState.SOLUTION_SHOWN, CycleState.REFLECTION,
    CycleState.PRACTICE_OFFERED, CycleState.CLOSED,
})


@dataclass(frozen=True, slots=True)
class CycleAssistance:
    """Assistance already issued this cycle (design doc §7.1: the ledger)."""

    hints_issued: int = 0
    explanations_issued: int = 0
    max_level_issued: int = 0

    def next_hint_level(self, policy: StagePolicy) -> int:
        """Escalate along the policy's ladder, at most one level per request
        (primary), bounded by the ladder length."""
        index = min(self.hints_issued, len(policy.hint_escalation) - 1)
        return policy.hint_escalation[index]


def solution_needs_hint(state: CycleState, policy: StagePolicy, assistance: CycleAssistance | None) -> bool:
    """Whether a full-solution request must first be preceded by a hint."""
    assistance = assistance or CycleAssistance()
    return (state not in SOLUTION_REVIEW_STATES and assistance.max_level_issued < 5
            and assistance.hints_issued < policy.min_hints_for_solution)


class PedagogyPlanner:
    """Server-owned teaching strategy (§7.3): policy over prompt."""

    def plan(
        self,
        *,
        state: CycleState,
        command: CycleCommand,
        policy: StagePolicy,
        assistance: CycleAssistance | None = None,
        verified_ref: VerifiedSolutionRef | None = None,
    ) -> TutorAction:
        assistance = assistance or CycleAssistance()

        if command == CycleCommand.REQUEST_HINT:
            level = assistance.next_hint_level(policy)
            return self._action(
                "GIVE_HINT",
                level,
                "hint",
                policy,
                target_step_index=None,
            )
        if command == CycleCommand.REQUEST_EXPLANATION:
            # Concept explanation: never above the policy's unrequested cap
            # and never carries answer-bearing content.
            level = min(1, policy.max_assistance_without_explicit_request)
            return self._action("EXPLAIN_CONCEPT", level, "none", policy)
        if command == CycleCommand.REQUEST_EXAMPLE:
            level = min(2, policy.max_assistance_without_explicit_request)
            return self._action("SHOW_EXAMPLE", level, "none", policy)
        if command == CycleCommand.DIAGNOSIS_INCORRECT or command == CycleCommand.DIAGNOSIS_PARTIAL:
            # Corrective feedback after a wrong attempt: allowed to point at
            # the failed step but never past it (L3 max — no answer content).
            return self._action(
                "CORRECT_STEP",
                min(3, policy.max_assistance_without_explicit_request),
                "step",
                policy,
                target_step_index=0,
            )
        if command == CycleCommand.SOLUTION_SHOWN_PERMITTED:
            # FAIL CLOSED: a full solution requires a VERIFIED reference.
            if verified_ref is None:
                raise DisclosurePolicyViolation(
                    "这道题的完整解答尚未通过验证，暂时不能展示。"
                    "你可以继续尝试，或先请求一个提示。"
                )
            # An open problem needs the policy's hint minimum first; a solved
            # or already-shown problem may always be reviewed.
            if solution_needs_hint(state, policy, assistance):
                raise HintRequiredForSolution(
                    "先看一次提示，自己再试一步；看过提示后仍然可以查看完整答案。"
                )
            return self._action("SHOW_SOLUTION", 5, "full", policy)
        if command == CycleCommand.DIAGNOSIS_AMBIGUOUS or command == CycleCommand.DIAGNOSIS_CORRECT:
            return self._action("ASK_STUDENT", 0, "none", policy)
        # Everything else (grounding/verification flows): no assistance.
        return self._action("ASK_STUDENT", 0, "none", policy)

    @staticmethod
    def _action(
        action: Literal[
            "ASK_STUDENT", "GIVE_HINT", "EXPLAIN_CONCEPT", "SHOW_EXAMPLE",
            "CORRECT_STEP", "REQUEST_RETRY", "SHOW_SOLUTION", "GENERATE_PRACTICE",
        ],
        level: int,
        visibility: Literal["none", "hint", "step", "partial", "full"],
        policy: StagePolicy,
        target_step_index: int | None = None,
    ) -> TutorAction:
        return TutorAction(
            action_id=uuid4(),
            action=action,
            effective_assistance_level=level,
            solution_visibility=visibility,
            target_mapping_id=None,
            target_step_index=target_step_index,
            stage_policy_version=policy.version,
            disclosure_policy_version="mt-disclosure-v1",
        )


__all__ = [
    "CycleAssistance",
    "DisclosurePolicyViolation",
    "PedagogyPlanner",
]
