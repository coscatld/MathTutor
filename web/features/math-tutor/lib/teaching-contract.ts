/** Public projections are shared by live frames and restart hydration. */
import type { ActiveOffer, ChoiceSet, DiagnosisSummary, EvidenceSummary, ProblemContext, TeachingPlan } from "../types";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}
function text(value: unknown): string { return typeof value === "string" ? value : ""; }
function strings(value: unknown): string[] { return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : []; }
function count(value: unknown): number { return typeof value === "number" && Number.isFinite(value) && value >= 0 ? Math.floor(value) : 0; }

export function projectTeachingPlan(value: unknown): TeachingPlan | null {
  const raw = record(value);
  if (!raw) return null;
  return { action: text(raw.action), strategy: text(raw.strategy), question_goal: text(raw.question_goal),
    target_subgoal_id: text(raw.target_subgoal_id), target_skill_ids: strings(raw.target_skill_ids),
    reason_codes: strings(raw.reason_codes), support_mode: text(raw.support_mode), exit_options: strings(raw.exit_options),
    ...(typeof raw.student_guidance === "string" ? { student_guidance: raw.student_guidance } : {}) };
}

export function projectProblemContext(value: unknown): ProblemContext | null {
  const raw = record(value);
  if (!raw || !text(raw.problem_id)) return null;
  const subgoal = record(raw.current_subgoal);
  const choices = projectChoices(raw.choices);
  return { problem_id: text(raw.problem_id), display_text: text(raw.display_text), skill_ids: strings(raw.skill_ids),
    lifecycle: text(raw.lifecycle), ...(typeof raw.understanding_check === "boolean" ? { understanding_check: raw.understanding_check } : {}), ...(typeof raw.graphable === "boolean" ? { graphable: raw.graphable } : {}), ...(choices ? {choices} : {}), current_subgoal: subgoal ? { id: text(subgoal.id), prompt_target: text(subgoal.prompt_target), status: text(subgoal.status) } : null };
}

export function projectChoices(value: unknown): ChoiceSet | null {
  const raw = record(value);
  if (!raw || raw.format !== "single_choice" || !text(raw.version) || !Array.isArray(raw.options) || raw.options.length !== 4) return null;
  const options = raw.options.map(record).map(row => ({ id: text(row?.id), text: text(row?.text) }));
  if (options.some(row => !/^[A-D]$/.test(row.id) || !row.text) || new Set(options.map(row => row.id)).size !== 4) return null;
  return {format: "single_choice", version: text(raw.version), options};
}

export function projectEvidenceSummary(value: unknown): EvidenceSummary | null {
  const raw = record(value);
  if (!raw) return null;
  return { independent: count(raw.independent), assisted: count(raw.assisted), post_solution: count(raw.post_solution),
    diagnostic: count(raw.diagnostic), ungradable: count(raw.ungradable), status: text(raw.status) };
}

export function projectActiveOffer(value: unknown): ActiveOffer | null {
  const raw = record(value);
  if (!raw || !text(raw.offer_id).trim()) return null;
  return { offer_id: text(raw.offer_id), title: text(raw.title), purpose: text(raw.purpose), status: text(raw.status) };
}

export function projectDiagnosis(value: unknown): DiagnosisSummary | null {
  const raw = record(value);
  if (!raw) return null;
  return { status: text(raw.status), can_skip: raw.can_skip === true, question_count: count(raw.question_count), answered: count(raw.answered), started_at: text(raw.started_at) };
}

/** Offer identity is mandatory even if an obsolete capability says enabled. */
export function isAcceptableOffer(offer?: ActiveOffer | null): offer is ActiveOffer {
  return Boolean(offer?.offer_id.trim() && offer.status.toUpperCase() === "ACTIVE");
}

