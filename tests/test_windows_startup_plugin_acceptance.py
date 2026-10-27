"""Windows acceptance-script contracts on any host; not a Windows target PASS."""
from copy import deepcopy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "desktop/scripts/verify-installed-windows-startup.py"
spec = importlib.util.spec_from_file_location("windows_startup_acceptance", SCRIPT)
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


@pytest.fixture
def install_paths(tmp_path, monkeypatch):
    system = tmp_path / "Windows"
    monkeypatch.setenv("SystemRoot", str(system))
    installed = tmp_path / "安装目录 蛋蛋的app" / "MathTutor"
    python = installed / "resources/python-runtime/python.exe"
    executable = installed / "MathTutor.exe"
    return python, executable, acceptance.clean_environment(tmp_path / "全新用户数据")


def test_packaged_code_smoke_has_typed_typescript_and_utf8_python_sources():
    compile(acceptance.PYTHON_PLUGIN, "python_acceptance.py", "exec")
    assert "request: Input" in acceptance.TYPESCRIPT_PLUGIN
    assert "const executions: number" in acceptance.TYPESCRIPT_PLUGIN
    assert "process.execPath" in acceptance.TYPESCRIPT_PLUGIN
    assert "sys.executable" in acceptance.PYTHON_PLUGIN


@pytest.mark.parametrize("failure,no_site", [(None, 1), (None, 0), ("isolated-disabled", 0),
        ("site-without-optin", 0), ("duplicate-execution", 1), ("global-runtime", 1)],
    ids=["valid-protocol", "embedded-site-explicitly-enabled", "nonisolated-python-rejected",
         "site-without-packaged-optin-rejected", "replay-side-effect-detected", "global-python-detected"])
def test_code_smoke_validates_explicit_consent_replay_and_install_runtime(tmp_path, monkeypatch, install_paths, failure, no_site):
    python, executable, environment = install_paths
    if no_site == 0:
        python.parent.mkdir(parents=True)
        lines = ["python312.zip", ".", "Lib", "Lib/site-packages", "../python-app"]
        if failure != "site-without-optin":
            lines.append("import site")
        (python.parent / "python312._pth").write_text("\n".join(lines) + "\n", encoding="ascii")
    rows, receipts, calls = {}, {}, []

    def local_api(base, path, *, origin, method="GET", payload=None, file=None, operation_id=None, expected_status=200):
        assert base == "http://127.0.0.1:8001" and origin == "http://127.0.0.1:8000"
        calls.append((path, method, deepcopy(payload), file, operation_id, expected_status))
        if path.endswith("/import"):
            filename, source = file
            runtime = "python" if filename.endswith(".py") else "typescript"
            assert source == (acceptance.PYTHON_PLUGIN if runtime == "python" else acceptance.TYPESCRIPT_PLUGIN)
            row = {"kind": "code-plugin", "command": runtime + "_acceptance", "runtime_available": True,
                "enabled": False, "consented_permissions": [], "plugin": {"id": "local." + runtime,
                "runtime": runtime, "required_permissions": ["execute_local_code"]}}
            rows[row["plugin"]["id"]] = row
            return {"kind": "plugin", "plugin": deepcopy(row)}
        plugin_id = path.split("/")[-2]
        row = rows[plugin_id]
        if path.endswith("/enabled"):
            row["enabled"] = payload["enabled"]
            if row["enabled"]:
                assert payload["consent_permissions"] == ["execute_local_code"]
                row["consented_permissions"] = payload["consent_permissions"]
            return deepcopy(row)
        assert path.endswith("/run")
        if expected_status == 409:
            assert not row["enabled"]
            return {"detail": "插件尚未启用"}
        assert row["enabled"] and row["consented_permissions"] == ["execute_local_code"]
        marker = Path(payload["config"]["marker"])
        if plugin_id not in receipts:
            assert not marker.exists()
            marker.write_text("1", encoding="utf-8")
            runtime = row["plugin"]["runtime"]
            actual_executable = python if runtime == "python" else executable
            if failure == "global-runtime":
                actual_executable = tmp_path / "global/python.exe"
            receipts[plugin_id] = {"authority": "reference_only", "read_only": False, "sandboxed": False,
                "data": {"text": payload["text"], "answer": 42, "executions": 1, "runtime": runtime,
                "executable": str(actual_executable), "isolated": 0 if failure == "isolated-disabled" else 1,
                "no_site": no_site, "node_version": "fixture-only"}}
        elif failure == "duplicate-execution":
            # Returning the old receipt alone must not hide a repeated side effect.
            marker.write_text("2", encoding="utf-8")
        return deepcopy(receipts[plugin_id])

    monkeypatch.setattr(acceptance, "local_api", local_api)
    if failure:
        with pytest.raises(AssertionError):
            acceptance.verify_code_plugins("http://127.0.0.1:8001", python, executable, tmp_path / "data", environment=environment, origin="http://127.0.0.1:8000")
    else:
        result = acceptance.verify_code_plugins("http://127.0.0.1:8001", python, executable, tmp_path / "data", environment=environment, origin="http://127.0.0.1:8000")
        assert result["status"] == "PASS" and result["provider_calls"] == 0
        assert {row["runtime"] for row in result["cases"]} == {"python", "typescript"}
        assert all(row["packaged_runtime"] and row["executions_after_replay"] == 1 for row in result["cases"])
        python_case = next(row for row in result["cases"] if row["runtime"] == "python")
        assert python_case["data"]["no_site"] == no_site
        if no_site == 0:
            assert python_case["python_path_configuration"]["file"] == "python312._pth"
            assert python_case["python_path_configuration"]["import_site"] is True
        assert len([call for call in calls if call[0].endswith("/run")]) == 6
        assert all(not row["enabled"] for row in rows.values())


