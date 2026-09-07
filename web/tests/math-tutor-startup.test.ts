import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { decideStartupRoute } from "../features/math-tutor/desktop/lib/startup";
import type { BootstrapPayload, DesktopSettings } from "../features/math-tutor/desktop/types";

const auth = { enabled: false, authenticated: true };
const bootstrap: BootstrapPayload = {
  readiness: "DEGRADED",
  phase: "READY",
  reason: "AI 模型未配置",
  steps: [],
};
const fresh: DesktopSettings = {
  preset_id: "",
  model: "",
  base_url: "",
  is_configured: false,
  onboarding_completed: false,
  key_masked: null,
};

test("fresh local desktop enters provider onboarding", () => {
  assert.equal(decideStartupRoute(auth, bootstrap, fresh), "onboarding");
});

test("configured, skipped, and key-removed restarts enter workspace", () => {
  assert.equal(decideStartupRoute(auth, bootstrap, {
    ...fresh,
    preset_id: "openai",
    is_configured: true,
    onboarding_completed: true,
    key_masked: "•••••••1234",
  }), "workspace");
  assert.equal(decideStartupRoute(auth, bootstrap, {
    ...fresh,
    onboarding_completed: true,
  }), "workspace");
});

test("auth-on server mode still redirects unauthenticated users", () => {
  assert.equal(decideStartupRoute(
    { enabled: true, authenticated: false },
    bootstrap,
    fresh,
  ), "login");
});

test("bootstrap waits for delayed backend and surfaces hard blocks", () => {
  assert.equal(decideStartupRoute(null, null, null), "waiting");
  assert.equal(decideStartupRoute(auth, { ...bootstrap, readiness: "BLOCKED" }, fresh), "blocked");
});

test("normal startup contains no checking-login copy or login/register route", () => {
  const boundary = readFileSync(
    path.resolve(process.cwd(), "features/math-tutor/desktop/components/StartupBoundary.tsx"),
    "utf8",
  );
  const desktop = readFileSync(path.resolve(process.cwd(), "../desktop/main.js"), "utf8");
  assert.ok(boundary.includes("正在启动 MathTutor"));
  assert.ok(!boundary.includes("正在验证登录状态"));
  assert.match(desktop, /const authEnabled = "0"/);
});
