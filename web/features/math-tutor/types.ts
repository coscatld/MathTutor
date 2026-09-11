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
  error_code?: string;
  content_mode?: string;
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
  delivery_id?: string;
  cycle_id?: string;
  problem_revision?: string;
  allowed_actions?: AllowedAction[];
  teaching_plan?: TeachingPlan | null;
  problem_context?: ProblemContext | null;
  evidence_summary?: EvidenceSummary | null;
  active_offer?: ActiveOffer | null;
  diagnosis?: DiagnosisSummary | null;
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
  | "request_solution"
  | "request_practice"
  | "request_foundation"
  | "request_review"
  | "resume_problem"
  | "end_problem"
  | "start_diagnostic"
  | "skip_diagnostic";

/** Envelope sent to the WS (allowlist: command/payload/cycle/session/idempotency keys). */
export interface ClientEnvelope {
  protocol_version?: number;
  command: string;
  payload: Record<string, string>;
  session_id: string;
  request_id?: string;
  idempotency_key?: string;
  expected_cycle_version?: number;
  expected_state_version?: number;
  cycle_id?: string;
  problem_revision?: string;
}

export interface AllowedAction {
  command: MathTutorCommand;
  enabled: boolean;
  reason_code: string;
  description: string;
  label: string;
}

/** Student-visible plan, never the material/answer keys used by the writer. */
export interface TeachingPlan {
  action: string;
  strategy: string;
  question_goal: string;
  target_subgoal_id: string;
  target_skill_ids: string[];
  reason_codes: string[];
  support_mode: string;
  exit_options: string[];
}

export interface ProblemContext {
  problem_id: string;
  display_text: string;
  skill_ids: string[];
  lifecycle: string;
  current_subgoal: { id: string; prompt_target: string; status: string } | null;
}

export interface EvidenceSummary {
  independent: number;
  assisted: number;
  post_solution: number;
  diagnostic: number;
  ungradable: number;
  status: string;
}

export interface ActiveOffer {
  offer_id: string;
  title: string;
  purpose: string;
  status: string;
}

export interface DiagnosisSummary {
  status: string;
  can_skip: boolean;
  question_count: number;
  answered?: number;
  started_at: string;
}

/** Session summary returned by GET /api/v2/math-tutor/sessions/{id} (recovery). */
export interface SessionSummary {
  problem_revision?: string;
  allowed_actions?: AllowedAction[];
  teaching_plan?: TeachingPlan | null;
  problem_context?: ProblemContext | null;
  evidence_summary?: EvidenceSummary | null;
  active_offer?: ActiveOffer | null;
  diagnosis?: DiagnosisSummary | null;
  effective_assistance_level?: number;
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
  cycleId: string;
  problemRevision: string;
  allowedActions?: AllowedAction[];
  teachingPlan?: TeachingPlan | null;
  problemContext?: ProblemContext | null;
  evidenceSummary?: EvidenceSummary | null;
  activeOffer?: ActiveOffer | null;
  diagnosis?: DiagnosisSummary | null;
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
  /** Actual disclosed help, not an estimate of student ability. */
  assistanceLevel: number;
  /** Command waiting for the server's turn_end (drives busy UI). */
  pendingCommand: MathTutorCommand | null;
  /** True once a problem was submitted and the cycle is still open. */
  problemActive: boolean;
}
