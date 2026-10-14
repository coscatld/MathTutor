/**
 * Desktop product API client — typed fetch helpers for
 * /api/v2/math-tutor/desktop, plus pure display formatters.
 *
 * KEY SAFETY INVARIANT: this module NEVER writes an API key to
 * localStorage/sessionStorage/IndexedDB. The only place a key ever goes is
 * the PUT /settings request body (→ backend SecretStore); the frontend only
 * keeps the masked tail in React state for the current page visit.
 */

import { apiFetch } from "@/lib/api";
import type {
  BackupActionResult,
  BackupRecord,
  BackupRestoreResult,
  BackupsList,
  BackupVerifyResult,
  BootstrapPayload,
  DesktopDocument,
  DesktopMemory,
  DesktopSettings,
  EmbeddingSettings,
  EmbeddingTestResult,
  EducationalHistoryResult,
  ModelErrorKind,
  ModelTestResult,
  PracticeOffer,
  ProviderPreset,
  PurgeDocumentsResult,
  PurgeMemoryResult,
  Readiness,
  RebuildIndexesResult,
  SettingsSaveResult,
  StudentExport,
  StudentSummary,
  TestConnectionResult,
  TutorSettings, CostSettings, CostSettingsInput } from "../types";

export const DESKTOP_PREFIX = "/api/v2/math-tutor/desktop";

export async function resumePractice(offerId: string): Promise<string> {
  const response = await apiFetch(`/api/v2/math-tutor/offers/${encodeURIComponent(offerId)}/resume`, {method:"POST"});
  if (!response.ok) throw new DesktopApiError(await toFriendlyMessage(response, "暂时无法继续，请刷新列表。"));
  const result = await response.json() as {session_id: string};
  return result.session_id;
}

export async function fetchLearningEvidence(query: { skill_id?: string; cycle_id?: string; cursor?: number }) {
  const params = new URLSearchParams();
  Object.entries(query).forEach(([key, value]) => { if (value !== undefined) params.set(key, String(value)); });
  return desktopFetch<import("../types").EvidencePage>(`/student-evidence?${params}`);
}

export async function excludeLearningEvidence(eventId: string) {
  return desktopFetch<{ok: boolean}>(`/student-evidence/${encodeURIComponent(eventId)}/exclude`, {method: "POST"});
}

export async function recomputeLearningProfile() {
  return desktopFetch<{ok: boolean}>("/privacy/recompute-profile", {method: "POST"});
}

export async function sendOfferFeedback(offerId: string, kind: "later" | "not_relevant") {
  const response = await apiFetch(`/api/v2/math-tutor/offers/${encodeURIComponent(offerId)}/feedback`, {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({kind}),
  });
  if (!response.ok) throw new DesktopApiError(await toFriendlyMessage(response, "暂时无法保存反馈，请重试。"));
}

export class DesktopApiError extends Error {}

/** Parse a backend error into a friendly message (detail or fallback). */
async function toFriendlyMessage(res: Response, fallback: string): Promise<string> {
  let detail = "";
  try {
    const body = (await res.json()) as { detail?: unknown };
    detail = typeof body.detail === "string" ? body.detail : "";
  } catch {
    detail = "";
  }
  return detail || fallback;
}

