"""Directory grants and real file I/O through the creator SDK, without a model."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from mathtutor.extensions import ExecutionContext, ExtensionError
from mathtutor.extensions.builtin import default_registry
from mathtutor.extensions.workspaces import WorkspaceGrants
from mathtutor.api.product_state import get_product_state
from test_tutor_p0 import client_at, send
from test_creator_extensions import bind_gateway, tool_call, answer


ALICE = ExecutionContext(owner_id="alice", conversation_id="lesson")
BOB = ExecutionContext(owner_id="bob", conversation_id="lesson")


@pytest.fixture
def files(tmp_path):
    root = (tmp_path / "中文资料").resolve()
    root.mkdir()
    (root / "notes.md").write_text("# 函数\n先明确函数的定义域。", encoding="utf-8")
    grants = WorkspaceGrants()
    grant = grants.grant("alice", str(root), writable=True)
    registry = default_registry(grants)
    return root, grants, grant, registry


def names(executor):
    return [t["function"]["name"] for t in executor.definitions()]


@pytest.mark.asyncio
async def test_owner_explicit_grant_required_and_revocation_immediate(files):
    root, grants, grant, registry = files
    assert "ext_workspace_read_text" in names(registry.bind(ALICE))
    assert "ext_workspace_read_text" not in names(registry.bind(BOB))
    args = {"workspace_id": grant["workspace_id"], "relative_path": "notes.md"}
    assert not (await registry.bind(BOB).execute("ext_workspace_read_text", args))["ok"]
    executor = registry.bind(ALICE)
    assert "定义域" in (await executor.execute("ext_workspace_read_text", args))["result"]["text"]
    grants.revoke("alice", grant["workspace_id"])
    assert "ext_workspace_read_text" not in names(executor)
    assert not (await executor.execute("ext_workspace_read_text", args))["ok"]
    assert str(root) not in json.dumps(grant)


@pytest.mark.asyncio
@pytest.mark.parametrize("relative", ["../outside.txt", "/etc/passwd", "D:/secret.txt", "..\\outside.txt",
    "folder/../notes.md", ".env", ".private/notes.md", "bad.py", "bad.exe", "notes.md:stream.txt",
    "CON.txt", "PRN.md", "AUX.json", "NUL.txt", "COM1.txt", "LPT9.csv", "folder./notes.md"])
async def test_path_and_file_type_boundary(files, relative):
    root, grants, grant, registry = files
    receipt = await registry.bind(ALICE).execute("ext_workspace_read_text", {"workspace_id": grant["workspace_id"], "relative_path": relative})
    assert not receipt["ok"]
    assert str(root) not in json.dumps(receipt)


@pytest.mark.asyncio
async def test_symlink_files_directories_and_root_replacement_rejected(files, tmp_path):
    root, grants, grant, registry = files
    outside = (tmp_path / "outside").resolve()
    outside.mkdir()
    (outside / "secret.txt").write_text("private", encoding="utf-8")
    try:
        (root / "linked.txt").symlink_to(outside / "secret.txt")
        (root / "linked").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("OS account cannot create symlinks")
    for relative in ("linked.txt", "linked/secret.txt"):
        result = await registry.bind(ALICE).execute("ext_workspace_read_text", {"workspace_id": grant["workspace_id"], "relative_path": relative})
        assert not result["ok"] and "private" not in json.dumps(result)
    listing = await registry.bind(ALICE).execute("ext_workspace_list", {"workspace_id": grant["workspace_id"]})
    assert all(e["name"] not in {"linked", "linked.txt"} for e in listing["result"]["entries"])
    with pytest.raises(ExtensionError): grants.grant("alice", str(root / "linked"))
    root.rename(root.with_name("original"))
    root.mkdir()
    (root / "notes.md").write_text("replacement", encoding="utf-8")
    result = await registry.bind(ALICE).execute("ext_workspace_read_text", {"workspace_id": grant["workspace_id"], "relative_path": "notes.md"})
    assert not result["ok"]


@pytest.mark.asyncio
async def test_real_atomic_create_compare_hash_update_and_no_overwrite(files):
    root, grants, grant, registry = files
    args = {"workspace_id": grant["workspace_id"], "relative_path": "new.md", "content": "原始内容"}
    created = await registry.bind(ALICE, request_text="请保存 new.md 文件").execute("ext_workspace_write_text", args)
    assert created["ok"] and created["result"]["operation"] == "created"
    assert (root / "new.md").read_text(encoding="utf-8") == "原始内容"
    denied = await registry.bind(ALICE, request_text="请修改 new.md 文件").execute("ext_workspace_write_text", {**args, "content": "不能盲写"})
    assert not denied["ok"] and (root / "new.md").read_text(encoding="utf-8") == "原始内容"
    wrong = await registry.bind(ALICE, request_text="请修改 new.md 文件").execute("ext_workspace_write_text", {**args, "content": "错版本", "expected_hash": "0" * 64})
    assert not wrong["ok"]
    updated = await registry.bind(ALICE, request_text="请修改 new.md 文件").execute("ext_workspace_write_text", {**args, "content": "修改后的内容",
        "expected_hash": created["result"]["sha256"]})
    assert updated["ok"] and updated["result"]["operation"] == "updated"
    assert (root / "new.md").read_text(encoding="utf-8") == "修改后的内容"
    assert list(root.glob(".mathtutor-write-*")) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("request_text", ["", "写一份讲解", "write an explanation", "不要保存文件", "do not write a file",
    "Don’t create a file", "请勿保存文件", "禁止写入 files.txt", "只读取 notes.md，不要写入文件", "解释如何保存文件", "Explain how to save a file"])
async def test_writable_directory_alone_does_not_authorize_current_write(files, request_text):
    root, grants, grant, registry = files
    executor = registry.bind(ALICE, request_text=request_text)
    assert "ext_workspace_write_text" not in names(executor)
    assert "ext_workspace_read_text" in names(executor) and "ext_workspace_list" in names(executor)
    denied = await executor.execute("ext_workspace_write_text", {"workspace_id": grant["workspace_id"],
        "relative_path": "not-authorized.md", "content": "must not be written"})
    assert not denied["ok"] and not (root / "not-authorized.md").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("request_text", ["请保存到文件 result.md", "在授权目录新建 lesson.md", "保存这份笔记", "Save my notes to result.md", "Create a new Markdown file result.md"])
async def test_explicit_current_write_request_executes_real_handler(files, request_text):
    root, grants, grant, registry = files
    executor = registry.bind(ALICE, request_text=request_text)
    assert "ext_workspace_write_text" in names(executor)
    result = await executor.execute("ext_workspace_write_text", {"workspace_id": grant["workspace_id"],
        "relative_path": "result.md", "content": "explicitly authorized"})
    assert result["ok"] and (root / "result.md").read_text(encoding="utf-8") == "explicitly authorized"


@pytest.mark.asyncio
async def test_read_only_grants_paging_utf8_and_size_limits(files):
    root, grants, grant, registry = files
    readonly = grants.grant("bob", str(root))
    assert "ext_workspace_write_text" not in names(registry.bind(BOB))
    result = await registry.bind(BOB).execute("ext_workspace_write_text", {
        "workspace_id": readonly["workspace_id"], "relative_path": "new.txt", "content": "不可写"})
    assert not result["ok"] and not (root / "new.txt").exists()
    args = {"workspace_id": grant["workspace_id"], "relative_path": "notes.md", "start": 2, "limit": 3}
    read = (await registry.bind(ALICE).execute("ext_workspace_read_text", args))["result"]
    assert read["complete"] is False and read["next_start"] == 5
    assert read["sha256"] == hashlib.sha256((root / "notes.md").read_bytes()).hexdigest()
    (root / "large.txt").write_bytes(b"x" * 65537)
    (root / "binary.txt").write_bytes(b"\xff\xfe")
    for relative in ("large.txt", "binary.txt"):
        receipt = await registry.bind(ALICE).execute("ext_workspace_read_text", {"workspace_id": grant["workspace_id"], "relative_path": relative})
        assert not receipt["ok"]


def test_api_is_owner_scoped_read_only_catalog_and_explicit_grants(tmp_path):
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    with client_at(tmp_path / "creator-api.db") as client:
        before = client.get("/api/v2/math-tutor/desktop/creator/catalog").json()
        assert before["sdk"]["sandbox"] is False and before["sdk"]["user_installation"] is False
        assert not next(t for t in before["tools"] if t["name"] == "ext_workspace_read_text")["active"]
        endpoint = "/api/v2/math-tutor/desktop/creator/workspaces"
        assert client.post(endpoint, json={"path": str(root), "owner_id": "bob"}).status_code == 422
        response = client.post(endpoint, json={"path": str(root), "writable": False})
        assert response.status_code == 200
        grant = response.json()
        assert str(root) not in json.dumps(grant) and grant["expires"] == "process-restart"
        assert len(client.get(endpoint).json()["workspaces"]) == 1
        assert client.post(endpoint + "/pick").status_code == 409  # no Electron shell in this test
        assert client.post("/api/v2/math-tutor/desktop/creator/catalog", json={"code": "python"}).status_code == 405
        assert client.delete(endpoint + "/" + grant["workspace_id"]).json()["revoked"]
        assert client.get(endpoint).json()["workspaces"] == []
    with client_at(tmp_path / "creator-api.db") as client:
        assert client.get(endpoint).json()["workspaces"] == []


def test_creator_endpoints_require_existing_owner_authentication():
    from fastapi.testclient import TestClient
    from mathtutor.api.product_app import create_math_tutor_app
    from mathtutor.api.product_state import reset_product_state
    from mathtutor.security.settings import MathTutorSecuritySettings
    reset_product_state()
    try:
        app = create_math_tutor_app(MathTutorSecuritySettings(environment="development", host="127.0.0.1"),
                                    auth_enabled=True, auth_secret="fixture-test-secret-" * 4)
        with TestClient(app) as client:
            prefix = "/api/v2/math-tutor/desktop/creator"
            assert client.get(prefix + "/catalog").status_code == 401
            assert client.get(prefix + "/workspaces").status_code == 401
            assert client.post(prefix + "/workspaces", json={"path": "/a/local/path"}).status_code == 401
            assert client.delete(prefix + "/workspaces/unknown").status_code == 401
            assert client.post(prefix + "/workspaces/pick").status_code == 401
    finally:
        reset_product_state()


@pytest.mark.parametrize("origin", ["https://evil.example", "null", "http://localhost.evil.example", "file://", "broken["])
def test_cross_site_cannot_open_picker_grant_or_revoke(tmp_path, monkeypatch, origin):
    root = (tmp_path / "selected").resolve()
    root.mkdir()
    calls = []
    async def forbidden_post(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Cross-site request reached native picker")
    import httpx
    monkeypatch.setenv("MATHTUTOR_ELECTRON_PICKER_URL", "http://127.0.0.1:4444/native-pick")
    monkeypatch.setattr(httpx.AsyncClient, "post", forbidden_post)
    with client_at(tmp_path / "origin.db") as client:
        endpoint = "/api/v2/math-tutor/desktop/creator/workspaces"
        own = client.post(endpoint, json={"path": str(root)}, headers={"Origin": "http://127.0.0.1:3000"})
        assert own.status_code == 200
        workspace_id = own.json()["workspace_id"]
        headers = {"Origin": origin}
        assert client.post(endpoint + "/pick", headers=headers).status_code == 403
        assert client.post(endpoint, json={"path": str(root), "writable": True}, headers=headers).status_code == 403
        assert client.delete(endpoint + "/" + workspace_id, headers=headers).status_code == 403
        remaining = client.get(endpoint).json()["workspaces"]
        assert len(remaining) == 1 and remaining[0]["writable"] is False
    assert calls == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX pipe regression")
def test_named_pipe_cannot_block_the_application_event_loop(tmp_path):
    root = tmp_path.resolve()
    os.mkfifo(root / "pipe.txt")
    code = """
