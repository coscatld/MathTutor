import {apiFetch} from "@/lib/api";
import {responseError} from "@/lib/api-error";

export type LoopDomain = "fraction_addition" | "signed_subtraction";
export type LoopPhase = "diagnose" | "practice" | "waiting" | "review" | "transfer" | "complete" | "exhausted";
export interface LoopQuestion {
  probe_id: string; domain: LoopDomain; family: string; purpose: string;
  statement: string; prompt_zh: string; prompt_en: string;
}
export interface LoopFeedback {
  kind: "correct" | "incorrect" | "unknown" | "help" | "recorded";
  probe_id: string; statement?: string; answer?: string; explanation_zh?: string; explanation_en?: string; independent?: boolean;
}
export interface LoopEpisode {
  episode_id: string; domain: LoopDomain; phase: LoopPhase; question: LoopQuestion | null;
  due_at: string | null; can_start: boolean; review_round: number;
  diagnostic: {status: string; answered: number; label_zh: string; label_en: string};
  evidence: {independent_practice: number; delayed_review: number; structural_transfer: number};
  feedback: LoopFeedback | null;
}
export interface LoopEntry {
  domain: LoopDomain; label_zh: string; label_en: string; episode: LoopEpisode | null;
}
export interface LearningLoop {
  schema_version: "learning_loop_v1"; server_time: string; domains: LoopEntry[];
}
export type LoopAction = "start" | "answer" | "help";
export type LoopRequest = {domain: LoopDomain; episode_id?: string; probe_id?: string; request_id?: string; answer?: string};

export async function learningLoopRequest(action?: LoopAction, body?: LoopRequest, signal?: AbortSignal): Promise<LearningLoop> {
  const response = await apiFetch(`/api/v2/math-tutor/desktop/learning-loop${action ? `/${action}` : ""}`, action ? {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal,
  } : {signal, cache: "no-store"});
  if (!response.ok) throw await responseError(response, "概念复查暂时无法同步，请重试。");
  const data = await response.json();
  if (data?.schema_version !== "learning_loop_v1" || !Array.isArray(data.domains)) {
    throw new Error("概念复查暂时无法同步，请重试。");
  }
  return data as LearningLoop;
}

export const LOOP_PHASE_LABELS: Record<LoopPhase, string> = {
  diagnose: "辨别作答模式", practice: "独立练习", waiting: "等待间隔复习",
  review: "间隔复习", transfer: "换一种结构", complete: "本轮复查已完成", exhausted: "本轮题目已用完",
};
