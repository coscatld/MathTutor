/**
 * Desktop product surfaces — wire types for /api/v2/math-tutor/desktop.
 *
 * These mirror the backend's PUBLIC projections only. No internal field
 * (storage refs, content hashes, chunk data, parser tracebacks, mastery or
 * attestation material) may ever appear here or in the components.
 */

export interface DesktopSettings {
  initial_assessment_required?: boolean;
  vision_mode?: "auto" | "enabled" | "disabled";
  preset_id: string;
  model: string;
  base_url: string;
  is_configured: boolean;
  onboarding_completed: boolean;
  /** Safe display tail only; the backend never returns the stored value. */
  key_masked: string | null;
  connection_status?: "unconfigured" | "configured" | "connecting" | "success" | "failure";
  provider_configs?: Record<string, {
    vision_mode?: "auto" | "enabled" | "disabled";
    model: string;
    base_url: string;
    has_api_key: boolean;
    key_masked: string | null;
  }>;
}

export interface ProviderPreset {
  preset_id: string;
  label: string;
  custom: boolean;
  default_model?: string;
  base_url?: string;
  requires_api_key?: boolean;
  editable_base_url?: boolean;
  local?: boolean;
}

export interface TutorSettings {
  personality: string;
  custom_instruction: string;
  presets: Array<{ id: string; label: string }>;
}

export interface SettingsSaveResult {
  initial_assessment_required?: boolean;
  vision_mode?: "auto" | "enabled" | "disabled";
  preset_id: string;
  model: string;
  base_url: string;
  /** Masked tail ("••••••••abcd") — the frontend never sees a full key. */
  key_masked: string | null;
  is_configured: boolean;
  onboarding_completed: boolean;
  connection_status?: "unconfigured" | "configured" | "connecting" | "success" | "failure";
}

export type EmbeddingProvider = "local" | "cloud";
export type EmbeddingStatus = "disabled" | "local_ready" | "cloud_configured" | "incomplete";
export type LocalEmbeddingDownloadStatus = "not_downloaded" | "downloading" | "ready" | "failed";

export interface LocalEmbeddingModel {
  model_id: string;
  label: string;
  dimension: number;
  size_label: string;
  source: string;
}

export interface EmbeddingSettings {
  enabled: boolean;
  provider: EmbeddingProvider;
  local_model_id: string;
  local_models: LocalEmbeddingModel[];
  local_download_status: LocalEmbeddingDownloadStatus;
  local_download_error: string | null;
  cloud_base_url: string;
  cloud_model: string;
  cloud_has_api_key: boolean;
  cloud_key_masked: string | null;
  status: EmbeddingStatus;
  status_label: string;
  runtime_reason: string | null;
  reindex_required: boolean;
}

export interface EmbeddingTestResult {
  ok: boolean;
  message: string;
}

export interface TestConnectionResult {
  status: "ok" | "error";
  message: string;
  resolved_model?: string;
}

export type CheckValue = "ok" | "degraded" | "error";

export type ReadinessStatus = "READY" | "DEGRADED" | "BLOCKED";

export interface Readiness {
  status: ReadinessStatus;
  checks: Record<string, CheckValue>;
  /** Human reasons per non-ok check (friendly Chinese text only). */
  reasons: Record<string, string>;
}

export type DocumentStatus =
  | "importing"
  | "parsing"
  | "ready"
  | "ready_with_warnings"
  | "needs_ocr"
  | "failed";

export interface DesktopDocument {
  document_id: string;
  filename: string;
  mime_type: string;
  status: DocumentStatus;
  retrieval_enabled: boolean;
  size_bytes: number;
  page_count: number;
  chunk_count: number;
  image_count: number;
  empty_page_count: number;
  /** Empty-page / no-text-layer warning; never raw parser internals. */
  parse_warning: string | null;
  created_at: string;
  /** Friendly parse error (failed / needs_ocr) — never raw tracebacks. */
  error: string | null;
  conversation_ids?: string[];
  conversation_titles?: Record<string, string>;
  is_global?: boolean;
}

