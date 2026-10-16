"""Explicitly trusted local code, in child processes; this is NOT an OS sandbox.

Imports never execute source or install dependencies. JSON stdin/stdout and
process/output budgets constrain the protocol, not the user's OS authority.
"""
from __future__ import annotations

import ast
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import unicodedata
import zipfile

from pydantic import Field, model_validator

from mathtutor.extensions.registry import ExtensionError, StrictArguments, _json_bytes

CODE_SCHEMA = "mathtutor.code-plugin.v1"
CODE_PERMISSION = "execute_local_code"
MAX_CODE_BYTES = 64 * 1024
MAX_EXPANDED_BYTES = 256 * 1024
MAX_PACKAGE_BYTES = 512 * 1024
MAX_OUTPUT_BYTES = 16 * 1024
MAX_STDERR_BYTES = 8 * 1024
MAX_LEDGER_BYTES = 24 * 1024 * 1024
MAX_RUNS = 1000
TIMEOUT_SECONDS = 5
COMMAND_PATTERN = r"^[a-z][a-z0-9_-]{1,31}$"


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate field")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite value")))
        if not isinstance(value, dict):
            raise ValueError("Object required")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise ExtensionError("插件文件或运行结果不是有效的有界对象。") from None


def safe_path(value):
    if (not isinstance(value, str) or not value or len(value) > 240 or "\\" in value or ":" in value
            or value.startswith("/") or any(ord(c) < 32 for c in value)):
        raise ValueError("Unsafe package path")
    if any(p in {"", ".", ".."} or p.casefold() == "node_modules" or p.startswith(".") or p.endswith((" ", "."))
            or any(c in '<>"|?*' for c in p)
            or re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p, re.I)
            for p in value.split("/")):
        raise ValueError("Unsafe package path")
    if PurePosixPath(value).name.casefold() in {"plugin.json", "package.json", "tsconfig.json"}:
        raise ValueError("Reserved package path")
    return value


class CodePluginPackage(StrictArguments):
    schema_version: str = CODE_SCHEMA
    kind: str = "code-plugin"
    workflow: str = "code"
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,79}$")
    version: str = Field(pattern=r"^(?:0|[1-9]\d{0,3})\.(?:0|[1-9]\d{0,3})\.(?:0|[1-9]\d{0,3})$")
    name: str = Field(min_length=1, max_length=80)
    author: str = Field(min_length=1, max_length=120)
    license: str = Field(pattern=r"^[A-Za-z0-9.+-]{1,80}$")
    description: str = Field(min_length=1, max_length=500)
    readme: str = Field(min_length=1, max_length=12000)
    changelog: str = Field(min_length=1, max_length=8000)
    tags: list[str] = Field(default_factory=list, max_length=12)
    grades: list[int] = Field(default_factory=list, max_length=12)
    defaults: dict = Field(default_factory=dict)
    teaching_guidance: str = Field(default="", max_length=2000)
    runtime: str = Field(pattern=r"^(python|typescript)$")
    command: str = Field(pattern=COMMAND_PATTERN)
    entrypoint: str = Field(min_length=1, max_length=240)
    required_permissions: list[str] = Field(default_factory=lambda: [CODE_PERMISSION], max_length=1)
    files: dict[str, str] = Field(min_length=1, max_length=32)
    file_hashes: dict[str, str] = Field(default_factory=dict, max_length=32)

    @model_validator(mode="after")
    def validate_code(self):
        if (self.schema_version != CODE_SCHEMA or self.kind != "code-plugin" or self.workflow != "code"
                or self.required_permissions != [CODE_PERMISSION]):
            raise ValueError("Unsupported code protocol")
        if any(not value.strip() for value in (self.name, self.author, self.description, self.readme, self.changelog)):
            raise ValueError("Empty metadata")
        if any(not tag.strip() or len(tag) > 32 for tag in self.tags):
            raise ValueError("Invalid tags")
        if any(type(g) is not int or not 1 <= g <= 12 for g in self.grades) or len(set(self.grades)) != len(self.grades):
            raise ValueError("Invalid grades")
        if len(_json_bytes(self.defaults)) > 8192:
            raise ValueError("Config too large")
        suffix = ".py" if self.runtime == "python" else ".ts"
        hashes, seen, total = {}, set(), 0
        for path, source in self.files.items():
            safe_path(path)
            key = unicodedata.normalize("NFC", path).casefold()
            if key in seen or PurePosixPath(path).suffix.lower() not in {suffix, ".md", ".txt", ".json"}:
                raise ValueError("Unsupported or duplicate source")
            seen.add(key)
            data = source.encode("utf-8")
            total += len(data)
            if not source or "\x00" in source or len(data) > MAX_CODE_BYTES:
                raise ValueError("Source size invalid")
            hashes[path] = hashlib.sha256(data).hexdigest()
        if total > MAX_EXPANDED_BYTES or self.entrypoint not in self.files or not self.entrypoint.endswith(suffix):
            raise ValueError("Invalid entrypoint")
        if self.file_hashes and self.file_hashes != hashes:
            raise ValueError("Source hashes disagree")
        self.file_hashes = hashes
        if self.runtime == "python":
            tree = ast.parse(self.files[self.entrypoint])
            if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run" for node in tree.body):
                raise ValueError("Python must define run(request)")
        return self


