import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {
  actionLabel,
  allowedInputsToButtons,
  allowsAttempt,
  allowsProblemSubmission,
  buildEnvelope,
  commandNeedsText,
  extractDisplayLatex,
  isStaleFrame,
  normalizeAssistanceLevel,
  projectStudentFrame,
  wrapLatexForDisplay,
} from "../features/math-tutor/lib/protocol";
import {
  initialMathTutorState,
  mathTutorReducer,
} from "../features/math-tutor/lib/reducer";
import type { StudentFrame } from "../features/math-tutor/types";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function frame(overrides: Partial<StudentFrame> = {}): StudentFrame {
  return {
    event_type: "tutor_action_committed",
    cycle_state: "awaiting_attempt",
    cycle_state_version: 3,
    allowed_next_inputs: [],
    payload: {
      action: "GIVE_HINT",
      effective_assistance_level: 2,
      student_message: "先想想两边同时除以 2。",
      trigger_command: "request_hint",
    },
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// envelope construction
// ---------------------------------------------------------------------------

test("buildEnvelope produces a JSON envelope with only allowlisted keys", () => {
  const raw = buildEnvelope("submit_attempt", { answer: "x = 2" }, "session-1", {
    requestId: "req-1",
    idempotencyKey: "idem-1",
    expectedCycleVersion: 7,
  });
  const envelope = JSON.parse(raw) as Record<string, unknown>;

  assert.equal(envelope.command, "submit_attempt");
  assert.deepEqual(envelope.payload, { answer: "x = 2" });
  assert.equal(envelope.session_id, "session-1");
  assert.equal(envelope.request_id, "req-1");
  assert.equal(envelope.idempotency_key, "idem-1");
  assert.equal(envelope.expected_cycle_version, 7);

  // Backend allowlist forbids identity/privilege/tool keys — none may appear.
  const forbidden = [
    "student_id",
    "user_id",
    "owner_id",
    "roles",
    "role",
    "tenant_id",
    "capability",
    "active_capability",
    "tools",
    "enabled_tools",
    "allowed_builtin_tools",
    "system_prompt",
    "provider",
    "model",
  ];
  for (const key of forbidden) {
    assert.ok(!(key in envelope), `forbidden key leaked into envelope: ${key}`);
  }
});

test("buildEnvelope omits expected_cycle_version when it is 0 or absent", () => {
  const withZero = JSON.parse(
    buildEnvelope("request_hint", {}, "s", { expectedCycleVersion: 0 }),
  ) as Record<string, unknown>;
  assert.ok(!("expected_cycle_version" in withZero));

  const absent = JSON.parse(buildEnvelope("request_hint", {}, "s")) as Record<string, unknown>;
  assert.ok(!("expected_cycle_version" in absent));
});

test("commandNeedsText covers text-carrying commands only", () => {
  assert.equal(commandNeedsText("submit_problem"), true);
  assert.equal(commandNeedsText("clarify_problem"), true);
  assert.equal(commandNeedsText("clarify_attempt"), true);
  assert.equal(commandNeedsText("submit_attempt"), false);
  assert.equal(commandNeedsText("request_hint"), false);
  assert.equal(commandNeedsText("cancel_turn"), false);
});

// ---------------------------------------------------------------------------
// frame projection (internal fields must never reach the UI)
// ---------------------------------------------------------------------------

test("projectStudentFrame strips internal and unknown fields", () => {
  const projected = projectStudentFrame({
    event_type: "tutor_action_committed",
    audience: "student",
    cycle_state: "awaiting_attempt",
    cycle_state_version: 5,
    allowed_next_inputs: ["submit_attempt", "request_hint"],
    // Internal fields that must not survive projection:
    candidate_solution: "x = 2",
    verification_log: [{ ok: true }],
    solver_trace: "…",
    model_prompt: "…",
    model_reasoning: "…",
    final_answer: "2",
    payload: {
      action: "GIVE_HINT",
      effective_assistance_level: 2,
      student_message: "hi",
      trigger_command: "request_hint",
      // Internal payload members must not survive either:
      verified_solution: "x = 2",
      attestation_payload: {},
      raw_internal_event: {},
    },
    some_unknown_field: 42,
  });

  assert.ok(projected);
  assert.deepEqual(projected.allowed_next_inputs, ["submit_attempt", "request_hint"]);
  assert.equal(projected.payload.student_message, "hi");
  const serialized = JSON.stringify(projected);
  const forbidden = [
    "candidate_solution",
    "verified_solution",
    "final_answer",
    "verification_log",
    "solver_trace",
    "model_prompt",
    "model_reasoning",
    "raw_internal_event",
    "attestation_payload",
  ];
  for (const key of forbidden) {
    assert.ok(!serialized.includes(key), `internal field leaked: ${key}`);
  }
  assert.ok(!serialized.includes("some_unknown_field"));
});

test("projectStudentFrame drops non-student and unknown event types", () => {
  assert.equal(projectStudentFrame({ event_type: "solver_trace", audience: "internal" }), null);
  assert.equal(projectStudentFrame({ event_type: "mystery_event", audience: "student" }), null);
  assert.equal(projectStudentFrame(null as never), null);
  assert.equal(projectStudentFrame("not an object" as never), null);
});

// ---------------------------------------------------------------------------
// stale-frame rule (B4)
// ---------------------------------------------------------------------------

test("isStaleFrame drops action/state frames at or below the seen version", () => {
  const seen = 8;
  assert.equal(isStaleFrame(frame({ cycle_state_version: 8 }), seen), true);
  assert.equal(isStaleFrame(frame({ cycle_state_version: 3 }), seen), true);
  assert.equal(isStaleFrame(frame({ cycle_state_version: 9 }), seen), false);
  // cycle_state_committed follows the same rule
  assert.equal(
    isStaleFrame(frame({ event_type: "cycle_state_committed", cycle_state_version: 8 }), seen),
    true,
  );
  // turn_error / turn_end are NEVER dropped
  assert.equal(
    isStaleFrame(frame({ event_type: "turn_error", cycle_state_version: 1 }), seen),
    false,
  );
  assert.equal(
    isStaleFrame(frame({ event_type: "turn_end", cycle_state_version: 0 }), seen),
    false,
  );
  // fresh session (seen = 0) accepts everything, including version 0
  assert.equal(isStaleFrame(frame({ cycle_state_version: 0 }), 0), false);
});

// ---------------------------------------------------------------------------
// INVARIANT 5 — capabilities come only from allowed_next_inputs
// ---------------------------------------------------------------------------

test("allowedInputsToButtons renders no button for inputs the server never sent", () => {
  // request_solution NOT granted → no 查看完整答案 button
  const withoutSolution = allowedInputsToButtons([
    "submit_attempt",
    "request_hint",
    "request_explanation",
    "request_example",
  ]);
  assert.ok(
    withoutSolution.every((spec) => spec.label !== "查看完整答案"),
    "solution button rendered without server grant",
  );
  assert.deepEqual(
    withoutSolution.map((spec) => spec.command),
    ["request_hint", "request_explanation", "request_example"],
  );

  // unknown input names render nothing
  assert.deepEqual(allowedInputsToButtons(["something_new"]), []);

  // server grants solution disclosure → button appears, last
  const withSolution = allowedInputsToButtons(["request_hint", "solution_shown_permitted"]);
  assert.equal(withSolution[withSolution.length - 1]?.label, "查看完整答案");
});

test("composer visibility helpers follow the same server-granted inputs", () => {
  assert.equal(allowsAttempt(["submit_attempt"]), true);
  assert.equal(allowsAttempt(["request_hint"]), false);
  assert.equal(allowsProblemSubmission(["submit_problem"]), true);
  assert.equal(allowsProblemSubmission(["cancel_turn"]), false);
});

test("reducer adopts allowed_next_inputs from frames only", () => {
  let state = initialMathTutorState("s1");
  state = mathTutorReducer(state, {
    type: "frame",
    frame: frame({
      cycle_state_version: 1,
      allowed_next_inputs: ["submit_attempt", "request_hint", "request_explanation", "request_example"],
    }),
  });
  assert.deepEqual(state.allowedNextInputs, [
    "submit_attempt",
    "request_hint",
    "request_explanation",
    "request_example",
  ]);
  // cycle_state is a public display field — but never a capability source
  state = mathTutorReducer(state, { type: "frame", frame: frame({ cycle_state_version: 2, allowed_next_inputs: [] }) });
  assert.deepEqual(state.allowedNextInputs, [
    "submit_attempt",
    "request_hint",
    "request_explanation",
    "request_example",
  ]);
});

// ---------------------------------------------------------------------------
// reducer frame flow
// ---------------------------------------------------------------------------

test("reducer drops stale action frames (B4) but keeps turn_error", () => {
  let state = initialMathTutorState("s1");
  state = mathTutorReducer(state, {
    type: "frame",
    frame: frame({
      cycle_state_version: 5,
      payload: { action: "GIVE_HINT", effective_assistance_level: 2, student_message: "先想这一步。" },
    }),
  });
  assert.equal(state.seenVersion, 5);
  const messageCount = state.messages.length;

  const stale = mathTutorReducer(state, {
    type: "frame",
    frame: frame({
      cycle_state_version: 5,
      payload: { action: "GIVE_HINT", effective_assistance_level: 3, student_message: "重复的旧帧" },
    }),
  });
  assert.equal(stale.messages.length, messageCount, "stale frame must not append a message");

  const turnError = mathTutorReducer(state, {
    type: "frame",
    frame: frame({
      event_type: "turn_error",
      cycle_state_version: 5,
      payload: { error: "状态不接受该命令" },
    }),
  });
  assert.equal(turnError.messages.length, messageCount + 1);
  assert.equal(turnError.messages[turnError.messages.length - 1]?.kind, "error");
});

test("reducer extracts the verified problem LaTeX and clears pending on turn_end", () => {
  let state = initialMathTutorState("s1");
  state = mathTutorReducer(state, { type: "command_sent", command: "submit_problem" });
  assert.equal(state.pendingCommand, "submit_problem");

  state = mathTutorReducer(state, {
    type: "frame",
    frame: frame({
      cycle_state_version: 3,
      cycle_state: "awaiting_attempt",
      payload: {
        action: "verified",
        effective_assistance_level: 0,
        student_message: "题目已解析并验证：2x + 3 = 7",
        trigger_command: "submit_problem",
      },
      allowed_next_inputs: ["submit_attempt", "request_hint", "request_explanation", "request_example"],
    }),
  });
  assert.equal(state.problemLatex, "2x + 3 = 7");
  assert.equal(state.problemActive, true);

  state = mathTutorReducer(state, { type: "frame", frame: frame({ event_type: "turn_end", cycle_state_version: 3 }) });
  assert.equal(state.pendingCommand, null);
});

test("reducer returns to the problem composer when the cycle closes", () => {
  let state = initialMathTutorState("s1");
  state = mathTutorReducer(state, {
    type: "frame",
    frame: frame({
      cycle_state_version: 1,
      payload: { action: "verified", student_message: "题目已解析并验证：1+1" },
    }),
  });
  assert.equal(state.problemActive, true);

  state = mathTutorReducer(state, {
    type: "frame",
    frame: frame({ cycle_state_version: 2, cycle_state: "closed" }),
  });
  assert.equal(state.problemActive, false);
});

test("restore adopts the server summary as the only authority", () => {
  const state = mathTutorReducer(initialMathTutorState("s1"), {
    type: "restore",
    summary: {
      state: "awaiting_retry",
      state_version: 12,
      allowed_next_inputs: ["submit_attempt", "request_hint"],
    },
  });
  assert.equal(state.cycleState, "awaiting_retry");
  assert.equal(state.seenVersion, 12);
  assert.deepEqual(state.allowedNextInputs, ["submit_attempt", "request_hint"]);
});

// ---------------------------------------------------------------------------
// small pure helpers
// ---------------------------------------------------------------------------

test("extractDisplayLatex only accepts verification frames", () => {
  assert.equal(extractDisplayLatex("题目已解析并验证：2x + 3 = 7", "verified"), "2x + 3 = 7");
  assert.equal(extractDisplayLatex("随便一句话", "verified"), "随便一句话");
  assert.equal(extractDisplayLatex("题目已解析并验证：x", "GIVE_HINT"), null);
  assert.equal(extractDisplayLatex("", "verified"), null);
});

test("normalizeAssistanceLevel clamps into the 1-5 ladder", () => {
  assert.equal(normalizeAssistanceLevel(0), 0);
  assert.equal(normalizeAssistanceLevel(2.6), 3);
  assert.equal(normalizeAssistanceLevel(9), 5);
  assert.equal(normalizeAssistanceLevel(-3), 0);
  assert.equal(normalizeAssistanceLevel(Number.NaN), 0);
});

test("wrapLatexForDisplay wraps raw LaTeX and leaves delimited content alone", () => {
  assert.equal(wrapLatexForDisplay("2x + 3 = 7"), "$$\n2x + 3 = 7\n$$");
  assert.equal(wrapLatexForDisplay("$$x=1$$"), "$$x=1$$");
  assert.equal(wrapLatexForDisplay("\\[x=1\\]"), "\\[x=1\\]");
  assert.equal(wrapLatexForDisplay("  "), "");
});

test("actionLabel maps known actions and never leaks raw codes for them", () => {
  assert.equal(actionLabel("GIVE_HINT"), "提示");
  assert.equal(actionLabel("SHOW_SOLUTION"), "完整答案");
  assert.equal(actionLabel("unknown_action"), "unknown_action");
  assert.equal(actionLabel(""), "");
});

// ---------------------------------------------------------------------------
// static assertion — no internal field names may appear in UI component code
// ---------------------------------------------------------------------------

test("student UI components contain no internal/forbidden field names", () => {
  // Compiled at dist/node-tests/tests/<file>.js → repo web/ root is ../../..
  const componentsDir = path.resolve(__dirname, "../../../features/math-tutor");
  const forbidden = [
    "candidate_solution",
    "verified_solution",
    "final_answer",
    "verification_log",
    "solver_trace",
    "model_prompt",
    "model_reasoning",
    "raw_internal_event",
    "attestation_payload",
    "solution_candidate",
  ];
  const walk = (dir: string): string[] =>
    fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) return walk(full);
      return entry.name.endsWith(".tsx") ? [full] : [];
    });

  const files = walk(componentsDir);
  assert.ok(files.length > 0, "expected component sources to exist");
  for (const file of files) {
    const source = fs.readFileSync(file, "utf8");
    for (const key of forbidden) {
      assert.ok(
        !source.includes(key),
        `forbidden internal field "${key}" appears in ${file}`,
      );
    }
  }
});