export type MemorySourceType = "USER_EXPLICIT" | "MODEL_INFERRED" | "USER_CONFIRMED";

export interface DesktopMemory {
  memory_id: string;
  memory_type: string;
  subject: string;
  predicate: string;
  object_json: Record<string, unknown>;
  source_type: MemorySourceType;
  confidence: number;
  retrieval_enabled: boolean;
  created_at: string;
  updated_at: string;
}

export type OfferStatus = "ACTIVE" | "ACCEPTED" | "EXPIRED" | "REVOKED";

/** Public practice-offer projection (contract: no solution/answer/mastery). */
export interface PracticeOffer {
  offer_id: string;
  status: OfferStatus;
  skill_labels: string[];
  concept_labels: string[];
  difficulty: string;
  offered_at: string;
  expires_at: string;
  parent_cycle_id: string;
  title?: string;
  reason?: string;
  observation_goal?: string;
  response_mode?: "free_response" | "single_choice";
  observation_kind?: "independent_transfer" | "diagnostic";
  question_count?: number;
  display_status?: "pending" | "in_progress" | "completed" | "later" | "history";
  feedback?: "later" | "not_relevant" | null;
  resume_session_id?: string | null;
  evidence_href?: string;
  update_reason?: string | null;
  evidence_ids?: string[];
  result_summary?: { independent_correct: number; first_free_response?: number; diagnostic_correct?: number; helped: number; observations: number } | null;
}

export type OfferAcceptState = "idle" | "connecting" | "accepting" | "accepted" | "error";

// ---------------------------------------------------------------------------
// Bootstrap — startup sequence (wire contract; MAIN implements the backend).
// ---------------------------------------------------------------------------

export type BootstrapStepStatus = "ok" | "degraded" | "blocked";

export interface BootstrapStep {
  /** Known keys: check_data_root|database|migration|secret_store|document_storage|curriculum|retrieval|outbox|model_gateway. */
  key: string;
  /** Friendly Chinese label (backend supplies it; UI falls back to a local map). */
  label: string;
  status: BootstrapStepStatus;
  /** Friendly explanation only — the backend never sends internals here; the UI renders it as plain text regardless. */
  detail: string | null;
}

export interface BootstrapPayload {
  readiness: ReadinessStatus;
  /** "READY" once the boot sequence finished; anything else = still booting. */
  phase: string;
  reason: string | null;
  steps: BootstrapStep[];
}

// ---------------------------------------------------------------------------
// Model connection test (wire contract; MAIN implements the backend).
// ---------------------------------------------------------------------------

export type ModelErrorKind =
  | "response_incomplete"
  | "request_rejected"
  | "quota_exceeded"
  | "rate_limited"
  | "provider_error"
  | "credential_invalid"
  | "network_unavailable"
  | "provider_unsupported"
  | "model_unavailable"
  | "gateway_disabled";

export interface ModelTestResult {
  ok: boolean;
  error_kind: ModelErrorKind | null;
  /** Friendly Chinese message only — never raw tracebacks or headers. */
  message: string | null;
  resolved_model?: string;
}

// ---------------------------------------------------------------------------
// Backups (wire contract; MAIN implements the backend).
// ---------------------------------------------------------------------------

export type BackupIntegrity = "ok" | "unknown";

export interface BackupRecord {
  /** File name or relative name only — the backend never sends a sensitive full path. */
  path: string;
  created_at: string;
  size_bytes: number;
  integrity: BackupIntegrity;
  /** First 12 hex chars of the file digest. */
  sha256_prefix: string;
}

export interface BackupsList {
  backups: BackupRecord[];
  /** Friendly short directory name (no sensitive user paths). */
  backup_dir: string;
  policy: {
    retention_limit: number;
    mode: string;
  };
}

export type BackupActionResult =
  | { ok: true; backup: BackupRecord }
  | { ok: false; message: string };

export type BackupVerifyResult = { ok: true } | { ok: false; message: string };

