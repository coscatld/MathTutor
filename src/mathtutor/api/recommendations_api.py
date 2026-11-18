from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.security.scopes import StudentOwnerScope

router = APIRouter(prefix="/recommendations")
Owner = Annotated[StudentOwnerScope, Depends(require_student_owner)]
Language = Literal["zh", "en"]


class RecommendationResource(BaseModel):
    resource_id: str
    title: str
    author: str | None = None
    url: str
    summary: str
    published_at: str | None = None
    source_time: str | None = None
    source_time_kind: str = "unknown"
    knowledge_points: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    recommendation_reason: str = ""
    selection_reason: str = ""
    review_status: str
    review: dict = Field(default_factory=dict)
    provenance: dict


class RecommendationGoal(BaseModel):
    id: str
    label: str


class RecommendationPrerequisite(BaseModel):
    id: str
    observed: bool


class LearningActionPlan(BaseModel):
    policy: str
    goal: str
    goal_label: str
    target: str
    target_label: str
    title: str
    action: Literal["explain", "check", "continue", "review_prerequisite", "explore"]
    reason: str
    reason_code: str
    evidence_count: int
    evidence_ids: list[str]
    profile_revision: str
    last_event_seq: int
    graph_version: str
    catalog_version: str
    prerequisites: list[RecommendationPrerequisite]
    resources: list[RecommendationResource]
    assessment_scope: str
    query: str


class DiscoveredResources(BaseModel):
    query: str
    retrieved_at: str
    resources: list[RecommendationResource]
    status: Literal["ready", "empty"]


class RecommendationView(BaseModel):
    enabled: bool
    goal: str
    goals: list[RecommendationGoal]
    status: Literal["disabled", "idle", "running", "cached", "rate_limited", "not_configured", "failed"]
    updated_at: str | None
    expires_at: str | None
    plan: LearningActionPlan
    discovery: DiscoveredResources | None


class RecommendationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    goal: str = Field(min_length=1, max_length=80)
    language: Language = "zh"


async def invoke(owner, operation):
    state = get_product_state()
    if state.recommendations is None:
        raise HTTPException(409, "学习记录存储尚未就绪。")
    async with state.turn_requests.owner(owner.student_id):
        try:
            return await operation(state.recommendations, str(owner.student_id))
        except ValueError as error:
            raise HTTPException(422, "请选择可用的学习方向。") from error


@router.get("", response_model=RecommendationView)
async def recommendations(owner: Owner, language: Language = "zh"):
    return await invoke(owner, lambda service, sid: service.get(sid, language=language))


@router.post("/start", response_model=RecommendationView)
async def start(owner: Owner, language: Language = "zh"):
    state = get_product_state()
    if state.recommendations is None:
        raise HTTPException(409, "学习记录存储尚未就绪。")
    return await state.recommendations.start(str(owner.student_id), language=language,
        owner_guard=lambda: state.turn_requests.owner(owner.student_id))


@router.put("/configuration", response_model=RecommendationView)
async def configure(body: RecommendationSettings, owner: Owner):
    return await invoke(owner, lambda service, sid: service.configure(sid, **body.model_dump()))


@router.delete("", response_model=RecommendationView)
async def delete(owner: Owner, language: Language = "zh"):
    async def clear(service, sid):
        await service.delete(sid)
        return await service.get(sid, language=language)
    return await invoke(owner, clear)
