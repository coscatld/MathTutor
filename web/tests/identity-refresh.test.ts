import test from "node:test";
import assert from "node:assert/strict";
import { login, logout } from "../lib/auth";

test("logout suspends owner data before the request and refreshes only after it settles", async () => {
  const originalWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const originalFetch = globalThis.fetch;
  const events: string[] = [];
  const windowEvents = new EventTarget();
  windowEvents.addEventListener("mathtutor-identity-changing", () => events.push("pause"));
  windowEvents.addEventListener("mathtutor-identity-changed", () => events.push("refresh"));
  Object.defineProperty(globalThis, "window", { configurable: true, value: windowEvents });
  let release!: () => void;
  globalThis.fetch = (async () => {
    events.push("request");
    await new Promise<void>(resolve => { release = resolve; });
    return new Response("{}", { status: 200 });
  }) as typeof fetch;
  try {
    const pending = logout();
    assert.deepEqual(events, ["pause", "request"]);
    release();
    await pending;
    assert.deepEqual(events, ["pause", "request", "refresh"]);
    globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch;
    assert.equal((await login("fixture", "fixture-password")).ok, true);
    assert.equal(events.at(-1), "refresh");
  } finally {
    globalThis.fetch = originalFetch;
    if (originalWindow) Object.defineProperty(globalThis, "window", originalWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
