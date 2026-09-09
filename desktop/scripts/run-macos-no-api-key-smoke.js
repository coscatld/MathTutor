#!/usr/bin/env node
"use strict";

const { execFileSync, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const desktop = path.resolve(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(desktop, "package.json"), "utf8"));
const dmg = path.resolve(process.argv[2] || path.join(desktop, "dist", `MathTutor-${pkg.version}-mac-arm64.dmg`));
const report = path.resolve(
  process.argv[3] || path.join(desktop, "dist", "release-manifest", "no-api-key-smoke-macos.json"),
);
const probe = path.join(desktop, "scripts", "no-api-key-smoke.py");
const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-no-key-"));
const mountpoint = path.join(work, "volume");
const dataRoot = path.join(work, "data");
const cwd = path.join(work, "cwd");
for (const directory of [mountpoint, dataRoot, cwd]) fs.mkdirSync(directory);
let mounted = false;
try {
  execFileSync("hdiutil", ["attach", "-nobrowse", "-readonly", "-mountpoint", mountpoint, dmg], { stdio: "inherit" });
  mounted = true;
  const resources = path.join(mountpoint, "MathTutor.app", "Contents", "Resources");
  const python = path.join(resources, "python-runtime", "bin", "python");
  const pythonApp = path.join(resources, "python-app");
  const result = spawnSync(python, [probe, "--data-root", dataRoot], {
    cwd,
    env: {
      PATH: process.env.PATH || "/usr/bin:/bin",
      HOME: process.env.HOME || os.homedir(),
      TMPDIR: process.env.TMPDIR || os.tmpdir(),
      LANG: process.env.LANG || "C.UTF-8",
      PYTHONPATH: pythonApp,
      PYTHONNOUSERSITE: "1",
      PYTHONDONTWRITEBYTECODE: "1",
    },
    encoding: "utf8",
    timeout: 120000,
  });
  process.stdout.write(result.stdout || "");
  process.stderr.write(result.stderr || "");
  const evidence = JSON.parse(String(result.stdout || "").trim().split(/\r?\n/).at(-1));
  if (result.status !== 0 || evidence.status !== "PASS") throw new Error("No-API-Key smoke failed");
  fs.mkdirSync(path.dirname(report), { recursive: true });
  fs.writeFileSync(report, `${JSON.stringify({
    ...evidence,
    platform: process.platform,
    arch: process.arch,
    readonly_dmg_mount: true,
    cwd_outside_checkout: true,
    packaged_runtime: true,
  }, null, 2)}\n`, { mode: 0o600 });
} finally {
  if (mounted) {
    try { execFileSync("hdiutil", ["detach", mountpoint], { stdio: "inherit" }); } catch {}
  }
  fs.rmSync(work, { recursive: true, force: true });
}
