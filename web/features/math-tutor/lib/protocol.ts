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
  AllowedAction,
  RecoveryProblem,
} from "../types";
import { projectActiveOffer, projectDiagnosis, projectEvidenceSummary, projectProblemContext, projectTeachingPlan } from "./teaching-contract";

// ---------------------------------------------------------------------------
// Frame projection — the client-side mirror of the backend's public-schema
// guarantee. Only whitelisted public keys survive; everything else (internal
// solver/verification/model fields) is structurally discarded before any
// component can read it.
// ---------------------------------------------------------------------------

const PAYLOAD_KEYS: ReadonlyArray<keyof StudentPayload> = [
  "message_id", "turn_id", "conversation_id", "status", "finish_reason", "final_text",
  "action",
  "effective_assistance_level",
  "student_message",
  "trigger_command",
  "error",
  "error_code", "content_mode",
  "verification_notice",
];

const EVENT_TYPES: ReadonlySet<string> = new Set<MathTutorEventType>([
  "tutor_action_committed",
  "tutor_message",
  "cycle_state_committed",
  "turn_error",
  "turn_end",
  "assistant_start", "assistant_delta", "assistant_complete", "assistant_partial", "assistant_error",
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
    if (key === "verification_notice") {
      if (typeof value === "string") payload[key] = value.trim();
      continue;
    }
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
  if (typeof raw.cycle_id === "string") frame.cycle_id = raw.cycle_id;
  if (typeof raw.delivery_id === "string" && raw.delivery_id.trim()) frame.delivery_id = raw.delivery_id;
  if (typeof raw.problem_revision === "string") frame.problem_revision = raw.problem_revision;
  if (Array.isArray(raw.allowed_actions)) frame.allowed_actions = projectAllowedActions(raw.allowed_actions);
  // StudentPublicEvent serializes absent optional fields as null on generic
  // lifecycle frames. Those are not state deletions. Only the public snapshot
  // (identified by its capability array) can explicitly clear contextual data.
  const hasSnapshot = Array.isArray(raw.allowed_actions);
  const hasContextField = (name: string) => raw[name] !== undefined && (raw[name] !== null || hasSnapshot);
  if (hasContextField("teaching_plan")) frame.teaching_plan = projectTeachingPlan(raw.teaching_plan);
  if (hasContextField("problem_context")) frame.problem_context = projectProblemContext(raw.problem_context);
  if (hasContextField("evidence_summary")) frame.evidence_summary = projectEvidenceSummary(raw.evidence_summary);
  if (hasContextField("active_offer")) frame.active_offer = projectActiveOffer(raw.active_offer);
  if (hasContextField("diagnosis")) frame.diagnosis = projectDiagnosis(raw.diagnosis);
  if (hasContextField("recovery_problem")) frame.recovery_problem = projectRecoveryProblem(raw.recovery_problem);
  return frame;
}

export function projectRecoveryProblem(raw: unknown): RecoveryProblem | null {
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  const families = ["arithmetic", "polynomial", "linear", "quadratic", "linear_system"];
  if (typeof value.text !== "string" || !value.text.trim() || value.text.length > 500
      || typeof value.relation !== "string" || !value.relation.trim() || value.relation.length > 500
      || typeof value.problem_type !== "string" || !families.includes(value.problem_type)) return null;
  return {text: value.text.trim(), problem_type: value.problem_type, relation: value.relation.trim()};
}

// ---------------------------------------------------------------------------
// Stale-frame rule (B4): tutor_action_committed / cycle_state_committed frames
// with cycle_state_version ≤ seenVersion are dropped. turn_error/turn_end are
// never dropped. A zero seenVersion (fresh session) accepts everything so an
// initial version-0 state frame is never discarded.
// ---------------------------------------------------------------------------

export function isStaleFrame(frame: StudentFrame, seenVersion: number): boolean {
  if (frame.event_type.startsWith("assistant_")) return false;
  if (frame.event_type === "turn_error" || frame.event_type === "turn_end" || frame.event_type === "tutor_message") {
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
  payload: Record<string, string | string[]>,
  sessionId: string,
  options: {
    requestId?: string;
    idempotencyKey?: string;
    expectedCycleVersion?: number;
    cycleId?: string;
    problemRevision?: string;
  } = {},
): string {
  const envelope: ClientEnvelope = {
    protocol_version: 2,
    command,
    payload,
    session_id: sessionId,
  };
  if (options.requestId) envelope.request_id = options.requestId;
  if (options.idempotencyKey) envelope.idempotency_key = options.idempotencyKey;
  if (options.cycleId !== undefined) envelope.cycle_id = options.cycleId;
  if (options.problemRevision !== undefined) envelope.problem_revision = options.problemRevision;
  if (options.expectedCycleVersion !== undefined && options.expectedCycleVersion >= 0) {
    envelope.expected_cycle_version = options.expectedCycleVersion;
    envelope.expected_state_version = options.expectedCycleVersion;
  }
  return JSON.stringify(envelope);
}

/** Commands that must carry free-text input from a composer. */
export function commandNeedsText(command: MathTutorCommand): boolean {
  return (
    command === "send_message" ||
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
    // Read-only compatibility with old server projections; never send events.
    command: "request_solution",
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
  request_practice: { command: "request_practice", label: "我想独立练一道", variant: "secondary" },
  request_foundation: { command: "request_foundation", label: "先补基础", variant: "secondary" },
  request_review: { command: "request_review", label: "做一道复习题", variant: "secondary" },
  resume_problem: { command: "resume_problem", label: "回到原题", variant: "secondary" },
  end_problem: { command: "end_problem", label: "结束本题", variant: "quiet" },
  start_diagnostic: { command: "start_diagnostic", label: "可选：了解当前基础", variant: "secondary" },
  skip_diagnostic: { command: "skip_diagnostic", label: "跳过诊断，继续辅导", variant: "quiet" },
  cancel_turn: { command: "cancel_turn", label: "停止生成", variant: "quiet" },
};

/**
 * Map the server's allowed_next_inputs onto renderable buttons.
 * Order is stable and solution-disclosure entries always come last so the
 * full-answer action is never promoted above learning-oriented actions.
 */
export function allowedInputsToButtons(allowed: string[]): ActionButtonSpec[] {
  // The legacy name is an inbound projection alias, not a sendable command.
  const order: Array<MathTutorCommand | "solution_shown_permitted"> = [
    "request_hint",
    "request_explanation",
    "request_example",
    "request_practice",
    "request_foundation",
    "request_review",
    "accept_practice_offer",
    "decline_practice_offer",
    "resume_problem",
    "end_problem",
    "start_diagnostic",
    "skip_diagnostic",
    "cancel_turn",
    "solution_shown_permitted",
    "request_solution",
  ];
  const specs: ActionButtonSpec[] = [];
  for (const name of order) {
    const spec = ACTION_BUTTON_TABLE[name];
    if (spec && allowed.includes(name) && !specs.some(item => item.command === spec.command)) specs.push(spec);
  }
  return specs;
}

/** Reject malformed capability proposals; only the public command table renders. */
export function projectAllowedActions(raw: unknown): AllowedAction[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap(value => {
    if (!value || typeof value !== "object" || typeof value.enabled !== "boolean") return [];
    const spec = ACTION_BUTTON_TABLE[String(value.command)];
    if (!spec || spec.command !== value.command) return [];
    return [{command: spec.command, enabled: value.enabled, reason_code: String(value.reason_code || ""),
      description: String(value.description || ""), label: String(value.label || "")}];
  });
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
  TUTOR_CHAT: "Tutor",
  TUTOR_CHAT_FIGURE: "讲解配图",
  ASK_STUDENT: "提问",
  GIVE_HINT: "提示",
  EXPLAIN_CONCEPT: "讲解",
  SHOW_EXAMPLE: "示例",
  SHOW_SOLUTION: "完整答案",
  SHOW_GRAPH: "图像",
  REQUEST_RETRY: "再试一次",
  GENERATE_PRACTICE: "练习",
  CORRECT_STEP: "步骤纠错",
  RESUME_PROBLEM: "回到原题",
  END_PROBLEM: "本题已结束",
  SELF_REPORT: "理解反馈（自述）",
  DIAGNOSTIC: "可跳过的基础检查",
  DIAGNOSTIC_COMPLETE: "诊断已完成",
  ERROR_ANALYSIS: "教师示例找错",
  PRACTICE_DECLINED: "已略过练习",
  verified: "题目确认",
  correct: "回答正确",
  incorrect: "回答不正确",
  partial: "部分正确",
  ambiguous: "需要澄清",
  practice_offered: "练习邀请",
  practice_started: "开始练习",
  CLARIFY_INTENT: "确认你的意思",
  ask_subgoal: "当前小问题",
  teacher_error_example: "找错练习 · 示例含错误",
  local_demonstration: "示范一步",
  diagnostic_started: "可跳过的基础检查",
  diagnostic_skipped: "已跳过检查",
  problem_resumed: "回到原题",
  problem_ended: "本题已结束",
};

export function actionLabel(action: string): string {
  const trimmed = String(action ?? "").trim();
  if (!trimmed) return "";
  if (ACTION_LABELS[trimmed]) return ACTION_LABELS[trimmed];
  if (/^(submit_problem|clarify_problem|clarify_attempt|grounding|cycle_state)/i.test(trimmed)) {
    return "";
  }
  return trimmed;
}

const STUDENT_STEP_FAILED = "刚才这一步没有处理成功，请再试一次。";

/** Drop internal command acknowledgements; they are not assistant utterances. */
export function shouldRenderTutorText(text: string): boolean {
  const compact = String(text ?? "").trim();
  if (!compact) return false;
  return !/^命令\s+\w+\s+已确认/.test(compact);
}

/** Project a turn_error string onto student-safe copy. */
export function projectTurnError(text: string): string {
  const compact = String(text ?? "").trim();
  if (!compact) return STUDENT_STEP_FAILED;
  if (/^(未知命令|内部错误|forbidden envelope|unknown envelope)/i.test(compact)) return STUDENT_STEP_FAILED;
  if (/状态\s+\w+\s+不接受命令/.test(compact)) return STUDENT_STEP_FAILED;
  if (/(submit_problem|clarify_problem|clarify_attempt|grounding_ok|cycle_state)/i.test(compact)) {
    return STUDENT_STEP_FAILED;
  }
  return compact;
}

/** Frame detail used to seed a new session id (pure, testable fallback). */
export function makeSessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `mt-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