@pytest.mark.parametrize("name", ["fresh_unicode", "restart_unicode"], ids=["fresh-runs-code", "restart-keeps-existing-schema"])
def test_startup_elapsed_is_captured_before_additional_code_smoke(tmp_path, monkeypatch, install_paths, name):
    python, executable, environment = install_paths
    data, output = tmp_path / "data", tmp_path / "output"
    (data / "logs").mkdir(parents=True)
    output.mkdir()
    (data / "logs/startup.log").write_text("backend: python --port 8001\n- Local: http://127.0.0.2026-10-27T14:04:57.037Z 1:8000\nstartup: ready\n", encoding="utf-8")
    clock, processes, smoke_calls = [10.0], [], []

    class Process:
        def __init__(self, *args, **kwargs):
            self.returncode = None
            processes.append(self)
        def poll(self): return self.returncode
        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    def local_read(base, path, *, origin):
        assert base == "http://127.0.0.1:8001" and origin == "http://127.0.0.1:8000"
        payload = {"checks": {"migrations": "ok"}} if path.endswith("readiness") else {"version": acceptance.EXPECTED_VERSION}
        return payload

    def code_smoke(*args, **kwargs):
        smoke_calls.append(kwargs)
        clock[0] += 30.0
        return {"status": "PASS", "cases": ["contract-fixture"]}

    monkeypatch.setattr(acceptance.subprocess, "Popen", Process)
    monkeypatch.setattr(acceptance, "kill_tree", lambda process: None)
    monkeypatch.setattr(acceptance, "local_read", local_read)
    monkeypatch.setattr(acceptance.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(acceptance, "probe", lambda *args: {"math_tutor.db": {"revisions": [["024"]]}})
    monkeypatch.setattr(acceptance, "verify_code_plugins", code_smoke)
    result = acceptance.run_gui(executable, python, data, output, name)
    assert result["seconds"] == 0.0 and result["version"] == acceptance.EXPECTED_VERSION
    assert len(processes) == 2 and result["duplicate_exit"] == 0
    if name == "fresh_unicode":
        assert smoke_calls and result["code_plugins"]["status"] == "PASS" and clock[0] == 40.0
        assert smoke_calls[0]["origin"] == "http://127.0.0.1:8000"
    else:
        assert not smoke_calls and "code_plugins" not in result and clock[0] == 10.0


def test_local_api_sends_utf8_file_origin_and_disables_proxy(tmp_path, monkeypatch):
    calls, handlers = [], []

    class Response(io.BytesIO):
        code = 200

    def build_opener(handler):
        handlers.append(handler)
        def open(request, timeout=None):
            calls.append((request, timeout))
            return Response(b'{"kind":"plugin"}')
        return SimpleNamespace(open=open)

    monkeypatch.setattr(acceptance.urllib.request, "build_opener", build_opener)
    result = acceptance.local_api("http://127.0.0.1:8001", "/api/v2/math-tutor/desktop/community/plugins/import",
        origin="http://127.0.0.1:8000", method="POST", file=("python_acceptance.py", 'def run(request):\n    return {"text":"中文🙂"}\n'), operation_id="once")
    request, timeout = calls[0]
    assert result["kind"] == "plugin" and timeout == 20
    assert request.get_header("Origin") == "http://127.0.0.1:8000"
    assert request.get_header("X-mathtutor-csrf") == "1"
    assert "multipart/form-data" in request.get_header("Content-type")
    assert b'name="file"; filename="python_acceptance.py"' in request.data
    assert '中文🙂'.encode() in request.data and b'name="operation_id"' in request.data
    assert handlers[0].proxies == {}
    with pytest.raises(AssertionError):
        acceptance.local_api("https://provider.example", "/api/v2/math-tutor/desktop/community/plugins/import", origin="http://127.0.0.1:8000")


@pytest.mark.parametrize("text", [
    "2026-10-27T14:04:57.035Z ▲ Next.js\n- Local: http://127.0.0.1:60050\n",
    "2026-10-27T14:04:57.035Z ▲ Next.js\n- Local: http://127.0.0.2026-10-27T14:04:57.037Z 1:60050\n- Network: http://12026-10-27T14:05:04.883Z startup: ready\n",
    "\x1b[32m- Local:\x1b[0m http://127.0.[child] 0.1:60050\n",
])
def test_frontend_origin_recovers_exact_next_local_url_across_logged_chunks(text):
    assert acceptance.frontend_origin(text, "http://127.0.0.1:60049") == "http://127.0.0.1:60050"


@pytest.mark.parametrize("text", [
    "startup: ready", "- Network: http://127.0.0.1:60050\n", "- Local: https://provider.example\n",
    "- Local: http://localhost:60050\n", "- Local: http://127.0.0.1:0\n", "- Local: http://127.0.0.1:65536\n",
    "- Local: http://127.0.0.1:60049\n", "- Local: http://127.0.0.1:60050@provider.example\n",
    "- Local: http://127.0.0.1:60050/path\n", "- Local: http://127.0.0.1:60050\n- Local: http://127.0.0.1:60051\n",
])
def test_frontend_origin_refuses_missing_ambiguous_backend_or_nonloopback_url(text):
    with pytest.raises(AssertionError):
        acceptance.frontend_origin(text, "http://127.0.0.1:60049")


def test_local_reads_require_explicit_origin_and_disable_proxy(monkeypatch):
    calls, handlers = [], []

    def build_opener(handler):
        handlers.append(handler)
        def open(request, timeout=None):
            calls.append((request, timeout))
            return io.BytesIO(b'{"ok":true}')
        return SimpleNamespace(open=open)

    monkeypatch.setattr(acceptance.urllib.request, "build_opener", build_opener)
    for path in ("/api/v2/math-tutor/desktop/readiness", "/version"):
        assert acceptance.local_read("http://127.0.0.1:8001", path, origin="http://127.0.0.1:8000") == {"ok": True}
    assert len(calls) == 2 and all(timeout == 5 for _, timeout in calls)
    assert all(request.get_header("Origin") == "http://127.0.0.1:8000" for request, _ in calls)
    assert all(handler.proxies == {} for handler in handlers)
    with pytest.raises(TypeError):
        acceptance.local_read("http://127.0.0.1:8001", "/version")
    with pytest.raises(AssertionError):
        acceptance.local_read("http://127.0.0.1:8001", "/version", origin="https://provider.example")
    with pytest.raises(AssertionError):
        acceptance.local_read("https://provider.example", "/version", origin="http://127.0.0.1:8000")
    with pytest.raises(TypeError):
        acceptance.local_api("http://127.0.0.1:8001", "/api/v2/math-tutor/desktop/community/plugins/import")


@pytest.mark.asyncio
async def test_acceptance_headers_pass_real_boundary_without_exporting_bridge_secret(monkeypatch):
    from mathtutor.api.local_boundary import LocalBoundaryMiddleware
    from mathtutor.security.settings import MathTutorSecuritySettings

    requests = []
    class Response(io.BytesIO):
        code = 200

    def build_opener(handler):
        assert handler.proxies == {}
        def open(request, timeout=None):
            requests.append(request)
            return Response(b'{"ok":true}')
        return SimpleNamespace(open=open)

    monkeypatch.setattr(acceptance.urllib.request, "build_opener", build_opener)
    base, origin = "http://127.0.0.1:8001", "http://127.0.0.1:8000"
    acceptance.local_read(base, "/api/v2/math-tutor/desktop/readiness", origin=origin)
    acceptance.local_read(base, "/version", origin=origin)
    acceptance.local_api(base, "/api/v2/math-tutor/desktop/community/plugins/run", origin=origin, method="POST", payload={"text": "fixture"})

    async def status(request, omit=None):
        messages = []
        async def business(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})
        async def receive(): return {"type": "http.request", "body": b""}
        async def send(message): messages.append(message)
        headers = [(b"host", b"127.0.0.1:8001")]
        headers += [(name.lower().encode(), value.encode()) for name, value in request.header_items() if name.lower() != omit]
        assert not any(name == b"x-mathtutor-bridge" for name, _ in headers)
        boundary = LocalBoundaryMiddleware(business, MathTutorSecuritySettings(
            allowed_hosts=("127.0.0.1:8001",), allowed_origins=(origin,), bridge_secret="private-fixture-not-exported"))
        await boundary({"type": "http", "method": request.get_method(), "headers": headers}, receive, send)
        return messages[0]["status"]

    for request in requests:
        assert await status(request) == 200
        assert await status(request, "origin") == 403
    assert await status(requests[-1], "x-mathtutor-csrf") == 403
