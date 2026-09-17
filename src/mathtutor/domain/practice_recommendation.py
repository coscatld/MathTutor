"""Recommendation intent is separate from exercise truth and task completion."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

PracticePurpose = Literal["A1", "A2", "B", "C", "D", "E"]
RecommendationStatus = Literal[
    "PREPARING", "ACTIVE", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED", "FAILED"
]


class RecommendationBasis(BaseModel):
    """Generation-time references; never a second copy of a student's answers."""
    model_config = ConfigDict(frozen=True)

    policy_version: Literal["mt-recommendation-basis-v1"] = "mt-recommendation-basis-v1"
    history_cutoff_seq: int = Field(ge=0)
    evidence_ids: tuple[str, ...] = ()
    target_revision: str
    target_skill_ids: tuple[str, ...]
    purpose: PracticePurpose
    reason_code: Literal["parent_attempt", "related_task"]
    initial_assessment_run_id: str | None = None
    initial_assessment_policy: str | None = None


class PracticeRecommendation(BaseModel):
    model_config = ConfigDict(frozen=True)

    recommendation_id: UUID = Field(default_factory=uuid4)
    student_id: UUID
    parent_cycle_id: UUID
    purpose: PracticePurpose
    target_revision: str
    target_skill_ids: tuple[str, ...]
    status: RecommendationStatus = "PREPARING"
    offer_id: UUID | None = None
    resume_parent_cycle_id: UUID | None = None
    desired_difficulty: int = Field(default=2, ge=1, le=5)
    decision_reason: str = ""
    failure_reason: str = ""
    candidate_count: int = Field(default=0, ge=0, le=3)
    material_basis: tuple[dict, ...] = ()
    basis: RecommendationBasis | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MaterialDesignBasis(BaseModel):
    """A checked citation and its concrete influence, not a retrieval-hit claim."""
    model_config = ConfigDict(frozen=True)

    source_chunk_id: UUID
    skill_id: str
    quote_start: int = Field(ge=0)
    quote_end: int = Field(gt=0)
    quote: str = Field(min_length=1)
    design_influence: str = Field(min_length=1)


PURPOSE_LABELS = {
    "A1": "独立完成后的迁移练习",
    "A2": "受助完成后的独立巩固",
    "B": "看过答案后的独立检测",
    "C": "先修知识补基础",
    "D": "主动练习",
    "E": "延迟复习",
}
