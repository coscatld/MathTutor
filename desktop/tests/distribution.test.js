"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const desktop = path.resolve(__dirname, "..");
const main = fs.readFileSync(path.join(desktop, "main.js"), "utf8");
const config = require(path.join(desktop, "electron-builder.config.cjs"));

test("packaged smoke follows independent recommendations without closing the parent", () => {
  assert.match(main, /!states\.includes\("practice_offered"\)/);
  assert.match(main, /parent\.body\.state === "solved"/);
  assert.doesNotMatch(main, /parent\.body\.state === "closed"/);
  assert.match(main, /3x \+ 1 = 10/);
  assert.match(main, /"child-judge", judgedStates\.includes\("solved"\)/);
  const migration = fs.readFileSync(path.join(desktop, "../src/mathtutor/infrastructure/migrate.py"), "utf8")
    .match(/MIGRATION_HEAD = "([0-9]+)"/)[1];
  assert.ok(main.includes(`frozen === "${migration}"`));
});

test("distribution keeps mutable data under Electron userData", () => {
  assert.match(main, /app\.getPath\("userData"\)/);
  assert.match(main, /MATHTUTOR_DB_PATH: dataLayout\.database/);
  assert.doesNotMatch(main, /cwd is pinned to the desktop dir/);
});

test("package contains standalone web, Python application and runtime", () => {
  const targets = config.extraResources.map((item) => item.to);
  assert.deepEqual(targets, [
    "web",
    "web/.next-mathtutor/static",
    "web/vendor_modules",
    "python-app/mathtutor",
    "python-runtime",
    "licenses/LICENSE",
    "licenses/THIRD_PARTY_NOTICES.md",
  ]);
  assert.equal(config.asar, true);
  assert.ok(config.extraResources[0].filter.includes("!**/.next-mathtutor/node_modules/rimraf-*"));
  assert.match(config.extraResources[1].from, /web[\/\\]\.next-mathtutor[\/\\]static$/);
  assert.match(main, /verifyFrontendAssets\(`\$\{frontendUrl\}\/math-tutor`\)/);
});

test("platform targets stay intentionally narrow", () => {
  assert.equal(config.mac.target[0].target, "dmg");
  assert.equal(config.win.target[0].target, "nsis");
  assert.equal(config.linux.target[0].target, "AppImage");
});

