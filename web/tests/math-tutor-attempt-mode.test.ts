import test from "node:test";
import assert from "node:assert/strict";
import { attemptBindingIsCurrent, currentAttemptBinding, deliverBoundAttempt } from "../features/math-tutor/lib/attempt";
import { buildEnvelope } from "../features/math-tutor/lib/protocol";
import { deliverDraft } from "../features/math-tutor/lib/attachments";
import { initialMathTutorState } from "../features/math-tutor/lib/reducer";

const state = { ...initialMathTutorState("chat"), cycleId: "check-cycle", problemRevision: "verified-revision", allowedActions: [{ command: "submit_attempt" as const, enabled: true, label: "", description: "", reason_code: "AVAILABLE" }] };

test("writing an intermediate equation sends a bound submit_attempt envelope, preserving the equation verbatim", async () => {
  const binding = currentAttemptBinding(state)!;
  let wire = "";
  let complete: ((success: boolean) => void) | undefined;
  const pending = deliverBoundAttempt(" 3z=18 ", binding, () => state, (command, payload, onComplete) => {
    wire = buildEnvelope(command, payload, state.sessionId, { cycleId: state.cycleId, problemRevision: state.problemRevision, expectedCycleVersion: state.seenVersion });
    complete = onComplete;
    return true;
  });
  assert.deepEqual(JSON.parse(wire), { protocol_version: 2, command: "submit_attempt", payload: { answer: "3z=18" }, session_id: "chat", expected_state_version: 0, expected_cycle_version: 0, cycle_id: "check-cycle", problem_revision: "verified-revision" });
  complete?.(true);
  assert.equal(await pending, true);
  assert.equal(attemptBindingIsCurrent(binding, state), true, "another step stays in writing mode on the same authorized task");
});

test("a changed task or revoked capability cannot receive the old writing draft", async () => {
  const binding = currentAttemptBinding(state)!;
  for (const changed of [
    { ...state, cycleId: "original-cycle" },
    { ...state, problemRevision: "edited-revision" },
    { ...state, allowedActions: [] },
    { ...state, allowedActions: [{ ...state.allowedActions[0], enabled: false }], allowedNextInputs: ["submit_attempt"] },
  ]) {
    assert.equal(attemptBindingIsCurrent(binding, changed), false);
    assert.equal(await deliverBoundAttempt("z=6", binding, () => changed, () => { assert.fail("stale draft must not be sent"); }), false);
  }
  assert.equal(currentAttemptBinding({ ...state, problemRevision: "" }), null);
});

test("an incomplete or failed step retains the draft until a later successful delivery", async () => {
  const binding = currentAttemptBinding(state)!;
  let draft = "3z=18";
  const send = async (text: string, success: boolean) => deliverBoundAttempt(text, binding, () => state, (_command, _payload, complete) => { complete(success); return true; });
  assert.equal(await deliverDraft(draft, [], text => send(text, false), () => { draft = ""; }), false);
  assert.equal(draft, "3z=18");
  assert.equal(await deliverDraft(draft, [], text => send(text, true), () => { draft = ""; }), true);
  assert.equal(draft, "");
  assert.equal(await deliverBoundAttempt("z=6", binding, () => state, () => false), false, "disconnected transport reports failure");
});
