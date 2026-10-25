"use strict";
const { secretRedactor } = require("./transport-boundary");

function claimSingleInstance(app, windows) {
  if (!app.requestSingleInstanceLock()) {
    app.quit();
    return false;
  }
  app.on("second-instance", () => {
    const win = windows()[0];
    if (!win) return; // the first instance is still starting
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  });
  return true;
}

/** Own the spawn error and retain a bounded diagnostic tail after exit. */
function monitorService(child, writeLog = () => {}, secret = "") {
  let stopped = false;
  let reason = "";
  let stderr = "";
  const stdoutLog = secretRedactor(secret, writeLog);
  const stderrLog = secretRedactor(secret, writeLog);
  child.stdout?.on("data", data => stdoutLog.write(data));
  child.stdout?.on("end", () => stdoutLog.end());
  child.stderr?.on("data", (data) => {
    stderr = (stderr + String(data)).slice(-8192);
    stderrLog.write(data);
  });
  child.stderr?.on("end", () => stderrLog.end());
  child.on("error", (error) => {
    stopped = true;
    reason = error.message;
    writeLog(`spawn error: ${reason}\n`);
  });
  child.on("exit", (code, signal) => {
    stopped = true;
    reason = signal ? `signal=${signal}` : `exit=${code}`;
    writeLog(`process stopped: ${reason}\n`);
  });
  return {
    assertRunning(what) {
      if (stopped) {
        const message = `${what}已退出（${reason}）。${stderr ? `\n${stderr.trim().slice(-2000)}` : ""}`;
        throw new Error(secret ? message.split(secret).join("[redacted]") : message);
      }
    },
  };
}

async function waitForService(url, { timeoutMs, what, services = [], intervalMs = 300, headers }) {
  const deadline = Date.now() + timeoutMs;
  const check = () => services.forEach((service) => service.assertRunning(what));
  while (Date.now() < deadline) {
    check();
    let ready = false;
    try {
      const response = await fetch(url, { headers, signal: AbortSignal.timeout(Math.max(1, Math.min(1000, deadline - Date.now()))) });
      ready = response.ok;
      await response.body?.cancel();
    } catch {
      // Not listening yet, or a connection that never sent a response.
    }
    check();
    if (ready) return true;
    await new Promise((resolve) => setTimeout(resolve, Math.min(intervalMs, Math.max(0, deadline - Date.now()))));
  }
  check();
  throw new Error(`${what}在 ${Math.round(timeoutMs / 1000)} 秒内未就绪。`);
}

module.exports = { claimSingleInstance, monitorService, waitForService };