def validate_code_package(payload):
    try:
        if not isinstance(payload, dict) or len(canonical(payload)) > MAX_PACKAGE_BYTES:
            raise ValueError("Package too large")
        return CodePluginPackage.model_validate(payload, strict=True)
    except (ValueError, TypeError, RecursionError, OverflowError, SyntaxError):
        raise ExtensionError("代码插件的文件、版本、命令或入口无效；未执行任何代码。") from None


def is_code_upload(data, filename):
    if PurePosixPath(str(filename).replace("\\", "/")).suffix.lower() in {".py", ".ts"}:
        return True
    if data.startswith(b"PK") and len(data) <= MAX_PACKAGE_BYTES:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                return "plugin.json" in archive.namelist()
        except (zipfile.BadZipFile, OSError):
            return False
    return False


def parse_code_upload(data, filename):
    try:
        if not data or len(data) > MAX_PACKAGE_BYTES:
            raise ValueError("Package size invalid")
        suffix = PurePosixPath(str(filename).replace("\\", "/")).suffix.lower()
        if not data.startswith(b"PK") and suffix in {".py", ".ts"}:
            if len(data) > MAX_CODE_BYTES:
                raise ValueError("Source too large")
            source = data.decode("utf-8-sig")
            display_name = PurePosixPath(str(filename).replace("\\", "/")).stem.strip()[:80]
            stem = display_name.lower()
            alias = stem if re.fullmatch(COMMAND_PATTERN, stem) else "script_" + hashlib.sha256(data).hexdigest()[:12]
            runtime = "python" if suffix == ".py" else "typescript"
            return validate_code_package({"schema_version": CODE_SCHEMA, "kind": "code-plugin", "workflow": "code",
                "id": f"local.{runtime}.{alias}", "version": "1.0.0", "name": display_name or alias, "command": alias,
                "author": "本地导入", "license": "LicenseRef-UserProvided", "description": "从单文件导入的本机代码插件。",
                "readme": "只在你明确信任作者后启用。代码以本机账户权限运行，不是操作系统沙箱。",
                "changelog": "1.0.0：单文件导入；修改代码须先卸载，或改用带明确版本的插件包升级。",
                "runtime": runtime, "entrypoint": "main" + suffix, "files": {"main" + suffix: source}})
        files, seen, total = {}, set(), 0
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if not 2 <= len(archive.infolist()) <= 64:
                raise ValueError("Invalid entry count")
            manifest = None
            for info in archive.infolist():
                path = info.filename.rstrip("/") if info.is_dir() else info.filename
                if info.orig_filename != info.filename:
                    raise ValueError("Normalized archive path")
                if path != "plugin.json":
                    safe_path(path)
                key = unicodedata.normalize("NFC", path).casefold()
                if key in seen:
                    raise ValueError("Duplicate archive path")
                seen.add(key)
                mode = info.external_attr >> 16
                if (stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)))
                        or info.flag_bits & 1):
                    raise ValueError("Links or encryption unsupported")
                if info.is_dir():
                    continue
                total += info.file_size
                maximum = MAX_CODE_BYTES if path != "plugin.json" else MAX_PACKAGE_BYTES
                if total > MAX_PACKAGE_BYTES or info.file_size > maximum or (info.file_size > 65536 and info.file_size > max(1, info.compress_size) * 200):
                    raise ValueError("Expansion budget exceeded")
                content = archive.read(info)
                if len(content) != info.file_size:
                    raise ValueError("Size mismatch")
                if path == "plugin.json":
                    manifest = strict_json(content)
                else:
                    files[path] = content.decode("utf-8")
            if manifest is None or "files" in manifest or not manifest.get("file_hashes"):
                raise ValueError("Missing manifest/hash inventory")
            return validate_code_package({**manifest, "files": files})
    except (ValueError, UnicodeError, OSError, RuntimeError, zipfile.BadZipFile, NotImplementedError):
        raise ExtensionError("代码插件压缩包不完整或包含不支持的路径、文件、编码或校验值。") from None


