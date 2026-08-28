"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const desktop = path.resolve(__dirname, "..");
const repo = path.resolve(desktop, "..");
const read = (...parts) => fs.readFileSync(path.join(repo, ...parts), "utf8");
const matrix = JSON.parse(read("docs", "rc", "PLATFORM_RELEASE_MATRIX.json"));
const spec = JSON.parse(read("docs", "rc", "RC_PUBLIC_RELEASE_SMOKE.json"));
const schema = JSON.parse(read("docs", "rc", "RC_PUBLIC_RELEASE_SMOKE_REPORT.schema.json"));
const config = require(path.join(desktop, "electron-builder.config.cjs"));
const main = read("desktop", "main.js");
const worker = read("src", "mathtutor", "infrastructure", "verifier_worker.py");
const keychain = read("src", "mathtutor", "infrastructure", "keychain_secret_store.py");
const desktopApi = read("src", "mathtutor", "api", "desktop_api.py");
const windowsAdapter = read("desktop", "scripts", "run-windows-release-smoke.ps1");
const linuxAdapter = read("desktop", "scripts", "run-linux-release-smoke.sh");
const macosAdapter = read("desktop", "scripts", "run-macos-public-release-smoke.js");
const sharedDriver = read("desktop", "scripts", "rc-public-release-smoke.js");
const secretProbe = read("desktop", "scripts", "rc-secret-store-sentinel.py");

const capabilities = [
  "Build", "Package", "Install", "Launch", "SecretStore", "Verifier Worker",
  "SQLite", "Native File Picker", "Document Import", "Model Config", "Backup",
  "Restore", "Restart", "Practice E2E", "Uninstall", "Upgrade",
];

test("machine matrix uses the closed status vocabulary and complete capability set", () => {
  const allowed = new Set(["PASS", "FAIL", "PARTIAL", "UNTESTED", "UNSUPPORTED"]);
  assert.deepEqual(matrix.allowed_statuses, [...allowed]);
  for (const platform of Object.values(matrix.platforms)) {
    assert.deepEqual(Object.keys(platform.capabilities), capabilities);
    for (const cell of Object.values(platform.capabilities)) {
      assert.ok(allowed.has(cell.status), cell.status);
      assert.equal(typeof cell.reason_code, "string");
    }
  }
});

test("Windows and Linux never derive support from packaging configuration", () => {
  for (const name of ["windows_x64", "linux_x64"]) {
    const platform = matrix.platforms[name];
    assert.equal(platform.public_release_status, "UNTESTED");
    assert.equal(platform.target_machine, null);
    for (const cell of Object.values(platform.capabilities)) {
      assert.deepEqual(cell, { status: "UNTESTED", reason_code: "NO_TARGET_MACHINE" });
    }
  }
  assert.deepEqual(matrix.platforms.windows_x64.authenticode, {
    status: "UNTESTED", reason_code: "MISSING_EXTERNAL_CREDENTIAL",
  });
});

test("NSIS and AppImage are the only configured Windows/Linux artifacts", () => {
  assert.deepEqual(config.win.target, [{ target: "nsis", arch: ["x64"] }]);
  assert.deepEqual(config.linux.target, [{ target: "AppImage", arch: ["x64"] }]);
  assert.equal(config.nsis.perMachine, false);
  assert.equal(config.nsis.allowToChangeInstallationDirectory, true);
  assert.doesNotMatch(JSON.stringify(config.linux), /deb/i);
});

test("packaged runtime relocation is explicit but target validation remains external", () => {
  assert.match(main, /process\.platform === "win32"/);
  assert.match(main, /"python-runtime", "python\.exe"/);
  assert.match(main, /"python-runtime", "bin", "python"/);
  assert.match(main, /PYTHONPATH: IS_PACKAGED \? path\.join\(RESOURCES_DIR, "python-app"\)/);
  assert.match(main, /packaged self-contained import failed/);
  assert.match(windowsAdapter, /Relocated Python missing/);
  assert.match(linuxAdapter, /RELOCATED_RUNTIME_MISSING/);
});

