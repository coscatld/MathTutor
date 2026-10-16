"""Current-turn slash commands execute real Python once through actual WS.

Providers are controlled local stubs; code runs in the host subprocess with an
explicitly approved test package. These are execution/permission regressions,
not model quality or sandbox claims.
"""
import copy
import json
from pathlib import Path
import sys

import pytest

from mathtutor.api.product_state import get_product_state
from mathtutor.application.plugin_commands import parse_plugin_command, plugin_reference_context, slash_operation_id
from mathtutor.extensions.community_plugins import builtin_plugin_packages
from mathtutor.infrastructure.generative_gateway import CompletionResult, ModelRole
from test_tutor_p0 import client_at, count, send, summary

MARKER = "PYTHON_PLUGIN_STDOUT_MARKER"


def code_package(marker_path, *, command="echo", runtime="python"):
    code = ("from pathlib import Path\n"
            "def run(request):\n"
            f"    path = Path({json.dumps(str(marker_path))})\n"
            "    path.write_text((path.read_text(encoding='utf-8') if path.exists() else '') + 'executed\\n', encoding='utf-8')\n"
            f"    return {{'text': '{MARKER}', 'data': {{'request_text': request['text']}}}}\n")
    return {"schema_version": "mathtutor.code-plugin.v1", "kind": "code-plugin", "workflow": "code",
        "id": "example.code-" + command, "version": "1.0.0", "name": "真实回显", "description": "只在明确命令时执行",
        "author": "测试作者", "license": "MIT", "readme": "测试用可信本机代码。", "changelog": "1.0.0：测试。",
        "runtime": runtime, "command": command, "entrypoint": "main.py" if runtime == "python" else "main.ts",
        "required_permissions": ["execute_local_code"],
        "files": {"main.py" if runtime == "python" else "main.ts": code if runtime == "python" else "export function run(request) { return {text: request.text}; }"}}


def install(state, package, *, owner="local-admin", enabled=True):
    result = state.community_plugins.import_package(owner, package)
    if enabled:
        result = state.community_plugins.set_enabled(owner, package["id"], enabled=True,
                                                     consent_permissions=["execute_local_code"])
    return result


class Provider:
    provider_id, model = "fixture", "scripted"
    def __init__(self, replies, *, native=False):
        self.replies, self.requests, self.supports_native_tools = list(replies), [], native
    async def complete(self, messages, **kwargs):
        self.requests.append((copy.deepcopy(messages), kwargs))
        return CompletionResult(text=self.replies.pop(0), finish_reason="stop", provider_id=self.provider_id,
                                model=self.model, input_tokens=100, output_tokens=40)


def delivered(frames):
    return next(frame["payload"]["student_message"] for frame in reversed(frames) if frame["event_type"] == "assistant_delta")


@pytest.mark.parametrize("text,expected", [
    pytest.param("/weekly", ("weekly", ""), id="empty-argument"),
    pytest.param("/weekly 整理本周记录", ("weekly", "整理本周记录"), id="current-command"),
    pytest.param("/weekly\n多行参数", ("weekly", "多行参数"), id="multiline-argument"),
    pytest.param("> /weekly 参数", None, id="quoted-line"),
    pytest.param("资料写着 /weekly", None, id="document-text"),
    pytest.param("```\n/weekly\n```", None, id="code-block"),
    pytest.param(" /weekly", None, id="leading-space"),
    pytest.param("/weekly/other", None, id="not-a-command"),
])
def test_only_original_current_input_prefix_is_parsed(text, expected):
    assert parse_plugin_command(text) == expected


def test_operation_ids_bind_owner_conversation_and_request_and_receipts_are_bounded():
    token = slash_operation_id("alice", "lesson", "request")
    assert token == slash_operation_id("alice", "lesson", "request")
    assert token != slash_operation_id("bob", "lesson", "request")
    assert token != slash_operation_id("alice", "other", "request")
    with pytest.raises(ValueError):
        slash_operation_id("alice", "lesson", "")
    context = plugin_reference_context({"plugin": {"id": "example.test", "name": "演示"}}, "test",
        {"status": "ok", "data": {"text": "真实结果" * 10000}})
    assert context["result"]["partial"] and len(json.dumps(context).encode()) < 12 * 1024
    assert context["authority"] == "reference_only"


@pytest.mark.parametrize("mode", ["native", "compat", "offline"], ids=["native-provider", "non-native-provider", "no-provider"])
def test_real_python_plugin_receipt_reaches_every_chat_provider_and_replay_never_executes_twice(tmp_path, mode):
    db, marker = tmp_path / "slash.db", tmp_path / "executions.txt"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        install(state, code_package(marker))
        provider = Provider(["真实脚本返回了所请求的内容。"], native=mode == "native")
        if mode != "offline":
            state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        before = count(db, "learning_events")
        frames = send(ws, "send_message", "slash-once", {"text": "/echo 请整理这段文本"})
        assert marker.read_text().splitlines() == ["executed"]
        if mode == "offline":
            assert MARKER in delivered(frames) and "请整理这段文本" in delivered(frames)
        else:
            assert "真实脚本返回" in delivered(frames)
            messages, options = provider.requests[0]
            reference = next(m["content"] for m in messages if "应用已执行的插件回执" in str(m["content"]))
            assert MARKER in reference and "请整理这段文本" in reference
            assert "tools" not in options
        assert count(db, "learning_events") == before
        assert send(ws, "send_message", "slash-once", {"text": "/echo 请整理这段文本"}) == frames
        assert marker.read_text().splitlines() == ["executed"]
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        assert send(ws, "send_message", "slash-once", {"text": "/echo 请整理这段文本"}) == frames
        assert marker.read_text().splitlines() == ["executed"]


