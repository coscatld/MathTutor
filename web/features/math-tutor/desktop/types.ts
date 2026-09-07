/**
 * Desktop product surfaces — wire types for /api/v2/math-tutor/desktop.
 *
 * These mirror the backend's PUBLIC projections only. No internal field
 * (storage refs, content hashes, chunk data, parser tracebacks, mastery or
 * attestation material) may ever appear here or in the components.
 */

export interface DesktopSettings {
  preset_id: string;
  model: string;
  base_url: string;
  is_configured: boolean;
  onboarding_completed: boolean;
  /** Safe display tail only; the backend never returns the stored value. */
  key_masked: string | null;
}

export interface ProviderPreset {
  preset_id: string;
  label: string;
  custom: boolean;
}

export interface SettingsSaveResult {
  preset_id: string;
  model: string;
  base_url: string;
  /** Masked tail ("••••••••abcd") — the frontend never sees a full key. */
  key_masked: string | null;
  is_configured: boolean;
  onboarding_completed: boolean;
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
}

export interface StudentSummary {
  skills: SkillSummary[];
  total_attempts: number;
  active_misconceptions: number;
}

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
  status: string;
  confidence: number;
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
  };
}
