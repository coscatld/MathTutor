"""Tutoring cycles, transitions, tutor actions and practice offers.

One main problem owns one tutoring cycle; every transition is versioned
(CAS on ``expected_cycle_version``) and recorded append-only (design doc
§5, §11.4). ``TutorAction`` records both the action type and its effective
assistance level L0–L5.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

CYCLE_SOURCE = Literal["problem_submission", "practice_offer"]

OfferStatus = Literal["ACTIVE", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED"]

TutorActionType = Literal[
    "ASK_STUDENT",
    "GIVE_HINT",
    "EXPLAIN_CONCEPT",
    "SHOW_EXAMPLE",
    "CORRECT_STEP",
    "REQUEST_RETRY",
    "SHOW_SOLUTION",
    "GENERATE_PRACTICE",
]
AssistanceLevel = Literal[0, 1, 2, 3, 4, 5]
SolutionVisibility = Literal["none", "hint", "step", "partial", "full"]


class TutorAction(BaseModel):
    """The single server-chosen action for a transition (design doc §10)."""

    model_config = ConfigDict(frozen=True)

    action_id: UUID = Field(default_factory=uuid4)
    action: TutorActionType
    effective_assistance_level: AssistanceLevel
    solution_visibility: SolutionVisibility = "none"
    target_mapping_id: UUID | None = None
    target_step_index: int | None = None
    pedagogy_policy_version: str = "mt-ped-v0"  # real StagePolicy lands in Phase 3
    stage_policy_version: str = "mt-stage-v0"
    disclosure_policy_version: str = "mt-disclosure-v0"


class TutoringCycle(BaseModel):
    """One tutoring cycle: state, version and its single source (XOR)."""

    model_config = ConfigDict(frozen=True)

    cycle_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    session_id: UUID
    problem_id: UUID | None = None
    practice_offer_id: UUID | None = None
    state: str
    state_version: int = Field(ge=0, default=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CycleTransition(BaseModel):
    """One versioned state transition — append-only record (design doc §5)."""

    model_config = ConfigDict(frozen=True)

    transition_id: UUID = Field(default_factory=uuid4)
    cycle_id: UUID
    from_state: str
    to_state: str
    trigger_command: str
    chosen_action: TutorAction | None = None
    prior_version: int
    new_version: int
    policy_versions: dict[str, str] = {}
    causation_id: UUID | None = None
    correlation_id: UUID | None = None
    idempotency_key: str = ""
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PracticeOffer(BaseModel):
    """A validated practice offer bound to an exact exercise release.

    Phase 5 lifecycle (§7.6/§7.9): ACTIVE → ACCEPTED (consumed) on accept,
    or → REVOKED (student declined / release revoked or superseded), or →
    EXPIRED (offer TTL passed; status is projected lazily by readers). An
    offer that was already ACCEPTED can never be accepted into a second
    child cycle (idempotent replay returns the SAME child cycle).
    """

    model_config = ConfigDict(frozen=True)

    offer_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    parent_cycle_id: UUID
    exercise_release_id: UUID
    target_mapping_ids: tuple[UUID, ...] = ()
    stage_policy_version: str = "mt-stage-v0"
    status: OfferStatus = "ACTIVE"
    offered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    consumed_at: datetime | None = None


__all__ = [
    "AssistanceLevel",
    "CycleTransition",
    "OfferStatus",
    "PracticeOffer",
    "SolutionVisibility",
    "TutorAction",
    "TutorActionType",
    "TutoringCycle",
]
