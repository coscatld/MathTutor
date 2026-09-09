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
  projectTurnError,
  shouldRenderTutorText,
} from "./protocol";

export type MathTutorAction =
  | { type: "connection"; status: ConnectionStatus; note: string }
  | { type: "frame"; frame: StudentFrame }
  | { type: "restore"; summary: SessionSummary }
  | { type: "command_sent"; command: MathTutorCommand; text?: string }
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
  if (frame.payload.conversation_id && frame.payload.conversation_id !== state.sessionId) return state;
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

  if (frame.event_type === "assistant_start") return next;
  if (frame.event_type === "assistant_delta") {
    const text = frame.payload.student_message || "";
    if (shouldRenderTutorText(text)) {
      const id = frame.payload.message_id || frame.payload.turn_id;
      const existing = state.messages.find(m => m.id === id && m.status === "STREAMING");
      next.messages = existing ? state.messages.map(m => m === existing ? { ...m, text: m.text + text } : m)
        : [...state.messages, { id: id || nextMessageId(), kind: "tutor", text, status: "STREAMING",
          turnId: frame.payload.turn_id, action: frame.payload.action || "",
          assistanceLevel: normalizeAssistanceLevel(frame.payload.effective_assistance_level || 0), version: next.seenVersion }].slice(-100) as TutorMessage[];
    }
    return next;
  }
  if (["assistant_complete", "assistant_partial", "assistant_error"].includes(frame.event_type)) {
    const status = frame.event_type === "assistant_complete" ? "COMPLETED" : frame.event_type === "assistant_partial" ? "PARTIAL" : frame.payload.status === "CANCELLED" ? "CANCELLED" : "FAILED";
    next.messages = state.messages.map(m => m.turnId === frame.payload.turn_id ? { ...m, status, finishReason: frame.payload.finish_reason } : m);
    const matching = next.messages.filter(m => m.turnId === frame.payload.turn_id);
    if (matching.length === 1 && shouldRenderTutorText(frame.payload.final_text || "")) {
      next.messages = next.messages.map(m => m === matching[0] ? { ...m, text: frame.payload.final_text! } : m);
    }
    if (frame.event_type === "assistant_error" && !next.messages.some(m => m.turnId === frame.payload.turn_id)) {
      next.messages = appendMessage(next, { kind: "tutor", text: status === "CANCELLED" ? "已停止生成。" : "这次回答未能生成，请重试。", status, turnId: frame.payload.turn_id, action: "", assistanceLevel: 0, version: next.seenVersion });
    }
    next.pendingCommand = null;
    return next;
  }

  if (frame.event_type === "turn_error") {
    const text = projectTurnError(frame.payload.error?.trim() || "出错了，请重试。");
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
    next.messages = state.messages.map(m => m.status === "STREAMING" ? { ...m, status: "PARTIAL", finishReason: "STREAM_INTERRUPTED" } : m);
    next.pendingCommand = null;
    return next;
  }

  // tutor_action_committed / tutor_message / cycle_state_committed
  const action = frame.payload.action ?? "";
  const message = frame.payload.student_message ?? "";
  const level = normalizeAssistanceLevel(frame.payload.effective_assistance_level ?? 0);

  if (level > 0) {
    next.assistanceLevel = level;
  }
  // cycle_state_committed is state-only; it never carries a student message.
  if (frame.event_type === "tutor_action_committed" || frame.event_type === "tutor_message") {
    if (!frame.payload.turn_id && shouldRenderTutorText(message)) {
      next.messages = appendMessage(state, {
        kind: "tutor",
        status: "STREAMING",
        turnId: frame.payload.turn_id,
        text: message.trim(),
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
  const restoredMessages = Array.isArray(summary.messages)
    ? summary.messages.flatMap((message) => {
        const text = String(message.content ?? "").trim();
        if (!text) return [];
        const kind = message.role === "student" ? "student" : message.role === "error" ? "error" : "tutor";
        if (kind !== "student" && !shouldRenderTutorText(text)) return [];
        const visible = kind === "error" ? projectTurnError(text) : text;
        return [{ status: message.status || "COMPLETED", turnId: message.turn_id, finishReason: message.finish_reason, id: message.message_id || nextMessageId(), kind, text: visible, action: String(message.action ?? ""), assistanceLevel: normalizeAssistanceLevel(Number(message.assistance_level ?? 0)), version: stateVersion } satisfies TutorMessage];
      })
    : null;
  return {
    ...state,
    cycleState: restoredState,
    seenVersion: Math.max(state.seenVersion, stateVersion),
    allowedNextInputs: allowed.length > 0 ? allowed : state.allowedNextInputs,
    problemActive: active || state.problemActive,
    pendingCommand: null,
    messages: restoredMessages ?? state.messages,
  };
}

export function mathTutorReducer(
  state: MathTutorUIState,
  action: MathTutorAction,
): MathTutorUIState {
  switch (action.type) {
    case "connection":
      return { ...state, connectionStatus: action.status, connectionNote: action.note,
        pendingCommand: action.status === "connected" ? state.pendingCommand : null,
        messages: action.status === "connected" ? state.messages : state.messages.map(m => m.status === "STREAMING" ? { ...m, status: "PARTIAL", finishReason: "STREAM_INTERRUPTED" } : m) };
    case "frame":
      return applyFrame(state, action.frame);
    case "restore":
      return applyRestore(state, action.summary);
    case "command_sent": {
      const text = action.text?.trim() ?? "";
      const last = state.messages[state.messages.length - 1];
      const duplicate =
        Boolean(text) &&
        state.pendingCommand !== null &&
        last?.kind === "student" &&
        last.text === text;
      return {
        ...state,
        pendingCommand: action.command,
        messages: text && !duplicate
          ? appendMessage(state, { kind: "student", text, action: action.command, assistanceLevel: 0, version: state.seenVersion })
          : state.messages,
      };
    }
    case "new_session": {
      const fresh = initialMathTutorState(action.sessionId);
      return { ...fresh, connectionStatus: state.connectionStatus, connectionNote: state.connectionNote };
    }
    default:
      return state;
  }
}