export type BackupRestoreResult =
  | { ok: true; restart_required: true; message: string }
  | { ok: false; message: string };

// ---------------------------------------------------------------------------
// Student summary — read-only projection (wire contract; MAIN implements).
// ---------------------------------------------------------------------------

export interface SkillSummary {
  code: string;
  label: string;
  /** 0..1 or null when no observation yet. Read-only: never editable here. */
  mastery: number | null;
  grade_band: string | null;
  evidence_summary?: import("../types").EvidenceSummary | null;
  evidence_status?: string;
  observation?: string;
  counts?: Record<string, {correct: number; incorrect: number}>;
  last_checked_at?: string | null;
  evidence_count?: number;
  joint_task_evidence?: number;
  next_href?: string;
  next_action?: string;
}

export interface ItemErrorObservation {
  rule_id: string;
  label: string;
  event_id: string;
  assessment_id: string;
  cycle_id: string;
  related_skill_ids: string[];
  last_seen_at: string | null;
  status: "unlocalized" | "corrected_later";
  correction_event_id: string | null;
}

export interface StudentSummary {
  skills: SkillSummary[];
  total_attempts: number;
  active_misconceptions: number;
  misconceptions?: {rule_id: string; label: string; skill_ids: string[]; last_seen_at: string | null}[];
  item_error_observations?: ItemErrorObservation[];
  schema_version?: string;
  has_conversations?: boolean;
  has_independent_evidence?: boolean;
  coverage?: {supported_skills: number; observed_skills: number};
}

export interface LearningEvidence {
  event_id: string;
  event_seq: number;
  cycle_id: string;
  occurred_at: string;
  skill_ids: string[];
  problem_text: string;
  student_response: string;
  correctness: string | null;
  evidence_kind: string;
  completion_scope: string;
  first_target: boolean;
  excluded: boolean;
  session_id: string | null;
}

export interface EvidencePage { items: LearningEvidence[]; next_cursor: number | null }

// ---------------------------------------------------------------------------
// Privacy / data lifecycle (wire contract; MAIN implements the backend).
// ---------------------------------------------------------------------------

export interface PurgeDocumentsResult {
  ok: boolean;
  documents_soft_deleted: number;
  chunks_removed: number;
  vectors_cleared: number;
  index_builds_removed: number;
  storage_files_removed: number;
}

export interface PurgeMemoryResult {
  ok: boolean;
  memories_soft_deleted: number;
}

export interface EducationalHistoryResult {
  ok: boolean;
  deleted_rows: number;
  by_table: Record<string, number>;
  kept_skeleton_tables: string[];
  projection: {
    projection_version: number;
    estimator_version: string;
    evidence_remaining: number;
    observations_remaining: number;
  } | null;
}

export interface RebuildIndexesResult {
  ok: boolean;
  documents: Record<
    string,
    { status: "rebuilt" | "unavailable" | "no_chunks"; reason?: string; index_version: number | null }
  >;
}

export interface ExportSkill {
  skill_id: string;
  mastery: number | null;
}

export interface ExportMisconception {
  rule_id: string;
  label?: string;
  skill_ids?: string[];
  last_seen_at?: string | null;
  status: string;
  confidence: number | null;
}

export interface StudentExport {
  meta: { schema_version: string; exported_at: string; student_id: string };
  documents: DesktopDocument[];
  memory: DesktopMemory[];
  student_summary: {
    total_attempts: number;
    estimator_version: string;
    projection_version: number | null;
    skills: ExportSkill[];
    active_misconceptions: ExportMisconception[];
    item_error_observations?: ItemErrorObservation[];
  };
}

export interface CostSettingsInput {
  input_price_per_mtok: number | null;
  output_price_per_mtok: number | null;
  currency: string;
  daily_budget: number | null;
  daily_token_budget: number | null;
}

export interface CostSettings extends CostSettingsInput {
  today: { date: string; tokens: number; cost: number; currency: string };
  over_budget: boolean;
}
