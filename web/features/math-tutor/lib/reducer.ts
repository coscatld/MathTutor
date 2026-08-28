/**
 * MathTutor workspace state reducer — pure, no React, fully unit-tested.
 *
 * INVARIANT 5: this reducer never invents capabilities. allowed_next_inputs
 * comes ONLY from server frames (or the recovery GET) — there is no
 * frontend "second state machine" that derives buttons from cycle_state.
 */

import type {
  ConnectionStatus,
  MathTutorCommand,
  MathTutorUIState,
  SessionSummary,
  StudentFrame,
  TutorMessage,
} from "../types";
import {
  extractDisplayLatex,
  isStaleFrame,
  normalizeAssistanceLevel,
} from "./protocol";

export type MathTutorAction =
  | { type: "connection"; status: ConnectionStatus; note: string }
  | { type: "frame"; frame: StudentFrame }
  | { type: "restore"; summary: SessionSummary }
  | { type: "command_sent"; command: MathTutorCommand }
  | { type: "new_session"; sessionId: string };

export function initialMathTutorState(sessionId: string): MathTutorUIState {
  return {
    connectionStatus: "connecting",
    connectionNote: "",
    sessionId,
    cycleState: "",
    seenVersion: 0,
    allowedNextInputs: [],
    messages: [],
    problemLatex: null,
    assistanceLevel: 0,
    pendingCommand: null,
    problemActive: false,
  };
}

let messageCounter = 0;
function nextMessageId(): string {
  messageCounter += 1;
  return `msg-${Date.now().toString(36)}-${messageCounter.toString(36)}`;
}

function appendMessage(
  state: MathTutorUIState,
  message: Omit<TutorMessage, "id">,
): TutorMessage[] {
  const entry: TutorMessage = { ...message, id: nextMessageId() };
  // Cap the list so a long session can never grow unbounded.
  return [...state.messages, entry].slice(-100);
}

/**
 * Apply one server frame. Stale action/state frames are dropped (B4);
 * turn_error and turn_end always apply.
 */
function applyFrame(state: MathTutorUIState, frame: StudentFrame): MathTutorUIState {
  if (isStaleFrame(frame, state.seenVersion)) {
    return state;
  }

  const next: MathTutorUIState = {
    ...state,
    seenVersion: Math.max(state.seenVersion, frame.cycle_state_version),
    cycleState: frame.cycle_state || state.cycleState,
  };

  if (frame.allowed_next_inputs.length > 0) {
    next.allowedNextInputs = frame.allowed_next_inputs;
  }

  // The server closed the cycle — the problem area returns to "write a new
  // problem" (a display decision from a public field, not a capability guess).
  if (frame.cycle_state === "closed") {
    next.problemActive = false;
    next.assistanceLevel = 0;
  }

  if (frame.event_type === "turn_error") {
    const text = frame.payload.error?.trim() || "出错了，请重试。";
    next.pendingCommand = null;
    next.messages = appendMessage(state, {
      kind: "error",
      text,
      action: "turn_error",
      assistanceLevel: 0,
      version: frame.cycle_state_version,
    });
    return next;
  }

  if (frame.event_type === "turn_end") {
    next.pendingCommand = null;
    return next;
  }

  // tutor_action_committed / cycle_state_committed
  const action = frame.payload.action ?? "";
  const message = frame.payload.student_message ?? "";
  const level = normalizeAssistanceLevel(frame.payload.effective_assistance_level ?? 0);

  if (level > 0) {
    next.assistanceLevel = level;
  }
  // cycle_state_committed is state-only; it never carries a student message.
  if (frame.event_type === "tutor_action_committed") {
    if (message.trim()) {
      next.messages = appendMessage(state, {
        kind: "tutor",
        text: message,
        action,
        assistanceLevel: level,
        version: frame.cycle_state_version,
      });
    }
    const problemLatex = extractDisplayLatex(message, action);
    if (problemLatex !== null) {
      next.problemLatex = problemLatex;
      next.problemActive = true;
    }
  }
  return next;
}

/**
 * Apply the recovery GET result (POST-reconnect resync). The server is the
 * authority: state/version/allowed inputs come from the summary, never from
 * a client-side guess.
 */
function applyRestore(
  state: MathTutorUIState,
  summary: SessionSummary,
): MathTutorUIState {
  const stateVersion =
    summary.state_version !== undefined &&
    summary.state_version !== null &&
    Number.isFinite(Number(summary.state_version))
      ? Number(summary.state_version)
      : 0;
  const allowed = Array.isArray(summary.allowed_next_inputs)
    ? summary.allowed_next_inputs.filter((item): item is string => typeof item === "string")
    : [];
  const restoredState = String(summary.state ?? "");
  const active = restoredState !== "" && restoredState !== "closed";
  return {
    ...state,
    cycleState: restoredState,
    seenVersion: Math.max(state.seenVersion, stateVersion),
    allowedNextInputs: allowed.length > 0 ? allowed : state.allowedNextInputs,
    problemActive: active || state.problemActive,
    pendingCommand: null,
  };
}

export function mathTutorReducer(
  state: MathTutorUIState,
  action: MathTutorAction,
): MathTutorUIState {
  switch (action.type) {
    case "connection":
      return { ...state, connectionStatus: action.status, connectionNote: action.note };
    case "frame":
      return applyFrame(state, action.frame);
    case "restore":
      return applyRestore(state, action.summary);
    case "command_sent":
      return { ...state, pendingCommand: action.command };
    case "new_session": {
      const fresh = initialMathTutorState(action.sessionId);
      return { ...fresh, connectionStatus: state.connectionStatus, connectionNote: state.connectionNote };
    }
    default:
      return state;
  }
}
