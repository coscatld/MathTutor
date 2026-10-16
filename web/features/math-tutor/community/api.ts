import { apiFetch } from "@/lib/api";

export const communityRoot = "/api/v2/math-tutor/desktop/community";
export type Permission = "question_bank" | "read_learning_records" | "execute_local_code";
type PluginMetadata = {id: string; version: string; name: string; description: string; author: string; license: string; tags: string[]; grades: number[]; readme: string; changelog: string; defaults: Record<string, unknown>; teaching_guidance: string; required_permissions: Permission[]};
export type TeachingPluginPackage = PluginMetadata & {schema_version: "mathtutor.community-plugin.v1"; kind: "teaching-plugin"; workflow: "exam-builder" | "mistake-review" | "learning-report"};
export type CodePluginPackage = PluginMetadata & {schema_version: "mathtutor.code-plugin.v1"; kind: "code-plugin"; workflow: "code"; runtime: "python" | "typescript"; entrypoint: string; file_hashes: Record<string, string>};
export type PluginPackage = TeachingPluginPackage | CodePluginPackage;
export type PluginRecord = {kind: PluginPackage["kind"]; command: string; runtime_available: boolean; plugin: PluginPackage; config: Record<string, unknown>; enabled: boolean; consented_permissions: Permission[]; package_hash: string; installed_at: string; updated_at: string};
export type PluginCommand = {command: string; plugin_id: string; name: string; description: string; kind: PluginPackage["kind"]; enabled: boolean; runtime_available: boolean};
export const PLUGINS_CHANGED = "mathtutor-plugins-changed";
export function notifyPluginsChanged() {if (typeof window !== "undefined") window.dispatchEvent(new Event(PLUGINS_CHANGED));}
export type ExamData = {title: string; questions: Array<{id: string; text: string; point_code: string; point_title: string; grade: number; difficulty: string | number; reference_answer?: string; explanation?: string}>; requested_count: number; actual_count: number; seed: number; answers_included: boolean};
export type MistakeData = {items: Array<{event_id: string; occurred_at: string; correctness: string; evidence_kind: string; completion_scope: string; skill_ids: string[]; problem_text: string; student_response: string; next_step: string}>; assessed_count: number; review_count: number; self_report_count: number; empty_reason?: string};
export type TrendData = {summary: {assessed_attempts: number; independent_attempts: number; independent_correct: number; independent_accuracy: number | null; assisted_attempts: number; post_solution_attempts: number; self_report_count: number}; trend: Array<{index: number; attempts: number; correct: number; accuracy: number; first_at: string; last_at: string}>; skills: Array<{skill_id: string; label: string; independent_correct: number; independent_incorrect: number; assisted_correct: number; assisted_incorrect: number; post_solution_correct: number; post_solution_incorrect: number}>; window: {max_events: number; included_events: number; truncated: boolean}};
export type RunResult = {schema_version: "mathtutor.community-result.v1"; plugin_id: string; plugin_version: string; workflow: PluginPackage["workflow"]; status: "ok" | "empty"; read_only: boolean; sandboxed?: false; execution_mode?: "trusted_local_code"; authority: "reference_only"; config: Record<string, unknown>; teaching_guidance: string; data: Record<string, unknown>; limitations: string[]};

export async function communityApi<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await apiFetch(communityRoot + path, {method: method || (body === undefined ? "GET" : "POST"), headers: {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(typeof data.detail === "string" ? data.detail : "操作未完成，请稍后重试。"); }
  return response.json() as Promise<T>;
}
export async function communityDownload(path: string, filename: string, body?: unknown) {
  const response = await apiFetch(communityRoot + path, {method: body === undefined ? "GET" : "POST", headers: body === undefined ? undefined : {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) { const value = await response.json().catch(() => ({})); throw new Error(typeof value.detail === "string" ? value.detail : "文件没有导出，请重试。"); }
  const link = document.createElement("a"), url = URL.createObjectURL(await response.blob());
  link.href = url; link.download = filename; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export const permissionLabel = (value: string) => ({question_bank: "读取题库与知识点", read_learning_records: "读取我的作答与核验记录", execute_local_code: "在本机运行插件代码"})[value] || `未识别权限：${value}`;
