/**
 * MathTutor student protocol helpers — pure functions, no React.
 *
 * Every function here is unit-tested in web/tests/math-tutor-protocol.test.ts.
 */

import type {
  ClientEnvelope,
  MathTutorCommand,
  MathTutorEventType,
  RawStudentFrame,
  StudentFrame,
  StudentPayload,
} from "../types";

// ---------------------------------------------------------------------------
// Frame projection — the client-side mirror of the backend's public-schema
// guarantee. Only whitelisted public keys survive; everything else (internal
// solver/verification/model fields) is structurally discarded before any
// component can read it.
// ---------------------------------------------------------------------------

const PAYLOAD_KEYS: ReadonlyArray<keyof StudentPayload> = [
  "action",
  "effective_assistance_level",
  "student_message",
  "trigger_command",
  "error",
];

const EVENT_TYPES: ReadonlySet<string> = new Set<MathTutorEventType>([
  "tutor_action_committed",
  "cycle_state_committed",
  "turn_error",
  "turn_end",
]);

function asStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string");
}

/**
 * Project a raw WS frame onto the typed public schema.
 * Unknown event types and non-student frames project to null (dropped).
 */
export function projectStudentFrame(raw: RawStudentFrame): StudentFrame | null {
  if (typeof raw !== "object" || raw === null) return null;
  if (raw.audience !== undefined && raw.audience !== "student") return null;

  const eventType = String(raw.event_type ?? "");
  if (!EVENT_TYPES.has(eventType)) return null;

  const rawPayload =
    typeof raw.payload === "object" && raw.payload !== null
      ? (raw.payload as Record<string, unknown>)
      : {};

  const payload: StudentPayload = {};
  for (const key of PAYLOAD_KEYS) {
    const value = rawPayload[key];
    if (value === undefined || value === null) continue;
    if (key === "effective_assistance_level") {
      const level = Number(value);
      payload[key] = Number.isFinite(level) ? level : 0;
      continue;
    }
    payload[key] = String(value);
  }

  const frame: StudentFrame = {
    event_type: eventType as MathTutorEventType,
    cycle_state: String(raw.cycle_state ?? ""),
    cycle_state_version: Number.isFinite(Number(raw.cycle_state_version))
      ? Number(raw.cycle_state_version)
      : 0,
    allowed_next_inputs: asStringList(raw.allowed_next_inputs),
    payload,
  };
  return frame;
}

// ---------------------------------------------------------------------------
// Stale-frame rule (B4): tutor_action_committed / cycle_state_committed frames
// with cycle_state_version ≤ seenVersion are dropped. turn_error/turn_end are
// never dropped. A zero seenVersion (fresh session) accepts everything so an
// initial version-0 state frame is never discarded.
// ---------------------------------------------------------------------------

export function isStaleFrame(frame: StudentFrame, seenVersion: number): boolean {
  if (frame.event_type === "turn_error" || frame.event_type === "turn_end") {
    return false;
  }
  if (seenVersion <= 0) return false;
  return frame.cycle_state_version <= seenVersion;
}

// ---------------------------------------------------------------------------
// Envelope construction (backend allowlist: command/payload/cycle/session/
// request/idempotency/expected_version keys only).
// ---------------------------------------------------------------------------

export function buildEnvelope(
  command: MathTutorCommand,
  payload: Record<string, string>,
  sessionId: string,
  options: {
    requestId?: string;
    idempotencyKey?: string;
    expectedCycleVersion?: number;
  } = {},
): string {
  const envelope: ClientEnvelope = {
    command,
    payload,
    session_id: sessionId,
  };
  if (options.requestId) envelope.request_id = options.requestId;
  if (options.idempotencyKey) envelope.idempotency_key = options.idempotencyKey;
  if (options.expectedCycleVersion !== undefined && options.expectedCycleVersion > 0) {
    envelope.expected_cycle_version = options.expectedCycleVersion;
  }
  return JSON.stringify(envelope);
}

/** Commands that must carry free-text input from a composer. */
export function commandNeedsText(command: MathTutorCommand): boolean {
  return (
    command === "submit_problem" ||
    command === "clarify_problem" ||
    command === "clarify_attempt"
  );
}

// ---------------------------------------------------------------------------
// Capability → action buttons (INVARIANT 5: the UI derives EVERY capability
// from allowed_next_inputs. Commands not in the table render no button.)
// ---------------------------------------------------------------------------

export type ActionVariant = "primary" | "secondary" | "solution" | "quiet" | "offer";

export interface ActionButtonSpec {
  command: MathTutorCommand;
  label: string;
  variant: ActionVariant;
  /** Whether this input needs the attempt composer instead of a plain button. */
  usesAttemptComposer?: boolean;
  /** Whether this input needs the problem composer. */
  usesProblemComposer?: boolean;
}

