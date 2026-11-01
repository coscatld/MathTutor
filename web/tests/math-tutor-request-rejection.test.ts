import test from "node:test";
import assert from "node:assert/strict";
import { projectStudentFrame, isUnstartedRequestRejection, rejectionMatchesRequest } from "../features/math-tutor/lib/protocol";
import { initialMathTutorState, mathTutorReducer } from "../features/math-tutor/lib/reducer";

for (const code of ["REQUEST_QUEUE_FULL", "REQUEST_CANCELLED_BEFORE_START"]) {
  test(`${code} is an explicit matching-request rejection, never a completion`, () => {
    const frame = projectStudentFrame({ event_type: "assistant_error", payload: {
      turn_id: "queued", conversation_id: "c", status: "FAILED", error_code: code,
      error: "这条请求尚未执行，请重试。", accepted: false, retryable: true,
    } } as never)!;
    assert.equal(isUnstartedRequestRejection(frame), true);
    assert.equal(rejectionMatchesRequest(frame, "queued"), true);
    assert.equal(rejectionMatchesRequest(frame, "active"), false);
    assert.equal(rejectionMatchesRequest(frame, undefined), false);
    const state = initialMathTutorState("c");
    state.pendingCommand = "send_message";
    state.messages = [{ id: "user", kind: "student", text: "原作答", turnId: "queued", action: "", assistanceLevel: 0, version: 0 }];
    const updated = mathTutorReducer(state, { type: "frame", frame });
    assert.equal(updated.messages[0].text, "原作答");
    assert.equal(updated.messages[1].kind, "error");
    assert.equal(updated.messages[1].status, "FAILED");
    assert.match(updated.messages[1].text, /尚未执行/);
    assert.equal(updated.pendingCommand, null);
    assert.equal(updated.cycleState, state.cycleState);
  });
}

test("a normal failed or completed accepted turn is not a pre-start rejection", () => {
  for (const event_type of ["assistant_error", "assistant_complete"]) {
    const frame = projectStudentFrame({ event_type, payload: { turn_id: "active", error_code: "INTERNAL_ERROR" } } as never)!;
    assert.equal(isUnstartedRequestRejection(frame), false);
    assert.equal(rejectionMatchesRequest(frame, "active"), false);
  }
});
