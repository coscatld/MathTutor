"""Student-state projection (Phase 4 learning loop, step 6).

``StudentStateProjection`` is DERIVED state: replay the append-only evidence
and misconception-observation sequences through the versioned estimator and
the deterministic misconception reducer, and the same inputs always yield
the byte-identical projection. Nothing here is ever mutated in place — the
repository persists projections via compare-and-set on
``projection_version``, where ``projection_version == len(evidence)``.

Misconception reducer (deterministic state-machine projection of
CANDIDATE -> ACTIVE -> RESOLVING -> RESOLVED):

- a single observation of a rule NEVER activates anything (CANDIDATE,
  not projected);
- >= ``ACTIVATION_OBSERVATION_COUNT`` observations from DISTINCT attempts
  activate the rule with ``BASE_CONFIDENCE + STEP * (count - 2)``
  (capped at ``MAX_CONFIDENCE``);
- each subsequent CORRECT evidence on the same skill decays the confidence
  by ``CORRECT_DECAY``: >= ``ACTIVE_THRESHOLD`` stays ACTIVE, below it is
  RESOLVING, <= 0 is RESOLVED and drops out of the projection;
- a later observation re-arms the rule (reinforcement), because the reducer
  always replays the full history — no hidden state.

Ordering: evidence/observations are processed in the order given (the
repository loaders return rows ordered by ``created_at``; in-memory callers
pass chronological order). Ties are resolved by input position — fully
deterministic.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from mathtutor.learning.diagnosis import MisconceptionObservation
from mathtutor.learning.estimator import ESTIMATOR_VERSION, MasteryEstimator
from mathtutor.learning.evidence import LearningEvidence
from mathtutor.learning.skills import (
    all_skill_ids,
    concept_for_skill,
)

# ---------------------------------------------------------------------------
# Reducer constant table (the only parameter source for the misconception
# state machine).
# ---------------------------------------------------------------------------

ACTIVATION_OBSERVATION_COUNT = 2  # observations from distinct attempts
BASE_CONFIDENCE = 0.75
CONFIDENCE_STEP = 0.1
MAX_CONFIDENCE = 0.95
ACTIVE_THRESHOLD = 0.7
CORRECT_DECAY = 0.4
CANDIDATE_CONFIDENCE = 0.4  # a lone observation stays a weak candidate


class MisconceptionStatus(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RESOLVING = "resolving"
    RESOLVED = "resolved"


class MisconceptionProjection(BaseModel):
    """Reducer output for one rule (full status; only ACTIVE/RESOLVING are
    stored in the persisted ``active_misconceptions`` column)."""

    model_config = ConfigDict(frozen=True)

    rule_id: str
    status: MisconceptionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    observation_attempts: int
    correct_after: int


class StudentStateProjection(BaseModel):
    """Deterministic projection of a student's mastery (frozen)."""

    model_config = ConfigDict(frozen=True)

    student_id: UUID
    estimator_version: str = ESTIMATOR_VERSION
    projection_version: int = Field(ge=0)
    concept_mastery: tuple[dict[str, Any], ...] = ()
    skill_mastery: tuple[dict[str, Any], ...] = ()
    active_misconceptions: tuple[dict[str, Any], ...] = ()


def project_student_state(
    *,
    student_id: UUID,
    evidence: Sequence[LearningEvidence] = (),
    observations: Sequence[MisconceptionObservation] = (),
    estimator: MasteryEstimator | None = None,
) -> StudentStateProjection:
    """Replay evidence + observations into a projection (pure, stateless).

    ``projection_version`` equals the number of replayed evidence rows, so
    the caller's compare-and-set persistence (expect current version, write
    version + 1 per new evidence) integrates directly.
    """
    estimator = estimator or MasteryEstimator()

    # 1) Skill mastery: apply evidence in replay order. Unknown skill ids
    # (a replayed row whose problem was deleted degrades to UNKNOWN_SKILL)
    # start at the baseline instead of crashing the replay.
    skills: dict[str, float] = {skill: estimator.initial_mastery() for skill in all_skill_ids()}
    for item in evidence:
        skills.setdefault(item.skill_id, estimator.initial_mastery())
        skills[item.skill_id] = estimator.apply(skills[item.skill_id], item)

    skill_mastery = tuple(
        {"skill_id": skill, "mastery": skills[skill]}
        for skill in sorted(skills)
    )
    # Concepts aggregate only KNOWN skills (an unknown skill has no concept).
    concept_pairs = []
    for skill in sorted(skills):
        try:
            concept_pairs.append((concept_for_skill(skill), skills[skill]))
        except ValueError:
            continue
    concept_mastery = tuple(
        {"concept_id": concept, "mastery": mastery}
        for concept, mastery in concept_pairs
    )

    # 2) Misconception reduction over the merged timeline.
    active = _reduce_misconceptions(evidence, observations)

    return StudentStateProjection(
        student_id=student_id,
        estimator_version=estimator.VERSION,
        projection_version=len(evidence),
        concept_mastery=concept_mastery,
        skill_mastery=skill_mastery,
        active_misconceptions=tuple(active),
    )


