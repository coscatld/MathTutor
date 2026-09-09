"""Tutor conversation orchestration: intent, state machine, projection."""

from __future__ import annotations

import json

import pytest

from mathtutor.api.event_stream import MathTutorEventStream
from mathtutor.application.controller import MathTutorController, MathTutorRequest
from mathtutor.application.message_intent import (
    ConversationIntent,
    classify_user_message,
    is_concrete_math_input,
)
from mathtutor.application.message_projection import (
    STUDENT_TRANSITION_FAILURE,
    project_assistant_message,
    project_turn_error,
)
from mathtutor.application.state_machine import CycleCommand, CycleState
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope




def _owner(student_id: str = "stu-orch") -> StudentOwnerScope:
    return StudentOwnerScope(
        principal=PrincipalScope(user_id=student_id, username="alice", role="user"),
        student_id=student_id,
    )


def _envelope(session_id: str, text: str, command: str = "send_message") -> str:
    payload = {"text": text}
    if command == "submit_attempt":
        payload = {"answer": text}
    return json.dumps(
        {"command": command, "payload": payload, "session_id": session_id},
        ensure_ascii=False,
    )


async def _turn(
    controller: MathTutorController,
    session_id: str,
    text: str,
    *,
    owner: StudentOwnerScope | None = None,
    command: str = "send_message",
    history: tuple = (),
) -> list:
    owner = owner or _owner()
    stream = MathTutorEventStream()
    await controller.run(
        MathTutorRequest(
            session_id=session_id,
            user_message=_envelope(session_id, text, command),
            owner=owner,
            conversation_messages=history,
        ),
        stream,
    )
    await stream.close()
    return [event async for event in stream.subscribe()]


def _contents(events) -> str:
    return "\n".join(event.content for event in events)


def test_greeting_is_not_math_input() -> None:
    assert classify_user_message("你好").intent is ConversationIntent.GENERAL_CHAT
    assert is_concrete_math_input("你好") is False


def test_model_id_question_is_not_math_input() -> None:
    text = "deepseek-v4-flash-vision-exp是什么"
    assert classify_user_message(text).intent is ConversationIntent.GENERAL_CHAT
    assert is_concrete_math_input(text) is False


def test_simple_arithmetic_is_math_problem() -> None:
    assert classify_user_message("2+2=?").intent is ConversationIntent.MATH_PROBLEM
    assert classify_user_message("求 x^2 + 2x + 1 = 0").intent is ConversationIntent.MATH_PROBLEM


def test_followup_uses_active_problem_context() -> None:
    routed = classify_user_message("我没懂", cycle_state=CycleState.AWAITING_ATTEMPT)
    assert routed.intent is ConversationIntent.PROBLEM_CONTINUATION


def test_internal_command_ack_is_dropped() -> None:
    assert project_assistant_message("命令 clarify_problem 已确认") is None


def test_invalid_transition_is_not_exposed() -> None:
    leaked = "状态 grounding 不接受命令 submit_problem"
    assert project_turn_error(leaked) == STUDENT_TRANSITION_FAILURE
    assert "grounding" not in project_turn_error(leaked)
    assert "submit_problem" not in project_turn_error(leaked)


@pytest.mark.asyncio
async def test_greeting_bypasses_math_parser() -> None:
    seen: list[str] = []

    class ChatResponder:
        async def respond(self, text: str, *, history=(), problem_context=""):
            seen.append(text)
            return "你好！很高兴见到你。"

    controller = MathTutorController(chat_responder=ChatResponder())
    events = await _turn(controller, "greet", "你好")
    blob = _contents(events)
    assert seen == ["你好"]
    assert "你好！很高兴见到你。" in blob
    assert "题目有歧义" not in blob
    assert "var" not in blob
    assert await controller.sessions.load(_owner().student_id, "greet") is None


@pytest.mark.asyncio
async def test_general_question_bypasses_problem_workflow() -> None:
    seen: list[str] = []

    class ChatResponder:
        async def respond(self, text: str, *, history=(), problem_context=""):
            seen.append(text)
            return "那是一个模型名称，用来描述多模态对话能力。"

    controller = MathTutorController(chat_responder=ChatResponder())
    events = await _turn(
        controller, "model-q", "deepseek-v4-flash-vision-exp是什么"
    )
    blob = _contents(events)
    assert seen == ["deepseek-v4-flash-vision-exp是什么"]
    assert "模型名称" in blob
    assert "submit_problem" not in blob
    assert "grounding" not in blob
    assert "题目有歧义" not in blob
    assert await controller.sessions.load(_owner().student_id, "model-q") is None


