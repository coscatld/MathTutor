"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { resolvePythonRuntime } = require("./packaging-prerequisites.cjs");

async function verifyRuntime({ runtime, platform = process.platform, arch = process.arch } = {}) {
  runtime = resolvePythonRuntime({ env: { ...process.env, MATHTUTOR_PYTHON_RUNTIME: runtime || process.env.MATHTUTOR_PYTHON_RUNTIME }, platform });
  if (platform !== process.platform || arch !== process.arch) throw new Error("Runtime must be verified on its target OS and architecture");
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-relocation-"));
  const relocated = path.join(work, "runtime");
  try {
    fs.cpSync(runtime, relocated, { recursive: true, verbatimSymlinks: true });
    const executable = path.join(relocated, platform === "win32" ? "python.exe" : "bin/python");
    const code = `
import json, pathlib, platform, sys
import ssl, sqlite3, ctypes, multiprocessing
import aiosqlite, alembic, bcrypt, fastapi, httpx, jose, pydantic, pypdf, sqlalchemy, uvicorn
root = pathlib.Path(${JSON.stringify(relocated)}).resolve()
assert pathlib.Path(sys.prefix).resolve() == root, (sys.prefix, str(root))
assert sys.platform == ${JSON.stringify(platform)}, sys.platform
machine = {"aarch64": "arm64", "AMD64": "x64", "x86_64": "x64"}.get(platform.machine(), platform.machine())
assert machine == ${JSON.stringify(arch)}, machine
assert (3, 11) <= sys.version_info[:2] < (3, 14), sys.version
for module in list(sys.modules.values()):
    filename = getattr(module, "__file__", None)
    if filename and not filename.startswith("<"):
        assert pathlib.Path(filename).resolve().is_relative_to(root), filename
print(json.dumps({"platform": sys.platform, "arch": machine, "relocated": True}))
`;
    const env = { PYTHONDONTWRITEBYTECODE: "1", PYTHONNOUSERSITE: "1" };
    for (const key of ["PATH", "SystemRoot", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE", "LANG"]) {
      if (process.env[key]) env[key] = process.env[key];
    }
    const output = execFileSync(executable, ["-I", "-B", "-c", code], { cwd: work, env, encoding: "utf8", timeout: 60000 });
    const result = JSON.parse(output.trim());
    if (!result.relocated || result.platform !== platform || result.arch !== arch) throw new Error("Invalid target runtime probe result");
    return result;
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
}

if (require.main === module) {
  verifyRuntime().then(result => console.log(`[distribution] PASS target runtime relocation ${JSON.stringify(result)}`)).catch(error => {
    console.error(`[distribution] FAIL: ${error.message}`);
    process.exitCode = 1;
  });
}
module.exports = { verifyRuntime };