async function desktopFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(`${DESKTOP_PREFIX}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    throw new DesktopApiError(await toFriendlyMessage(res, "请求失败，请稍后再试。"));
  }
  return (await res.json()) as T;
}

// ---------------------------------------------------------------------------
// Settings — AI model configuration
// ---------------------------------------------------------------------------

export async function fetchSettings(): Promise<DesktopSettings> {
  return desktopFetch<DesktopSettings>("/settings");
}

export async function fetchPresets(): Promise<ProviderPreset[]> {
  return desktopFetch<ProviderPreset[]>("/settings/presets");
}

export async function saveSettings(input: {
  vision_mode?: "auto" | "enabled" | "disabled";
  preset_id: string;
  api_key?: string;
  base_url?: string;
  model?: string;
}): Promise<SettingsSaveResult> {
  return desktopFetch<SettingsSaveResult>("/settings", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function skipProviderOnboarding(): Promise<{
  ok: boolean;
  onboarding_completed: boolean;
}> {
  return desktopFetch("/settings/onboarding/skip", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function removeApiKey(): Promise<DesktopSettings> {
  return desktopFetch<DesktopSettings>("/settings/api-key", {
    method: "DELETE",
  });
}

export async function testConnection(): Promise<TestConnectionResult> {
  return desktopFetch<TestConnectionResult>("/settings/test-connection", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function fetchModels(): Promise<string[]> {
  return desktopFetch<string[]>("/settings/models");
}

export async function fetchEmbeddingSettings(): Promise<EmbeddingSettings> {
  return desktopFetch<EmbeddingSettings>("/settings/embedding");
}

export async function saveEmbeddingSettings(input: {
  enabled: boolean;
  provider: "local" | "cloud";
  local_model_id: string;
  cloud_base_url: string;
  cloud_model: string;
  cloud_api_key?: string;
}): Promise<EmbeddingSettings> {
  return desktopFetch<EmbeddingSettings>("/settings/embedding", {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function downloadLocalEmbeddingModel(model_id: string): Promise<EmbeddingSettings> {
  return desktopFetch<EmbeddingSettings>("/settings/embedding/local/download", {
    method: "POST",
    body: JSON.stringify({ model_id }),
  });
}

export async function deleteLocalEmbeddingModel(model_id: string): Promise<EmbeddingSettings> {
  return desktopFetch<EmbeddingSettings>(`/settings/embedding/local/${encodeURIComponent(model_id)}`, {
    method: "DELETE",
  });
}

export async function removeEmbeddingApiKey(): Promise<EmbeddingSettings> {
  return desktopFetch<EmbeddingSettings>("/settings/embedding/api-key", { method: "DELETE" });
}

export async function testEmbeddingConnection(): Promise<EmbeddingTestResult> {
  return desktopFetch<EmbeddingTestResult>("/settings/embedding/test", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function fetchTutorSettings(): Promise<TutorSettings> { return desktopFetch<TutorSettings>("/settings/tutor"); }
export async function saveTutorSettings(input: { personality: string; custom_instruction: string }): Promise<TutorSettings> { return desktopFetch<TutorSettings>("/settings/tutor", { method: "PUT", body: JSON.stringify(input) }); }
export async function fetchCostSettings(): Promise<CostSettings> { return desktopFetch<CostSettings>("/settings/cost"); }
export async function saveCostSettings(input: CostSettingsInput): Promise<CostSettings> { return desktopFetch<CostSettings>("/settings/cost", { method: "PUT", body: JSON.stringify(input) }); }

// ---------------------------------------------------------------------------
// Readiness
// ---------------------------------------------------------------------------

export async function fetchReadiness(): Promise<Readiness> {
  return desktopFetch<Readiness>("/readiness");
}

// ---------------------------------------------------------------------------
// Bootstrap — startup sequence (wire contract; MAIN implements the backend).
// ---------------------------------------------------------------------------

export async function fetchBootstrap(): Promise<BootstrapPayload> {
  return desktopFetch<BootstrapPayload>("/bootstrap");
}

// ---------------------------------------------------------------------------
// Model connection test (wire contract; MAIN implements the backend).
// ---------------------------------------------------------------------------

/**
 * Probe the configured provider. ``message`` is a friendly Chinese hint by
 * contract — the UI additionally maps ``error_kind`` onto distinct copy.
 * Never renders raw HTTP detail / Authorization headers / key material.
 */
export async function testModelConnection(): Promise<ModelTestResult> {
  return desktopFetch<ModelTestResult>("/model/test", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ---------------------------------------------------------------------------
// Backups (wire contract; MAIN implements the backend).
// ---------------------------------------------------------------------------

export async function fetchBackups(): Promise<BackupsList> {
  return desktopFetch<BackupsList>("/backups");
}

export async function createBackup(): Promise<BackupActionResult> {
  return desktopFetch<BackupActionResult>("/backup", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function verifyBackup(path: string): Promise<BackupVerifyResult> {
  return desktopFetch<BackupVerifyResult>("/backup/verify", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export async function restoreBackup(path: string, recoveryKey?: string): Promise<BackupRestoreResult> {
  return desktopFetch<BackupRestoreResult>("/backup/restore", {
    method: "POST",
    body: JSON.stringify(recoveryKey ? { path, recovery_key: recoveryKey } : { path }),
  });
}

export interface EncryptionStatus {
  mode: "plaintext" | "encrypted";
  pending: "encrypt" | "decrypt" | null;
  available: boolean;
  backups_encrypted: boolean;
  reason: string;
  restart_required?: boolean;
}

export async function fetchEncryption(): Promise<EncryptionStatus> { return desktopFetch<EncryptionStatus>("/privacy/encryption"); }
export async function saveEncryption(enabled: boolean): Promise<EncryptionStatus> {
  return desktopFetch<EncryptionStatus>("/privacy/encryption", { method: "PUT", body: JSON.stringify({ enabled }) });
}
export async function revealRecoveryKey(): Promise<{ recovery_key: string }> {
  return desktopFetch<{ recovery_key: string }>("/privacy/encryption/recovery-key", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Student summary — read-only projection (wire contract; MAIN implements).
// ---------------------------------------------------------------------------

export async function fetchStudentSummary(): Promise<StudentSummary> {
  return desktopFetch<StudentSummary>("/student-summary");
}

// ---------------------------------------------------------------------------
// Privacy / data lifecycle (wire contract; MAIN implements the backend).
// Destructive by design — the UI confirms twice before calling any of these.
// ---------------------------------------------------------------------------

export async function purgeDocuments(): Promise<PurgeDocumentsResult> {
  return desktopFetch<PurgeDocumentsResult>("/privacy/purge-documents", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function purgeMemory(): Promise<PurgeMemoryResult> {
  return desktopFetch<PurgeMemoryResult>("/privacy/purge-memory", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function deleteEducationalHistory(): Promise<EducationalHistoryResult> {
  return desktopFetch<EducationalHistoryResult>("/privacy/educational-history", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function rebuildIndexes(): Promise<RebuildIndexesResult> {
  return desktopFetch<RebuildIndexesResult>("/privacy/rebuild-indexes", {
    method: "POST",
    body: JSON.stringify({}),
  });
}

export async function fetchStudentExport(): Promise<StudentExport> {
  return desktopFetch<StudentExport>("/privacy/export");
}

// ---------------------------------------------------------------------------
// Documents — explicit user pick / import; public projections only.
// ---------------------------------------------------------------------------

export async function fetchDocuments(conversationId?: string): Promise<DesktopDocument[]> {
  return desktopFetch<DesktopDocument[]>(`/documents${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`);
}

export async function fetchDocumentDestinations(): Promise<Array<{conversation_id: string; title: string}>> {
  const response = await apiFetch("/api/v2/math-tutor/sessions");
  if (!response.ok) throw new DesktopApiError("对话列表暂时不可用");
  return response.json();
}

export function setDocumentGlobal(documentId: string, isGlobal: boolean) {
  return desktopFetch<DesktopDocument>(`/documents/${encodeURIComponent(documentId)}/scope`, { method: "PATCH", body: JSON.stringify({ is_global: isGlobal }) });
}

export function fetchConversationResources(conversationId: string) {
  return desktopFetch<{ documents: DesktopDocument[]; images: Array<{ id: string; name: string; url: string }>; message_count: number }>(`/conversations/${encodeURIComponent(conversationId)}/resources`);
}

/** Multipart import (browser `<input type=file>` fallback pick path). */
export async function importDocumentFile(file: File, conversationId?: string): Promise<DesktopDocument> {
  const body = new FormData();
  body.append("file", file);
  const res = await apiFetch(`${DESKTOP_PREFIX}/documents/import${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`, {
    method: "POST",
    body,
  });
  if (!res.ok) {
    throw new DesktopApiError(await toFriendlyMessage(res, "导入失败，请稍后再试。"));
  }
  return (await res.json()) as DesktopDocument;
}

/**
 * Ask the Python bridge to run the native picker (Electron shell). Only
 * called when the shell is reachable; otherwise the UI falls back to the
 * browser file input. Cancelled → null.
 */
export async function nativePickAndImport(conversationId?: string): Promise<DesktopDocument | null> {
  const res = await apiFetch(`${DESKTOP_PREFIX}/documents/pick${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!res.ok) {
    throw new DesktopApiError(await toFriendlyMessage(res, "无法打开文件选择器。"));
  }
  const body = (await res.json()) as { status?: string; document?: DesktopDocument };
  if (body.status === "cancelled") return null;
  return body.document ?? null;
}

export async function attachDocumentToConversation(conversationId: string, documentId: string): Promise<void> { await desktopFetch(`/conversations/${encodeURIComponent(conversationId)}/documents/${encodeURIComponent(documentId)}`, { method: "POST", body: JSON.stringify({}) }); }
export async function detachDocumentFromConversation(conversationId: string, documentId: string): Promise<void> { await desktopFetch(`/conversations/${encodeURIComponent(conversationId)}/documents/${encodeURIComponent(documentId)}`, { method: "DELETE" }); }
export async function renameDocument(documentId: string, filename: string): Promise<DesktopDocument> { return desktopFetch(`/documents/${encodeURIComponent(documentId)}`, { method: "PATCH", body: JSON.stringify({ filename }) }); }

export async function toggleDocumentRetrieval(
  documentId: string,
  enabled: boolean,
): Promise<DesktopDocument> {
  return desktopFetch<DesktopDocument>(`/documents/${documentId}/retrieval`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export async function deleteDocument(documentId: string): Promise<void> {
  await desktopFetch<{ deleted: boolean }>(`/documents/${documentId}`, {
    method: "DELETE",
  });
}

export async function reparseDocument(documentId: string): Promise<DesktopDocument> {
  return desktopFetch<DesktopDocument>(`/documents/${documentId}`, {
    method: "PUT",
    body: JSON.stringify({}),
  });
}

// ---------------------------------------------------------------------------
// Memory — personal memory KG
// ---------------------------------------------------------------------------

export async function fetchMemories(): Promise<DesktopMemory[]> {
  return desktopFetch<DesktopMemory[]>("/memory");
}

export async function createMemory(input: {
  memory_type: string;
  subject: string;
  predicate: string;
  object_json: Record<string, unknown>;
}): Promise<DesktopMemory> {
  return desktopFetch<DesktopMemory>("/memory", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function updateMemory(
  memoryId: string,
  input: { predicate?: string; object_json?: Record<string, unknown> },
): Promise<DesktopMemory> {
  return desktopFetch<DesktopMemory>(`/memory/${memoryId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteMemory(memoryId: string): Promise<void> {
  await desktopFetch<{ deleted: boolean }>(`/memory/${memoryId}`, {
    method: "DELETE",
  });
}

export async function toggleMemoryRetrieval(
  memoryId: string,
  enabled: boolean,
): Promise<DesktopMemory> {
  return desktopFetch<DesktopMemory>(`/memory/${memoryId}/retrieval`, {
    method: "PATCH",
    body: JSON.stringify({ enabled }),
  });
}

export async function confirmMemory(memoryId: string): Promise<DesktopMemory> {
  return desktopFetch<DesktopMemory>(`/memory/${memoryId}/confirm`, {
    method: "POST",
    body: JSON.stringify({}),
  });
}

// ---------------------------------------------------------------------------
// Offers — public offer list (contract: no solution/answer/mastery).
// ---------------------------------------------------------------------------

/**
 * Public practice-offer list (SUBAGENT B's endpoint, not the desktop
 * prefix). Tolerant: until the offers surface is wired the UI shows an
 * empty state instead of failing.
 */
export async function fetchOffers(): Promise<PracticeOffer[]> {
  try {
    const res = await apiFetch("/api/v2/math-tutor/offers");
    if (!res.ok) return [];
    const body = (await res.json()) as PracticeOffer[] | { offers?: PracticeOffer[] };
    if (Array.isArray(body)) return body;
    return Array.isArray(body?.offers) ? body.offers : [];
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Pure display formatters (unit-tested).
// ---------------------------------------------------------------------------

/** Mask a key for display: bullets + last 4. Never the full value. */
export function maskKeyTail(key: string): string {
  const value = String(key ?? "");
  if (!value) return "";
  const tail = value.length >= 4 ? value.slice(-4) : value;
  return `••••••••${tail}`;
}

export function formatBytes(size: number): string {
  if (!Number.isFinite(size) || size < 0) return "0 B";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`;
}

// ---------------------------------------------------------------------------
// Model connection error copy — five distinct kinds, friendly copy + advice.
// Never show raw HTTP tracebacks / Authorization headers / key material.
// ---------------------------------------------------------------------------

export interface ModelErrorCopy {
  title: string;
  advice: string;
}

export const MODEL_ERROR_COPY: Record<ModelErrorKind, ModelErrorCopy> = {
  response_incomplete: { title: "模型回答不完整", advice: "服务已响应，但正文为空或被截断，请重试。" },
  request_rejected: { title: "请求参数不兼容", advice: "请检查模型名称与 API 接口兼容性。" },
  quota_exceeded: { title: "余额或配额不足", advice: "请到服务商控制台检查账户余额和配额。" },
  rate_limited: { title: "请求受到限流", advice: "请稍后重试。" },
  provider_error: { title: "模型服务调用失败", advice: "请稍后重试，这不代表服务商不受支持。" },
  credential_invalid: {
    title: "API 密钥无效",
    advice: "密钥可能已失效或粘贴不完整，请重新粘贴完整密钥后再试。",
  },
  network_unavailable: {
    title: "无法连接网络",
    advice: "请检查电脑的网络或代理设置，稍后再试。",
  },
  provider_unsupported: {
    title: "暂不支持此服务商",
    advice: "请更换其他模型服务商，或在高级选项中使用自定义服务地址。",
  },
  model_unavailable: {
    title: "所选模型不可用",
    advice: "该服务商当前不提供所选模型，请更换模型名称或服务商。",
  },
  gateway_disabled: {
    title: "AI 服务未启用",
    advice: "AI 生成功能当前不可用；模板辅导与核心练习不受影响。",
  },
};

/** Map an error_kind onto friendly title + advice (unknown kinds fall back). */
export function modelErrorCopy(kind: ModelErrorKind | null): ModelErrorCopy {
  if (kind && MODEL_ERROR_COPY[kind]) return MODEL_ERROR_COPY[kind];
  return { title: "连接失败", advice: "请稍后重试，或检查网络与密钥设置。" };
}

/** Newest-first backup ordering (invalid dates sort last). */
export function sortBackups(backups: BackupRecord[]): BackupRecord[] {
  return [...backups].sort((a, b) => {
    const at = Date.parse(a.created_at);
    const bt = Date.parse(b.created_at);
    const av = Number.isFinite(at) ? at : 0;
    const bv = Number.isFinite(bt) ? bt : 0;
    return bv - av;
  });
}

/** Friendly mastery band for a 0..1 mastery value (read-only display). */
export function masteryLevelLabel(mastery: number | null): string {
  if (mastery === null || !Number.isFinite(mastery)) return "暂无数据";
  if (mastery >= 0.8) return "熟练";
  if (mastery >= 0.55) return "进阶中";
  return "起步中";
}
