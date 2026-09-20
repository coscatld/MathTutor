"use strict";

const { execFileSync, spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const desktop = path.resolve(__dirname, "..");
const pkg = JSON.parse(fs.readFileSync(path.join(desktop, "package.json"), "utf8"));
const dmg = path.join(desktop, "dist", `MathTutor-${pkg.version}-mac-arm64.dmg`);
const appRoot = path.join(desktop, "dist", "mac-arm64", "MathTutor.app");
const appExecutable = path.join(appRoot, "Contents", "MacOS", "MathTutor");
const evidencePath = path.join(desktop, "dist", "package-smoke-evidence.json");
const keychainProbe = path.join(desktop, "scripts", "macos-keychain-sentinel.py");
const migrationRelative = path.join("Contents", "Resources", "python-app", "mathtutor", "infrastructure", "migrations", "versions", "023_citation_receipts.py");
for (const required of [dmg, appExecutable, path.join(appRoot, migrationRelative)]) {
  if (!fs.existsSync(required)) throw new Error(`Packaged artifact missing: ${required}`);
}

function cleanEnvironment() {
  return {
    PATH: process.env.PATH || "/usr/bin:/bin",
    HOME: process.env.HOME || os.homedir(),
    TMPDIR: process.env.TMPDIR || os.tmpdir(),
    LANG: process.env.LANG || "C.UTF-8",
    PYTHONDONTWRITEBYTECODE: "1",
  };
}

function run(executable, args, cwd, extraEnvironment = {}) {
  return new Promise((resolve) => {
    const child = spawn(executable, args, {
      cwd,
      env: { ...cleanEnvironment(), ...extraEnvironment },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let output = "";
    for (const stream of [child.stdout, child.stderr]) {
      stream.on("data", (chunk) => {
        const text = String(chunk);
        output += text;
        process.stdout.write(text);
      });
    }
    child.on("exit", (code, signal) => resolve({ code, signal, output }));
  });
}

async function runKeychainSentinel(packagedApp, cwd) {
  const resources = path.join(packagedApp, "Contents", "Resources");
  const python = path.join(resources, "python-runtime", "bin", "python");
  const pythonApp = path.join(resources, "python-app");
  const result = await run(python, [keychainProbe], cwd, {
    PYTHONPATH: pythonApp,
    PYTHONNOUSERSITE: "1",
    PYTHONDONTWRITEBYTECODE: "1",
  });
  let evidence = null;
  try {
    evidence = JSON.parse(result.output.trim().split(/\r?\n/).at(-1));
  } catch {
    throw new Error("macOS Keychain sentinel emitted invalid evidence");
  }
  if (result.code !== 0 || evidence.status !== "PASS" || !evidence.cleanup_complete ||
      evidence.secret_in_argv !== false || evidence.plaintext_fallback !== false) {
    throw new Error(`macOS Keychain sentinel failed: ${JSON.stringify(evidence)}`);
  }
  return { ...evidence, exit_code: result.code };
}

function metric(output, name) {
  const match = output.match(new RegExp(`${name}=(\\d+)`));
  return match ? Number(match[1]) : null;
}

function fullResult(result) {
  return {
    exit_code: result.code,
    signal: result.signal,
    backend_ready_ms: metric(result.output, "backend_ready_ms"),
    frontend_ready_ms: metric(result.output, "frontend_ready_ms"),
    smoke_steps: result.output.match(/完成 — (\d+)\/(\d+) 步通过/)?.slice(1).map(Number) || null,
    self_contained_import: result.output.includes("SELF_CONTAINED_IMPORT="),
    local_provider: result.output.includes("ASSERT PASS local-provider"),
  };
}

function productionResult(result) {
  return {
    exit_code: result.code,
    signal: result.signal,
    auth_on_register_login_readiness: result.output.includes("PASS auth-on register/login/readiness"),
    backend_ready_ms: metric(result.output, "backend_ready_ms"),
    frontend_ready_ms: metric(result.output, "frontend_ready_ms"),
    self_contained_import: result.output.includes("SELF_CONTAINED_IMPORT="),
  };
}

function auditReleaseLogs(namedOutputs) {
  const forbidden = [
    ["authorization_header", /authorization\s*:/i],
    ["bearer_token", /bearer\s+[A-Za-z0-9._~+\/-]+/i],
    ["document_raw_text", /一元一次方程：移项时两边做相同运算。/],
    ["personal_memory_value", /逐步提示/],
    ["hidden_reasoning", /hidden[_ -]?reasoning/i],
    ["attestation_payload", /attestation[_ -]?payload/i],
  ];
  const matches = [];
  for (const [stream, output] of Object.entries(namedOutputs)) {
    for (const [kind, pattern] of forbidden) {
      if (pattern.test(output)) matches.push({ stream, kind });
    }
  }
  return {
    status: matches.length === 0 ? "PASS" : "FAIL",
    checked_streams: Object.keys(namedOutputs),
    forbidden_matches: matches,
    keychain_value_not_logged: true,
    installer_log: "NOT_APPLICABLE_DMG_NO_INSTALLER_LOG",
  };
}

(async () => {
  const startedAt = new Date().toISOString();
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-package-runner-"));
  const appCwd = path.join(work, "app-cwd");
  const mountedCwd = path.join(work, "dmg-cwd");
  const mountpoint = path.join(work, "volume");
  for (const dir of [appCwd, mountedCwd, mountpoint]) fs.mkdirSync(dir);
  let mounted = false;
  let keychainSentinel = null;
  let appProduction = { code: null, signal: null, output: "" };
  let appFull = { code: null, signal: null, output: "" };
  let dmgFull = { code: null, signal: null, output: "" };
  try {
    keychainSentinel = await runKeychainSentinel(appRoot, appCwd);
    appProduction = await run(appExecutable, ["--smoke-production"], appCwd);
    if (appProduction.code !== 0) throw new Error("packaged production-profile smoke failed");
    appFull = await run(appExecutable, ["--smoke-full"], appCwd);
    if (appFull.code !== 0) throw new Error("packaged full smoke failed");
    execFileSync("hdiutil", ["attach", "-nobrowse", "-readonly", "-mountpoint", mountpoint, dmg], { stdio: "inherit" });
    mounted = true;
    const mountedExecutable = path.join(mountpoint, "MathTutor.app", "Contents", "MacOS", "MathTutor");
    dmgFull = await run(mountedExecutable, ["--smoke-full"], mountedCwd);
    if (dmgFull.code !== 0) throw new Error("DMG mounted full smoke failed");
  } finally {
    if (mounted) {
      try { execFileSync("hdiutil", ["detach", mountpoint], { stdio: "inherit" }); } catch {}
    }
  }

  const dmgBytes = fs.readFileSync(dmg);
  const dmgSha256 = crypto.createHash("sha256").update(dmgBytes).digest("hex");
  const currentRun = {
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    macos_keychain_sentinel: keychainSentinel,
    app_production_launch: productionResult(appProduction),
    app_full_smoke: fullResult(appFull),
    dmg_readonly_mount_full_smoke: fullResult(dmgFull),
    release_log_audit: auditReleaseLogs({
      keychain_sentinel: keychainSentinel ? JSON.stringify(keychainSentinel) : "",
      app_production: appProduction.output,
      app_full: appFull.output,
      dmg_full: dmgFull.output,
    }),
  };
  const gates = [
    currentRun.macos_keychain_sentinel?.status === "PASS",
    currentRun.macos_keychain_sentinel?.cleanup_complete === true,
    currentRun.app_production_launch.auth_on_register_login_readiness,
    currentRun.app_production_launch.self_contained_import,
    currentRun.app_full_smoke.self_contained_import,
    currentRun.app_full_smoke.local_provider,
    currentRun.app_full_smoke.smoke_steps?.join("/") === "17/17",
    currentRun.dmg_readonly_mount_full_smoke.smoke_steps?.join("/") === "17/17",
    currentRun.release_log_audit.status === "PASS",
  ];
  if (!gates.every(Boolean)) throw new Error(`evidence gate failed: ${JSON.stringify(currentRun)}`);
  let consecutiveRunResults = [];
  try {
    const previous = JSON.parse(fs.readFileSync(evidencePath, "utf8"));
    if (previous.schema_version === 2 && previous.dmg_sha256 === dmgSha256 &&
        Array.isArray(previous.consecutive_run_results)) {
      consecutiveRunResults = previous.consecutive_run_results;
    }
  } catch {}
  consecutiveRunResults.push(currentRun);
  const evidence = {
    schema_version: 2,
    started_at: consecutiveRunResults[0].started_at,
    completed_at: currentRun.completed_at,
    platform: process.platform,
    arch: process.arch,
    artifact: path.relative(desktop, appExecutable),
    dmg_artifact: path.relative(desktop, dmg),
    dmg_size_bytes: dmgBytes.length,
    dmg_sha256: dmgSha256,
    packaged_migration_head: "023",
    packaged_migration_file: migrationRelative.split(path.sep).join("/"),
    runner_isolation: { cwd_outside_checkout: true, inherited_pythonpath: false, inherited_conda_or_virtualenv: false },
    consecutive_runs: consecutiveRunResults.length,
    consecutive_run_results: consecutiveRunResults,
    app_production_launch: currentRun.app_production_launch,
    app_full_smoke: currentRun.app_full_smoke,
    dmg_readonly_mount_full_smoke: currentRun.dmg_readonly_mount_full_smoke,
    release_log_audit: currentRun.release_log_audit,
    keychain_sentinel: currentRun.macos_keychain_sentinel,
    performance_claim: "Each run is n=1; observed values are not a percentile distribution.",
  };
  fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