const ACTION_BUTTON_TABLE: Readonly<Record<string, ActionButtonSpec>> = {
  submit_attempt: {
    command: "submit_attempt",
    label: "提交答案",
    variant: "primary",
    usesAttemptComposer: true,
  },
  submit_problem: {
    command: "submit_problem",
    label: "提交题目",
    variant: "primary",
    usesProblemComposer: true,
  },
  request_hint: { command: "request_hint", label: "请求提示", variant: "secondary" },
  request_explanation: {
    command: "request_explanation",
    label: "请求讲解",
    variant: "secondary",
  },
  request_example: {
    command: "request_example",
    label: "请求示例",
    variant: "secondary",
  },
  solution_shown_permitted: {
    command: "solution_shown_permitted",
    label: "查看完整答案",
    variant: "solution",
  },
  request_solution: {
    command: "request_solution",
    label: "查看完整答案",
    variant: "solution",
  },
  accept_practice_offer: {
    command: "accept_practice_offer",
    label: "接受练习",
    variant: "offer",
  },
  decline_practice_offer: {
    command: "decline_practice_offer",
    label: "暂不练习",
    variant: "quiet",
  },
  cancel_turn: { command: "cancel_turn", label: "结束本题", variant: "quiet" },
};

/**
 * Map the server's allowed_next_inputs onto renderable buttons.
 * Order is stable and solution-disclosure entries always come last so the
 * full-answer action is never promoted above learning-oriented actions.
 */
export function allowedInputsToButtons(allowed: string[]): ActionButtonSpec[] {
  const order: MathTutorCommand[] = [
    "request_hint",
    "request_explanation",
    "request_example",
    "accept_practice_offer",
    "decline_practice_offer",
    "cancel_turn",
    "solution_shown_permitted",
    "request_solution",
  ];
  const specs: ActionButtonSpec[] = [];
  for (const name of order) {
    const spec = ACTION_BUTTON_TABLE[name];
    if (spec && allowed.includes(name)) specs.push(spec);
  }
  return specs;
}

/** Whether the attempt composer should be enabled for these inputs. */
export function allowsAttempt(allowed: string[]): boolean {
  return allowed.includes("submit_attempt");
}

/** Whether the problem composer should be enabled for these inputs. */
export function allowsProblemSubmission(allowed: string[]): boolean {
  return allowed.includes("submit_problem");
}

// ---------------------------------------------------------------------------
// Problem LaTeX extraction — the backend embeds the verified display_latex in
// the verification message ("题目已解析并验证：<latex>", action="verified").
// ---------------------------------------------------------------------------

const VERIFIED_MESSAGE_PREFIX = "题目已解析并验证：";

/**
 * Extract the verified problem's display LaTeX from a verification frame.
 * Returns null when the frame is not a verification message.
 */
export function extractDisplayLatex(
  studentMessage: string,
  action: string,
): string | null {
  if (action !== "verified") return null;
  const message = String(studentMessage ?? "");
  if (message.startsWith(VERIFIED_MESSAGE_PREFIX)) {
    const latex = message.slice(VERIFIED_MESSAGE_PREFIX.length).trim();
    if (latex) return latex;
  }
  return message.trim() || null;
}

/**
 * Wrap raw display LaTeX in display-math delimiters so remark-math +
 * rehype-katex typeset it. Content that already carries delimiters is
 * rendered as-is.
 */
export function wrapLatexForDisplay(latex: string): string {
  const trimmed = String(latex ?? "").trim();
  if (!trimmed) return "";
  if (/^\$\$/.test(trimmed) || /^\\\[/.test(trimmed)) return trimmed;
  return `$$\n${trimmed}\n$$`;
}

// ---------------------------------------------------------------------------
// Hint ladder — pure display normalization (data comes from event frames).
// ---------------------------------------------------------------------------

export const HINT_LADDER_MAX = 5;

/** Clamp a raw assistance level into the 1-5 ladder range (0 = none shown). */
export function normalizeAssistanceLevel(level: number): number {
  if (!Number.isFinite(level)) return 0;
  return Math.min(HINT_LADDER_MAX, Math.max(0, Math.round(level)));
}

// ---------------------------------------------------------------------------
// Human-facing labels for tutor actions (no raw codes/IDs on screen).
// ---------------------------------------------------------------------------

const ACTION_LABELS: Readonly<Record<string, string>> = {
  ASK_STUDENT: "提问",
  GIVE_HINT: "提示",
  EXPLAIN_CONCEPT: "讲解",
  SHOW_EXAMPLE: "示例",
  SHOW_SOLUTION: "完整答案",
  REQUEST_RETRY: "再试一次",
  GENERATE_PRACTICE: "练习",
  verified: "题目确认",
  correct: "回答正确",
  incorrect: "回答不正确",
  partial: "部分正确",
  ambiguous: "需要澄清",
};

export function actionLabel(action: string): string {
  const trimmed = String(action ?? "").trim();
  if (!trimmed) return "";
  return ACTION_LABELS[trimmed] ?? trimmed;
}

/** Frame detail used to seed a new session id (pure, testable fallback). */
export function makeSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `mt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
