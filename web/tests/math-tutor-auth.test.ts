import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import {
  checkIsFirstUser,
  fetchAuthStatus,
  login,
  logout,
  register,
} from "../lib/auth";

test("standalone auth client uses only the allowlisted v2 API", async () => {
  const originalFetch = globalThis.fetch;
  const requests: Array<{ url: string; method: string }> = [];
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push({
      url: String(input),
      method: String(init?.method || "GET"),
    });
    return new Response(
      JSON.stringify({
        enabled: true,
        authenticated: false,
        is_first_user: true,
        ok: true,
        role: "admin",
      }),
      { status: 200, headers: { "content-type": "application/json" } },
    );
  }) as typeof fetch;

  try {
    await fetchAuthStatus();
    await checkIsFirstUser();
    await register("preview", "password123");
    await login("preview", "password123");
    await logout();
  } finally {
    globalThis.fetch = originalFetch;
  }

  assert.deepEqual(requests, [
    { url: "/api/v2/auth/status", method: "GET" },
    { url: "/api/v2/auth/is_first_user", method: "GET" },
    { url: "/api/v2/auth/register", method: "POST" },
    { url: "/api/v2/auth/login", method: "POST" },
    { url: "/api/v2/auth/logout", method: "POST" },
  ]);
});

test("workspace is mounted behind the runtime auth boundary", () => {
  const layout = readFileSync(
    path.resolve(process.cwd(), "app/(workspace)/math-tutor/layout.tsx"),
    "utf8",
  );
  const authClient = readFileSync(path.resolve(process.cwd(), "lib/auth.ts"), "utf8");
  assert.match(layout, /<AuthBoundary>/);
  assert.doesNotMatch(authClient, /\/api\/v1\/auth\//);
});