def _timeline(evidence: Sequence[LearningEvidence], observations: Sequence[MisconceptionObservation]):
    """Merge evidence and observations deterministically by created_at."""
    events: list[tuple[str, int, str, Any]] = []
    for index, item in enumerate(evidence):
        events.append((item.created_at, index, "evidence", item))
    for index, item in enumerate(observations):
        events.append((item.created_at, index, "observation", item))
    events.sort(key=lambda event: (event[0], event[1], event[2]))
    return events


def _reduce_misconceptions(
    evidence: Sequence[LearningEvidence],
    observations: Sequence[MisconceptionObservation],
) -> list[dict[str, Any]]:
    """Deterministic misconception state machine over the full history."""
    # Deduplicate observations per (attempt, rule) — first wins.
    seen: set[tuple[UUID, str]] = set()
    unique_observations: list[MisconceptionObservation] = []
    for item in observations:
        key = (item.attempt_id, item.rule_id)
        if key in seen:
            continue
        seen.add(key)
        unique_observations.append(item)

    events = _timeline(evidence, unique_observations)
    rules = sorted({item.rule_id for item in unique_observations})

    projections: list[dict[str, Any]] = []
    for rule_id in rules:
        rule_observations = [item for item in unique_observations if item.rule_id == rule_id]
        rule_positions = [events.index(entry) for entry in events if entry[2] == "observation" and entry[3].rule_id == rule_id]
        last_observation_pos = max(rule_positions)
        # The skill this rule was observed on (diagnosis records it).
        skill_ids = {item.detail.get("skill_id") for item in rule_observations}
        skill_ids.discard(None)

        distinct_attempts: list[UUID] = []
        for item in rule_observations:
            if item.attempt_id not in distinct_attempts:
                distinct_attempts.append(item.attempt_id)
        count = len(distinct_attempts)

        correct_after = 0
        for pos, entry in enumerate(events):
            kind, item = entry[2], entry[3]
            if kind != "evidence" or pos <= last_observation_pos:
                continue
            if item.correctness != "correct":
                continue
            if skill_ids and item.skill_id not in skill_ids:
                continue
            correct_after += 1

        if count < ACTIVATION_OBSERVATION_COUNT:
            status = MisconceptionStatus.CANDIDATE
            confidence = CANDIDATE_CONFIDENCE
        else:
            confidence = min(
                MAX_CONFIDENCE,
                BASE_CONFIDENCE + CONFIDENCE_STEP * (count - ACTIVATION_OBSERVATION_COUNT),
            )
            confidence -= CORRECT_DECAY * correct_after
            if confidence <= 0.0:
                status = MisconceptionStatus.RESOLVED
            elif confidence < ACTIVE_THRESHOLD:
                status = MisconceptionStatus.RESOLVING
            else:
                status = MisconceptionStatus.ACTIVE

        if status in (MisconceptionStatus.ACTIVE, MisconceptionStatus.RESOLVING):
            projections.append(
                {
                    "rule_id": rule_id,
                    "status": status.value,
                    "confidence": confidence,
                }
            )
    return projections


__all__ = [
    "ACTIVATION_OBSERVATION_COUNT",
    "ACTIVE_THRESHOLD",
    "BASE_CONFIDENCE",
    "CANDIDATE_CONFIDENCE",
    "CONFIDENCE_STEP",
    "CORRECT_DECAY",
    "MAX_CONFIDENCE",
    "MisconceptionProjection",
    "MisconceptionStatus",
    "StudentStateProjection",
    "project_student_state",
]
