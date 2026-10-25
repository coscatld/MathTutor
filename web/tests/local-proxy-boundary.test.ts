import test from "node:test";
import assert from "node:assert/strict";
import { inspectProxyRequest, type BoundaryEnvironment } from "../lib/server-boundary";
import { apiFetch } from "../lib/api";
import { NextRequest } from "next/server";
import { proxy } from "../proxy";

const origin = "http://127.0.0.1:31245";
const secret = "per-launch-" + "s".repeat(48);
const env = { MATHTUTOR_ALLOWED_ORIGINS: origin, MATHTUTOR_BRIDGE_SECRET: secret };
const inspect = (values: Record<string, string>, method = "POST", options: BoundaryEnvironment = env) =>
  inspectProxyRequest(new Headers({ host: "127.0.0.1:31245", ...values }), method, options);

test("proxy rejects alien origins and hosts even with a valid bridge credential", () => {
  for (const value of ["null", "https://evil.example", "http://localhost:31245", origin.replace("31245", "31246"), origin + ".evil.example"]) {
    assert.equal(inspect({ origin: value, "x-mathtutor-bridge": secret }).allowed, false);
  }
  assert.equal(inspect({ host: "evil.example", origin, "x-mathtutor-bridge": secret }).allowed, false);
  assert.equal(inspect({ "x-forwarded-host": "127.0.0.1:31245", host: "evil.example", origin }).allowed, false);
});

test("native no-Origin requests require the credential and simple forms cannot mutate", () => {
  assert.equal(inspect({}, "GET").allowed, false);
  assert.equal(inspect({ "x-mathtutor-csrf": "1" }, "GET").allowed, false);
  assert.equal(inspect({ origin }).allowed, false);
  assert.equal(inspect({ origin, "x-mathtutor-csrf": "1" }).allowed, true);
  assert.equal(inspect({ "x-mathtutor-bridge": secret }).allowed, true);
  assert.equal(inspect({ origin }, "GET").allowed, true); // WS upgrade carries Origin
});

test("rejected WS upgrades reach the ASGI rejection gate with null Origin and no credential", () => {
  const previous = process.env.MATHTUTOR_ALLOWED_ORIGINS;
  process.env.MATHTUTOR_ALLOWED_ORIGINS = origin;
  try {
    const response = proxy(new NextRequest(origin + "/api/v2/math-tutor/ws", { headers: {
      Host: "evil.example", Origin: origin, Upgrade: "websocket", "X-MathTutor-Bridge": secret,
    } }));
    assert.equal(response.headers.get("x-middleware-request-origin"), "null");
    assert.equal(response.headers.get("x-middleware-request-x-mathtutor-bridge"), null);
    assert.match(response.headers.get("x-middleware-rewrite") ?? "", /\/api\/v2\/math-tutor\/ws$/);
    const http = proxy(new NextRequest(origin + "/api/v2/auth/status", { headers: { Host: "evil.example" } }));
    assert.equal(http.status, 403);
  } finally {
    if (previous === undefined) delete process.env.MATHTUTOR_ALLOWED_ORIGINS;
    else process.env.MATHTUTOR_ALLOWED_ORIGINS = previous;
  }
});

test("explicit browser dev and account web profiles require browser-controlled metadata", () => {
  const headers = { "x-mathtutor-csrf": "1", "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", referer: origin + "/math-tutor" };
  for (const profile of [{ MATHTUTOR_BROWSER_DEV: "1" }, { MATHTUTOR_AUTH_ENABLED: "1" }]) {
    const options = { ...env, ...profile };
    assert.deepEqual(inspect(headers, "GET", options), { allowed: true, origin });
    assert.equal(inspect({ ...headers, "sec-fetch-site": "cross-site" }, "GET", options).allowed, false);
    assert.equal(inspect({ ...headers, referer: origin.replace("http:", "https:") }, "GET", options).allowed, false);
    assert.equal(inspect(headers, "POST", options).allowed, false);
    assert.equal(inspect({ "x-mathtutor-csrf": "1" }, "GET", options).allowed, false);
    const resources: Array<Record<string, string>> = [
      { "sec-fetch-mode": "no-cors", "sec-fetch-dest": "image" },
      { "sec-fetch-mode": "navigate", "sec-fetch-dest": "document", "sec-fetch-user": "?1" },
    ];
    for (const resource of resources) {
      assert.equal(inspect({ "sec-fetch-site": "same-origin", referer: origin, ...resource }, "GET", options).allowed, true);
      assert.equal(inspect({ "sec-fetch-site": "same-site", referer: origin, ...resource }, "GET", options).allowed, false);
    }
  }
  assert.equal(inspect(headers, "GET", { ...env, MATHTUTOR_BROWSER_DEV: "1", MATHTUTOR_ENVIRONMENT: "production" }).allowed, false);
});

test("apiFetch adds the non-simple CSRF header including multipart calls", async () => {
  const original = globalThis.fetch;
  const requests: Headers[] = [];
  globalThis.fetch = (async (_url, init) => {
    requests.push(new Headers(init?.headers));
    return new Response("{}");
  }) as typeof fetch;
  try {
    await apiFetch("/api/status");
    await apiFetch("/api/import", { method: "POST", body: new FormData() });
    assert.equal(requests.every(headers => headers.get("x-mathtutor-csrf") === "1"), true);
    assert.equal(requests[1].has("content-type"), false);
  } finally { globalThis.fetch = original; }
});
