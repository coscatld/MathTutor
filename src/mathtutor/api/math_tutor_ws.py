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
import time
from mathtutor.application.tutor_runtime import TutorTurnResult, FinishReason, current_turn, record_turn
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from mathtutor.api.auth_deps import ws_require_student_owner
from mathtutor.pedagogy.events import StudentPublicEvent
from mathtutor.api.event_stream import MathTutorEventStream
from mathtutor.api.product_state import get_product_state
from mathtutor.application.controller import MathTutorRequest
from mathtutor.application.conversation_scope import reset_document_scope, set_document_scope
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
    active_task: asyncio.Task | None = None
    active_conversation = ""
    incoming: asyncio.Queue[str | None] = asyncio.Queue(maxsize=16)
    disconnect_reason = FinishReason.STREAM_INTERRUPTED

    async def safe_send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            await ws.send_text(json.dumps(data, ensure_ascii=False, default=str))
        except Exception:
            closed = True

    async def receive_messages() -> None:
        nonlocal closed, disconnect_reason
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    envelope = json.loads(raw)
                    validate_client_envelope(envelope)
                except (ValueError, SecurityViolationError):
                    envelope = {}
                if isinstance(envelope, dict) and envelope.get("command") == "cancel_turn" and (not envelope.get("session_id") or envelope.get("session_id") == active_conversation) and active_task is not None and not active_task.done():
                    disconnect_reason = FinishReason.USER_CANCELLED
                    active_task.cancel()
                else:
                    await incoming.put(raw)
        except WebSocketDisconnect:
            closed = True
            if active_task is not None and not active_task.done():
                active_task.cancel()
        finally:
            try:
                incoming.put_nowait(None)
            except asyncio.QueueFull:
                pass

    reader = asyncio.create_task(receive_messages())
    try:
        while not closed:
            raw = await incoming.get()
            if raw is None:
                break
            user_message, session_id = await _normalize_message(raw, safe_send)
            if user_message is not None:
                session_id = session_id or "default"
                display_text, event_key = _message_projection(user_message)
                await state.conversations.ensure(owner.student_id, session_id)
                await state.conversations.append_message(
                    owner.student_id,
                    session_id,
                    role="student",
                    content=display_text,
                    event_key=f"student:{event_key}",
                )
                request = MathTutorRequest(
                    session_id=session_id,
                    user_message=user_message,
                    owner=owner,
                    conversation_messages=tuple(
                        await state.conversations.messages(owner.student_id, session_id)
                    ),
                )
                event_stream = MathTutorEventStream()
                turn = TutorTurnResult(turn_id=event_key, conversation_id=session_id)
                started = time.monotonic()

                async def _run() -> None:
                    token = None
                    turn_token = current_turn.set(turn)
                    try:
                        token = set_document_scope(await state.conversations.document_ids(owner.student_id, session_id))
                        await state.controller.run(request, event_stream)
                    except asyncio.CancelledError:
                        turn.stop(disconnect_reason, "\n\n".join(str(p["student_message"]) for p in pending_messages))
                    except Exception:
                        turn.stop(FinishReason.INTERNAL_ERROR, "\n\n".join(str(p["student_message"]) for p in pending_messages))
                    finally:
                        current_turn.reset(turn_token)
                        if token is not None:
                            reset_document_scope(token)
                        await event_stream.close()

                disconnect_reason = FinishReason.STREAM_INTERRUPTED
                pending_messages = []
                task = asyncio.create_task(_run())
                active_task = task
                active_conversation = session_id
                await safe_send(StudentPublicEvent(event_type="assistant_start", payload={"turn_id": event_key, "conversation_id": session_id}).wire_dict())
                async for event in event_stream.subscribe():
                    frame = _to_student_frame(event)
                    payload = frame.setdefault("payload", {})
                    payload.update({"turn_id": event_key, "conversation_id": session_id})
                    if frame.get("event_type") == "turn_error":
                        turn.stop(FinishReason.INTERNAL_ERROR, turn.final_text)
                    if frame.get("event_type") in {"tutor_action_committed", "tutor_message"} and payload.get("student_message"):
                        turn.final_text = str(payload["student_message"])
                        payload["message_id"] = f"{event_key}:{len(pending_messages)}"
                        payload.update({"turn_id": event_key, "conversation_id": session_id, "status": "STREAMING"})
                        pending_messages.append(dict(payload, cycle_state_version=frame.get("cycle_state_version", 0)))
                    await safe_send(frame)
                    if frame.get("event_type") in {"tutor_action_committed", "tutor_message"} and payload.get("student_message"):
                        await safe_send(StudentPublicEvent(event_type="assistant_delta", payload=payload).wire_dict())
                await task
                active_task = None
                turn.final_text = "\n\n".join(str(p["student_message"]) for p in pending_messages)
                if turn.partial and not turn.final_text:
                    turn.status = "FAILED"
                for payload in pending_messages:
                    await state.conversations.append_message(owner.student_id, session_id, role="tutor",
                        content=str(payload["student_message"]), action=str(payload.get("action") or ""),
                        assistance_level=int(payload.get("effective_assistance_level") or 0),
                        status=turn.status, finish_reason=turn.finish_reason.value, turn_id=event_key,
                        continuation_context=getattr(turn, "continuation_context", ""),
                        event_key=f"tutor:{event_key}:{payload['cycle_state_version']}:{payload.get('action', '')}")
                if not turn.final_text and turn.status != "COMPLETED":
                    await state.conversations.append_message(owner.student_id, session_id, role="tutor",
                        content="已停止生成。" if turn.status == "CANCELLED" else "这次回答未能生成，请重试。",
                        status=turn.status, finish_reason=turn.finish_reason.value, turn_id=event_key,
                        event_key=f"tutor:{event_key}:outcome")
                turn.latency_ms = int((time.monotonic() - started) * 1000)
                record_turn(turn)
                terminal = "assistant_complete" if turn.status == "COMPLETED" else "assistant_partial" if turn.partial else "assistant_error"
                await safe_send(StudentPublicEvent(event_type=terminal, payload=turn.wire()).wire_dict())
            # Turn-termination frame: the client reads events until it sees
            # this marker (the socket stays open for the next command).
            await safe_send(StudentPublicEvent(event_type="turn_end", payload={"conversation_id": session_id}).wire_dict())
    except WebSocketDisconnect:
        pass
    finally:
        reader.cancel()
        if active_task is not None and not active_task.done():
            active_task.cancel()
            await asyncio.gather(active_task, return_exceptions=True)
        await asyncio.gather(reader, return_exceptions=True)


