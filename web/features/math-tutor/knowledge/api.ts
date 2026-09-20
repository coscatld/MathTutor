import { apiFetch } from "@/lib/api";

export const root = "/api/v2/math-tutor/desktop/knowledge";
export async function knowledgeApi<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await apiFetch(root + path, {method: method ?? (body === undefined ? "GET" : "POST"),
    headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === "string" ? data.detail : "操作未完成，请刷新后重试。"); }
  return response.json() as Promise<T>;
}
export type Library = {space_id: string; name: string; kind: "personal" | "course" | "session"; conversation_id: string; enabled: number};
export type Note = {document_id: string; title: string; version: number; tags: string[]; links: string[]; retrieval_enabled: boolean; editable: boolean};
export type Source = {document_id: string; title: string; version: number; body?: string; text?: string; body_hash: string; tags?: string[]; links?: string[]; line_start?: number; line_end?: number; backlinks?: Array<{document_id: string; title: string}>; provenance?: {format?: string; relative_path?: string}};
export type Mount = {space_ids: string[]; document_ids: string[]; only_selected: boolean; mode?: "knowledge" | "tutor"; save_space_id?: string; tool_mode?: "native" | "structured"; hints_only?: boolean; available_documents?: Array<{document_id: string; title: string; enabled: boolean}>};
export type Draft = {draft_id: string; title: string; markdown: string; conversation_id: string};
