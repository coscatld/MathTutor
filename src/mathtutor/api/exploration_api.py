from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from mathtutor.api.auth_deps import require_student_owner
from mathtutor.api.product_state import get_product_state
from mathtutor.application.exploration_evidence import EvidencePlan
from mathtutor.application.exploration_learning import CheckPrompt, LearningPlan
from mathtutor.infrastructure.zhihu import ZhihuError, secret_name
from mathtutor.repositories.exploration_repository import ExplorationConflict
from mathtutor.security.scopes import StudentOwnerScope

Owner = Annotated[StudentOwnerScope, Depends(require_student_owner)]
Language = Literal["zh", "en"]
Goal = Literal["understand", "apply", "compare"]


class SafeValidationRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                return JSONResponse(status_code=422, content={"detail": [
                    {key: value for key, value in item.items() if key in {"type", "loc", "msg"}}
                    for item in error.errors()]})
        return safe


router = APIRouter(prefix="/exploration", route_class=SafeValidationRoute)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExplorationConfiguration(Strict):
    configured: bool
    environment_managed: bool
    persistent: bool
    has_saved_secret: bool


class ExplorationCredential(Strict):
    api_key: SecretStr = Field(max_length=4096)


class InquiryCreate(Strict):
    inquiry_id: UUID
    generation: int = Field(ge=0)
    question: str = Field(min_length=2, max_length=200)
    goal: Goal = "understand"
    language: Language = "zh"


class InquiryOperation(Strict):
    revision: int = Field(ge=1)
    language: Language = "zh"


class InquiryReflection(InquiryOperation):
    reflection: str = Field(max_length=3000)


class InquiryResponse(InquiryOperation):
    check_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(min_length=1, max_length=240)


class InquiryExplanation(InquiryOperation):
    check_id: str = Field(min_length=1, max_length=100)


class InquirySummary(Strict):
    inquiry_id: str
    question: str
    goal: Goal
    revision: int
    updated_at: str


class InquiryList(Strict):
    generation: int
    items: list[InquirySummary]


class ExplorationView(InquirySummary):
    reflection: str
    evidence: EvidencePlan
    learning: LearningPlan
    ai_status: Literal["not_requested", "ready", "unavailable"]
    organization_attempts: int
    last_feedback: str
    last_check: CheckPrompt | None
    last_correctness: Literal["correct", "incorrect", "unknown", "explanation"] | None
    observation_count: int


async def invoke(owner, action, request: Request | None = None):
    state = get_product_state()

    async def run():
        async with state.turn_requests.owner(owner.student_id):
            try:
                return await action(state, str(owner.student_id))
            except LookupError as error:
                raise HTTPException(404, str(error)) from error
            except ExplorationConflict as error:
                raise HTTPException(409, str(error)) from error
            except ZhihuError as error:
                status = 409 if error.kind == "not_configured" else 429 if error.kind == "rate_limited" else 502
                raise HTTPException(status, str(error)) from error

    if request is None:
        return await run()
    task = asyncio.create_task(run())
    try:
        async with asyncio.timeout(75):
            while not task.done():
                if await request.is_disconnected():
                    raise HTTPException(499, "请求已取消。")
                await asyncio.wait({task}, timeout=0.1)
            return await task
    except TimeoutError as error:
        raise HTTPException(504, "请求耗时过长，已停止。") from error
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, HTTPException):
            await task


@router.get("/configuration", response_model=ExplorationConfiguration)
async def configuration(owner: Owner):
    try:
        return await get_product_state().exploration.client.configuration(str(owner.student_id))
    except Exception as error:
        raise HTTPException(503, "系统凭据库暂不可用。") from error


@router.put("/configuration", response_model=ExplorationConfiguration)
async def configure(body: ExplorationCredential, owner: Owner):
    value = body.api_key.get_secret_value().strip()
    if not 8 <= len(value) <= 4096 or any(character.isspace() for character in value):
        raise HTTPException(422, "请填写完整的知乎 Access Secret。")
    try:
        async with get_product_state().turn_requests.owner(owner.student_id):
            await get_product_state().secret_store.put(secret_name(str(owner.student_id)), value)
    except Exception as error:
        raise HTTPException(503, "系统凭据库未能保存，请重试。") from error
    return await configuration(owner)


@router.delete("/configuration", response_model=ExplorationConfiguration)
async def disconnect(owner: Owner):
    try:
        async with get_product_state().turn_requests.owner(owner.student_id):
            await get_product_state().secret_store.delete(secret_name(str(owner.student_id)))
    except Exception as error:
        raise HTTPException(503, "系统凭据库未能清除，请重试。") from error
    return await configuration(owner)


@router.get("/inquiries", response_model=InquiryList)
async def inquiries(owner: Owner):
    return await invoke(owner, lambda state, sid: state.exploration.repository.list(sid))


@router.post("/inquiries", response_model=ExplorationView)
async def create(body: InquiryCreate, request: Request, owner: Owner):
    if len(body.question.strip()) < 2:
        raise HTTPException(422, "请写下想弄清的问题。")
    return await invoke(owner, lambda state, sid: state.exploration.create(sid,
        **{**body.model_dump(), "inquiry_id": str(body.inquiry_id)}), request)


@router.get("/inquiries/{inquiry_id}", response_model=ExplorationView)
async def read(inquiry_id: UUID, owner: Owner, language: Language = "zh"):
    return await invoke(owner, lambda state, sid: state.exploration.read(sid, str(inquiry_id), language))


@router.post("/inquiries/{inquiry_id}/organize", response_model=ExplorationView)
async def organize(inquiry_id: UUID, body: InquiryOperation, request: Request, owner: Owner):
    return await invoke(owner, lambda state, sid: state.exploration.organize(sid, str(inquiry_id), **body.model_dump()), request)


@router.put("/inquiries/{inquiry_id}/reflection", response_model=ExplorationView)
async def reflection(inquiry_id: UUID, body: InquiryReflection, owner: Owner):
    return await invoke(owner, lambda state, sid: state.exploration.reflect(sid, str(inquiry_id), **body.model_dump()))


@router.post("/inquiries/{inquiry_id}/response", response_model=ExplorationView)
async def respond(inquiry_id: UUID, body: InquiryResponse, owner: Owner):
    return await invoke(owner, lambda state, sid: state.exploration.check(sid, str(inquiry_id), **body.model_dump()))


@router.post("/inquiries/{inquiry_id}/explanation", response_model=ExplorationView)
async def explanation(inquiry_id: UUID, body: InquiryExplanation, owner: Owner):
    return await invoke(owner, lambda state, sid: state.exploration.check(sid, str(inquiry_id),
        **body.model_dump(), show_explanation=True))


@router.delete("/inquiries/{inquiry_id}", response_model=InquiryList)
async def delete(inquiry_id: UUID, owner: Owner):
    async def action(state, sid):
        await state.exploration.repository.delete(sid, str(inquiry_id))
        return await state.exploration.repository.list(sid)
    return await invoke(owner, action)
