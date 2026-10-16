import { apiFetch } from "@/lib/api";

export const root = "/api/v2/math-tutor/desktop/knowledge";
export type KnowledgeSection = "files" | "skills";
export function knowledgeSection(value: string | null): KnowledgeSection { return value === "skills" ? "skills" : "files"; }
export async function knowledgeApi<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await apiFetch(root + path, {method: method ?? (body === undefined ? "GET" : "POST"),
    headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === "string" ? data.detail : "操作未完成，请刷新后重试。"); }
  return response.json() as Promise<T>;
}
export type Library = {space_id: string; name: string; kind: "personal" | "course" | "session"; conversation_id: string; enabled: number};
export type Note = {document_id: string; title: string; version: number; tags: string[]; links: string[]; retrieval_enabled: boolean; editable: boolean};
export type Source = {document_id: string; title: string; version: number; body?: string; text?: string; body_hash: string; tags?: string[]; links?: string[]; line_start?: number; line_end?: number; backlinks?: Array<{document_id: string; title: string}>; provenance?: {format?: string; relative_path?: string}};
export type ScopeDocument = {document_id: string; title: string; enabled: boolean; status?: string; retrieval_enabled?: boolean; origin?: "conversation" | "global" | "library"; space_ids?: string[]; selected?: boolean};
export type Mount = {space_ids: string[]; document_ids: string[]; only_selected: boolean; mode?: "knowledge" | "tutor"; save_space_id?: string; tool_mode?: "native" | "structured"; hints_only?: boolean; available_documents?: ScopeDocument[]; effective_document_ids?: string[]};
/** Keep read-only projections out of mutation payloads and compare explicit defaults. */
export function mountConfiguration(value: Mount): Mount {
  if (!value || !Array.isArray(value.space_ids) || !Array.isArray(value.document_ids) || typeof value.only_selected !== "boolean") throw new Error("资料范围响应不完整，请重新读取。");
  return {space_ids: [...value.space_ids], document_ids: [...value.document_ids], only_selected: value.only_selected,
    mode: value.mode || "tutor", save_space_id: value.save_space_id || "", tool_mode: value.tool_mode || "native", hints_only: value.hints_only || false};
}
export type Draft = {draft_id: string; title: string; markdown: string; conversation_id: string};