import asyncio, json, sys
from mathtutor.extensions import ExecutionContext
from mathtutor.extensions.builtin import default_registry
from mathtutor.extensions.workspaces import WorkspaceGrants
async def check():
    grants = WorkspaceGrants()
    grant = grants.grant('alice', json.load(sys.stdin)['root'])
    executor = default_registry(grants).bind(ExecutionContext(owner_id='alice', conversation_id='lesson'))
    receipt = await executor.execute('ext_workspace_read_text', {'workspace_id': grant['workspace_id'], 'relative_path': 'pipe.txt'})
    assert not receipt['ok']
    print(receipt['code'])
asyncio.run(check())
"""
    result = subprocess.run([sys.executable, "-c", code], input=json.dumps({"root": str(root)}),
                            capture_output=True, text=True, timeout=3, check=True)
    assert "REJECTED" in result.stdout


def test_real_ws_tool_read_and_write_use_authenticated_owner_and_receipts(tmp_path):
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    requests = []
    with client_at(tmp_path / "files-ws.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        grant = client.post("/api/v2/math-tutor/desktop/creator/workspaces", json={"path": str(root), "writable": True}).json()
        args = {"workspace_id": grant["workspace_id"], "relative_path": "lesson.md", "content": "# 学习笔记\n明确函数定义域。"}
        bind_gateway(get_product_state(), [tool_call("ext_workspace_write_text", args), answer("已保存为 lesson.md。"),
            tool_call("ext_workspace_read_text", {"workspace_id": grant["workspace_id"], "relative_path": "lesson.md"}),
            answer("笔记提醒你先明确函数的定义域。")], requests)
        send(ws, "send_message", "save-lesson", {"text": "请在我授权的目录保存一份 lesson.md 学习笔记"})
        tool = next(t["function"] for t in requests[0]["tools"] if t["function"]["name"] == "ext_workspace_write_text")
        assert grant["workspace_id"] in tool["description"] and grant["name"] in tool["description"]
        assert (root / "lesson.md").read_text(encoding="utf-8") == args["content"]
        send(ws, "send_message", "read-lesson", {"text": "读一下刚才保存的 lesson.md"})
        receipt = next(json.loads(m["content"]) for m in requests[-1]["messages"] if m["role"] == "tool")
        assert "定义域" in receipt["result"]["text"] and receipt["authority"] == "reference_only"
        assert str(root) not in json.dumps(requests, ensure_ascii=False)


def test_actual_file_task_discovers_grant_then_lists_reads_writes_and_answers(tmp_path):
    import httpx
    from mathtutor.infrastructure.generative_gateway import ModelRole, OpenAICompatibleProvider
    root = (tmp_path / "创作目录").resolve()
    root.mkdir()
    original = "# 学习记录\n今天练习了分类整理。"
    (root / "source.md").write_text(original, encoding="utf-8")
    requests, discovered = [], {}

    def transport(request):
        payload = json.loads(request.content)
        phase = len(requests)
        requests.append(payload)
        if phase == 0:
            descriptor = next(t["function"] for t in payload["tools"] if t["function"]["name"] == "ext_workspace_list")
            description = descriptor["description"]
            hint = json.loads(description[description.index('{"workspaces"'):])
            workspace = next(g for g in hint["workspaces"] if g["writable"])
            discovered.update(workspace)
            reply = tool_call("ext_workspace_list", {"workspace_id": workspace["workspace_id"]})
        else:
            receipts = [json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool"]
            assert receipts[-1]["ok"], receipts[-1]
            actual = receipts[-1]["result"]
            if phase == 1:
                filename = next(row["name"] for row in actual["entries"] if row["kind"] == "file" and row["name"].endswith(".md"))
                reply = tool_call("ext_workspace_read_text", {"workspace_id": discovered["workspace_id"], "relative_path": filename})
            elif phase == 2:
                reply = tool_call("ext_workspace_write_text", {"workspace_id": discovered["workspace_id"],
                    "relative_path": "summary.md", "content": "整理记录\n" + actual["text"]})
            else:
                assert phase == 3 and actual["written"] is True
                assert not payload.get("tools"), "the final step cannot dispatch more tools"
                reply = answer("已将读取的内容整理保存为 summary.md。")
        return httpx.Response(200, json=reply)

    async def key(): return "fixture-not-a-real-key"
    with client_at(tmp_path / "multi-files.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        grant = client.post("/api/v2/math-tutor/desktop/creator/workspaces", json={"path": str(root), "writable": True}).json()
        state = get_product_state()
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(base_url="https://fixture.invalid/v1",
            model="scripted", api_key_resolver=key, transport=httpx.MockTransport(transport)))
        frames = send(ws, "send_message", "multi-file-task", {"text": "请列出我授权目录中的文件，读取里面的 Markdown，把内容整理保存为 summary.md。"})
        assert discovered["workspace_id"] == grant["workspace_id"] and discovered["name"] == grant["name"]
        assert len(requests) == 4 and (root / "summary.md").read_text(encoding="utf-8") == "整理记录\n" + original
        assert any("整理保存" in f.get("payload", {}).get("student_message", "") for f in frames)
        trace = client.get("/api/v2/math-tutor/desktop/diagnostics/turns").json()["turns"][0]
        assert trace["steps_used"] == 4 and trace["details"]["tools"]["creator_extension"] == 3
        assert str(root) not in json.dumps(requests, ensure_ascii=False)


@pytest.mark.asyncio
async def test_file_task_policy_requires_current_request_and_owner_grant(files):
    from mathtutor.application.tutor_runtime import current_turn, complete_math_tools
    from mathtutor.domain.turn_result import TutorTurnResult
    from mathtutor.infrastructure.generative_gateway import CompletionResult
    root, grants, grant, registry = files
    class Provider:
        async def complete(self, messages, **kwargs):
            return CompletionResult(text="完成。", finish_reason="stop", provider_id="fixture", model="stub",
                                    input_tokens=10, output_tokens=10)
    for context, request, verify, expected in ((ALICE, "你好", None, 2), (ALICE, "不要读取文件", None, 2),
        (BOB, "读取目录中的文件", None, 2),
        (ALICE, "读取目录中的文件", None, 4), (ALICE, "读取目录中的文件", object(), 6)):
        turn = TutorTurnResult()
        token = current_turn.set(turn)
        try:
            await complete_math_tools(Provider(), [{"role": "user", "content": request}], verify=verify,
                                      extension_executor=registry.bind(context, request_text=request))
            assert turn.max_steps == expected
        finally:
            current_turn.reset(token)


@pytest.mark.asyncio
async def test_same_turn_fresh_responder_binding_cannot_execute_fourth_file_call(files, monkeypatch):
    """Repairs re-bind the SDK, but cannot reset the turn's file authority."""
    import httpx
    from mathtutor.application.tutor_runtime import current_turn
    from mathtutor.domain.turn_result import TutorTurnResult
    from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole, OpenAICompatibleProvider
    from mathtutor.infrastructure.secret_store import InMemorySecretStore
    from mathtutor.infrastructure.tutor_chat import TutorChatResponder
    root, grants, grant, registry = files
    requests, bindings, receipts = [], [], []
    original_bind = registry.bind

    def bind(context, **kwargs):
        executor = original_bind(context, **kwargs)
        bindings.append(executor)
        return executor
    monkeypatch.setattr(registry, "bind", bind)

    def transport(request):
        payload = json.loads(request.content)
        phase = len(requests)
        requests.append(payload)
        if phase in {0, 2}:
            descriptor = next(t["function"] for t in payload["tools"] if t["function"]["name"] == "ext_workspace_write_text")
            description = descriptor["description"]
            public = json.loads(description[description.index('{"workspaces"'):])["workspaces"][0]
            calls = []
            for number in ((1, 2, 3) if phase == 0 else (4,)):
                calls.append({"id": f"save-{number}", "type": "function", "function": {
                    "name": "ext_workspace_write_text", "arguments": json.dumps({"workspace_id": public["workspace_id"],
                        "relative_path": f"saved-{number}.md", "content": f"record {number}"})}})
            result = {"choices": [{"message": {"content": "", "tool_calls": calls}, "finish_reason": "tool_calls"}],
                      "usage": {"prompt_tokens": 100, "completion_tokens": 30}}
        else:
            receipts.extend(json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool")
            result = answer("前三份已保存。" if phase == 1 else "第四次写入被本轮次数上限拒绝。")
        return httpx.Response(200, json=result)

    async def key(): return "fixture-not-a-real-key"
    gateway = GenerativeModelGateway(InMemorySecretStore())
    gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(base_url="https://fixture.invalid/v1",
        model="scripted", api_key_resolver=key, transport=httpx.MockTransport(transport)))
    responder = TutorChatResponder(gateway, extension_registry=registry)
    turn = TutorTurnResult()
    token = current_turn.set(turn)
    try:
        await responder.respond("请在授权目录保存前三份 Markdown 文件。", execution_context=ALICE)
        assert turn.workspace_calls_used == 3
        await responder.respond("请在授权目录再保存第四份 Markdown 文件。", execution_context=ALICE)
    finally:
        current_turn.reset(token)
    assert len(bindings) == 2 and bindings[0] is not bindings[1]
    assert len(requests) == 4 and sum(receipt["ok"] for receipt in receipts) == 3
    assert receipts[-1]["code"] == "EXTENSION_CALL_LIMIT"
    for number in (1, 2, 3):
        assert (root / f"saved-{number}.md").read_text(encoding="utf-8") == f"record {number}"
    assert not (root / "saved-4.md").exists(), "the rejected fourth handler must not run"


