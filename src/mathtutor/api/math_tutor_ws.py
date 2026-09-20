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
import anyio
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
from mathtutor.application.controller import LEGACY_COMMAND_ALIASES
from mathtutor.application.message_projection import project_turn_error
from mathtutor.domain.hashing import content_hash
from mathtutor.repositories.conversation_repository import message_id_for
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
            payload={"error": project_turn_error(event.content), "error_code": metadata.get("error_code", "REQUEST_FAILED")},
        ).wire_dict()
    if event.type == "content":
        return StudentPublicEvent(
            event_type=str(metadata.get("event_type") or "tutor_action_committed"),
            cycle_id=str(metadata.get("cycle_id") or ""),
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

    def set_active(task, conversation_id):
        nonlocal active_task, active_conversation
        active_task, active_conversation = task, conversation_id

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
                    if (isinstance(envelope, dict) and envelope.get("type") == "delivery_presented"
                            and set(envelope) == {"type", "delivery_id"}
                            and isinstance(envelope["delivery_id"], str) and len(envelope["delivery_id"]) <= 160):
                        await state.controller.mark_delivery(owner.student_id, envelope["delivery_id"], "presented")
                        continue
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
                disconnect_reason = FinishReason.STREAM_INTERRUPTED
                await _process_request(state, owner, session_id, user_message, event_key,
                                       display_text, safe_send, set_active,
                                       lambda: disconnect_reason)
            # Turn-termination frame: the client reads events until it sees
            # this marker (the socket stays open for the next command).
            await safe_send(StudentPublicEvent(event_type="turn_end", payload={"conversation_id": session_id}).wire_dict())
    except WebSocketDisconnect:
        pass
    finally:
        with anyio.fail_after(5, shield=True):
            owned = {reader}
            if active_task is not None:
                owned.add(active_task)
            for task in owned:
                if not task.done():
                    task.cancel()
            results = await asyncio.gather(*owned, return_exceptions=True)
            from mathtutor.infrastructure.lifecycle_trace import trace
            for task, result in zip(owned, results):
                trace(id(state), "websocket_task_joined", owned_task=id(task),
                      error=result if isinstance(result, BaseException) else None)
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result


def _canonical_envelope(user_message: str) -> dict:
    try:
        envelope = json.loads(user_message)
    except ValueError:
        envelope = {"command": "send_message", "payload": {"text": user_message}}
    if not isinstance(envelope, dict):
        envelope = {"command": "send_message", "payload": {"text": user_message}}
    if envelope.get("protocol_version", 1) == 1:
        envelope["command"] = LEGACY_COMMAND_ALIASES.get(envelope.get("command"), envelope.get("command", "send_message"))
    return envelope


async def _process_request(state, owner, session_id, user_message, event_key,
                           display_text, send, set_active, cancellation_reason):
    """One serialized request, with durable approved-result replay."""
    journal = state.turn_requests
    key = (owner.student_id, session_id, event_key)
    envelope = _canonical_envelope(user_message)
    attachments = []
    ids = (envelope.get("payload") or {}).get("attachment_ids")
    if ids:
        from mathtutor.repositories.image_repository import public_image
        from mathtutor.infrastructure.generative_gateway import ModelRole
        from mathtutor.infrastructure.vision import supports_vision, VISION_UNSUPPORTED
        try:
            if envelope.get("command") != "send_message":
                raise ValueError("图片只能作为聊天消息附件发送")
            rows = await state.images.resolve(owner.student_id, ids)
            if not await supports_vision(state.gateway.provider_for(ModelRole.TUTOR_WRITER)):
                raise ValueError(VISION_UNSUPPORTED)
            attachments = [public_image(row) for row in rows]
        except ValueError as exc:
            await send(StudentPublicEvent(event_type="assistant_error", payload={
                "turn_id": event_key, "conversation_id": session_id,
                "status": "FAILED", "error": str(exc), "error_code": "IMAGE_INPUT_REJECTED",
            }).wire_dict())
            return
    fingerprint = content_hash({k: v for k, v in envelope.items()
                                if k not in {"request_id", "idempotency_key"}})
    async with journal.conversation(owner.student_id, session_id):
        conversation = await state.conversations.get(owner.student_id, session_id)
        if conversation and (conversation.get("trashed_at") or conversation.get("purged_at")):
            await send(StudentPublicEvent(event_type="assistant_error", payload={
                "turn_id": event_key, "conversation_id": session_id,
                "status": "FAILED", "error_code": "CONVERSATION_DELETED",
                "error": "对话已移入垃圾桶或已删除，请先恢复或新建对话。",
            }).wire_dict())
            return
        await state.conversations.ensure(owner.student_id, session_id)
        created, stored = await journal.claim(*key, fingerprint)
        recovery = None
        if not created:
            if stored["payload_hash"] != fingerprint:
                await send(StudentPublicEvent(event_type="assistant_error", payload={
                    "turn_id": f"{event_key}:conflict", "conversation_id": session_id,
                    "status": "FAILED", "error_code": "REQUEST_ID_CONFLICT",
                    "error": "同一个请求标识对应了不同内容，请重新发送。",
                }).wire_dict())
                return
            failed_or_interrupted = stored["status"] != "FINISHED" or any(
                frame["event_type"] in {"assistant_error", "assistant_partial"} for frame in stored["frames"])
            if failed_or_interrupted:
                cycle = await state.store.load(owner.student_id, session_id)
                context = await state.store.teaching.load(owner.student_id, cycle.cycle.cycle_id) if cycle else None
                checkpoint = (context or {}).get("pending_expression", {})
                if (checkpoint.get("request_id") == event_key and checkpoint.get("phase") != "done"
                        and checkpoint.get("cycle_version") == cycle.version
                        and checkpoint.get("command") in {"request_hint", "request_explanation", "request_example", "request_solution"}):
                    recovery = checkpoint
        image_retry = bool(attachments and not created and stored["status"] == "FINISHED"
            and any(f["event_type"] == "assistant_error" for f in stored["frames"])
            and not any(f["event_type"] == "assistant_delta" for f in stored["frames"]))
        if not created and recovery is None and not image_retry:
            frames = stored["frames"]
            if stored["status"] != "FINISHED":
                # A previous process stopped after claim. Do not replay effects.
                snapshots = [f["payload"].get("student_message", "") for f in frames if f["event_type"] == "assistant_delta"]
                text = snapshots[-1] if snapshots else ""
                # The approved history snapshot is written before its frame.
                # A crash in that gap must not discard already saved content.
                messages = await state.conversations.messages(owner.student_id, session_id)
                saved = next((m for m in reversed(messages) if m.get("turn_id") == event_key and m["role"] == "tutor"), None)
                if saved and saved["content"] != text:
                    text = saved["content"]
                    frames = [*frames, StudentPublicEvent(event_type="assistant_delta", payload={
                        "turn_id": event_key, "conversation_id": session_id,
                        "message_id": saved["message_id"], "student_message": text,
                        "content_mode": "snapshot", "action": saved["action"],
                        "effective_assistance_level": saved["assistance_level"],
                    }).wire_dict()]
                recovered = TutorTurnResult(turn_id=event_key, conversation_id=session_id)
                recovered.stop(FinishReason.STREAM_INTERRUPTED, text)
                if not text:
                    await state.conversations.save_turn_message(*key, role="error",
                        content="上次处理已中断；已保存的作答不会重复提交，请重新同步题目状态。",
                        status="FAILED", finish_reason=recovered.finish_reason.value)
                await state.conversations.finalize_turn(*key, status=recovered.status, finish_reason=recovered.finish_reason.value)
                frames = [*frames, StudentPublicEvent(
                    event_type="assistant_partial" if text else "assistant_error",
                    payload={**recovered.wire(), "error_code": "REQUEST_INTERRUPTED",
                             "error": "上次处理已中断；已保存的作答不会重复提交，请重新同步题目状态。"},
                ).wire_dict()]
                await journal.record(*key, frames, finished=True)
            for frame in frames:
                await send(frame)
            return

        frames = []

        async def publish(frame, *, finished=False):
            frames.append(frame)
            await journal.record(*key, frames, finished=finished)
            await send(frame)

        if not recovery:
            await state.conversations.append_message(owner.student_id, session_id,
                role="student", content=display_text, event_key=f"student:{event_key}", attachments=attachments)
        # Evidence keys are globally unique; a client key is only conversation-local.
        envelope["idempotency_key"] = content_hash({"owner": key[0], "conversation": key[1], "request": key[2]})
        request = MathTutorRequest(session_id=session_id,
            user_message=json.dumps(envelope, ensure_ascii=False), owner=owner,
            conversation_messages=tuple(await state.conversations.messages(owner.student_id, session_id)))
        stream = MathTutorEventStream()
        turn = TutorTurnResult(turn_id=event_key, conversation_id=session_id)
        started = time.monotonic()
        texts = [recovery["feedback"]] if recovery and recovery.get("feedback") else []
        error_text = ""
        display_action = ""
        display_level = 0

        async def run():
            token = None
            turn_token = current_turn.set(turn)
            try:
                if getattr(state, "knowledge", None):
                    document_ids = await state.knowledge.scope(owner.student_id, session_id)
                else:
                    document_ids = await state.conversations.document_ids(owner.student_id, session_id)
                    document_ids += [d.document_id for d in await state.documents.list_documents(owner.student_id) if d.is_global]
                token = set_document_scope(list(dict.fromkeys(document_ids)))
                if recovery:
                    await state.controller.recover_expression(request, recovery, stream)
                else:
                    await state.controller.run(request, stream)
            except asyncio.CancelledError:
                turn.stop(cancellation_reason(), "\n\n".join(texts) or getattr(turn, "knowledge_receipt_text", ""))
            except Exception:
                logger.exception("Tutor request failed conversation_id=%s", session_id)
                turn.stop(FinishReason.INTERNAL_ERROR, "\n\n".join(texts))
            finally:
                current_turn.reset(turn_token)
                if token is not None:
                    reset_document_scope(token)
                await stream.close()

        task = asyncio.create_task(run())
        set_active(task, session_id)
        try:
            await publish(StudentPublicEvent(event_type="assistant_start", payload={"turn_id": event_key, "conversation_id": session_id}).wire_dict())
            async for event in stream.subscribe():
                frame = _to_student_frame(event)
                payload = frame["payload"]
                payload.update(turn_id=event_key, conversation_id=session_id)
                is_content = frame["event_type"] in {"tutor_action_committed", "tutor_message"} and payload.get("student_message")
                if frame["event_type"] == "turn_error":
                    if error_text:
                        continue
                    error_text = payload["error"]
                    turn.stop(FinishReason.INTERNAL_ERROR, "\n\n".join(texts))
                    payload["message_id"] = message_id_for(owner.student_id, session_id, f"tutor:{event_key}:result")
                    await state.conversations.save_turn_message(*key,
                        role="tutor" if texts else "error", content="\n\n".join([*texts, error_text]),
                        status="FAILED", finish_reason=turn.finish_reason.value)
                if is_content:
                    unique = f"tutor:{event_key}:result"
                    payload.update(message_id=message_id_for(owner.student_id, session_id, unique),
                                   status="STREAMING", content_mode="snapshot")
                    texts.append(payload["student_message"])
                    payload["student_message"] = "\n\n".join(texts)
                    level = payload.get("effective_assistance_level", 0)
                    if not display_action or level > display_level:
                        display_action, display_level = payload.get("action", ""), level
                    # Store approved content before sending; wire and history IDs agree.
                    await state.conversations.save_turn_message(*key,
                        role="tutor", content=payload["student_message"], action=display_action,
                        assistance_level=display_level,
                        status="STREAMING",
                        continuation_context=getattr(turn, "continuation_context", ""))
                await publish(frame)
                if is_content:
                    await publish(StudentPublicEvent(event_type="assistant_delta", payload={
                        **payload, "action": display_action, "effective_assistance_level": display_level,
                    }).wire_dict())
            await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            set_active(None, session_id)
        knowledge_receipt = getattr(turn, "knowledge_receipt_text", "")
        if not texts and knowledge_receipt:
            # Only the runtime's fixed, application-generated save/draft receipt
            # survives here; no unfinished model prose is ever published.
            texts.append(knowledge_receipt)
            await state.conversations.save_turn_message(*key, role="tutor", content=knowledge_receipt,
                status=turn.status, finish_reason=turn.finish_reason.value)
        turn.final_text = "\n\n".join(texts)
        if error_text:
            turn.stop(FinishReason.INTERNAL_ERROR, turn.final_text)
            turn.final_text = "\n\n".join([*texts, error_text])
        if turn.partial and not turn.final_text:
            turn.status = "FAILED"
        await state.conversations.finalize_turn(*key, status=turn.status, finish_reason=turn.finish_reason.value)
        if not texts and not error_text and turn.status != "COMPLETED":
            error_text = "已停止生成。" if turn.status == "CANCELLED" else "这次回答未能生成，请重新同步后再试。"
            await state.conversations.save_turn_message(*key,
                role="error", content=error_text, status=turn.status,
                finish_reason=turn.finish_reason.value)
        turn.latency_ms = int((time.monotonic() - started) * 1000)
        record_turn(turn)
        terminal = "assistant_complete" if turn.status == "COMPLETED" else "assistant_partial" if turn.partial else "assistant_error"
        from mathtutor.application.student_contract import session_contract
        contract = await session_contract(state.store, owner.student_id, await state.store.load(owner.student_id, session_id))
        await publish(StudentPublicEvent(event_type=terminal,
            cycle_id=contract["cycle_id"], cycle_state=contract["state"], cycle_state_version=contract["state_version"],
            problem_revision=contract["problem_revision"], allowed_actions=contract["allowed_actions"],
            allowed_next_inputs=contract["allowed_next_inputs"],
            **{key: contract[key] for key in ("teaching_plan", "problem_context", "evidence_summary", "active_offer", "diagnosis")},
            delivery_id=json.loads(getattr(turn, "continuation_context", "") or "{}").get("delivery_id"),
            payload={**turn.wire(), "error": error_text, "effective_assistance_level": contract["effective_assistance_level"]},
        ).wire_dict(), finished=True)
        if turn.status == "COMPLETED":
            active = await state.store.load(owner.student_id, session_id)
            context = await state.store.teaching.load(owner.student_id, active.cycle.cycle_id) if active else None
            if context and context.get("pending_expression", {}).get("request_id") == event_key:
                context["pending_expression"]["phase"] = "done"
                await state.store.teaching.save(owner.student_id, active.cycle.cycle_id, context)


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
    if not isinstance(envelope, dict):
        return user_message.strip(), str(uuid4())
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    text = next((str(payload.get(key) or "").strip() for key in ("text", "answer") if str(payload.get(key) or "").strip()), "")
    command = str(envelope.get("command") or "")
    if command == "submit_attempt" and payload.get("choice_id") in {"A", "B", "C", "D"}:
        text = f"选择 {payload['choice_id']}"
    if envelope.get("protocol_version", 1) == 1:
        command = LEGACY_COMMAND_ALIASES.get(command, command)
    if not text and not payload.get("attachment_ids"):
        from mathtutor.application.message_projection import command_message_label
        text = command_message_label(command)
    key = str(envelope.get("request_id") or envelope.get("idempotency_key") or uuid4())
    return text, key


__all__ = ["router"]
