"""Strict, replayable facts; absence of a label is never an incorrect label."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from mathtutor.learning.skill_graph import GRAPH_VERSION

EVENT_SCHEMA = "learning_event_v2"
FEATURE_SCHEMA = "structured_kt_v1"
LABEL_POLICY = "first_content_submission_v1"
BASELINE_POLICY = "evidence_beta_v1"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class LearningEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: str
    student_id: str
    session_id: str
    cycle_id: str
    event_seq: int = Field(default=0, ge=0)
    request_id: str = ""
    event_type: Literal[
        "attempt_assessed", "help_requested", "help_committed",
        "help_possibly_exposed", "help_presented", "self_explanation",
        "evidence_invalidated", "problem_started", "problem_ended", "attempt_submitted",
    ]
    occurred_at: str = Field(default_factory=utcnow)
    problem_id: str
    problem_revision: str
    item_family_id: str
    leakage_group_id: str = ""
    subgoal_id: str = ""
    skill_ids: tuple[str, ...] = ()
    skill_weights: tuple[float, ...] = ()
    assessment_id: str = ""
    attempt_id: str = ""
    response_fingerprint: str = Field(default="", max_length=128)
    response_format: Literal["free_response", "single_choice"] = "free_response"
    duplicate_response: bool = False
    prior_task_attempt: bool = False
    submission_event_id: str = ""
    supervision_policy_version: str = "legacy_response_distinct_v1"
    prediction_id: str = ""
    correctness: Literal["correct", "incorrect", "partial", "unknown"] | None = None
    completion_scope: Literal["full_problem", "subgoal", "reflection", "error_analysis"] = "full_problem"
    evidence_kind: Literal["independent", "assisted", "post_solution", "unknown", "none"] = "none"
    target_answer_exposed_before_attempt: bool = False
    prior_help_event_ids: tuple[str, ...] = ()
    active_response_ms: int | None = Field(default=None, ge=0)
    time_gap_ms: int | None = Field(default=None, ge=0)
    difficulty: float | None = Field(default=None, ge=1, le=5)
    misconception_codes: tuple[str, ...] = ()
    verified_error_skill_ids: tuple[str, ...] = ()
    task_purpose: str = "practice"
    help_kind: Literal["", "hint", "explanation", "example", "solution"] = ""
    target_answer_exposed: bool = False
    target_answer_authorized: bool | None = None
    eligible_cycle: bool | None = None
    lifecycle_status: Literal["", "active", "completed", "paused", "closed", "exited", "failed"] = ""
    delivery_id: str = ""
    provenance_uncertain: bool = False
    invalidates_event_id: str = ""
    graph_version: str = GRAPH_VERSION
    schema_version: str = EVENT_SCHEMA

    @model_validator(mode="after")
    def validate_fact(self):
        if len(self.skill_ids) != len(set(self.skill_ids)):
            raise ValueError("skill ids must be unique")
        if self.skill_weights and (
            len(self.skill_weights) != len(self.skill_ids)
            or any(x <= 0 for x in self.skill_weights)
        ):
            raise ValueError("skill weights must be positive and aligned")
        if self.event_type != "attempt_assessed" and self.correctness is not None:
            raise ValueError("only a validated assessment can supply correctness")
        if self.event_type == "attempt_assessed" and not (self.assessment_id and self.attempt_id):
            raise ValueError("assessment and attempt identities are required")
        if self.event_type == "evidence_invalidated" and not self.invalidates_event_id:
            raise ValueError("invalidation requires its source event")
        if not set(self.verified_error_skill_ids).issubset(self.skill_ids):
            raise ValueError("error localization must refer to bound skills")
        return self

    @property
    def independent_target(self) -> bool:
        """Primary loss: a single, trustworthy, whole-task binary observation."""
        return (
            self.event_type == "attempt_assessed"
            and self.evidence_kind == "independent"
            and self.correctness in {"correct", "incorrect"}
            and self.completion_scope == "full_problem"
            and self.task_purpose not in {"diagnostic", "error_analysis"}
            and self.response_format == "free_response"
            and bool(self.skill_ids)
            and not self.provenance_uncertain
            and not self.duplicate_response
            and not self.prior_task_attempt
            and not self.target_answer_exposed_before_attempt
        )


def ordered_attempts(events: Sequence[LearningEvent]) -> list[LearningEvent]:
    """Derive first-task eligibility BEFORE exclusions, including old exports.

    An excluded verdict still occupies its chronological attempt position.
    The original event disappears only when the entire learning history does.
    """
    # A raw submission and its assessment occupy ONE position, not two.
    # Unassessed submissions (including judge failures) still reserve a slot.
    seen, assessed_submissions, unique, result = {}, set(), set(), []
    for event in sorted(events, key=lambda e: (e.event_seq, e.occurred_at, e.event_id)):
        identity = (event.student_id, event.event_id)
        if identity in unique:
            continue
        unique.add(identity)
        if event.event_type == "attempt_submitted":
            key = (event.student_id, event.problem_revision)
            seen.setdefault(key, ("submission", event.event_id))
        elif event.event_type == "attempt_assessed":
            key = (event.student_id, event.problem_revision)
            slot = ("submission", event.submission_event_id) if event.submission_event_id else ("assessment", event.event_id)
            binding = (event.student_id, event.submission_event_id)
            repeated_binding = bool(event.submission_event_id) and binding in assessed_submissions
            event = event.model_copy(update={"prior_task_attempt": event.prior_task_attempt
                or (key in seen and seen[key] != slot) or repeated_binding})
            seen.setdefault(key, slot)
            if event.submission_event_id:
                assessed_submissions.add(binding)
        result.append(event)
    return result


def valid_events(events: Sequence[LearningEvent]) -> list[LearningEvent]:
    """Append-only correction events invalidate facts without erasing history."""
    invalidated = {(x.student_id, x.invalidates_event_id) for x in events if x.event_type == "evidence_invalidated"}
    return [x for x in ordered_attempts(events)
            if (x.student_id, x.event_id) not in invalidated and x.event_type != "evidence_invalidated"]


def evidence_category(event: LearningEvent) -> str | None:
    """Classify a replayed assessment without changing its recorded facts.

    Call with ``valid_events`` so first-attempt eligibility is derived before
    exclusions. Choice, step and diagnostic work are observations, not the
    existing first independent free-response target. Repeated independent
    whole-task attempts remain in history but do not create another target.
    """
    if event.event_type != "attempt_assessed" or event.duplicate_response:
        return None
    if event.correctness in {None, "unknown"} or event.provenance_uncertain or event.evidence_kind == "unknown":
        return "unknown"
    if (event.task_purpose in {"diagnostic", "error_analysis"}
            or event.response_format == "single_choice"
            or event.completion_scope != "full_problem" or event.correctness == "partial"):
        return "diagnostic"
    if event.target_answer_exposed_before_attempt:
        return "post_solution"
    if event.evidence_kind in {"assisted", "post_solution"}:
        return event.evidence_kind
    if event.independent_target:
        return "independent"
    if event.evidence_kind == "independent" and event.prior_task_attempt:
        return None
    return "unknown"


def has_verified_outcome(event: LearningEvent) -> bool:
    """A recorded mathematical verdict, independent of help or task repetition."""
    return (event.event_type == "attempt_assessed" and not event.duplicate_response
            and event.correctness in {"correct", "incorrect", "partial"}
            and event.evidence_kind in {"independent", "assisted", "post_solution"}
            and not event.provenance_uncertain)


def attributed_skill_ids(event: LearningEvent) -> tuple[str, ...]:
    """The skills this outcome can address, not every skill the item involves.

    Single-skill observations keep their existing scope (including unknown
    outcomes). For a multi-skill error, only server-verifier localization is
    accepted. A final answer, signal name or current teaching goal alone does
    not identify a failed/successful component. This never changes event facts.
    """
    if event.event_type != "attempt_assessed":
        return ()
    if len(event.skill_ids) <= 1:
        return event.skill_ids
    if has_verified_outcome(event) and event.correctness in {"incorrect", "partial"}:
        return tuple(skill for skill in event.skill_ids if skill in event.verified_error_skill_ids)
    return ()


def independent_skill_success_ids(event: LearningEvent) -> tuple[str, ...]:
    """A new independent single-skill task or explicitly identified step.

    A verified step may address its own skill without becoming a whole-task
    training label. Call after valid_events so retries/exclusions cannot reset
    first-attempt eligibility. Multi-skill final answers never clear all rules.
    """
    targets = attributed_skill_ids(event)
    if (len(targets) == 1 and has_verified_outcome(event) and event.correctness == "correct"
            and event.evidence_kind == "independent" and not event.prior_task_attempt
            and not event.target_answer_exposed_before_attempt and event.response_format == "free_response"
            and event.task_purpose not in {"diagnostic", "error_analysis"}
            and (event.completion_scope == "full_problem"
                 or (event.completion_scope == "subgoal" and bool(event.subgoal_id)))):
        return targets
    return ()


def evidence_summary(events: Sequence[LearningEvent]) -> dict:
    """Counts are attributable facts, never level-based mastery increments.

    A multiskill whole-task error cannot identify which skill failed. Such
    failures remain item-level unless the verifier supplies a localized skill.
    Correct multiskill answers are also reported as joint evidence, not copied
    into multiple independent successes.
    """
    skills: dict[str, dict] = {}
    item_uncertain = 0
    accepted = valid_events(events)
    for event in accepted:
        if event.event_type != "attempt_assessed":
            continue
        for skill in event.skill_ids:
            skills.setdefault(skill, {
                "skill_id": skill, "independent": {"correct": 0, "incorrect": 0},
                "assisted": {"correct": 0, "incorrect": 0},
                "post_solution": {"correct": 0, "incorrect": 0},
                "step_correct": 0, "unknown": 0, "joint_task_evidence": 0, "diagnostic": {"correct": 0, "incorrect": 0},
                "duplicate_responses": 0,
                "repeat_attempts": 0,
                "assessment_ids": [],
            })
        if event.duplicate_response:
            for skill in event.skill_ids:
                skills[skill]["duplicate_responses"] += 1
            continue
        if event.prior_task_attempt:
            for skill in event.skill_ids:
                skills[skill]["repeat_attempts"] += 1
        category = evidence_category(event)
        if category is None:
            continue
        targets = attributed_skill_ids(event)
        if len(event.skill_ids) > 1 and not targets:
            item_uncertain += 1
            for skill in event.skill_ids:
                skills[skill]["joint_task_evidence"] += 1
            continue
        for skill in targets:
            row = skills[skill]
            row["assessment_ids"].append(event.assessment_id)
            if category == "unknown":
                row["unknown"] += 1
            elif category == "diagnostic":
                if event.correctness == "partial" and skill in event.verified_error_skill_ids:
                    # A partially successful item can contain a verified
                    # failed component; do not call that component a success.
                    row["diagnostic"]["incorrect"] += 1
                elif event.correctness in {"correct", "incorrect"}:
                    row["diagnostic"][event.correctness] += 1
                if ((event.completion_scope != "full_problem" or event.correctness == "partial")
                        and event.correctness in {"correct", "partial"}
                        and skill not in event.verified_error_skill_ids):
                    row["step_correct"] += 1
            else:
                row[category][event.correctness] += 1
    for row in skills.values():
        correct = row["independent"]["correct"]
        incorrect = row["independent"]["incorrect"]
        # Neutral Beta(1,1) supports internal baseline prediction only. The
        # student contract exposes counts/status, not an uncalibrated percent.
        row["status"] = "已有独立正确证据" if correct else "建议复习" if incorrect >= 2 else "仍需确认"
        row["confidence_band"] = "证据有限" if correct + incorrect < 5 else "已有多次观察，仍需独立检测"
        row["id"] = row["skill_id"]
        row["ungradable"] = row["unknown"]
        row["evidence_status"] = row["status"]
        row["evidence_summary"] = {key: row[key] for key in (
            "independent", "assisted", "post_solution", "diagnostic", "ungradable", "step_correct", "joint_task_evidence", "duplicate_responses", "repeat_attempts")}
    return {
        "estimator": "evidence_tracker_v2", "skills": [skills[x] for x in sorted(skills)],
        "item_level_uncertain": item_uncertain,
        "event_count": len(accepted), "last_event_seq": max((x.event_seq for x in events), default=0),
        "totals": {kind: sum(evidence_category(x) == kind for x in accepted)
                   for kind in ("independent", "assisted", "post_solution", "unknown", "diagnostic")} | {
                       "duplicate_responses": sum(x.duplicate_response for x in accepted),
                       "repeat_attempts": sum(x.prior_task_attempt for x in accepted)},
    }


def baseline_prediction(events: Sequence[LearningEvent], skill_ids: Sequence[str]) -> float:
    rows = {x["skill_id"]: x for x in evidence_summary(events)["skills"]}
    estimates = []
    for skill in dict.fromkeys(skill_ids):
        independent = rows.get(skill, {}).get("independent", {})
        correct, incorrect = independent.get("correct", 0), independent.get("incorrect", 0)
        estimates.append((1 + correct) / (2 + correct + incorrect))
    return sum(estimates) / len(estimates) if estimates else 0.5