def export_code_package(payload):
    package = validate_code_package(payload)
    manifest = package.model_dump(exclude={"files"})
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.json", canonical(manifest))
        for path, source in package.files.items():
            archive.writestr(path, source.encode("utf-8"))
    return output.getvalue()


PYTHON_RUNNER = r'''
import asyncio, importlib.util, inspect, json, pathlib, sys
entry = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(entry.parent))
request = json.load(sys.stdin)
spec = importlib.util.spec_from_file_location("mathtutor_user_plugin", entry)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
result = module.run(request)
if inspect.isawaitable(result): result = asyncio.run(result)
json.dump(result, sys.stdout, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
'''

TYPESCRIPT_RUNNER = r'''
import { pathToFileURL } from "node:url";
let input = "";
process.stdin.setEncoding("utf8");
for await (const chunk of process.stdin) input += chunk;
const module = await import(pathToFileURL(process.argv[2]).href);
if (typeof module.run !== "function") throw new Error("Export run(request) is required");
const result = await module.run(JSON.parse(input));
let count = 0, budget = 0;
function check(value, depth = 0) {
  if (++count > 2000 || depth > 12) throw new Error("Result complexity limit");
  if (value === null || typeof value === "boolean") budget += 5;
  else if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Finite numbers required");
    budget += 32;
  } else if (typeof value === "string") {
    if (value.length > 16384) throw new Error("String too large");
    budget += Buffer.byteLength(JSON.stringify(value));
  } else if (Array.isArray(value)) {
    budget += value.length + 2;
    for (const child of value) check(child, depth + 1);
  } else if (typeof value === "object" && [null, Object.prototype].includes(Object.getPrototypeOf(value))) {
    for (const [key, child] of Object.entries(value)) {
      budget += Buffer.byteLength(JSON.stringify(key)) + 2;
      check(child, depth + 1);
    }
  } else throw new Error("JSON values required");
  if (budget > 16384) throw new Error("Result too large");
}
if (!result || typeof result !== "object" || Array.isArray(result)) throw new Error("Object result required");
check(result);
process.stdout.write(JSON.stringify(result));
'''