@pytest.mark.asyncio
async def test_simple_math_problem_is_accepted() -> None:
    controller = MathTutorController()
    events = await _turn(controller, "arith", "2+2=?")
    blob = _contents(events)
    session = await controller.sessions.load(_owner().student_id, "arith")
    assert session is not None
    assert session.state is CycleState.AWAITING_ATTEMPT
    assert "题目已解析并验证" in blob
    assert "不接受命令" not in blob
    assert "grounding" not in blob


@pytest.mark.asyncio
async def test_grounding_accepts_completed_problem_transition() -> None:
    controller = MathTutorController()
    owner = _owner()
    session = await controller.sessions.create(owner.student_id, "stuck-ground")
    session.step(CycleCommand.SUBMIT_PROBLEM)
    assert session.state is CycleState.GROUNDING
    events = await _turn(controller, "stuck-ground", "2+2=?", owner=owner)
    blob = _contents(events)
    session = await controller.sessions.load(owner.student_id, "stuck-ground")
    assert session is not None
    assert session.state is CycleState.AWAITING_ATTEMPT
    assert "题目已解析并验证" in blob
    assert "不接受命令" not in blob


@pytest.mark.asyncio
async def test_internal_command_not_rendered_to_user() -> None:
    controller = MathTutorController()
    owner = _owner()
    first = await _turn(controller, "clarify-ui", "2 3 + 4", owner=owner)
    blob = _contents(first)
    assert "clarify_problem" not in blob
    assert "命令" not in blob
    assert "乘" in blob or "题目" in blob or "没法确定" in blob
    second = await _turn(controller, "clarify-ui", "2x + 3 = 7", owner=owner)
    blob = _contents(second)
    assert "命令" not in blob
    assert "clarify_problem" not in blob
    session = await controller.sessions.load(owner.student_id, "clarify-ui")
    assert session is not None
    assert session.state is CycleState.AWAITING_ATTEMPT


@pytest.mark.asyncio
async def test_invalid_transition_not_exposed_to_ui() -> None:
    controller = MathTutorController()
    events = await _turn(controller, "bad-hint", "给我提示", command="request_hint")
    blob = _contents(events)
    assert STUDENT_TRANSITION_FAILURE in blob
    assert "grounding" not in blob
    assert "submit_problem" not in blob
    assert "request_hint" not in blob


@pytest.mark.asyncio
async def test_followup_message_uses_active_problem_context() -> None:
    controller = MathTutorController()
    owner = _owner()
    await _turn(controller, "follow", "2x + 3 = 7", owner=owner)
    events = await _turn(controller, "follow", "我没懂", owner=owner)
    blob = _contents(events)
    session = await controller.sessions.load(owner.student_id, "follow")
    assert session is not None
    assert session.state in {CycleState.AWAITING_ATTEMPT, CycleState.EXPLAINING, CycleState.HINTED}
    assert "题目有歧义" not in blob
    assert "相邻的" not in blob


@pytest.mark.asyncio
async def test_quadratic_enters_math_workflow() -> None:
    controller = MathTutorController()
    events = await _turn(controller, "quad", "求 x^2 + 2x + 1 = 0")
    session = await controller.sessions.load(_owner().student_id, "quad")
    assert session is not None
    assert session.state is CycleState.AWAITING_ATTEMPT
    assert "题目已解析并验证" in _contents(events)


@pytest.mark.asyncio
async def test_provider_success_not_overwritten_by_state_error() -> None:
    class ChatResponder:
        async def respond(self, text: str, *, history=(), problem_context=""):
            return "你好！很高兴见到你，今天想聊哪一道题？"

    controller = MathTutorController(chat_responder=ChatResponder())
    events = await _turn(controller, "provider-ok", "你好")
    blob = _contents(events)
    assert "很高兴见到你" in blob
    assert "不接受命令" not in blob
    errors = [event for event in events if event.type.value == "error"]
    assert errors == []


@pytest.mark.asyncio
async def test_new_problem_replaces_active_cycle() -> None:
    controller = MathTutorController()
    owner = _owner()
    await _turn(controller, "next-p", "2+2=?", owner=owner)
    events = await _turn(controller, "next-p", "2x + 3 = 7", owner=owner)
    session = await controller.sessions.load(owner.student_id, "next-p")
    assert session is not None
    assert session.state is CycleState.AWAITING_ATTEMPT
    assert "2x + 3 = 7" in _contents(events) or "2 x + 3 = 7" in _contents(events)
    assert "不接受命令" not in _contents(events)
