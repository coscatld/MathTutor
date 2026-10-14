"""The full solution of an open problem needs one hint first."""
import pytest

from mathtutor.application.state_machine import CycleCommand, CycleState
from mathtutor.pedagogy.exceptions import HintRequiredForSolution
from mathtutor.pedagogy.planner import CycleAssistance, PedagogyPlanner, solution_needs_hint
from mathtutor.pedagogy.stage_policy import ADAPTIVE_POLICY, STAGE_POLICIES


def test_every_policy_requires_one_hint():
    assert ADAPTIVE_POLICY.min_hints_for_solution == 1
    assert {p.min_hints_for_solution for p in STAGE_POLICIES.values()} == {1}


@pytest.mark.parametrize("state", [CycleState.AWAITING_ATTEMPT, CycleState.AWAITING_RETRY])
def test_open_problem_refuses_without_hint(state):
    with pytest.raises(HintRequiredForSolution) as raised:
        PedagogyPlanner().plan(state=state, command=CycleCommand.SOLUTION_SHOWN_PERMITTED,
                               policy=ADAPTIVE_POLICY, assistance=CycleAssistance(explanations_issued=2),
                               verified_ref=object())
    assert raised.value.error_code == "HINT_REQUIRED"


@pytest.mark.parametrize("state,assistance", [
    (CycleState.AWAITING_ATTEMPT, CycleAssistance(hints_issued=1, max_level_issued=2)),
    (CycleState.AWAITING_RETRY, CycleAssistance(max_level_issued=5)),
    (CycleState.SOLVED, CycleAssistance()),
    (CycleState.SOLUTION_SHOWN, CycleAssistance()),
])
def test_hint_issued_or_review_unlocks_solution(state, assistance):
    assert not solution_needs_hint(state, ADAPTIVE_POLICY, assistance)
    action = PedagogyPlanner().plan(state=state, command=CycleCommand.SOLUTION_SHOWN_PERMITTED,
                                    policy=ADAPTIVE_POLICY, assistance=assistance, verified_ref=object())
    assert action.action == "SHOW_SOLUTION"