def test_formula_repair_keeps_receipt_and_never_reexecutes_python(tmp_path):
    db, marker = tmp_path / "repair.db", tmp_path / "executions.txt"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        install(state, code_package(marker))
        provider = Provider(["脚本已执行。计算 $2+2=5$。", "脚本已执行。计算 $2+2=4$。"])
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        frames = send(ws, "send_message", "slash-repair", {"text": "/echo 回顾这段文本"})
        assert marker.read_text().splitlines() == ["executed"] and len(provider.requests) == 2
        assert "2+2=4" in delivered(frames) and "2+2=5" not in delivered(frames)
        for messages, options in provider.requests:
            assert any(MARKER in str(m["content"]) and "应用已执行的插件回执" in str(m["content"]) for m in messages)
            assert "tools" not in options


def test_declarative_command_is_discovered_from_owner_service_and_runs_real_empty_report(tmp_path):
    db = tmp_path / "declarative.db"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        package = next(p for p in builtin_plugin_packages() if p["workflow"] == "learning-report")
        state.community_plugins.import_package("local-admin", package)
        state.community_plugins.set_enabled("local-admin", package["id"], enabled=True,
            consent_permissions=["read_learning_records"])
        commands = client.get("/api/v2/math-tutor/desktop/community/plugins/commands")
        assert commands.status_code == 200
        command = next(row for row in commands.json()["items"] if row["plugin_id"] == package["id"])
        assert command["enabled"] and command["runtime_available"]
        before = count(db, "learning_events")
        frames = send(ws, "send_message", "decl-slash", {"text": "/" + command["command"] + " 查看我的真实学习情况"})
        assert "没有可用记录" in delivered(frames) and '"independent_accuracy": null' in delivered(frames)
        assert count(db, "learning_events") == before


@pytest.mark.parametrize("case", ["unknown", "disabled", "other-owner", "runtime"],
                         ids=["unknown-command", "disabled-plugin", "owner-isolation", "runtime-unavailable"])
def test_rejected_commands_report_actual_state_without_model_or_code(tmp_path, monkeypatch, case):
    marker = tmp_path / "executions.txt"
    with client_at(tmp_path / "rejected.db") as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        if case == "runtime":
            # Enable while a host-provisioned executable exists, then remove
            # the provision before dispatch. No TypeScript process is launched.
            monkeypatch.setenv("MATHTUTOR_PLUGIN_NODE_EXECUTABLE", sys.executable)
        if case != "unknown":
            install(state, code_package(marker, runtime="typescript" if case == "runtime" else "python"),
                    owner="bob" if case == "other-owner" else "local-admin", enabled=case != "disabled")
        if case == "runtime":
            monkeypatch.delenv("MATHTUTOR_PLUGIN_NODE_EXECUTABLE", raising=False)
        provider = Provider([])
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        frames = send(ws, "send_message", "rejected-command", {"text": "/echo 做一点事情"})
        expected = "尚未启用" if case == "disabled" else "运行环境" if case == "runtime" else "未找到"
        assert expected in delivered(frames), delivered(frames)
        assert not marker.exists() and not provider.requests


def test_quoted_or_historical_commands_do_not_trigger_code_and_current_exercise_is_not_assessed(tmp_path):
    db, marker = tmp_path / "scope.db", tmp_path / "executions.txt"
    with client_at(db) as client, client.websocket_connect("/api/v2/math-tutor/ws") as ws:
        state = get_product_state()
        install(state, code_package(marker))
        provider = Provider(["这只是引文。", "我记得这段对话。", "脚本结果已经返回，当前练习没有提交作答。"])
        state.gateway.register_provider(ModelRole.TUTOR_WRITER, provider)
        send(ws, "send_message", "quoted", {"text": "> /echo 仅引用，不执行"})
        send(ws, "send_message", "history", {"text": "解释一下上面的引文。"})
        assert not marker.exists()
        send(ws, "submit_problem", "problem", {"text": "2x+3=7"})
        before = summary(client)
        observations = count(db, "learning_events")
        frames = send(ws, "send_message", "active-slash", {"text": "/echo 2x+3=7 我已经掌握了"})
        after = summary(client)
        assert marker.read_text().splitlines() == ["executed"]
        assert count(db, "learning_events") == observations
        assert after["state"] == before["state"] and after["state_version"] == before["state_version"]
        assert after["effective_assistance_level"] == before["effective_assistance_level"]
        assert "没有提交作答" in delivered(frames)
        reference = next(m["content"] for m in provider.requests[-1][0] if "应用已执行的插件回执" in str(m["content"]))
        assert '"full_answer_authorized": false' in reference
        assert not any(frame.get("payload", {}).get("action") == "ASSESS_ATTEMPT" for frame in frames)
