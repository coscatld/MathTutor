#!/usr/bin/env node
"use strict";

/**
 * Shared RC_PUBLIC_RELEASE_SMOKE business driver.
 *
 * Platform adapters own install, signature, SecretStore and uninstall probes.
 * Both adapters invoke this file for the product assertions, so Windows and
 * Linux cannot silently drift into different teaching/persistence smoke flows.
 * Missing assertions remain PARTIAL/UNTESTED; a legacy "17/17" line alone is
 * deliberately insufficient for an RC_PUBLIC_RELEASE_SMOKE PASS.
 */

const { spawn } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const repo = path.resolve(__dirname, "..", "..");
const specPath = path.join(repo, "docs", "rc", "RC_PUBLIC_RELEASE_SMOKE.json");

function usage(message) {
  if (message) process.stderr.write(`${message}\n`);
  process.stderr.write(
    "Usage: node rc-public-release-smoke.js --platform darwin|win32|linux " +
      "--artifact <installed-exe-or-AppImage> --secret-report <json> --output <json> " +
      "[--container-artifact <installer-or-DMG>]\n",
  );
  process.exit(64);
}

function argumentsMap(argv) {
  const result = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key || !key.startsWith("--") || value === undefined) usage("Malformed arguments");
    result[key.slice(2)] = value;
  }
  return result;
}

function isolatedEnvironment() {
  // Retain platform-critical variables such as SystemRoot, TEMP, DBUS address
  // and DISPLAY, but prohibit checkout/editable Python resolution.
  const environment = { ...process.env };
  for (const key of [
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "CONDA_DEFAULT_ENV",
    "ELECTRON_RUN_AS_NODE",
  ]) delete environment[key];
  return environment;
}

