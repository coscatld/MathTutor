"""MathTutor product WebSocket (design doc §13.1, §13.2, §16).

The ONLY student entry into the tutoring pipeline:

    WS connect → ws_require_student_owner (fail closed)
               → envelope allowlist validation
               → trusted MathTutorRequest
               → MathTutorController → typed events over the socket

No general turn runtime, no capability selection, no tool fields. The
general DeepTutor ``/ws`` surface is NOT part of the product app.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mathtutor.api.auth_deps import ws_require_student_owner
from mathtutor.api.event_stream import MathTutorEventStream
from mathtutor.api.product_state import get_product_state
from mathtutor.application.controller import MathTutorRequest
from mathtutor.security.allowlist import (
    SecurityViolationError,
    validate_client_envelope,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _to_student_frame(event: Any) -> dict[str, Any]:
    """Project a MathTutor event onto the typed STUDENT public schema (Phase 3E).

    The student serializer accepts only StudentPublicEvent — internal
    solver/model/tool traces have no path through this function. The wire
    shape structurally excludes candidate/verification/trace fields.
    """
    from mathtutor.pedagogy.events import (
        StudentPublicEvent,
        build_student_extra,
    )

    metadata = event.metadata or {}
    if event.type == "error":
        return StudentPublicEvent(
            event_type="turn_error",
            cycle_state=str(metadata.get("cycle_state", "")),
            cycle_state_version=int(metadata.get("cycle_state_version") or 0),
            payload={"error": event.content},
        ).wire_dict()
    if event.type == "content":
        return StudentPublicEvent(
            event_type=str(metadata.get("event_type") or "tutor_action_committed"),
            cycle_state=str(metadata.get("cycle_state", "")),
            cycle_state_version=int(metadata.get("cycle_state_version") or 0),
            allowed_next_inputs=[str(x) for x in metadata.get("allowed_next_inputs") or []],
            payload={
                "action": str(metadata.get("action") or metadata.get("detail") or ""),
                "effective_assistance_level": int(metadata.get("effective_assistance_level") or 0),
                "student_message": str(event.content or ""),
                "trigger_command": str(metadata.get("trigger_command") or ""),
                # Structured problem surface (student-safe fields only).
                "problem_latex": str(metadata.get("problem_latex") or ""),
                "problem_type": str(metadata.get("problem_type") or ""),
            },
            # Phase 5 public projections ONLY — every other metadata key
            # (internal fields included) is structurally dropped.
            extra=build_student_extra(metadata),
        ).wire_dict()
    # Non-student event types never reach the student channel.
    return StudentPublicEvent(event_type="turn_error", payload={"error": "internal event dropped"}).wire_dict()


@router.websocket("/ws")
async def math_tutor_websocket(ws: WebSocket) -> None:
    owner = await ws_require_student_owner(ws)
    if owner is None:  # socket already closed (401-style rejection)
        return

    await ws.accept()
    state = get_product_state()
    closed = False

    async def safe_send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
        except Exception:
            closed = True

    try:
        while not closed:
            raw = await ws.receive_text()
            user_message, session_id = await _normalize_message(raw, safe_send)
            if user_message is not None:
                request = MathTutorRequest(
                    session_id=session_id,
                    user_message=user_message,
                    owner=owner,
                )
                event_stream = MathTutorEventStream()

                async def _run() -> None:
                    try:
                        await state.controller.run(request, event_stream)
                    finally:
                        await event_stream.close()

                task = asyncio.create_task(_run())
                async for event in event_stream.subscribe():
                    await safe_send(_to_student_frame(event))
                await task
            # Turn-termination frame: the client reads events until it sees
            # this marker (the socket stays open for the next command).
            from mathtutor.pedagogy.events import StudentPublicEvent

            await safe_send(StudentPublicEvent(event_type="turn_end").wire_dict())
    except WebSocketDisconnect:
        pass


async def _normalize_message(
    raw: str, safe_send: Any
) -> tuple[str | None, str]:
    """Parse + validate one WS frame; returns (user_message, session_id).

    A JSON object is validated against the envelope allowlist (§21/§23:
    identity, role, capability and tool keys are rejected); plain text is
    accepted as a ``submit_problem`` shorthand. Returns (None, "") when the
    frame was rejected (a student-schema error was already sent).
    """
    from mathtutor.pedagogy.events import StudentPublicEvent

    async def _reject(message: str) -> None:
        await safe_send(
            StudentPublicEvent(
                event_type="turn_error", payload={"error": message}
            ).wire_dict()
        )

    text = raw.strip()
    if not text:
        await _reject("Empty message.")
        return None, ""

    if not text.startswith("{"):
        return text, ""

    try:
        envelope = json.loads(text)
    except json.JSONDecodeError:
        await _reject("Invalid JSON.")
        return None, ""

    if not isinstance(envelope, dict):
        await _reject("Envelope must be a JSON object.")
        return None, ""

    try:
        validate_client_envelope(envelope)
    except SecurityViolationError as exc:
        await _reject(str(exc))
        return None, ""

    session_id = str(envelope.get("session_id") or "")
    return json.dumps(envelope, ensure_ascii=False), session_id


__all__ = ["router"]
