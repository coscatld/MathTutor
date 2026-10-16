/**
 * Question bank helpers (pure, unit-tested). See docs/QUESTION_BANK_SPEC.md.
 *
 * Starting a problem or a demo opens a NEW tutor conversation. The bank page
 * navigates to `/math-tutor?session=<new id>&start=<text>` (submit_problem)
 * or `&ask=<request>` (send_message); the tutor page reads the query once
 * through `parseTutorLaunch`, sends it, and strips it from the URL.
 */

import type { MathTutorCommand } from "../../types";
import type { BankDemo, BankProblem, BankReferenceProblem, BankTerm, LearnerStage } from "../../lib/question-bank-types";

export const STAGES: { stage: LearnerStage; label: string; grades: number[] }[] = [
  { stage: "primary", label: "小学", grades: [1, 2, 3, 4, 5, 6] },
  { stage: "middle", label: "初中", grades: [7, 8, 9] },
  { stage: "high", label: "高中", grades: [10, 11, 12] },
];

export function stageLabel(stage: LearnerStage | null | undefined): string {
  return STAGES.find(item => item.stage === stage)?.label ?? "未设置";
}

const GRADE_LABELS: Record<number, string> = {
  1: "一年级", 2: "二年级", 3: "三年级", 4: "四年级", 5: "五年级", 6: "六年级",
  7: "七年级", 8: "八年级", 9: "九年级", 10: "高一", 11: "高二", 12: "高三",
};
export function gradeLabel(grade: number): string { return GRADE_LABELS[grade] ?? `${grade} 年级`; }

/** ★ repeated by difficulty (clamped 1..5). */
export function difficultyStars(difficulty: number): string {
  const n = Math.min(5, Math.max(1, Math.round(Number(difficulty) || 1)));
  return "★".repeat(n);
}

/** Terms sorted by `order`, keeping only points whose title matches `query`. */
export function filterBankTerms(terms: BankTerm[], query: string, grade: number | null = null): BankTerm[] {
  const sorted = terms.filter(term => grade === null || (term.recommended_grades ?? [term.grade]).includes(grade)).sort((a, b) => a.order - b.order);
  const q = query.trim().toLowerCase();
  if (!q) return sorted;
  return sorted
    .map(term => ({ ...term, units: term.units
      .map(unit => ({ ...unit, points: unit.points.filter(point => point.title.toLowerCase().includes(q)) }))
      .filter(unit => unit.points.length > 0) }))
    .filter(term => term.units.length > 0);
}

export const LAUNCH_TEXT_MAX = 300;

export interface TutorLaunch {
  command: Extract<MathTutorCommand, "submit_problem" | "send_message">;
  payload: { text: string };
}

export function buildPracticeLaunch(problem: Pick<BankProblem, "text">): TutorLaunch {
  return { command: "submit_problem", payload: { text: problem.text } };
}

export function buildDemoLaunch(demo: Pick<BankDemo, "request">): TutorLaunch {
  return { command: "send_message", payload: { text: demo.request } };
}

/** Send only the complete question to ordinary tutoring; never its reference answer. */
export function buildReferenceLaunch(problem: Pick<BankReferenceProblem, "text">): TutorLaunch | null {
  if (!problem.text.trim() || problem.text.length > LAUNCH_TEXT_MAX) return null;
  return { command: "send_message", payload: { text: problem.text } };
}

/** URL that opens a fresh conversation and asks the tutor page to send `launch` once. */
export function tutorLaunchHref(launch: TutorLaunch, sessionId: string): string {
  const key = launch.command === "submit_problem" ? "start" : "ask";
  const params = new URLSearchParams({ session: sessionId, [key]: launch.payload.text });
  return `/math-tutor?${params.toString()}`;
}

function cleanLaunchText(value: string | null): string | null {
  if (value == null) return null;
  const text = value.trim();
  if (!text || text.length > LAUNCH_TEXT_MAX) return null;
  return text;
}

/** Read `?start=` / `?ask=` (text only, at most 300 chars). `start` wins if both are present. */
export function parseTutorLaunch(params: { get(name: string): string | null } | null | undefined): TutorLaunch | null {
  if (!params) return null;
  const start = cleanLaunchText(params.get("start"));
  if (start) return { command: "submit_problem", payload: { text: start } };
  const ask = cleanLaunchText(params.get("ask"));
  if (ask) return { command: "send_message", payload: { text: ask } };
  return null;
}
