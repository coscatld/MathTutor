import { apiFetch } from "@/lib/api";

export const communityRoot = "/api/v2/math-tutor/desktop/community";
export type Permission = "question_bank" | "read_learning_records";
export type CommunitySource = {id: string; name: string; kind: "builtin" | "imported" | "remote"; source_url: string | null; sha256: string | null; last_refreshed: string | null; error: string | null; stale: boolean; resource_count: number};
export type Resource = {id: string; version: string; type: "question-pack" | "plugin"; name: string; author: string; license: string; description: string; tags: string[]; grades: number[]; readme: string; changelog: string; package_sha256: string; package_size_bytes: number | null; project_example: boolean; source_id: string; source_name: string; favorite: boolean; imported_versions: string[]; latest_imported_version: string | null; installed_version?: string | null; update_status: "not_imported" | "current" | "update_available" | "different_content"; importable: boolean; permissions: string[]; plugin_id?: string | null; source_url?: string | null; project_url?: string | null; issues_url?: string | null; discussions_url?: string | null};
export type ResourceDetail = Resource & {preview: {documents: Array<{path: string; title: string; body: string}>; partial: boolean; available?: boolean}};
export type Catalog = {resources: Resource[]; sources: CommunitySource[]; notice: string};
export type PluginPackage = {schema_version: "mathtutor.community-plugin.v1"; kind: "teaching-plugin"; id: string; version: string; name: string; description: string; author: string; license: string; tags: string[]; grades: number[]; readme: string; changelog: string; workflow: "exam-builder" | "mistake-review" | "learning-report"; defaults: Record<string, unknown>; teaching_guidance: string; required_permissions: Permission[]};
export type PluginRecord = {plugin: PluginPackage; config: Record<string, unknown>; enabled: boolean; consented_permissions: Permission[]; package_hash: string; installed_at: string; updated_at: string};
export type ExamData = {title: string; questions: Array<{id: string; text: string; point_code: string; point_title: string; grade: number; difficulty: string | number; reference_answer?: string; explanation?: string}>; requested_count: number; actual_count: number; seed: number; answers_included: boolean};
export type MistakeData = {items: Array<{event_id: string; occurred_at: string; correctness: string; evidence_kind: string; completion_scope: string; skill_ids: string[]; problem_text: string; student_response: string; next_step: string}>; assessed_count: number; review_count: number; self_report_count: number; empty_reason?: string};
export type TrendData = {summary: {assessed_attempts: number; independent_attempts: number; independent_correct: number; independent_accuracy: number | null; assisted_attempts: number; post_solution_attempts: number; self_report_count: number}; trend: Array<{index: number; attempts: number; correct: number; accuracy: number; first_at: string; last_at: string}>; skills: Array<{skill_id: string; label: string; independent_correct: number; independent_incorrect: number; assisted_correct: number; assisted_incorrect: number; post_solution_correct: number; post_solution_incorrect: number}>; window: {max_events: number; included_events: number; truncated: boolean}};
export type RunResult = {schema_version: "mathtutor.community-result.v1"; plugin_id: string; plugin_version: string; workflow: PluginPackage["workflow"]; status: "ok" | "empty"; read_only: true; authority: "reference_only"; config: Record<string, unknown>; teaching_guidance: string; data: Record<string, unknown>; limitations: string[]};

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
export function downloadCommunityJson(value: unknown, filename: string) {
  const link = document.createElement("a"), url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2) + "\n"], {type: "application/json"}));
  link.href = url; link.download = filename; link.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function publicHttps(value?: string | null): string | null {
  try { if (!value) return null; const url = new URL(value); return url.protocol === "https:" && !url.username && !url.password ? url.href : null; } catch { return null; }
}
export const permissionLabel = (value: string) => ({question_bank: "读取题库与知识点", read_learning_records: "读取我的作答与核验记录"})[value] || `未识别权限：${value}`;
export const permissionExplanation = (value: string) => ({question_bank: "用于挑选练习与生成试卷，不改动题库。", read_learning_records: "用于分析错题与学习趋势；不写入成绩、学习记忆或掌握度。"})[value] || "当前界面无法说明此权限，请先核对包说明。";
export function resourceAdded(resource: Resource, plugins: PluginRecord[] = []) {
  return resource.type === "plugin" ? plugins.some(item => item.plugin.id === (resource.plugin_id || resource.id)) : resource.imported_versions.length > 0;
}
export function gradeLabel(grades: number[]) {
  if (!grades.length) return "未限定年级";
  const stages = [...new Set(grades.map(grade => grade <= 6 ? "小学" : grade <= 9 ? "初中" : "高中"))];
  return stages.join(" / ");
}
