"""Real local interpreters and files; no provider calls or claimed OS sandbox."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from mathtutor.extensions.code_plugins import (CODE_PERMISSION, CodePluginRuntime, export_code_package,
    parse_code_upload, validate_code_package)
from mathtutor.extensions.community_plugins import (CommunityPluginService, builtin_plugin_packages,
    canonical_bytes, package_hash, register_community_tool)
from mathtutor.extensions.registry import ExecutionContext, ExtensionError, ExtensionRegistry
from mathtutor.api.auth_deps import require_student_owner
from mathtutor.security.scopes import PrincipalScope, StudentOwnerScope
from test_tutor_p0 import client_at


def package(source='def run(request):\n    return {"text": request["text"], "answer": 42}\n', *, runtime="python", **updates):
    suffix = ".py" if runtime == "python" else ".ts"
    return {"schema_version": "mathtutor.code-plugin.v1", "kind": "code-plugin", "workflow": "code",
        "id": "example.echo", "version": "1.0.0", "name": "测试回显", "author": "测试作者", "license": "MIT",
        "description": "本机代码测试", "readme": "本机账户权限，不在OS沙箱中", "changelog": "1.0.0",
        "runtime": runtime, "command": "echo", "entrypoint": "main" + suffix, "files": {"main" + suffix: source}, **updates}


def service(tmp_path):
    return CommunityPluginService(state=SimpleNamespace(), storage_root=tmp_path / "plugins")


def enable(s, payload):
    row = s.import_package("alice", payload)
    s.set_enabled("alice", row["plugin"]["id"], enabled=True, consent_permissions=[CODE_PERMISSION])
    return row


@pytest.fixture
def native_node(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    candidates = [os.environ.get("MATHTUTOR_PLUGIN_NODE_EXECUTABLE", ""),
        str(root / "desktop/node_modules/electron/dist/electron.exe"),
        str(root / "desktop/node_modules/electron/dist/electron"),
        str(root / "desktop/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron"),
        str(root / "desktop/dist/macos-0.7.0-7eac01a-with-creator-candidate/mac-arm64/MathTutor.app/Contents/MacOS/MathTutor"),
        shutil.which("node") or ""]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            try:
                probe = subprocess.run([candidate, "--experimental-strip-types", "-p", "JSON.stringify(process.versions)"],
                    env={**os.environ, "ELECTRON_RUN_AS_NODE": "1"}, capture_output=True, text=True, timeout=10)
                if probe.returncode == 0:
                    monkeypatch.setenv("MATHTUTOR_PLUGIN_NODE_EXECUTABLE", str(Path(candidate).resolve()))
                    return candidate
            except (OSError, subprocess.TimeoutExpired):
                pass
    pytest.skip("No explicitly discoverable Node runtime with native TypeScript support; packaged target acceptance verifies it separately")


def test_import_is_not_execution_and_requires_distinct_local_code_consent(tmp_path):
    marker = tmp_path / "never-at-import.txt"
    source = f'from pathlib import Path\nPath({str(marker)!r}).write_text("ran")\ndef run(request):\n    return {{"text":"ok"}}\n'
    s = service(tmp_path)
    row = s.import_package("alice", package(source))
    assert not marker.exists() and row["enabled"] is False and row["kind"] == "code-plugin"
    assert row["command"] == "echo" and row["runtime_available"] is True
    assert "files" not in row["plugin"] and "main.py" in row["plugin"]["file_hashes"]
    with pytest.raises(ExtensionError): s.set_enabled("alice", "example.echo", enabled=True)
    with pytest.raises(ExtensionError): s.set_enabled("alice", "example.echo", enabled=True, consent_permissions=["question_bank"])
    assert s.resolve_command("bob", "echo") is None and s.commands("bob") == []


@pytest.mark.asyncio
async def test_real_python_utf8_clean_environment_and_reference_only_result(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fixture-secret-do-not-forward")
    monkeypatch.setenv("PYTHONPATH", "fixture-checkout-path-do-not-forward")
    source = ('def run(request):\n    import os, sys\n    return {"text":request["text"], "keys":sorted(request), '
        '"secret":os.environ.get("DEEPSEEK_API_KEY"), "pythonpath":os.environ.get("PYTHONPATH"), '
        '"isolated":sys.flags.isolated, "no_site":sys.flags.no_site, "cfg":request["config"]}\n')
    s = service(tmp_path)
    enable(s, package(source, defaults={"factor": 7}))
    with pytest.raises(ExtensionError, match="明确"):
        await s.run("alice", "example.echo")
    result = await s.run_slash("alice", "echo", "中文输入🙂", operation_id="unicode")
    assert result["data"] == {"text": "中文输入🙂", "keys": ["config", "text"], "secret": None,
        "pythonpath": None, "isolated": 1, "no_site": 1, "cfg": {"factor": 7}}
    assert result["read_only"] is False and result["sandboxed"] is False and result["authority"] == "reference_only"


@pytest.mark.asyncio
async def test_real_code_runs_once_receipts_survive_restart_and_uncertain_started_never_retries(tmp_path):
    marker = tmp_path / "counter.txt"
    source = ('def run(request):\n    from pathlib import Path\n    p=Path(request["config"]["marker"])\n'
        '    count=int(p.read_text())+1 if p.exists() else 1\n    p.write_text(str(count))\n    return {"count":count}\n')
    s = service(tmp_path)
    enable(s, package(source, defaults={"marker": str(marker)}))
    first = await s.run_slash("alice", "echo", "一次", operation_id="once", conversation_id="same")
    repeated = await service(tmp_path).run_slash("alice", "echo", "一次", operation_id="once", conversation_id="same")
    assert first == repeated and marker.read_text() == "1"
    with pytest.raises(ExtensionError, match="不一致"):
        await s.run_slash("alice", "echo", "不同输入", operation_id="once", conversation_id="same")
    ledger = s.code_runtime._load("alice")
    ledger[0].pop("result")
    ledger[0]["status"] = "started"
    s.code_runtime._save("alice", ledger)
    with pytest.raises(ExtensionError, match="状态不明"):
        await s.run_slash("alice", "echo", "一次", operation_id="once", conversation_id="same")
    assert marker.read_text() == "1" and s.code_runtime._load("bob") == []


@pytest.mark.asyncio
async def test_registry_never_runs_code_even_with_forged_model_tool_arguments(tmp_path):
    s = service(tmp_path)
    enable(s, package())
    registry = ExtensionRegistry()
    register_community_tool(registry, s)
    executor = registry.bind(ExecutionContext(owner_id="alice", conversation_id="turn"))
    assert executor.definitions() == []
    assert not (await executor.execute("ext_community_run", {"plugin_id": "example.echo"}, "fake"))["ok"]
    s.import_package("alice", builtin_plugin_packages()[0])
    s.set_enabled("alice", "mathtutor.exam-builder", enabled=True, consent_permissions=["question_bank"])
    executor = registry.bind(ExecutionContext(owner_id="alice", conversation_id="turn2"))
    rejected = await executor.execute("ext_community_run", {"plugin_id": "example.echo"}, "fake2")
    assert rejected["code"] == "REJECTED" and not rejected["ok"]


def test_code_alias_unique_upgrade_clears_code_consent_and_restore_revokes_it(tmp_path):
    s = service(tmp_path)
    original = package()
    row = enable(s, original)
    with pytest.raises(ExtensionError, match="相同"):
        s.import_package("alice", {**original, "id": "example.other"})
    assert s.import_package("alice", original)["package_hash"] == row["package_hash"]
    s.configure("alice", "example.echo", {"keep": True})
    update = s.import_package("alice", {**original, "version": "1.1.0", "changelog": "新版"})
    assert update["enabled"] is False and update["consented_permissions"] == [] and update["config"] == {"keep": True}
    s.set_enabled("alice", "example.echo", enabled=True, consent_permissions=[CODE_PERMISSION])
    assert s.revoke_all_consents()["disabled"] == 1
    restored = service(tmp_path).list_installed("alice")[0]
    assert restored["enabled"] is False and restored["consented_permissions"] == []


@pytest.mark.parametrize("bad_path", ["../escape.py", "/absolute.py", "C:/drive.py", "a\\b.py", "CON.py", "folder/aux.txt",
    "trailing .py ", "node_modules/tool.py", "bad?.py", "x|y.py", ".hidden/main.py"], ids=["parent", "absolute", "drive", "backslash", "device", "nested-device", "trailing-space", "node_modules", "question-mark", "pipe", "hidden"])
def test_code_paths_are_rejected_before_install(tmp_path, bad_path):
    payload = package(entrypoint=bad_path, files={bad_path: 'def run(request):\n    return {}\n'})
    s = service(tmp_path)
    with pytest.raises(ExtensionError): s.import_package("alice", payload)
    assert s.list_installed("alice") == []


def test_zip_exact_hashes_duplicate_unicode_links_and_binary_files(tmp_path):
    payload = package()
    raw = export_code_package(payload)
    parsed = parse_code_upload(raw, "download.zip").model_dump()
    assert package_hash(parsed) == package_hash(payload)
    invalid = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        manifest = json.loads(z.read("plugin.json"))
        source = z.read("main.py")
    for items in [[("plugin.json", json.dumps(manifest)), ("main.py", source + b"# tampered")],
        [("plugin.json", json.dumps(manifest)), ("main.py", source), ("evil.exe", b"binary")],
        [("plugin.json", json.dumps(manifest)), ("main.py", source), ("MAIN.py", source)],
        [("plugin.json", json.dumps(manifest)), ("main.py", source), ("caf\u00e9.txt", "a"), ("cafe\u0301.txt", "a")]]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as z:
            for path, body in items: z.writestr(path, body)
        invalid.append(stream.getvalue())
    link = zipfile.ZipInfo("main.py"); link.create_system = 3; link.external_attr = (stat.S_IFLNK | 0o777) << 16
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as z:
        z.writestr("plugin.json", json.dumps(manifest)); z.writestr(link, "target.py")
    invalid.append(stream.getvalue())
    for data in invalid:
        with pytest.raises(ExtensionError): parse_code_upload(data, "bad.zip")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ['def run(request):\n    print("not json")\n    return {}\n',
    'def run(request):\n    return {"n":float("nan")}\n',
    'def run(request):\n    print("x"*100000)\n    return {}\n',
    'def run(request):\n    import sys\n    print("x"*100000,file=sys.stderr)\n    return {}\n'],
    ids=["stdout-noise", "nonfinite", "stdout-budget", "stderr-budget"])
async def test_invalid_python_outputs_are_bounded_fixed_errors_and_not_retried(tmp_path, source):
    s = service(tmp_path); enable(s, package(source))
    with pytest.raises(ExtensionError) as first:
        await s.run_slash("alice", "echo", "", operation_id="bad")
    assert "Traceback" not in str(first.value) and str(tmp_path) not in str(first.value)
    assert s.code_runtime._load("alice")[0]["status"] == "failed"
    with pytest.raises(ExtensionError): await s.run_slash("alice", "echo", "", operation_id="bad")


@pytest.mark.asyncio
async def test_timeout_and_cancel_kill_owned_process_and_leave_honest_receipts(tmp_path, monkeypatch):
    import mathtutor.extensions.code_plugins as module
    monkeypatch.setattr(module, "TIMEOUT_SECONDS", 0.1)
    s = service(tmp_path); enable(s, package('def run(request):\n    import time\n    time.sleep(60)\n    return {}\n'))
    with pytest.raises(ExtensionError, match="超时"):
        await s.run_slash("alice", "echo", "", operation_id="timeout")
    assert not s.code_runtime._processes and s.code_runtime._load("alice")[0]["status"] == "failed"
    monkeypatch.setattr(module, "TIMEOUT_SECONDS", 5)
    task = asyncio.create_task(s.run_slash("alice", "echo", "", operation_id="cancel"))
    for _ in range(100):
        if s.code_runtime._processes: break
        await asyncio.sleep(0.01)
    process = next(iter(s.code_runtime._processes))
    task.cancel()
    with pytest.raises(asyncio.CancelledError): await task
    assert process.returncode is not None and not s.code_runtime._processes
    assert s.code_runtime._load("alice")[-1]["status"] == "started"
    with pytest.raises(ExtensionError, match="状态不明"):
        await s.run_slash("alice", "echo", "", operation_id="cancel")


@pytest.mark.asyncio
async def test_close_runtime_terminates_live_child_and_revokes_further_runs(tmp_path):
    s = service(tmp_path); enable(s, package('def run(request):\n    import time\n    time.sleep(60)\n    return {}\n'))
    task = asyncio.create_task(s.run_slash("alice", "echo", "", operation_id="shutdown"))
    for _ in range(100):
        if s.code_runtime._processes: break
        await asyncio.sleep(0.01)
    process = next(iter(s.code_runtime._processes))
    s.close_runtime()
    with pytest.raises(ExtensionError): await task
    assert process.returncode is not None and not s.code_runtime._processes and s.commands("alice") == []
    with pytest.raises(ExtensionError): await s.run_slash("alice", "echo", "", operation_id="after-close")


@pytest.mark.asyncio
async def test_shutdown_during_spawn_never_releases_stdin_to_unregistered_child(tmp_path, monkeypatch):
    import mathtutor.extensions.code_plugins as module
    marker = tmp_path / "must-not-execute-after-close.txt"
    source = f'def run(request):\n    from pathlib import Path\n    Path({str(marker)!r}).write_text("ran")\n    return {{"text":"done"}}\n'
    s = service(tmp_path); enable(s, package(source))
    original = module.asyncio.create_subprocess_exec
    spawned, release = asyncio.Event(), asyncio.Event()
    processes = []
    async def delayed_spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        spawned.set()
        await release.wait()
        return process
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", delayed_spawn)
    task = asyncio.create_task(s.run_slash("alice", "echo", "", operation_id="close-during-spawn"))
    await asyncio.wait_for(spawned.wait(), 3)
    assert not s.code_runtime._processes
    s.close_runtime()
    release.set()
    with pytest.raises(ExtensionError, match="已关闭"):
        await asyncio.wait_for(task, 6)
    assert not marker.exists() and not s.code_runtime._processes
    assert all(process.returncode is not None for process in processes)


@pytest.mark.asyncio
async def test_startup_oserror_is_recorded_as_failure_and_start_record_failure_never_executes(tmp_path, monkeypatch):
    s = service(tmp_path); enable(s, package())
    async def fail_start(*args, **kwargs):
        raise OSError("fixture private path must not escape")
    with monkeypatch.context() as patch:
        patch.setattr("mathtutor.extensions.code_plugins.asyncio.create_subprocess_exec", fail_start)
        with pytest.raises(ExtensionError, match="启动或文件访问失败"):
            await s.run_slash("alice", "echo", "", operation_id="start-fails")
    assert s.code_runtime._load("alice")[0]["status"] == "failed"
    def fail_save(*args):
        raise OSError("fixture record write failure")
    monkeypatch.setattr(s.code_runtime, "_save", fail_save)
    with pytest.raises(ExtensionError, match="本次未执行"):
        await s.run_slash("alice", "echo", "", operation_id="no-start-record")
    assert not s.code_runtime._processes


@pytest.mark.asyncio
async def test_real_typescript_utf8_long_input_and_finite_result(tmp_path, native_node):
    source = 'type Request = {text:string,config:Record<string,unknown>}; export function run(request:Request) { return {text:request.text,length:request.text.length,value:6*7}; }'
    s = service(tmp_path); enable(s, package(source, runtime="typescript"))
    text = "中文🙂" * 1500
    result = await s.run_slash("alice", "echo", text, operation_id="typescript")
    # The long UTF-8 request crosses pipe chunks while its echo stays below the
    # bounded result budget. Node must preserve split multibyte characters.
    assert result["data"]["text"] == text


@pytest.mark.asyncio
@pytest.mark.parametrize("expression", ["Infinity", "NaN", "undefined", "1n"], ids=["infinity", "nan", "undefined", "bigint"])
async def test_real_typescript_rejects_values_json_stringify_would_silently_change(tmp_path, native_node, expression):
    source = f'export function run(request:unknown) {{ return {{bad:{expression}}}; }}'
    s = service(tmp_path); enable(s, package(source, runtime="typescript"))
    with pytest.raises(ExtensionError): await s.run_slash("alice", "echo", "", operation_id="invalid-ts")


def test_raw_python_http_commands_run_export_and_other_owner_reimport(tmp_path):
    prefix = "/api/v2/math-tutor/desktop/community/plugins"
    source = b'def run(request):\n    return {"text": request["text"]}\n'
    with client_at(tmp_path / "code-http.db") as client:
        result = client.post(prefix + "/import", files={"file": ("echo.py", source)}, data={"operation_id": "import-code"})
        assert result.status_code == 200, result.text
        installed = result.json()["plugin"]
        plugin_id = installed["plugin"]["id"]
        assert installed["enabled"] is False and installed["kind"] == "code-plugin"
        assert client.put(prefix + f"/{plugin_id}/enabled", json={"enabled": True}).status_code == 409
        assert client.put(prefix + f"/{plugin_id}/enabled", json={"enabled": True, "consent_permissions": [CODE_PERMISSION]}).status_code == 200
        assert client.get(prefix + "/commands").json()["items"][0]["command"] == "echo"
        run = client.post(prefix + f"/{plugin_id}/run", json={"text": "中文🙂", "operation_id": "run-code"})
        assert run.status_code == 200 and run.json()["data"]["text"] == "中文🙂"
        exported = client.get(prefix + f"/{plugin_id}/export")
        assert exported.status_code == 200 and exported.headers["content-type"] == "application/zip"
        bob = StudentOwnerScope(principal=PrincipalScope(user_id="bob", username="bob", role="student"), student_id="bob")
        client.app.dependency_overrides[require_student_owner] = lambda: bob
        assert client.get(prefix + "/commands").json()["items"] == []
        copied = client.post(prefix + "/import", files={"file": ("shared.zip", exported.content)})
        assert copied.status_code == 200 and copied.json()["plugin"]["enabled"] is False
        assert copied.json()["plugin"]["package_hash"] == installed["package_hash"]
        assert client.post(prefix + f"/{plugin_id}/run", json={"text": "no authority"}).status_code == 409
        client.app.dependency_overrides.pop(require_student_owner)


def test_legacy_manifest_hash_does_not_gain_command_or_kind_fields(tmp_path):
    s = service(tmp_path)
    original = builtin_plugin_packages()[0]
    expected = sha256(canonical_bytes(original)).hexdigest()
    row = s.import_package("alice", original)
    before = (s._owner_directory("alice") / "plugins.json").read_bytes()
    assert row["package_hash"] == expected and "command" not in row["plugin"]
    assert service(tmp_path).list_installed("alice")[0]["package_hash"] == expected
    assert (s._owner_directory("alice") / "plugins.json").read_bytes() == before
