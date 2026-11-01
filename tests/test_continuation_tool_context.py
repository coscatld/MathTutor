"""Continuation authority comes from the new host turn, never saved instructions."""
import json

import httpx
import pytest

from mathtutor.application.controller import MathTutorController
from mathtutor.application.tutor_runtime import current_turn
from mathtutor.domain.turn_result import TutorTurnResult
from mathtutor.api.product_state import get_product_state
from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
from mathtutor.infrastructure.tutor_chat import TutorChatResponder
from test_tutor_orchestration import _owner, _turn
from test_tutor_p0 import client_at, send


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_id,session_id", [("alice", "current-session"), ("bob", "other-session")])
async def test_partial_chat_uses_authenticated_request_scope_not_saved_context(owner_id, session_id):
    seen = []
    class Responder:
        async def respond(self, text, *, history=(), problem_context="", unstructured_math=False, execution_context=None,
                          response_request=None, authorization_request=None):
            seen.append((text, execution_context, response_request, authorization_request))
            return "接着说明这一点。"
    controller = MathTutorController(chat_responder=Responder())
    historical_request = "请创建 legacy.md 并写入旧内容"
    previous = {"role": "tutor", "content": "尚未结束，", "status": "PARTIAL", "action": "TUTOR_CHAT",
                "continuation_context": json.dumps({"kind": "chat", "response_request": historical_request,
                    "client_session_id": "untrusted-history-session", "request_id": "old-write-operation"})}
    turn = TutorTurnResult(turn_id="new-host-turn", conversation_id=session_id)
    token = current_turn.set(turn)
    try:
        await _turn(controller, session_id, "继续", owner=_owner(owner_id), history=(previous,))
    finally:
        current_turn.reset(token)
    assert seen
    text, context, semantic_request, authorization = seen[0]
    assert text == authorization == "继续" and semantic_request == historical_request
    assert context.owner_id == owner_id and context.conversation_id == session_id
    assert context.request_id == "new-host-turn"


@pytest.mark.parametrize("revoke", [False, True])
def test_real_partial_turn_rebinds_live_grants_without_restoring_write_intent(tmp_path, revoke):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "notes.md").write_text("READABLE_SENTINEL", encoding="utf-8")
    target = root / "continuation-target.md"
    requests, bound = [], []
    with client_at(tmp_path / "continuation.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        grant = state.workspace_grants.grant("local-admin", str(root.resolve()), writable=True)
        original_bind = state.extension_registry.bind
        def recording_bind(context, *, request_text=""):
            bound.append((context, request_text))
            return original_bind(context, request_text=request_text)
        state.extension_registry.bind = recording_bind
        index = 0
        def handler(request):
            nonlocal index
            body = json.loads(request.content)
            requests.append(body)
            index += 1
            if index == 1:
                message, finish = {"content": "这份说明还没有结束，"}, "length"
            elif index == 2:
                message, finish = {"content": "", "tool_calls": [
                    {"id": "forbidden-write", "type": "function", "function": {"name": "ext_workspace_write_text",
                        "arguments": json.dumps({"workspace_id": grant["workspace_id"], "relative_path": target.name, "content": "must not be written"})}},
                    {"id": "live-read", "type": "function", "function": {"name": "ext_workspace_read_text",
                        "arguments": json.dumps({"workspace_id": grant["workspace_id"], "relative_path": "notes.md"})}},
                ]}, "tool_calls"
            else:
                message, finish = {"content": "已收到本轮工具收据，没有执行写入。"}, "stop"
            return httpx.Response(200, json={"choices": [{"message": message, "finish_reason": finish}],
                                           "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        async def key(): return "fake-test-key"
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(base_url="https://offline.invalid/v1",
            model="continuation", api_key_resolver=key, transport=httpx.MockTransport(handler)))
        state.controller.chat_responder = TutorChatResponder(state.gateway, extension_registry=state.extension_registry)
        first = send(ws, "send_message", "host-first", {"text": "请创建 continuation-target.md，内容是对数学概念的解释。"}, session="trusted-session")
        assert any(frame["event_type"] == "assistant_partial" for frame in first)
        assert bound[0][0].conversation_id == "trusted-session" and bound[0][0].request_id == "host-first"
        assert not target.exists()
        if revoke:
            state.workspace_grants.revoke("local-admin", grant["workspace_id"])
        send(ws, "send_message", "host-continue", {"text": "继续"}, session="trusted-session")
        current = [(context, text) for context, text in bound if context.request_id == "host-continue"]
        assert current and all(context.owner_id == "local-admin" and context.conversation_id == "trusted-session" and text == "继续" for context, text in current)
        offered = {tool["function"]["name"] for tool in requests[1]["tools"]}
        assert "ext_workspace_write_text" not in offered
        assert ("ext_workspace_read_text" in offered) is not revoke
        receipts = {row["tool_call_id"]: json.loads(row["content"]) for row in requests[-1]["messages"] if row.get("role") == "tool"}
        assert receipts["forbidden-write"]["ok"] is False
        assert receipts["live-read"]["ok"] is not revoke
        assert not target.exists() and (root / "notes.md").read_text() == "READABLE_SENTINEL"
        assert len(requests) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("text,semantic,expected", [
    ("继续", "请创建 previous-write.md", "继续"),
    ("修复反馈：请新建 repair-created.md", "只读取 notes.md", "只读取 notes.md"),
])
async def test_responder_defaults_do_not_confuse_continuation_or_repair_with_authorization(text, semantic, expected):
    from types import SimpleNamespace
    from mathtutor.extensions import ExecutionContext
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    bound = []
    class Registry:
        def skill_instruction(self): return ""
        def bind(self, context, *, request_text):
            bound.append(request_text)
            return SimpleNamespace(definitions=lambda: [])
    class Gateway:
        def provider_for(self, _role): return SimpleNamespace(model="offline")
        async def complete(self, *_args, **_kwargs):
            return CompletionResult(text="本轮不会写入文件。", provider_id="offline", model="offline", finish_reason="stop")
    responder = TutorChatResponder(Gateway(), extension_registry=Registry())
    await responder.respond(text, response_request=semantic,
        execution_context=ExecutionContext(owner_id="alice", conversation_id="session", request_id="new-request"))
    assert bound == [expected]