class CodePluginRuntime:
    def __init__(self, storage_root):
        self.root = Path(storage_root)
        self._lock = threading.RLock()
        self._processes = set()
        self.closed = False

    def available(self, runtime):
        if runtime == "python":
            return bool(sys.executable and Path(sys.executable).is_file())
        node = os.environ.get("MATHTUTOR_PLUGIN_NODE_EXECUTABLE", "")
        return bool(node and Path(node).is_absolute() and Path(node).is_file())

    def _ledger_path(self, owner):
        directory = self.root / hashlib.sha256(owner.encode("utf-8")).hexdigest()
        if self.root.is_symlink() or directory.is_symlink():
            raise ExtensionError("插件运行记录目录无效。")
        return directory / "code-runs.json"

    def _load(self, owner):
        path = self._ledger_path(owner)
        if not path.exists():
            return []
        try:
            if path.is_symlink() or path.stat().st_size > MAX_LEDGER_BYTES:
                raise ValueError
            value = strict_json(path.read_bytes())
            if set(value) != {"runs"} or not isinstance(value["runs"], list) or len(value["runs"]) > MAX_RUNS:
                raise ValueError
            seen = set()
            for row in value["runs"]:
                if (not isinstance(row, dict) or row.get("status") not in {"started", "failed", "complete"}
                        or not re.fullmatch(r"[a-f0-9]{64}", row.get("id", "")) or row["id"] in seen
                        or not re.fullmatch(r"[a-f0-9]{64}", row.get("fingerprint", ""))
                        or not isinstance(row.get("plugin_id"), str) or not isinstance(row.get("at"), str)):
                    raise ValueError
                seen.add(row["id"])
                if row["status"] == "complete" and (not isinstance(row.get("result"), dict) or len(_json_bytes(row["result"])) > MAX_OUTPUT_BYTES):
                    raise ValueError
                if row["status"] == "failed" and (not isinstance(row.get("message"), str) or len(row["message"]) > 500):
                    raise ValueError
            return value["runs"]
        except (ValueError, OSError):
            raise ExtensionError("插件运行记录无法读取；为避免重复执行，本次未运行代码。") from None

    def _save(self, owner, rows):
        path = self._ledger_path(owner)
        data = canonical({"runs": rows})
        if len(data) > MAX_LEDGER_BYTES:
            raise ExtensionError("插件运行记录已满；本次未再次运行代码。")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(prefix=".code-runs-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def close(self):
        self.closed = True
        for process in tuple(self._processes):
            try:
                if os.name == "posix": os.killpg(process.pid, signal.SIGKILL)
                else:
                    taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
                    try:
                        subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=False)
                    except (OSError, subprocess.TimeoutExpired):
                        process.kill()
            except (ProcessLookupError, OSError):
                pass

    async def _terminate(self, process):
        if os.name == "posix":
            try: os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError): pass
        else:
            taskkill = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/taskkill.exe"
            try:
                killer = await asyncio.create_subprocess_exec(str(taskkill), "/PID", str(process.pid), "/T", "/F",
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
                await asyncio.wait_for(killer.wait(), 2)
            except (OSError, TimeoutError):
                try: process.kill()
                except (ProcessLookupError, OSError): pass
        try: await asyncio.wait_for(process.wait(), 2)
        except TimeoutError: pass

    async def _execute(self, package, request):
        if self.closed or not self.available(package.runtime):
            raise ExtensionError("代码插件运行时不可用，请在完整桌面安装包中运行。")
        with tempfile.TemporaryDirectory(prefix="mathtutor-trusted-plugin-") as temporary:
            work = Path(temporary)
            source_root = work / "plugin"
            source_root.mkdir()
            for path, source in package.files.items():
                target = source_root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.encode("utf-8"))
            env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "LANG", "LC_ALL") if key in os.environ}
            env.update(HOME=str(work), TMPDIR=str(work), TEMP=str(work), TMP=str(work), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
            if package.runtime == "python":
                runner = work / "host-runner.py"
                runner.write_text(PYTHON_RUNNER, encoding="utf-8")
                command = [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(runner), str(source_root / package.entrypoint)]
            else:
                (work / "package.json").write_text('{"type":"module"}', encoding="utf-8")
                runner = work / "host-runner.mjs"
                runner.write_text(TYPESCRIPT_RUNNER, encoding="utf-8")
                env["ELECTRON_RUN_AS_NODE"] = "1"
                command = [os.environ["MATHTUTOR_PLUGIN_NODE_EXECUTABLE"], "--experimental-strip-types", str(runner), str(source_root / package.entrypoint)]
            options = {"start_new_session": True} if os.name == "posix" else {"creationflags": 0x00000200}
            process = await asyncio.create_subprocess_exec(*command, cwd=work, env=env,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options)
            self._processes.add(process)
            async def read(stream, maximum):
                output = bytearray()
                while True:
                    chunk = await stream.read(4096)
                    if not chunk: return bytes(output)
                    output.extend(chunk)
                    if len(output) > maximum: raise ExtensionError("插件输出超过限制，已停止执行。")
            tasks = [asyncio.create_task(read(process.stdout, MAX_OUTPUT_BYTES)), asyncio.create_task(read(process.stderr, MAX_STDERR_BYTES))]
            try:
                # Creating a process yields to the event loop before its
                # handle is registered. A concurrent shutdown may therefore
                # have seen no children. Both host runners wait for stdin
                # before importing user code; never release that input after
                # shutdown, and let the same finally path reap this child.
                if self.closed:
                    raise ExtensionError("插件运行时已关闭，本次未运行代码。")
                process.stdin.write(canonical(request))
                await process.stdin.drain()
                process.stdin.close()
                async def collect():
                    stdout, _ = await asyncio.gather(*tasks)
                    await process.wait()
                    return stdout
                stdout = await asyncio.wait_for(collect(), TIMEOUT_SECONDS)
                if process.returncode != 0:
                    raise ExtensionError("插件执行失败；未将错误输出交给模型或当作学习证据。")
                result = strict_json(stdout)
                if len(_json_bytes(result)) > MAX_OUTPUT_BYTES:
                    raise ExtensionError("插件运行结果超过限制。")
                return result
            except TimeoutError:
                raise ExtensionError("插件执行超时，已停止本次执行。") from None
            except ExtensionError:
                raise
            except (BrokenPipeError, ConnectionResetError, ValueError, UnicodeError, RecursionError):
                raise ExtensionError("插件没有返回有效的有界结果。") from None
            finally:
                await self._terminate(process)
                for task in tasks:
                    if not task.done(): task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                self._processes.discard(process)

    async def run(self, owner, package, config, text, *, operation_id, conversation_id=""):
        if not isinstance(text, str) or len(text) > 8000 or len(_json_bytes(config)) > 8192:
            raise ExtensionError("插件输入或设置超过限制。")
        if not isinstance(operation_id, str) or not operation_id.strip() or len(operation_id) > 256:
            raise ExtensionError("插件运行缺少有效的请求标识。")
        key = hashlib.sha256(operation_id.encode()).hexdigest()
        fingerprint = hashlib.sha256(canonical({"package": package.model_dump(), "config": config,
            "text": text, "conversation": conversation_id})).hexdigest()
        with self._lock:
            rows = self._load(owner)
            old = next((row for row in rows if row.get("id") == key), None)
            if old:
                if old.get("fingerprint") != fingerprint:
                    raise ExtensionError("重复插件请求的内容不一致；本次未再次运行。")
                if old.get("status") == "complete": return old["result"]
                if old.get("status") == "failed": raise ExtensionError(old["message"])
                raise ExtensionError("上次插件执行尚未完成或状态不明；为避免重复操作，未自动重跑。")
            if len(rows) >= MAX_RUNS:
                raise ExtensionError("插件运行记录已满；本次未运行代码。")
            rows.append({"id": key, "fingerprint": fingerprint, "status": "started", "plugin_id": package.id,
                "at": datetime.now(timezone.utc).isoformat()})
            try: self._save(owner, rows)
            except (OSError, ExtensionError):
                raise ExtensionError("无法保存插件运行记录，本次未执行代码。") from None
        try:
            result = await self._execute(package, {"text": text, "config": config})
        except (ExtensionError, OSError, ValueError) as error:
            public = error if isinstance(error, ExtensionError) else ExtensionError("插件运行时启动或文件访问失败，未自动重跑。")
            with self._lock:
                rows = self._load(owner)
                row = next(row for row in rows if row["id"] == key)
                row.update(status="failed", message=str(public))
                try: self._save(owner, rows)
                except (OSError, ExtensionError):
                    raise ExtensionError("插件执行失败且记录未能保存；请勿自动重跑。") from None
            raise public from None
        with self._lock:
            rows = self._load(owner)
            row = next(row for row in rows if row["id"] == key)
            row.update(status="complete", result=result)
            try: self._save(owner, rows)
            except (OSError, ExtensionError):
                raise ExtensionError("插件已执行，但结果记录未能保存；为避免重复操作，请勿自动重跑。") from None
        return result
