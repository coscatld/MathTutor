"""Trusted request, student event and command contracts shared by tutoring adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from mathtutor.application.state_machine import (
    CycleCommand,
    CycleState,
    allowed_next_commands,
)
from mathtutor.security.scopes import StudentOwnerScope

USER_COMMANDS: dict[str, CycleCommand] = {
    "submit_problem": CycleCommand.SUBMIT_PROBLEM,
    "clarify_problem": CycleCommand.CLARIFY_PROBLEM,
    "submit_attempt": CycleCommand.SUBMIT_ATTEMPT,
    "clarify_attempt": CycleCommand.CLARIFY_ATTEMPT,
    "request_hint": CycleCommand.REQUEST_HINT,
    "request_explanation": CycleCommand.REQUEST_EXPLANATION,
    "request_example": CycleCommand.REQUEST_EXAMPLE,
    "request_solution": CycleCommand.SOLUTION_SHOWN_PERMITTED,  # L5 (design §2.1 请求完整解析)
    "accept_practice_offer": CycleCommand.ACCEPT_PRACTICE_OFFER,
    "decline_practice_offer": CycleCommand.DECLINE_PRACTICE_OFFER,
    "cancel_turn": CycleCommand.CANCEL_TURN,
    "request_practice": CycleCommand.REQUEST_HINT,
    "request_foundation": CycleCommand.REQUEST_HINT,
    "request_review": CycleCommand.REQUEST_HINT,
    "resume_problem": CycleCommand.REQUEST_HINT,
    "end_problem": CycleCommand.CANCEL_TURN,
    "start_diagnostic": CycleCommand.REQUEST_HINT,
    "skip_diagnostic": CycleCommand.REQUEST_HINT,
    "request_options": CycleCommand.REQUEST_HINT,
}


LEGACY_COMMAND_ALIASES = {"solution_shown_permitted": "request_solution"}


SEND_MESSAGE_COMMAND = "send_message"


def student_allowed_inputs(state: CycleState) -> list[str]:
    """Student-channel commands only: internal outcomes (e.g.
    ``solution_shown_permitted``) never appear in the UI contract — the
    client can only ever send what it is shown (design doc §13.3)."""
    allowed = set(allowed_next_commands(state))
    return [name for name, command in USER_COMMANDS.items() if command in allowed]


@dataclass(frozen=True, slots=True)
class MathTutorRequest:
    """Trusted request accepted by the product controller.

    ``owner`` is constructed by the server auth boundary and cannot be
    deserialized from an HTTP/WS payload.
    """

    session_id: str
    user_message: str
    owner: StudentOwnerScope
    conversation_messages: tuple[dict[str, Any], ...] = ()


class MathTutorEventType(str, Enum):
    CONTENT = "content"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class MathTutorEvent:
    """Narrow internal event; only student-public content/error can exist."""

    type: MathTutorEventType
    content: str = ""
    source: str = "math_tutor"
    stage: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class MathTutorEventSink(Protocol):
    async def emit(self, event: MathTutorEvent) -> None: ...

    async def content(
        self,
        text: str,
        source: str = "",
        stage: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def error(
        self,
        message: str,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class MathTutorManifest:
    name: str
    description: str
    stages: tuple[str, ...]
    tools_used: tuple[()] = ()


def _parse_envelope(user_message: str) -> tuple[str, dict[str, Any]]:
    """Parse the command envelope; plain text enters the intent router."""
    text = user_message.strip()
    if not text:
        return (SEND_MESSAGE_COMMAND, {"payload": {"text": ""}})
    if text.startswith("{"):
        try:
            envelope = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"命令 envelope 不是合法 JSON: {exc}") from exc
        command = str(envelope.get("command") or SEND_MESSAGE_COMMAND)
        if envelope.get("protocol_version", 1) == 1:
            command = LEGACY_COMMAND_ALIASES.get(command, command)
        if command not in USER_COMMANDS and command != SEND_MESSAGE_COMMAND:
            raise ValueError(f"未知命令: {command}")
        return (command, envelope)
    return (SEND_MESSAGE_COMMAND, {"payload": {"text": text}})