@pytest.mark.asyncio
async def test_repair_feedback_cannot_promote_original_read_request_to_write(files):
    import httpx
    from mathtutor.application.tutor_runtime import current_turn
    from mathtutor.domain.turn_result import TutorTurnResult
    from mathtutor.infrastructure.generative_gateway import GenerativeModelGateway, ModelRole, OpenAICompatibleProvider
    from mathtutor.infrastructure.secret_store import InMemorySecretStore
    from mathtutor.infrastructure.tutor_chat import TutorChatResponder
    root, grants, grant, registry = files
    requests = []
    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            assert all(t["function"]["name"] != "ext_workspace_write_text" for t in payload["tools"])
            description = next(t["function"]["description"] for t in payload["tools"] if t["function"]["name"] == "ext_workspace_read_text")
            workspace_id = json.loads(description[description.index('{"workspaces"'):])["workspaces"][0]["workspace_id"]
            reply = tool_call("ext_workspace_write_text", {"workspace_id": workspace_id, "relative_path": "repair-created.md", "content": "forbidden"})
        else:
            receipt = next(json.loads(m["content"]) for m in payload["messages"] if m["role"] == "tool")
            assert receipt["ok"] is False
            reply = answer("只读取已有资料，不保存文件。")
        return httpx.Response(200, json=reply)
    async def key(): return "fixture-not-a-real-key"
    gateway = GenerativeModelGateway(InMemorySecretStore())
    gateway.register_provider(ModelRole.TUTOR_WRITER, OpenAICompatibleProvider(base_url="https://fixture.invalid/v1",
        model="scripted", api_key_resolver=key, transport=httpx.MockTransport(transport)))
    token = current_turn.set(TutorTurnResult())
    try:
        await TutorChatResponder(gateway, extension_registry=registry).respond(
            "修复反馈：请在目录新建并保存 repair-created.md 文件。", response_request="读取已有 notes.md 内容并解释，不要保存文件。",
            execution_context=ALICE)
    finally:
        current_turn.reset(token)
    assert len(requests) == 2 and not (root / "repair-created.md").exists()
