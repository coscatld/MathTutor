#!/usr/bin/env node
"use strict";

/** Real pre-RC DMG -> current RC DMG data upgrade evidence (macOS arm64). */

const { execFileSync, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const desktop = path.resolve(__dirname, "..");
const oldDmg = path.join(desktop, "dist", "pre-rc", "MathTutor-0.2.0-pre-rc-9cde02bd.dmg");
const pkg = JSON.parse(fs.readFileSync(path.join(desktop, "package.json"), "utf8"));
const newDmg = path.join(desktop, "dist", `MathTutor-${pkg.version}-mac-arm64.dmg`);
const probe = path.join(desktop, "scripts", "macos-upgrade-probe.py");
const reportPath = path.join(desktop, "dist", "release-manifest", "macos-upgrade-report.json");
const expectedOldHash = "9cde02bd7f997438b854949e1b5c8d959b9d63b6947e18ac006da446c9718670";

function sha256(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

function cleanEnvironment(pythonApp, dataRoot) {
  return {
    PATH: process.env.PATH || "/usr/bin:/bin",
    HOME: process.env.HOME || os.homedir(),
    TMPDIR: process.env.TMPDIR || os.tmpdir(),
    LANG: process.env.LANG || "C.UTF-8",
    PYTHONPATH: pythonApp,
    PYTHONNOUSERSITE: "1",
    PYTHONDONTWRITEBYTECODE: "1",
    MATHTUTOR_DB_PATH: path.join(dataRoot, "math_tutor.db"),
    MATHTUTOR_DATA_ROOT: dataRoot,
    MATHTUTOR_ENVIRONMENT: "test",
    AUTH_ENABLED: "0",
    MATHTUTOR_AUTH_ENABLED: "0",
  };
}

function mountedApp(mountpoint) {
  const app = path.join(mountpoint, "MathTutor.app");
  if (!fs.existsSync(app)) throw new Error(`mounted app missing: ${app}`);
  return app;
}

function runProbe(app, operation, moduleName, work, dataRoot, statePath) {
  const resources = path.join(app, "Contents", "Resources");
  const python = path.join(resources, "python-runtime", "bin", "python");
  const pythonApp = path.join(resources, "python-app");
  const env = cleanEnvironment(pythonApp, dataRoot);
  const imported = spawnSync(
    python,
    [
      "-c",
      "import importlib,pathlib,sys; m=importlib.import_module(sys.argv[1]); print(pathlib.Path(m.__file__).resolve())",
      `${moduleName}.api.product_app`,
    ],
    { cwd: work, env, encoding: "utf8", timeout: 30000 },
  );
  const importedPath = String(imported.stdout || "").trim();
  // macOS exposes /var as a symlink to /private/var.  Compare canonical paths
  // so a module that is genuinely inside the readonly mounted app is not
  // rejected merely because Python resolved that system symlink.
  const canonicalPythonApp = fs.realpathSync(pythonApp);
  const canonicalImportedPath = importedPath ? fs.realpathSync(importedPath) : "";
  if (
    imported.status !== 0
    || !canonicalImportedPath.startsWith(canonicalPythonApp + path.sep)
  ) {
    throw new Error(`artifact import is not self-contained: ${imported.stderr || importedPath}`);
  }
  const result = spawnSync(
    python,
    [probe, operation, "--namespace", moduleName, "--data-root", dataRoot, "--state", statePath],
    { cwd: work, env, encoding: "utf8", timeout: 120000 },
  );
  process.stdout.write(result.stdout || "");
  process.stderr.write(result.stderr || "");
  const line = String(result.stdout || "").trim().split(/\r?\n/).at(-1);
  const evidence = JSON.parse(line);
  if (result.status !== 0 || evidence.status !== "PASS") {
    throw new Error(`${operation} probe failed: ${line || result.stderr}`);
  }
  return {
    ...evidence,
    self_contained_import: true,
    packaged_module: path.relative(fs.realpathSync(app), canonicalImportedPath),
  };
}

function attach(dmg, mountpoint) {
  execFileSync(
    "hdiutil",
    ["attach", "-nobrowse", "-readonly", "-mountpoint", mountpoint, dmg],
    { stdio: "inherit" },
  );
}

function detach(mountpoint) {
  execFileSync("hdiutil", ["detach", mountpoint], { stdio: "inherit" });
}

(async () => {
  for (const required of [oldDmg, newDmg, probe]) {
    if (!fs.existsSync(required)) throw new Error(`missing upgrade input: ${required}`);
  }
  if (sha256(oldDmg) !== expectedOldHash) throw new Error("pre-RC baseline hash changed");

  const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-real-upgrade-"));
  const oldMount = path.join(work, "old-volume");
  const newMount = path.join(work, "new-volume");
  const dataRoot = path.join(work, "user-data");
  const statePath = path.join(work, "expected.json");
  for (const directory of [oldMount, newMount, dataRoot]) fs.mkdirSync(directory);
  const startedAt = new Date().toISOString();
  let mounted = null;
  let seedEvidence;
  let verifyEvidence;
  try {
    attach(oldDmg, oldMount);
    mounted = oldMount;
    seedEvidence = runProbe(
      mountedApp(oldMount),
      "seed",
      "deeptutor.math_tutor",
      work,
      dataRoot,
      statePath,
    );
    detach(oldMount);
    mounted = null;

    attach(newDmg, newMount);
    mounted = newMount;
    verifyEvidence = runProbe(
      mountedApp(newMount),
      "verify",
      "mathtutor",
      work,
      dataRoot,
      statePath,
    );
    detach(newMount);
    mounted = null;
  } finally {
    if (mounted) {
      try { detach(mounted); } catch {}
    }
  }
  const report = {
    schema_version: 1,
    status: "PASS",
    platform: process.platform,
    arch: process.arch,
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    isolation: {
      readonly_dmg_mounts: true,
      cwd_outside_checkout: true,
      inherited_pythonpath: false,
      inherited_conda_or_virtualenv: false,
    },
    pre_rc_artifact: {
      path: path.relative(desktop, oldDmg),
      size_bytes: fs.statSync(oldDmg).size,
      sha256: sha256(oldDmg),
    },
    rc_artifact: {
      path: path.relative(desktop, newDmg),
      size_bytes: fs.statSync(newDmg).size,
      sha256: sha256(newDmg),
    },
    flow: [
      "mount_pre_rc_readonly",
      "seed_existing_profile",
      "backup",
      "unmount_pre_rc",
      "mount_new_rc_readonly",
      "migrate_and_bootstrap",
      "verify_persistence_and_replay",
    ],
    seed: seedEvidence,
    verify: verifyEvidence,
    rollback_contract: "Keep the verified pre-upgrade backup and reinstall the frozen pre-RC artifact; never overwrite the live DB after a failed migration.",
  };
  fs.mkdirSync(path.dirname(reportPath), { recursive: true });
  fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`MACOS_UPGRADE_SMOKE=PASS; report=${reportPath}\n`);
  fs.rmSync(work, { recursive: true, force: true });
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
