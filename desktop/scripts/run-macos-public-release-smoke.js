#!/usr/bin/env node
"use strict";

/** macOS readonly-DMG adapter for the shared 19-step RC business smoke. */

const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const desktop = path.resolve(__dirname, "..");
const dmg = path.resolve(process.argv[2] || path.join(desktop, "dist", "MathTutor-0.2.0-mac-arm64.dmg"));
const output = path.resolve(
  process.argv[3] || path.join(desktop, "dist", "release-manifest", "rc-public-release-smoke-macos.json"),
);
const sharedDriver = path.join(desktop, "scripts", "rc-public-release-smoke.js");
const keychainProbe = path.join(desktop, "scripts", "macos-keychain-sentinel.py");

if (process.platform !== "darwin") throw new Error("macOS adapter requires a macOS target machine");
if (!fs.existsSync(dmg)) throw new Error(`DMG missing: ${dmg}`);

const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-rc-public-macos-"));
const mountpoint = path.join(work, "volume");
const cwd = path.join(work, "outside-checkout");
const secretReport = path.join(work, "keychain-report.json");
for (const directory of [mountpoint, cwd]) fs.mkdirSync(directory);
let mounted = false;
try {
  execFileSync(
    "hdiutil",
    ["attach", "-nobrowse", "-readonly", "-mountpoint", mountpoint, dmg],
    { stdio: "inherit" },
  );
  mounted = true;
  const app = path.join(mountpoint, "MathTutor.app");
  const resources = path.join(app, "Contents", "Resources");
  const python = path.join(resources, "python-runtime", "bin", "python");
  const pythonApp = path.join(resources, "python-app");
  const executable = path.join(app, "Contents", "MacOS", "MathTutor");
  for (const required of [python, pythonApp, executable]) {
    if (!fs.existsSync(required)) throw new Error(`mounted resource missing: ${required}`);
  }
  const environment = {
    PATH: process.env.PATH || "/usr/bin:/bin",
    HOME: process.env.HOME || os.homedir(),
    TMPDIR: process.env.TMPDIR || os.tmpdir(),
    LANG: process.env.LANG || "C.UTF-8",
    PYTHONPATH: pythonApp,
    PYTHONNOUSERSITE: "1",
    PYTHONDONTWRITEBYTECODE: "1",
  };
  const sentinel = spawnSync(python, [keychainProbe], {
    cwd,
    env: environment,
    encoding: "utf8",
    timeout: 30000,
  });
  process.stdout.write(sentinel.stdout || "");
  process.stderr.write(sentinel.stderr || "");
  const sentinelEvidence = JSON.parse(String(sentinel.stdout || "").trim().split(/\r?\n/).at(-1));
  if (sentinel.status !== 0 || sentinelEvidence.status !== "PASS" ||
      sentinelEvidence.plaintext_fallback !== false || !sentinelEvidence.cleanup_complete) {
    throw new Error("packaged Keychain sentinel failed");
  }
  fs.writeFileSync(secretReport, `${JSON.stringify(sentinelEvidence, null, 2)}\n`, { mode: 0o600 });
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const shared = spawnSync(
    process.execPath,
    [
      sharedDriver,
      "--platform", "darwin",
      "--artifact", executable,
      "--secret-report", secretReport,
      "--output", output,
      "--container-artifact", dmg,
    ],
    { cwd, env: environment, encoding: "utf8", timeout: 300000 },
  );
  process.stdout.write(shared.stdout || "");
  process.stderr.write(shared.stderr || "");
  if (shared.status !== 0) throw new Error(`shared RC smoke failed with exit ${shared.status}`);
} finally {
  if (mounted) {
    try { execFileSync("hdiutil", ["detach", mountpoint], { stdio: "inherit" }); } catch {}
  }
  fs.rmSync(work, { recursive: true, force: true });
}
