"use strict";

// Exercise a writable installed copy, without inherited Python flags. A
// readonly DMG alone cannot reveal caches that corrupt a resource seal.
const { execFileSync, spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { verifyApplication } = require("./verify-macos-signature.cjs");

async function main() {
  if (process.platform !== "darwin") throw new Error("macOS required");
  const source = path.resolve(process.argv[2]);
  const reportFile = path.resolve(process.argv[3]);
  verifyApplication(source);
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "mathtutor-sealed-startup-"));
  const app = path.join(work, "中文安装目录", "MathTutor.app");
  fs.mkdirSync(path.dirname(app));
  const cwd = path.join(work, "outside-checkout");
  fs.mkdirSync(cwd);
  const env = {};
  for (const key of ["PATH", "HOME", "TMPDIR", "LANG"]) if (process.env[key]) env[key] = process.env[key];
  let server;
  const checks = {};
  try {
    execFileSync("ditto", [source, app]);
    verifyApplication(app);
    const executable = path.join(app, "Contents", "MacOS", "MathTutor");
    const full = execFileSync(executable, ["--smoke-full"], { cwd, env, encoding: "utf8", timeout: 180000 });
    if (!/完成 — 17\/17 步通过/.test(full)) throw new Error("Writable-copy business smoke failed");
    checks.business_smoke = "PASS";
    verifyApplication(app);
    checks.signature_after_python_import_and_business = "PASS";

    // Model a browser-origin quarantine explicitly. The per-app removal is
    // the documented user trust action, never a Gatekeeper PASS or a global
    // security-setting change. Only this verified disposable copy is touched.
    execFileSync("xattr", ["-w", "com.apple.quarantine", "0083;00000000;MathTutorVerification;", app]);
    const quarantine = execFileSync("xattr", ["-p", "com.apple.quarantine", app], { encoding: "utf8" });
    if (!quarantine.includes("MathTutorVerification")) throw new Error("Quarantine fixture missing");
    execFileSync("xattr", ["-dr", "com.apple.quarantine", app]);
    const launchLog = path.join(work, "launchservices.log");
    execFileSync("open", ["-W", "-n", "-g", "--stdout", launchLog, "--stderr", launchLog, app, "--args", "--smoke-production"], { cwd, env, timeout: 180000 });
    if (!fs.readFileSync(launchLog, "utf8").includes("PASS auth-on register/login/readiness")) throw new Error("LaunchServices startup failed");
    checks.launchservices_after_explicit_per_app_trust = "PASS";
    verifyApplication(app);
    checks.signature_after_launchservices = "PASS";

    const resources = path.join(app, "Contents", "Resources");
    const port = await new Promise(resolve => {
      const listener = net.createServer();
      listener.listen(0, "127.0.0.1", () => {
        const number = listener.address().port;
        listener.close(() => resolve(number));
      });
    });
    server = spawn(executable, [path.join(resources, "web", "server.js")], {
      cwd, env: { ...env, ELECTRON_RUN_AS_NODE: "1", PORT: String(port), HOSTNAME: "127.0.0.1", NODE_PATH: path.join(resources, "web", "vendor_modules") },
      stdio: "ignore",
    });
    const base = `http://127.0.0.1:${port}`;
    let ready = false;
    for (let i = 0; i < 100; i++) {
      if (server.exitCode !== null) throw new Error("Packaged frontend exited");
      try { ready = (await fetch(`${base}/math-tutor`, { signal: AbortSignal.timeout(1000) })).ok; } catch {}
      if (ready) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    if (!ready) throw new Error("Packaged frontend not ready");
    for (const route of ["/", "/login", "/register", "/math-tutor/knowledge", "/math-tutor/community", "/math-tutor/settings"]) {
      const response = await fetch(base + route, { signal: AbortSignal.timeout(10000) });
      if (!response.ok) throw new Error(`Packaged page failed: ${route} ${response.status}`);
      await response.arrayBuffer();
    }
    checks.packaged_page_requests = "PASS";
    verifyApplication(app);
    checks.signature_after_page_requests = "PASS";
    fs.writeFileSync(reportFile, JSON.stringify({
      schema_version: 1, status: "PASS", checks,
      writable_copy: true, chinese_install_directory: true,
      inherited_python_flags: false, global_gatekeeper_settings_changed: false,
      default_gatekeeper_approval: false, trust_action: "REMOVE_QUARANTINE_FROM_VERIFIED_DISPOSABLE_APP_ONLY",
      paid_model_calls: 0,
    }, null, 2) + "\n");
    process.stdout.write(`SEALED_STARTUP=PASS; report=${reportFile}\n`);
  } catch (error) {
    const diagnosis = spawnSync("codesign", ["--verify", "--deep", "--strict", "--verbose=2", app], { encoding: "utf8" });
    fs.writeFileSync(`${reportFile}.failure.log`, JSON.stringify(checks) + "\n" + diagnosis.stderr);
    throw error;
  } finally {
    if (server && server.exitCode === null) {
      await new Promise(resolve => {
        const timer = setTimeout(() => server.kill("SIGKILL"), 5000);
        server.once("exit", () => { clearTimeout(timer); resolve(); });
        server.kill("SIGTERM");
      });
    }
    fs.rmSync(work, { recursive: true, force: true });
  }
}
main().catch(error => { process.stderr.write(String(error.stderr || error.stack) + "\n"); process.exitCode = 1; });