test("worker requests spawn and no fork-only desktop path is claimed", () => {
  assert.match(worker, /mp_context: str = "spawn"/);
  assert.match(worker, /multiprocessing\.get_context\(mp_context\)/);
  assert.match(worker, /process\.terminate\(\)/);
  assert.match(worker, /process\.kill\(\)/);
  assert.doesNotMatch(worker, /get_context\(["']fork["']\)/);
  assert.match(main, /child\.kill\("SIGTERM"\)/);
});

test("Credential Manager and secret-tool contracts are fail closed and secret-free", () => {
  assert.match(keychain, /CredWriteW/);
  assert.match(keychain, /CredReadW/);
  assert.match(keychain, /CredDeleteW/);
  assert.match(keychain, /value\.encode\("utf-16-le"\)/);
  assert.match(keychain, /secret-tool/);
  assert.match(keychain, /stdin = f"\{value\}\\n"\.encode/);
  assert.match(keychain, /credential store CLI missing/);
  assert.match(desktopApi, /return "degraded"/);
  assert.doesNotMatch(keychain.toLowerCase(), /plaintext fallback enabled/);
  assert.match(secretProbe, /secrets\.token_urlsafe/);
  assert.doesNotMatch(secretProbe, /add_argument\("--value"/);
});

test("native picker stays explicit and single-file only", () => {
  assert.match(main, /dialog\s*\.showOpenDialog/);
  assert.match(main, /properties: \["openFile"\]/);
  assert.doesNotMatch(main, /openDirectory/);
  assert.match(main, /MAX_PICK_BYTES = 20 \* 1024 \* 1024/);
});

test("one shared 19-step business specification drives every target adapter", () => {
  assert.equal(spec.spec_id, "RC_PUBLIC_RELEASE_SMOKE");
  assert.equal(spec.required_steps.length, 19);
  assert.deepEqual(spec.required_steps.map((step) => step.ordinal), Array.from({ length: 19 }, (_, i) => i + 1));
  assert.match(windowsAdapter, /rc-public-release-smoke\.js/);
  assert.match(linuxAdapter, /rc-public-release-smoke\.js/);
  assert.match(macosAdapter, /rc-public-release-smoke\.js/);
  assert.equal(spec.platform_adapters.macos_arm64, "desktop/scripts/run-macos-public-release-smoke.js");
  assert.match(sharedDriver, /legacy "17\/17" line alone is/);
  assert.match(sharedDriver, /ASSERTION_NOT_IMPLEMENTED/);
  assert.doesNotMatch(windowsAdapter, /submit_problem|practice-offer|child-cycle/);
  assert.doesNotMatch(linuxAdapter, /submit_problem|practice-offer|child-cycle/);
  assert.doesNotMatch(macosAdapter, /submit_problem|practice-offer|child-cycle/);
});

test("report schema cannot represent a target-machine PASS without 19 assertions", () => {
  assert.equal(schema.properties.target_machine.const, true);
  assert.equal(schema.properties.steps.minItems, 19);
  assert.equal(schema.properties.steps.maxItems, 19);
  assert.equal(schema.properties.secret_store.properties.plaintext_fallback.const, false);
  assert.deepEqual(schema.properties.status.enum, ["PASS", "FAIL", "PARTIAL"]);
});

test("uninstall adapters assert user-data retention and never claim credential deletion", () => {
  assert.match(windowsAdapter, /uninstall-must-preserve\.txt/);
  assert.match(windowsAdapter, /uninstall_preserves_user_data/);
  assert.match(linuxAdapter, /uninstall-must-preserve\.txt/);
  assert.match(linuxAdapter, /uninstall_preserves_user_data/);
  assert.doesNotMatch(`${windowsAdapter}\n${linuxAdapter}`, /delete.*credential/i);
});