async def _normalize_message(
    raw: str, safe_send: Any
) -> tuple[str | None, str]:
    """Parse + validate one WS frame; returns (user_message, session_id).

    A JSON object is validated against the envelope allowlist (§21/§23:
    identity, role, capability and tool keys are rejected); plain text enters
    the server-side Tutor intent router. Returns (None, "") when the
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


def _message_projection(user_message: str) -> tuple[str, str]:
    """Return safe visible text and a retry-stable event key."""
    try:
        envelope = json.loads(user_message)
    except (TypeError, json.JSONDecodeError):
        return user_message.strip(), str(uuid4())
    payload = envelope.get("payload") if isinstance(envelope, dict) else {}
    if not isinstance(payload, dict):
        payload = {}
    text = next((str(payload.get(key) or "").strip() for key in ("text", "answer") if str(payload.get(key) or "").strip()), "")
    command = str(envelope.get("command") or "")
    if not text:
        text = {
            "request_hint": "给我一点提示",
            "request_explanation": "讲解这个知识点",
            "request_example": "给我一个类似例子",
            "request_solution": "查看完整答案",
            "accept_practice_offer": "接受练习",
            "decline_practice_offer": "暂不练习",
        }.get(command, command or "继续")
    key = str(envelope.get("request_id") or envelope.get("idempotency_key") or uuid4())
    return text, key


__all__ = ["router"]
