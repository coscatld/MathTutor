"use client";

import { Check, CornerUpLeft, ListChecks } from "lucide-react";
import type { DiagnosisSummary, EvidenceSummary, ProblemContext } from "../types";
import { evidenceStatusLabel } from "../lib/teaching-contract";

const LIFECYCLE_LABELS: Record<string, string> = { ACTIVE: "辅导中", COMPLETED: "本题已完成", RESOLVED: "本题已完成", PAUSED: "已搁置", CLOSED: "已结束", ENDED: "已结束", SKIPPED: "已跳过", NEEDS_CLARIFICATION: "待补充题目" };

/** Source and goal come from the persisted context, not text-message parsing. */
export function CurrentProblem({ context }: { context?: ProblemContext | null }) {
  if (!context) return null;
  const lifecycle = context.lifecycle.toUpperCase();
  const completeStep = ["completed", "verified", "resolved"].includes(context.current_subgoal?.status.toLowerCase() || "");
  return <section aria-label="当前题目与目标" className="shrink-0 border-b border-[#e3e1da] bg-[#f4f3ee] px-5 py-3 dark:border-slate-800 dark:bg-[#171d21]">
    <div className="mx-auto max-w-3xl">
      <div className="flex items-center gap-2 text-xs text-slate-500"><ListChecks className="h-3.5 w-3.5" aria-hidden="true" /><span>当前题目</span><span className="ml-auto rounded-full border border-[#deddd7] px-2 py-0.5 dark:border-slate-700">{LIFECYCLE_LABELS[lifecycle] || "当前任务"}</span></div>
      <p className="mt-1.5 max-h-20 overflow-y-auto whitespace-pre-wrap break-words text-sm leading-6 text-slate-800 dark:text-slate-200">{context.display_text || "请补充当前题目的完整要求。"}</p>
      {context.current_subgoal?.prompt_target ? <div className="mt-1 flex items-start gap-1.5 text-xs leading-5 text-[#1d5fd1] dark:text-blue-300">{completeStep ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : <CornerUpLeft className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />}<span>{completeStep ? "已验证步骤：" : "当前小目标："}{context.current_subgoal.prompt_target}</span></div> : null}
    </div>
  </section>;
}

export function EvidenceSummaryCard({ evidence }: { evidence?: EvidenceSummary | null }) {
  if (!evidence) return null;
  const entries = [["独立作答", evidence.independent], ["受助作答", evidence.assisted], ["看答案后作答", evidence.post_solution], ["诊断作答", evidence.diagnostic], ["暂无法判断", evidence.ungradable]] as const;
  return <section aria-label="本题学习证据" className="rounded-2xl border border-[#deddd7] bg-white p-4 dark:border-slate-700 dark:bg-slate-900">
    <h2 className="text-sm font-semibold">本题学习证据</h2>
    <dl className="mt-3 space-y-2">{entries.map(([label, count]) => <div key={label} className="flex items-center justify-between gap-3 text-xs"><dt className="text-slate-500">{label}</dt><dd className="tabular-nums text-slate-700 dark:text-slate-300">{count} 次</dd></div>)}</dl>
    <p className="mt-3 border-t border-[#eeece6] pt-3 text-xs leading-5 text-slate-500 dark:border-slate-800">{evidenceStatusLabel(evidence.status)}。观看答案不计作独立掌握。</p>
  </section>;
}

export function DiagnosisNotice({ diagnosis }: { diagnosis?: DiagnosisSummary | null }) {
  if (!diagnosis || !["active", "in_progress", "running"].includes(diagnosis.status.toLowerCase())) return null;
  return <section aria-label="可跳过的基础检查" className="rounded-2xl border border-[#d7e2f3] bg-[#f2f6fc] p-4 dark:border-blue-900 dark:bg-blue-950/30"><h2 className="text-sm font-semibold">了解当前基础</h2><p className="mt-2 text-xs leading-5 text-slate-500">已作答 {diagnosis.answered ?? 0} / {diagnosis.question_count} 道，题量会根据实际回答调整。跳过不会记为错误。{diagnosis.can_skip ? "你可以随时跳过，回到当前辅导。" : ""}</p></section>;
}
