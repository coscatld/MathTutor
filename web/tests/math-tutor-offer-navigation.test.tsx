import test from "node:test";
import assert from "node:assert/strict";
import {
  buildChildNavigationPath,
  extractChildCycleId,
  resolveChildSessionId,
} from "../features/math-tutor/desktop/lib/offer-navigation";

type FakeResponse = { ok: boolean; json: () => Promise<unknown> };

function jsonResponse(payload: unknown, ok = true): FakeResponse {
  return { ok, json: async () => payload };
}

test("extractChildCycleId: reads ONLY the whitelisted public extra.child_cycle_id", () => {
  assert.equal(
    extractChildCycleId({
      event_type: "cycle_state_committed",
      extra: { child_cycle_id: "cycle-42" },
    }),
    "cycle-42",
  );
  assert.equal(
    extractChildCycleId({ event_type: "turn_end", extra: { child_cycle_id: "cycle-7" } }),
    "cycle-7",
  );
});

test("extractChildCycleId: ignores other event types, shapes and extra keys", () => {
  assert.equal(extractChildCycleId({ event_type: "connection_ready", extra: { child_cycle_id: "c1" } }), null);
  assert.equal(extractChildCycleId({ event_type: "cycle_state_committed", extra: {} }), null);
  assert.equal(extractChildCycleId({ event_type: "cycle_state_committed" }), null);
  assert.equal(extractChildCycleId({ event_type: "cycle_state_committed", extra: { other_key: "c1" } }), null);
  assert.equal(extractChildCycleId({ event_type: "cycle_state_committed", extra: { child_cycle_id: 5 } }), null);
  assert.equal(extractChildCycleId("string"), null);
  assert.equal(extractChildCycleId(null), null);
});

test("resolveChildSessionId: resolves via the public cycles read endpoint", async () => {
  const seen: string[] = [];
  const fetcher = async (path: string) => {
    seen.push(path);
    return jsonResponse({ session_id: "session-abc" }) as Response;
  };
  assert.equal(await resolveChildSessionId("cycle-42", fetcher), "session-abc");
  assert.deepEqual(seen, ["/api/v2/math-tutor/cycles/cycle-42"]);
});

test("resolveChildSessionId: safe failure paths (404 / malformed / throw / empty)", async () => {
  assert.equal(
    await resolveChildSessionId("cycle-1", async () => jsonResponse({}, false) as Response),
    null,
  );
  assert.equal(
    await resolveChildSessionId("cycle-2", async () => jsonResponse({ cycle_id: "x" }) as Response),
    null,
  );
  assert.equal(
    await resolveChildSessionId("cycle-3", async () => {
      throw new Error("network");
    }),
    null,
  );
  let called = false;
  await resolveChildSessionId("", async () => {
    called = true;
    return jsonResponse({ session_id: "s" }) as Response;
  });
  assert.equal(called, false, "empty id never fetches");
});

test("buildChildNavigationPath: encodes the session into the workspace URL", () => {
  assert.equal(buildChildNavigationPath("session-abc"), "/math-tutor?session=session-abc");
  assert.equal(buildChildNavigationPath("a b&c"), "/math-tutor?session=a%20b%26c");
});