test("macOS package uses the MathTutor icon and a background-only frontend runtime", () => {
  assert.equal(config.mac.icon, "build/icon.icns");
  assert.equal(fs.existsSync(path.join(desktop, config.mac.icon)), true);
  assert.match(main, /utilityProcess\.fork\(runner, \[server\]/);
  assert.match(main, /serviceName: "MathTutor Web Runtime"/);
  assert.match(main, /if \(IS_PACKAGED\) \{\s*frontendChild = startPackagedFrontend/);
  const runner = fs.readFileSync(path.join(desktop, "runtime", "frontend-runner.js"), "utf8");
  assert.match(runner, /Module\._initPaths\(\)/);
});

test("macOS hardened-runtime entitlements stay minimal", () => {
  const entitlements = fs.readFileSync(path.join(desktop, "build", "entitlements.mac.plist"), "utf8");
  assert.match(entitlements, /com\.apple\.security\.cs\.allow-jit/);
  assert.doesNotMatch(entitlements, /allow-unsigned-executable-memory/);
  assert.doesNotMatch(entitlements, /disable-library-validation/);
  assert.doesNotMatch(entitlements, /get-task-allow/);
});

test("public macOS build signs bundled native Resources before the app", () => {
  assert.equal(config.afterPack, "scripts/after-pack-macos.cjs");
  const hook = fs.readFileSync(path.join(desktop, "scripts", "after-pack-macos.cjs"), "utf8");
  assert.match(hook, /MATHTUTOR_PUBLIC_RELEASE/);
  assert.match(hook, /requires explicit CSC_NAME/);
  assert.match(hook, /--options", "runtime"/);
  assert.match(hook, /codesign[\s\S]*--verify/);
});

test("ad-hoc packaging is explicit and cannot weaken the signed release configuration", () => {
  const { execFileSync, spawnSync } = require("node:child_process");
  const configPath = path.join(desktop, "electron-builder.config.cjs");
  const env = { ...process.env, MATHTUTOR_ADHOC_SIGN: "1", MATHTUTOR_PUBLIC_RELEASE: "0" };
  const mac = JSON.parse(execFileSync(process.execPath, ["-e", `process.stdout.write(JSON.stringify(require(${JSON.stringify(configPath)}).mac))`], { env, encoding: "utf8" }));
  assert.equal(mac.identity, "-");
  assert.equal(mac.hardenedRuntime, false);
  const invalid = spawnSync(process.execPath, ["-e", `require(${JSON.stringify(configPath)})`], {
    env: { ...env, MATHTUTOR_PUBLIC_RELEASE: "1" }, encoding: "utf8",
  });
  assert.notEqual(invalid.status, 0);
  assert.match(invalid.stderr, /cannot use ad-hoc signing/);
  assert.equal(config.afterSign, "scripts/after-sign-macos.cjs");
  assert.equal(config.artifactBuildCompleted, "scripts/verify-macos-dmg.cjs");
});

test("real macOS signature verifier rejects unsealed and modified applications", { skip: process.platform !== "darwin" }, () => {
  const { execFileSync } = require("node:child_process");
  const os = require("node:os");
  const { verifyApplication } = require("../scripts/verify-macos-signature.cjs");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-signature-test-"));
  const app = path.join(root, "Probe.app");
  const contents = path.join(app, "Contents");
  try {
    fs.mkdirSync(path.join(contents, "MacOS"), { recursive: true });
    fs.mkdirSync(path.join(contents, "Resources"));
    fs.copyFileSync("/usr/bin/true", path.join(contents, "MacOS", "Probe"));
    fs.writeFileSync(path.join(contents, "Info.plist"), `<?xml version="1.0"?><plist version="1.0"><dict><key>CFBundleExecutable</key><string>Probe</string><key>CFBundleIdentifier</key><string>com.mathtutor.signature-probe</string><key>CFBundlePackageType</key><string>APPL</string></dict></plist>`);
    const resource = path.join(contents, "Resources", "lesson.txt");
    fs.writeFileSync(resource, "original lesson");
    assert.throws(() => verifyApplication(app));
    execFileSync("codesign", ["--force", "--sign", "-", "--timestamp=none", app], { stdio: "pipe" });
    assert.equal(verifyApplication(app).status, "PASS");
    assert.equal(verifyApplication(app).identity, "AD_HOC");
    assert.throws(() => verifyApplication(app, { requireDeveloperId: true }), /Developer ID Application/);
    fs.writeFileSync(resource, "changed after signing");
    assert.throws(() => verifyApplication(app));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("API keys and embedding weights are not package resources", () => {
  const packageInputs = config.extraResources.map((resource) => ({
    from: resource.from,
    to: resource.to,
    // Deny patterns may safely name a forbidden package; only positive
    // resource selectors describe content that can enter the artifact.
    filter: (resource.filter || []).filter((pattern) => !pattern.startsWith("!")),
  }));
  const serialized = JSON.stringify(packageInputs).toLowerCase();
  assert.doesNotMatch(serialized, /api[_-]?key|secret|model.*weight|\.safetensors|\.onnx|\.gguf/);
});

test("normal GUI is login-free by architecture for Python and frontend", () => {
  assert.match(main, /const authEnabled = "0"/);
  assert.match(main, /\.\.\.authEnvironment\(authEnabled\)/);
  assert.match(main, /MATHTUTOR_AUTH_ENABLED: normalized, AUTH_ENABLED: normalized/);
});

test("runtime and data paths are centralized in the desktop infrastructure layer", () => {
  assert.match(main, /require\("\.\/runtime\/paths"\)/);
  assert.match(config.files.join("\n"), /runtime\/\*\*\/\*/);
});

test("package filters editable imports and bytecode caches", () => {
  const source = config.extraResources.find((item) => item.to === "python-app/mathtutor");
  const runtime = config.extraResources.find((item) => item.to === "python-runtime");
  assert.ok(source.filter.includes("!**/__pycache__/**"));
  assert.ok(runtime.filter.includes("!**/site-packages/__editable__.mathtutor-*.pth"));
  assert.ok(runtime.filter.includes("!**/site-packages/__editable___mathtutor_*_finder.py"));
  assert.ok(runtime.filter.includes("!**/site-packages/mathtutor/**"));
  assert.ok(runtime.filter.includes("!**/site-packages/mathtutor-*.dist-info/**"));
  assert.ok(runtime.filter.includes("!**/site-packages/deeptutor/**"));
  assert.match(main, /PYTHONPATH: IS_PACKAGED \? path\.join\(RESOURCES_DIR, "python-app"\)/);
  assert.doesNotMatch(main, /python-app"\), process\.env\.PYTHONPATH/);
});

test("release inventory comes from the readonly DMG and smoke cannot add bytecode", () => {
  const generator = fs.readFileSync(
    path.join(desktop, "scripts", "generate-macos-release-manifest.js"),
    "utf8",
  );
  const audit = fs.readFileSync(
    path.join(desktop, "scripts", "audit-package-surface.py"),
    "utf8",
  );
  const runner = fs.readFileSync(
    path.join(desktop, "scripts", "run-packaged-smoke.js"),
    "utf8",
  );
  assert.match(generator, /"attach", "-nobrowse", "-readonly", "-mountpoint"/);
  assert.match(generator, /PYTHONDONTWRITEBYTECODE: "1"/);
  assert.match(audit, /"readonly_dmg"/);
  assert.match(runner, /PYTHONDONTWRITEBYTECODE: "1"/);
});

test("packaged evidence runner clears inherited Python and conda state", () => {
  const runner = fs.readFileSync(path.join(desktop, "scripts", "run-packaged-smoke.js"), "utf8");
  assert.match(runner, /function cleanEnvironment\(\)/);
  assert.doesNotMatch(runner, /\.\.\.process\.env/);
  assert.match(runner, /--smoke-production/);
  assert.match(runner, /local_provider/);
  assert.match(runner, /dmg_sha256/);
  assert.match(runner, /packaged_migration_head/);
  assert.match(runner, /consecutive_run_results/);
  assert.match(runner, /consecutive_runs/);
  assert.match(runner, /runKeychainSentinel/);
  assert.match(runner, /cleanup_complete/);
});

test("real macOS Keychain sentinel always deletes twice without exposing its value", () => {
  const sentinel = fs.readFileSync(path.join(desktop, "scripts", "macos-keychain-sentinel.py"), "utf8");
  assert.match(sentinel, /value = secrets\.token_urlsafe/);
  assert.match(sentinel, /await store\.put\(key, value\)/);
  assert.match(sentinel, /hmac\.compare_digest/);
  assert.match(sentinel, /finally:/);
  assert.ok((sentinel.match(/await store\.delete\(key\)/g) || []).length >= 2);
  assert.match(sentinel, /missing_after_finally/);
  assert.doesNotMatch(sentinel, /print\([^\n]*value/);
});

test("local provider sentinel stays random and out of argv/log/config", () => {
  assert.match(main, /const smokeKey = `smoke-\$\{crypto\.randomBytes/);
  assert.match(main, /persisted\.includes\(smokeKey\)/);
  assert.doesNotMatch(main, /local-smoke-sentinel/);
  assert.doesNotMatch(main, /log\([^\n]*smokeKey/);
});

test("upgrade harness uses each artifact's own package namespace", () => {
  const runner = fs.readFileSync(
    path.join(desktop, "scripts", "run-macos-upgrade-smoke.js"),
    "utf8",
  );
  const probe = fs.readFileSync(
    path.join(desktop, "scripts", "macos-upgrade-probe.py"),
    "utf8",
  );
  assert.match(runner, /"seed",\s*oldNamespace/);
  assert.match(runner, /const oldNamespace = .*"mathtutor" : "deeptutor\.math_tutor"/);
  assert.match(runner, /"verify",\s*"mathtutor"/);
  assert.match(probe, /importlib\.import_module/);
  assert.match(probe, /choices=\("deeptutor\.math_tutor", "mathtutor"\)/);
});
