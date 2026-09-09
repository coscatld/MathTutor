"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const test = require("node:test");
const { resolvePythonRuntime, resolvePackagingPrerequisites } = require("../scripts/packaging-prerequisites.cjs");
const configPath = path.resolve(__dirname, "../electron-builder.config.cjs");

function fixture(t, platform = "darwin") {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-contract-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const runtime = path.join(root, "python");
  const executable = path.join(runtime, platform === "win32" ? "python.exe" : "bin/python");
  fs.mkdirSync(path.dirname(executable), { recursive: true });
  // Structural fixture only: this file must never be claimed to be runnable Python.
  fs.writeFileSync(executable, "fixture, not an executable");
  fs.mkdirSync(path.join(runtime, platform === "win32" ? "Lib/encodings" : "lib/python3.12/encodings"), { recursive: true });
  return { root, runtime, env: { MATHTUTOR_PYTHON_RUNTIME: runtime }, platform };
}

test("requiring config requires neither runtime nor frontend build outputs", t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-config-"));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.copyFileSync(configPath, path.join(root, "electron-builder.config.cjs"));
  fs.copyFileSync(path.resolve(__dirname, "../package_allowlist.json"), path.join(root, "package_allowlist.json"));
  const env = { ...process.env };
  delete env.MATHTUTOR_PYTHON_RUNTIME;
  delete env.CONDA_PREFIX;
  execFileSync(process.execPath, ["-e", "const c=require('./electron-builder.config.cjs'); JSON.stringify(c); if(!c.beforePack)process.exit(1)"], { cwd: root, env });
});

test("explicit resolution without env fails even if development Python exists", () => {
  assert.throws(() => resolvePythonRuntime({ env: { CONDA_PREFIX: process.cwd() } }), /not provisioned/);
});

test("invalid runtime and executable instead of directory fail closed", t => {
  const f = fixture(t);
  assert.throws(() => resolvePythonRuntime({ env: { MATHTUTOR_PYTHON_RUNTIME: path.join(f.root, "missing") } }));
  assert.throws(() => resolvePythonRuntime({ env: { MATHTUTOR_PYTHON_RUNTIME: path.join(f.runtime, "bin/python") } }), /directory/);
  fs.writeFileSync(path.join(f.runtime, "pyvenv.cfg"), "home = /host/python");
  assert.throws(() => resolvePythonRuntime(f), /venv/);
});

for (const platform of ["darwin", "win32", "linux"]) {
  test(`${platform} valid structural fixture passes packaging prerequisite resolution`, t => {
    const f = fixture(t, platform);
    const web = path.join(f.root, "web/.next-mathtutor");
    fs.mkdirSync(path.join(web, "standalone/node_modules"), { recursive: true });
    fs.mkdirSync(path.join(web, "static"));
    fs.writeFileSync(path.join(web, "standalone/server.js"), "fixture");
    assert.equal(resolvePackagingPrerequisites({ ...f, repoDir: f.root }), fs.realpathSync(f.runtime));
    fs.rmSync(path.join(web, "static"), { recursive: true });
    assert.throws(() => resolvePackagingPrerequisites({ ...f, repoDir: f.root }), /frontend prerequisite/);
  });
}

test("hosted toolcache cannot masquerade as a distribution runtime", t => {
  const f = fixture(t);
  f.env.RUNNER_TOOL_CACHE = f.root;
  assert.throws(() => resolvePythonRuntime(f), /Hosted Python/);
});

test("beforePack fails without runtime, so direct electron-builder cannot bypass the gate", async () => {
  const env = { ...process.env };
  delete env.MATHTUTOR_PYTHON_RUNTIME;
  assert.throws(() => execFileSync(process.execPath, ["-e", `require('./scripts/before-pack.cjs')({electronPlatformName:process.platform,arch:process.arch}).catch(e=>{console.error(e.message);process.exit(1)})`], { cwd: path.resolve(__dirname, ".."), env, stdio: "pipe" }), /not provisioned/);
});

test("a fake executable cannot pass real distribution verification", async t => {
  const f = fixture(t, process.platform);
  const { verifyRuntime } = require("../scripts/verify-distribution-runtime.cjs");
  await assert.rejects(verifyRuntime({ runtime: f.runtime }));
});

test("release workflow provisions target runtimes before distribution and packaging", () => {
  const workflow = fs.readFileSync(path.resolve(__dirname, "../../.github/workflows/release-packaging.yml"), "utf8");
  const verify = workflow.indexOf("npm run test:distribution");
  assert.ok(workflow.indexOf("prepare-macos-python-runtime.py") < verify);
  assert.ok(workflow.indexOf("prepare-windows-python-runtime.ps1") < verify);
  assert.ok(workflow.indexOf("MATHTUTOR_PYTHON_RUNTIME=$GITHUB_WORKSPACE/.runtime/") < verify);
  assert.ok(workflow.indexOf("npm run package:mac:release") > verify);
  assert.ok(workflow.indexOf("--win nsis --x64") > verify);
  assert.doesNotMatch(workflow, /MATHTUTOR_PYTHON_RUNTIME=.*(?:pythonLocation|\/usr\/bin|toolcache)/);
  assert.doesNotMatch(workflow, /package:mac:unsigned/);
});
