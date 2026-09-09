"""Constraint layer: parser failure is not semantic ambiguity."""

from __future__ import annotations

import json

import pytest

from mathtutor.api.event_stream import MathTutorEventStream
from mathtutor.application.constraint_layer import (
    ConstraintStatus,
    evaluate_constraints,
)
from mathtutor.application.controller import MathTutorController, MathTutorRequest
from mathtutor.application.input_normalizer import normalize_input
from mathtutor.application.message_intent import ConversationIntent, classify_user_message
from mathtutor.application.state_machine import CycleState
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from mathtutor.solving.parser import parse_problem


def _owner(student_id: str = "stu-constraint") -> StudentOwnerScope:
    return StudentOwnerScope(
        principal=PrincipalScope(user_id=student_id, username="alice", role="user"),
        student_id=student_id,
    )


def _envelope(session_id: str, text: str) -> str:
    return json.dumps(
        {"command": "send_message", "payload": {"text": text}, "session_id": session_id},
        ensure_ascii=False,
    )


async def _turn(controller: MathTutorController, session_id: str, text: str) -> list:
    stream = MathTutorEventStream()
    await controller.run(
        MathTutorRequest(
            session_id=session_id,
            user_message=_envelope(session_id, text),
            owner=_owner(),
        ),
        stream,
    )
    await stream.close()
    return [event async for event in stream.subscribe()]


def _blob(events) -> str:
    return "\n".join(event.content for event in events)


def test_parser_failure_does_not_imply_ambiguity() -> None:
    failed = parse_problem(r"解释为什么 \frac{0}{0} 不能直接认为等于 1")
    assert failed.kind == "unparseable"
    result = evaluate_constraints(r"解释为什么 \frac{0}{0} 不能直接认为等于 1")
    assert result.status is ConstraintStatus.SOFT_FAIL
    assert result.status is not ConstraintStatus.NEED_CLARIFICATION


def test_latex_bracket_input_is_repaired() -> None:
    normalized = normalize_input("[ 17\\times 23=? ]")
    assert "square-bracket-wrap" in normalized.repairs
    assert "*" in normalized.normalized
    result = evaluate_constraints("[ 17\\times 23=? ]")
    assert result.status in {ConstraintStatus.PASS, ConstraintStatus.REPAIRED}
    assert result.parse is not None and result.parse.kind == "parsed"


def test_simple_arithmetic_never_requires_clarification() -> None:
    for text in ("2+2=?", "17\\times 23=?", "17×23=?", "[ 17\\times 23=? ]"):
        result = evaluate_constraints(text)
        assert result.status is not ConstraintStatus.NEED_CLARIFICATION, text
        assert result.status in {ConstraintStatus.PASS, ConstraintStatus.REPAIRED}, (
            text,
            result.status,
            result.reason,
        )


def test_natural_language_math_question_soft_fallback() -> None:
    text = r"解释为什么 \frac{0}{0} 不能直接认为等于 1"
    result = evaluate_constraints(text)
    assert result.status is ConstraintStatus.SOFT_FAIL
    assert result.raw_text == text
    limit = r"求 \lim_{x\to0}\frac{\sin x}{x}"
    assert evaluate_constraints(limit).status is ConstraintStatus.SOFT_FAIL


def test_real_ambiguity_requests_specific_clarification() -> None:
    result = evaluate_constraints("求根号 x 加 1")
    assert result.status is ConstraintStatus.NEED_CLARIFICATION
    assert "根号是作用于" in result.clarification_prompt
    assert "再完整写一遍" not in result.clarification_prompt
    numbers = evaluate_constraints("2 3")
    assert numbers.status is ConstraintStatus.NEED_CLARIFICATION
    assert "乘" in numbers.clarification_prompt


def test_general_chat_bypasses_math_parser() -> None:
    assert classify_user_message("你好").intent is ConversationIntent.GENERAL_CHAT


@pytest.mark.asyncio
async def test_controller_times_product_is_verified() -> None:
    controller = MathTutorController()
    events = await _turn(controller, "times", "17\\times 23=?")
    blob = _blob(events)
    assert "需要澄清" not in blob
    assert "没法确定" not in blob
    session = await controller.sessions.load(_owner().student_id, "times")
    assert session is not None
    assert session.state is CycleState.AWAITING_ATTEMPT


@pytest.mark.asyncio
async def test_controller_zero_over_zero_goes_to_tutor() -> None:
    class ChatResponder:
        async def respond(self, text, *, history=(), problem_context="", unstructured_math=False):
            assert unstructured_math is True
            return "0/0 没有确定的除法意义，所以不能直接当成 1。"

    controller = MathTutorController(chat_responder=ChatResponder())
    events = await _turn(
        controller, "undef", r"解释为什么 \frac{0}{0} 不能直接认为等于 1"
    )
    blob = _blob(events)
    assert "没法确定" not in blob
    assert "0/0" in blob or "除法" in blob
    session = await controller.sessions.load(_owner().student_id, "undef")
    assert session is None


@pytest.mark.asyncio
async def test_controller_limit_soft_fallback() -> None:
    class ChatResponder:
        async def respond(self, text, *, history=(), problem_context="", unstructured_math=False):
            return "这是一个标准极限，结果是 1。我们先从图像上看 sin x 和 x 在 0 附近的关系。"

    controller = MathTutorController(chat_responder=ChatResponder())
    events = await _turn(controller, "lim", r"求 \lim_{x\to0}\frac{\sin x}{x}")
    blob = _blob(events)
    assert "没法确定" not in blob
    assert "极限" in blob or "1" in blob


@pytest.mark.asyncio
async def test_controller_greeting_bypasses_parser() -> None:
    seen: list[str] = []

    class ChatResponder:
        async def respond(self, text, *, history=(), problem_context="", unstructured_math=False):
            seen.append(text)
            return "你好！"

    controller = MathTutorController(chat_responder=ChatResponder())
    events = await _turn(controller, "hi", "你好")
    assert seen == ["你好"]
    assert "题目" not in _blob(events)
    assert await controller.sessions.load(_owner().student_id, "hi") is None


@pytest.mark.asyncio
async def test_controller_followup_uses_context() -> None:
    controller = MathTutorController()
    await _turn(controller, "follow", "2x + 3 = 7")
    events = await _turn(controller, "follow", "我没懂")
    assert "没法确定" not in _blob(events)
    assert "相邻的" not in _blob(events)


@pytest.mark.asyncio
async def test_controller_radical_scope_is_specific() -> None:
    controller = MathTutorController()
    events = await _turn(controller, "rad", "求根号 x 加 1")
    blob = _blob(events)
    assert "根号是作用于" in blob
    assert "再完整写一遍" not in blob
