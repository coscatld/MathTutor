import test from "node:test";
import assert from "node:assert/strict";
import path from "node:path";
import { inspectProxyRequest } from "../lib/server-boundary";
import { fetchAuthStatus } from "../lib/auth";
import { ApiError } from "../lib/api-error";
import { DesktopApiError, nativePickAndImport, setDocumentGlobal } from "../features/math-tutor/desktop/lib/desktop-api";
import { documentResult } from "../features/math-tutor/desktop/lib/document-result";
import type { DesktopDocument } from "../features/math-tutor/desktop/types";

const { browserDevEnvironment } = require(path.join(process.cwd(), "scripts/browser-dev.cjs"));
const headers = new Headers({ host: "127.0.0.1:3000", referer: "http://127.0.0.1:3000/", "sec-fetch-site": "same-origin", "sec-fetch-mode": "cors", "x-mathtutor-csrf": "1" });
test("documented dev launcher enables browser reads without relaxing production or foreign-source checks", () => {
  const env = browserDevEnvironment({});
  assert.equal(inspectProxyRequest(headers, "GET", env).allowed, true);
  for (const override of [{ NODE_ENV: "production" }, { MATHTUTOR_ENVIRONMENT: "production" }]) {
    assert.throws(() => browserDevEnvironment(override), /development/);
    assert.equal(inspectProxyRequest(headers, "GET", { ...env, ...override }).allowed, false);
  }
  for (const override of [{ host: "evil.example" }, { origin: "https://evil.example" }, { "sec-fetch-site": "cross-site" }]) {
    const bad = new Headers(headers);
    Object.entries(override).forEach(([name, value]) => bad.set(name, value));
    assert.equal(inspectProxyRequest(bad, "GET", env).allowed, false);
  }
});

test("startup retains deterministic HTTP rejection and still tolerates network startup delay", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => Response.json({ detail: "Untrusted request source", code: "untrusted_source" }, { status: 403 });
    await assert.rejects(fetchAuthStatus({ throwHttpErrors: true }), (error: unknown) => error instanceof ApiError && error.status === 403);
    assert.equal(await fetchAuthStatus(), null);
    globalThis.fetch = async () => { throw new TypeError("offline"); };
    assert.equal(await fetchAuthStatus({ throwHttpErrors: true }), null);
  } finally { globalThis.fetch = original; }
});

test("desktop picker/scope errors keep HTTP status and optional machine code", async () => {
  const original = globalThis.fetch;
  try {
    for (const status of [501, 422, 500]) {
      globalThis.fetch = async () => Response.json({ detail: "fixture", code: "fixture_code" }, { status });
      for (const action of [() => nativePickAndImport(), () => setDocumentGlobal("doc", true)]) {
        await assert.rejects(action(), (error: unknown) => error instanceof DesktopApiError && error.status === status && error.code === "fixture_code");
      }
    }
  } finally { globalThis.fetch = original; }
});

const document = { filename: "lecture.pdf", status: "ready", retrieval_enabled: true, chunk_count: 2, is_global: true } as DesktopDocument;
for (const status of ["needs_ocr", "failed", "parsing", "importing"] as const) test(`${status} never announces retrieval success`, () => {
  const result = documentResult({ ...document, status });
  assert.match(result.description, /当前不可检索/);
  assert.doesNotMatch(result.description, /可在所选范围内检索/);
});
test("ready projections distinguish warning, disabled retrieval and unassigned scope", () => {
  assert.match(documentResult(document).description, /可在所选范围内检索/);
  assert.match(documentResult({ ...document, status: "ready_with_warnings", parse_warning: "第 2 页为空" }).description, /第 2 页为空/);
  assert.match(documentResult({ ...document, retrieval_enabled: false }).description, /检索已停用/);
  assert.match(documentResult({ ...document, is_global: false }).description, /未归类，不跨对话检索/);
});
