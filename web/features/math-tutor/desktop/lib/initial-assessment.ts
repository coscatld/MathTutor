import { apiFetch } from "@/lib/api";
import type { ChoiceSet } from "../../types";

export interface InitialAssessment {
  status: "not_started" | "pending" | "in_progress" | "completed" | "skipped";
  run_id?: string;
  total: number;
  answered: number;
  question?: {index: number; skill_label: string; statement: string; choices: ChoiceSet} | null;
  result?: {notice: string; skills: {skill_id: string; label: string; observed: number; correct: number; unknown: number; starting_difficulty: number; observation: string}[]} | null;
}

export async function assessmentRequest(action = "", body?: object): Promise<InitialAssessment> {
  const response = await apiFetch(`/api/v2/math-tutor/desktop/initial-assessment${action ? `/${action}` : ""}`, action ? {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body ?? {}),
  } : undefined);
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(typeof data.detail === "string" ? data.detail : "暂时无法保存，请检查连接后重试。");
  }
  return response.json();
}