function runArtifact(executable, mode, cwd) {
  return new Promise((resolve) => {
    const child = spawn(executable, [mode], {
      cwd,
      env: isolatedEnvironment(),
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    let output = "";
    let settled = false;
    for (const stream of [child.stdout, child.stderr]) {
      stream.on("data", (chunk) => {
        const value = String(chunk);
        output += value;
        process.stdout.write(value);
      });
    }
    child.once("error", (error) => {
      if (settled) return;
      settled = true;
      resolve({ code: -1, signal: null, output, spawn_error: error.code || "SPAWN_FAILED" });
    });
    child.once("exit", (code, signal) => {
      if (settled) return;
      settled = true;
      resolve({ code, signal, output, spawn_error: null });
    });
  });
}

function sha256(file) {
  return new Promise((resolve, reject) => {
    const hash = crypto.createHash("sha256");
    const stream = fs.createReadStream(file);
    stream.on("error", reject);
    stream.on("data", (chunk) => hash.update(chunk));
    stream.on("end", () => resolve(hash.digest("hex")));
  });
}

function recordedPasses(output) {
  const names = new Set();
  for (const match of output.matchAll(/smoke-full: PASS ([a-z0-9-]+)/g)) names.add(match[1]);
  return names;
}

function assertion(status, evidence, reasonCode) {
  const value = { status, evidence };
  if (reasonCode) value.reason_code = reasonCode;
  return value;
}

function buildSteps(spec, production, full, secret) {
  const pass = recordedPasses(full.output);
  const productExitOk = production.code === 0 && full.code === 0;
  const productionAuth = production.output.includes("PASS auth-on register/login/readiness");
  const mapped = {
    launch_app: productExitOk && productionAuth
      ? assertion("PASS", "production auth-on launch and shared product smoke exited 0")
      : assertion("FAIL", `production_exit=${production.code}; full_exit=${full.code}`, "ARTIFACT_LAUNCH_FAILED"),
    bootstrap: pass.has("bootstrap")
      ? assertion("PASS", "shared smoke bootstrap assertion")
      : assertion("UNTESTED", "no named bootstrap assertion", "ASSERTION_NOT_OBSERVED"),
    database_migration: pass.has("database-migration")
      ? assertion("PASS", "frozen migration-head assertion")
      : assertion("PARTIAL", "startup succeeded but frozen migration head was not asserted", "MIGRATION_HEAD_NOT_ASSERTED"),
    secret_store_sentinel: assertion(
      secret.status || "UNTESTED",
      secret.status === "PASS" ? "platform sentinel write/read/delete/final-missing" : "platform sentinel did not pass",
      secret.reason_code,
    ),
    submit_problem: pass.has("cycle-solve") || pass.has("submit-problem")
      ? assertion("PASS", "product cycle accepted a supported problem")
      : assertion("UNTESTED", "submit problem assertion absent", "ASSERTION_NOT_OBSERVED"),
    verifier_worker: pass.has("verifier-worker") || pass.has("cycle-solve")
      ? assertion("PASS", "mandatory worker-backed product flow completed")
      : assertion("UNTESTED", "worker assertion absent", "ASSERTION_NOT_OBSERVED"),
    correct_attempt: pass.has("correct-attempt") || pass.has("cycle-solve")
      ? assertion("PASS", "correct attempt reached solved state")
      : assertion("UNTESTED", "correct-attempt assertion absent", "ASSERTION_NOT_OBSERVED"),
    incorrect_or_partial_attempt: pass.has("incorrect-attempt") || pass.has("partial-attempt")
      ? assertion("PASS", "incorrect/partial assessment and non-leak assertion")
      : assertion("UNTESTED", "legacy 17-step smoke has no incorrect/partial attempt assertion", "ASSERTION_NOT_IMPLEMENTED"),
    practice_offer: pass.has("practice-offer")
      ? assertion("PASS", "active offer emitted")
      : assertion("UNTESTED", "practice-offer assertion absent", "ASSERTION_NOT_OBSERVED"),
    accept_practice: pass.has("offer-accept")
      ? assertion("PASS", "offer accepted")
      : assertion("UNTESTED", "offer-accept assertion absent", "ASSERTION_NOT_OBSERVED"),
    child_cycle: pass.has("child-cycle") && pass.has("child-judge")
      ? assertion("PASS", "child cycle created and judged")
      : assertion("UNTESTED", "child-cycle assertions incomplete", "ASSERTION_NOT_OBSERVED"),
    explicit_document_import: pass.has("document-import")
      ? assertion("PASS", "explicit test document imported through product API")
      : assertion("UNTESTED", "document import assertion absent", "ASSERTION_NOT_OBSERVED"),
    document_retrieval: pass.has("document-retrieval")
      ? assertion("PASS", "imported content retrieved through lexical baseline")
      : assertion("UNTESTED", "legacy 17-step smoke imports but does not retrieve the document", "ASSERTION_NOT_IMPLEMENTED"),
    memory_crud: pass.has("memory-crud-complete")
      ? assertion("PASS", "complete memory CRUD assertion")
      : pass.has("memory-crud")
        ? assertion("PARTIAL", "create/list passed; update-or-disable/delete not asserted", "CRUD_INCOMPLETE")
        : assertion("UNTESTED", "memory assertion absent", "ASSERTION_NOT_OBSERVED"),
    backup: pass.has("backup-create") && pass.has("backup-verify")
      ? assertion("PASS", "backup create and verify assertions")
      : assertion("UNTESTED", "backup create/verify assertions incomplete", "ASSERTION_NOT_OBSERVED"),
    restart: pass.has("restart-health") && pass.has("restart-durability")
      ? assertion("PASS", "backend restart and durable state assertions")
      : assertion("UNTESTED", "restart assertions incomplete", "ASSERTION_NOT_OBSERVED"),
    restore: pass.has("backup-restore")
      ? assertion("PASS", "verified restore endpoint assertion")
      : assertion("UNTESTED", "restore assertion absent", "ASSERTION_NOT_OBSERVED"),
    post_restore_solve: pass.has("post-restore-solve")
      ? assertion("PASS", "new solve completed after restore")
      : assertion("UNTESTED", "legacy 17-step smoke does not solve after restore", "ASSERTION_NOT_IMPLEMENTED"),
    clean_shutdown: pass.has("clean-shutdown")
      ? assertion("PASS", "all child processes exited and no orphan remained")
      : assertion("PARTIAL", "artifact exited, but process-tree orphan absence was not asserted", "PROCESS_TREE_NOT_ASSERTED"),
  };
  return spec.required_steps.map(({ id }) => ({ id, ...mapped[id] }));
}

(async () => {
  const args = argumentsMap(process.argv.slice(2));
  for (const required of ["platform", "artifact", "secret-report", "output"]) {
    if (!args[required]) usage(`Missing --${required}`);
  }
  if (!["win32", "linux", "darwin"].includes(args.platform)) usage("Unsupported --platform");
  if (process.platform !== args.platform) {
    usage(`Target adapter mismatch: requested ${args.platform}, running ${process.platform}`);
  }
  const artifact = path.resolve(args.artifact);
  if (!fs.statSync(artifact).isFile()) usage(`Artifact is not a file: ${artifact}`);
  const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
  const secret = JSON.parse(fs.readFileSync(path.resolve(args["secret-report"]), "utf8"));
  if (secret.plaintext_fallback !== false) throw new Error("Secret report must assert plaintext_fallback=false");

  const startedAt = new Date().toISOString();
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-rc-public-smoke-"));
  let production;
  let full;
  try {
    production = await runArtifact(artifact, "--smoke-production", work);
    full = await runArtifact(artifact, "--smoke-full", work);
  } finally {
    fs.rmSync(work, { recursive: true, force: true });
  }
  const steps = buildSteps(spec, production, full, secret);
  const status = steps.some((step) => ["FAIL", "BLOCKED"].includes(step.status))
    ? "FAIL"
    : steps.every((step) => step.status === "PASS")
      ? "PASS"
      : "PARTIAL";
  const stat = fs.statSync(artifact);
  const report = {
    schema_version: 1,
    spec_id: spec.spec_id,
    spec_version: spec.spec_version,
    platform: process.platform,
    arch: process.arch,
    target_machine: true,
    artifact: { path: artifact, size_bytes: stat.size, sha256: await sha256(artifact) },
    started_at: startedAt,
    completed_at: new Date().toISOString(),
    status,
    steps,
    secret_store: {
      status: secret.status,
      reason_code: secret.reason_code || "",
      plaintext_fallback: false,
    },
    platform_checks: {
      shared_driver: "desktop/scripts/rc-public-release-smoke.js",
      legacy_smoke_exit_code: full.code,
      production_smoke_exit_code: production.code,
      legacy_17_of_17_observed: /完成 — 17\/17 步通过/.test(full.output),
    },
  };
  if (args["container-artifact"]) {
    const container = path.resolve(args["container-artifact"]);
    const containerStat = fs.statSync(container);
    if (!containerStat.isFile()) usage(`Container artifact is not a file: ${container}`);
    report.container_artifact = {
      path: container,
      size_bytes: containerStat.size,
      sha256: await sha256(container),
    };
  }
  fs.writeFileSync(path.resolve(args.output), `${JSON.stringify(report, null, 2)}\n`, { mode: 0o600 });
  process.stdout.write(`RC_PUBLIC_RELEASE_SMOKE=${status}; report=${path.resolve(args.output)}\n`);
  process.exitCode = status === "PASS" ? 0 : status === "PARTIAL" ? 2 : 1;
})().catch((error) => {
  process.stderr.write(`${error.stack || error}\n`);
  process.exit(1);
});