const STRATEGY_LABELS: Record<string, string> = {
  guided_steps: "分步引导", micro_diagnosis: "相关知识点检查", concept_explanation: "理解概念",
  error_analysis: "分析错误", worked_example: "局部示范", local_demonstration: "示范一步",
  scaffold: "提供具体支架", full_solution: "完整讲解", method_comparison: "比较方法",
  targeted_correction: "检查当前步骤", socratic: "提问引导", independent_practice: "独立练习",
  focused_question: "围绕当前小目标提问", worked_solution: "完整讲解", verified_analogy: "关联示例",
  smaller_step: "把问题再拆小一步", worked_prefix: "示范一段已验证过程", definition_to_problem: "从概念回到本题",
  locate_verified_error: "定位已验证的错误", offer_alternative: "换一种支持方式",
  compare_methods: "比较可行方法", prerequisite_check: "检查相关基础", teacher_error_example: "分析教师故意设置的错误",
};
const REASON_LABELS: Record<string, string> = {
  insufficient_skill_evidence: "当前知识点的独立证据还不充分。",
  current_step_unanswered: "先确认当前这一步。", verified_error: "围绕刚才已经核实的问题调整。",
  repeated_stall: "已经卡住几轮，换一种支架。", stalled: "把当前问题拆得更小。",
  explicit_solution_request: "按你的选择展示验证过的完整解答。",
  independent_success: "已有独立作答证据，可以减少支架。",
  post_solution: "看过答案后，用新题检查能否独立运用。",
  prerequisite_gap: "先检查与本题有关的基础知识。",
  current_subgoal: "继续解决当前的小目标。",
  repeated_explicit_stuck: "你连续表示还不理解，这次把问题再拆小。",
  help_without_verified_progress: "还没有可验证的新步骤，改用局部示范。",
  repeated_teaching_operation: "这类提示已经展示过，提供其他支持选择。",
  multiple_independent_items: "已有多道不同题目的独立作答记录，这次减少支架。",
  repeated_independent_difficulty: "不同题目中都遇到困难，先检查相关基础。",
  language_confusion: "你表达了当前的困惑，这次调整讲解方式。",
  semantic_intent: "结合你的原话和当前目标理解这次求助。",
};
export function teachingStrategyLabel(strategy: string): string { return STRATEGY_LABELS[strategy] || "围绕当前目标辅导"; }
export function teachingReasonLabels(reasons: string[]): string[] { return [...new Set(reasons.flatMap(code => REASON_LABELS[code.toLowerCase()] ? [REASON_LABELS[code.toLowerCase()]] : []))]; }

/** Describes disclosed material, never a score or a required sequence. */
export function supportExposureLabel(level: number): string {
  const labels = ["尚未展示解题支架", "相关概念", "方法方向", "一个具体步骤", "局部过程示范", "完整验证解答"];
  return labels[Number.isFinite(level) ? Math.max(0, Math.min(5, Math.round(level))) : 0];
}

const EVIDENCE_STATUS_LABELS: Record<string, string> = {
  independent_evidence: "已有独立作答证据", has_independent_evidence: "已有独立作答证据",
  needs_confirmation: "仍需独立检测", insufficient_evidence: "证据仍不足", needs_review: "建议复习",
  "已有独立作答记录，仍需跨题验证": "已有独立作答记录，仍需跨题验证",
  "已看过解答，需换题独立检测": "已看过解答，需换题独立检测",
  "尚无整题独立作答证据": "尚无整题独立作答证据",
  "尚无独立检测证据": "尚无独立检测证据",
};
export function evidenceStatusLabel(status: string): string { return EVIDENCE_STATUS_LABELS[status] || "这些是作答记录，不代表已掌握"; }

export function offerPurposeLabel(purpose: string): string {
  const labels: Record<string, string> = { A1: "独立完成后的迁移", A2: "获得帮助后的巩固", B: "看答案后的独立检测",
    C: "先补基础", D: "主动练习", E: "复习检查", transfer: "同技能迁移", consolidation: "独立巩固",
    post_solution: "看答案后的独立检测", prerequisite: "先补基础", remediation: "先补基础", voluntary: "主动练习", review: "复习检查" };
  return labels[purpose] || "针对当前知识点的练习";
}
