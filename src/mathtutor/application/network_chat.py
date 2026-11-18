import json
from dataclasses import replace

from mathtutor.application.state_machine import CycleState
from mathtutor.application.student_contract import REVIEW_STATES
from mathtutor.application.tutor_runtime import current_turn
from mathtutor.application.exploration_evidence import text_hash
from mathtutor.application.network_qa import POLICY


def merge_continuation_context(turn, values):
    try:
        context = json.loads(getattr(turn, "continuation_context", "") or "{}")
    except (TypeError, ValueError):
        context = {}
    if not isinstance(context, dict):
        context = {}
    context.update(values)
    turn.continuation_context = json.dumps(context, ensure_ascii=False)


class NetworkFallbackSink:
    def __init__(self, stream, notice):
        self.stream, self.notice = stream, notice

    def _text(self, text, metadata):
        if self.notice and (metadata or {}).get("event_type") in {"tutor_message", "tutor_action_committed"}:
            text = f"{text}\n\n{self.notice}"
            self.notice = ""
        return text

    async def emit(self, event):
        await self.stream.emit(replace(event, content=self._text(event.content, event.metadata)))

    async def content(self, text, source="", stage="", metadata=None):
        await self.stream.content(self._text(text, metadata), source=source, stage=stage, metadata=metadata)

    async def error(self, message, source="", metadata=None):
        await self.stream.error(message, source=source, metadata=metadata)


async def network_reply(controller, request, session, payload):
    service = getattr(controller, "network_qa", None)
    if service is None or payload.get("network_search") is not True:
        return None
    if session and session.state not in REVIEW_STATES and session.state != CycleState.CLOSED:
        return None
    knowledge = getattr(controller, "knowledge", None)
    if knowledge and (await knowledge.configuration(request.owner.student_id, request.session_id)).get("hints_only"):
        return None
    reply = await service.maybe_respond(request.owner.student_id, text=str(payload.get("text", "")),
        history=request.conversation_messages, language=payload.get("reply_language", "zh"), enabled=True,
        prior_question=payload.get("network_context", ""), allow_verified_examples=True)
    if reply is not None and (reply.sources or reply.audit or reply.planner_receipt or reply.calculation_receipts):
        turn = current_turn.get()
        if turn is not None:
            merge_continuation_context(turn, {"network_evidence": {
                "policy": POLICY, "query": reply.query, "status": reply.status,
                "sources": reply.sources, "claims": reply.audit, "planner": reply.planner_receipt,
                "calculations": reply.calculation_receipts,
                "network_text": reply.text, "network_text_sha256": text_hash(reply.text)}})
    return reply
