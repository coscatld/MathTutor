"""StagePolicy — the server-owned, versioned teaching policy (Phase 3A).

Hard policy, not prompt. It decides HOW MUCH to teach per school stage
(budgets, symbol density, hint escalation, proof rigor); it never judges
mathematical correctness (verifier) or flow legality (state machine).

Boundary (design doc §7.3):
    MathVerifier → math right or wrong
    StateMachine → flow allowed or not
    StagePolicy  → how much to teach right now
    TutorWriter  → how to express it
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

Stage = Literal["primary", "middle", "high"]
SymbolDensity = Literal["low", "medium", "high"]
ProofRigor = Literal["none", "basic", "strict"]


class StagePolicy(BaseModel):
    """Frozen per-stage teaching policy (design doc §7.3)."""

    model_config = ConfigDict(frozen=True)

    policy_id: str
    version: str
    stage: Stage
    grade_min: int
    grade_max: int

    # Response/step budgets
    max_response_chars: int
    max_steps_per_turn: int

    # Representation rules
    symbol_density: SymbolDensity
    proof_rigor: ProofRigor
    allow_multi_method: bool
    allow_formula_first: bool
    prefer_concrete_representation: bool

    # Assistance ladder rules
    hint_escalation: tuple[int, ...]
    max_assistance_without_explicit_request: int
    # Disclosure policy (§7.1): the full solution (L5) is only permitted
    # after this many hints have actually been issued — "仅在策略允许后".
    min_hints_for_solution: int = 2


PRIMARY_POLICY = StagePolicy(
    policy_id="mt-stage-primary",
    version="1",
    stage="primary",
    grade_min=1,
    grade_max=6,
    max_response_chars=200,
    max_steps_per_turn=1,
    symbol_density="low",
    proof_rigor="none",
    allow_multi_method=False,
    allow_formula_first=False,
    prefer_concrete_representation=True,
    # One hint at a time, escalate at most one level per request.
    hint_escalation=(1, 2, 3),
    min_hints_for_solution=3,
    max_assistance_without_explicit_request=1,
)

MIDDLE_POLICY = StagePolicy(
    policy_id="mt-stage-middle",
    version="1",
    stage="middle",
    grade_min=7,
    grade_max=9,
    max_response_chars=500,
    max_steps_per_turn=3,
    symbol_density="medium",
    proof_rigor="basic",
    allow_multi_method=False,
    allow_formula_first=True,
    prefer_concrete_representation=False,
    hint_escalation=(2, 3, 4),
    max_assistance_without_explicit_request=2,
    min_hints_for_solution=2,
)

HIGH_POLICY = StagePolicy(
    policy_id="mt-stage-high",
    version="1",
    stage="high",
    grade_min=10,
    grade_max=12,
    max_response_chars=800,
    max_steps_per_turn=5,
    symbol_density="high",
    proof_rigor="strict",
    allow_multi_method=True,
    allow_formula_first=True,
    prefer_concrete_representation=False,
    hint_escalation=(2, 3, 4, 5),
    max_assistance_without_explicit_request=3,
    min_hints_for_solution=1,
)

STAGE_POLICIES: dict[Stage, StagePolicy] = {
    "primary": PRIMARY_POLICY,
    "middle": MIDDLE_POLICY,
    "high": HIGH_POLICY,
}


def policy_for_stage(stage: str) -> StagePolicy:
    """Resolve the stage policy; unknown stage fails closed to primary
    (the most restrictive) — never to the loosest."""
    return STAGE_POLICIES.get(stage, PRIMARY_POLICY)  # type: ignore[arg-type]


def new_policy_id() -> str:
    return f"mt-stage-{uuid4().hex[:8]}"


__all__ = [
    "HIGH_POLICY",
    "MIDDLE_POLICY",
    "PRIMARY_POLICY",
    "STAGE_POLICIES",
    "StagePolicy",
    "policy_for_stage",
]
