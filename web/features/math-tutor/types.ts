/**
 * MathTutor student workspace — wire types (Phase 3F).
 *
 * These mirror the backend's StudentPublicEvent schema (audience="student")
 * over `/api/v2/math-tutor/ws`. The student UI ONLY consumes these public
 * fields — internal solver/verification/model fields must never be read
 * or rendered (see PROJECTED frame whitelist in lib/protocol.ts).
 */

export type MathTutorEventType =
  | "tutor_action_committed"
  | "tutor_message"
  | "cycle_state_committed"
  | "turn_error"
  | "turn_end"
  | "assistant_start" | "assistant_delta" | "assistant_complete" | "assistant_partial" | "assistant_error";

/** Public payload of a student frame (projected server-side). */
export interface StudentPayload {
  message_id?: string;
  turn_id?: string;
  conversation_id?: string;
  status?: string;
  finish_reason?: string;
  final_text?: string;
  action?: string;
  effective_assistance_level?: number;
  student_message?: string;
  trigger_command?: string;
  /** Present on turn_error frames. */
  error?: string;
}

/** Raw frame as parsed from the WS (before client-side projection). */
export interface RawStudentFrame {
  event_type?: string;
  audience?: string;
  cycle_id?: string;
  cycle_state?: string;
  cycle_state_version?: number;
  allowed_next_inputs?: unknown;
  payload?: unknown;
  [key: string]: unknown;
}

/** Projected, whitelisted student frame — the only shape the UI consumes. */
export interface StudentFrame {
  event_type: MathTutorEventType;
  cycle_state: string;
  cycle_state_version: number;
  allowed_next_inputs: string[];
  payload: StudentPayload;
}

/**
 * Commands the client may send (state-machine user commands + the
 * solution-disclosure input names the contract reserves for the future).
 */
export type MathTutorCommand =
  | "send_message"
  | "submit_problem"
  | "submit_attempt"
  | "request_hint"
  | "request_explanation"
  | "request_example"
  | "cancel_turn"
  | "clarify_problem"
  | "clarify_attempt"
  | "accept_practice_offer"
  | "decline_practice_offer"
  | "solution_shown_permitted"
  | "request_solution";

/** Envelope sent to the WS (allowlist: command/payload/cycle/session/idempotency keys). */
export interface ClientEnvelope {
  command: string;
  payload: Record<string, string>;
  session_id: string;
  request_id?: string;
  idempotency_key?: string;
  expected_cycle_version?: number;
}

/** Session summary returned by GET /api/v2/math-tutor/sessions/{id} (recovery). */
export interface SessionSummary {
  client_session_id?: string;
  cycle_id?: string;
  state?: string;
  state_version?: number;
  allowed_next_inputs?: string[];
  title?: string;
  document_ids?: string[];
  messages?: Array<{
    message_id?: string;
    status?: string;
    turn_id?: string;
    finish_reason?: string;
    role?: "student" | "tutor" | "error";
    content?: string;
    action?: string;
    assistance_level?: number;
    created_at?: string;
  }>;
}

export type ConnectionStatus =
  | "connecting"
  | "connected"
  | "reconnecting"
  | "disconnected"
  | "error";

/** A rendered tutor message (from tutor_action_committed / turn_error). */
export interface TutorMessage {
  status?: string;
  turnId?: string;
  finishReason?: string;
  id: string;
  kind: "student" | "tutor" | "error";
  text: string;
  action: string;
  assistanceLevel: number;
  version: number;
}

/** Full UI state for the workspace (see lib/reducer.ts). */
export interface MathTutorUIState {
  connectionStatus: ConnectionStatus;
  /** Status detail for the user (Chinese, no internal codes). */
  connectionNote: string;
  sessionId: string;
  cycleState: string;
  /** Highest cycle_state_version seen — frames ≤ this are stale (B4). */
  seenVersion: number;
  allowedNextInputs: string[];
  messages: TutorMessage[];
  /** Verified problem LaTeX (extracted from the verification message). */
  problemLatex: string | null;
  /** Latest assistance level from events (drives the HintLadder). */
  assistanceLevel: number;
  /** Command waiting for the server's turn_end (drives busy UI). */
  pendingCommand: MathTutorCommand | null;
  /** True once a problem was submitted and the cycle is still open. */
  problemActive: boolean;
}
