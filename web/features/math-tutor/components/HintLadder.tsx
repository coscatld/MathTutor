"use client";

import { normalizeAssistanceLevel } from "../lib/protocol";
import { supportExposureLabel, teachingReasonLabels, teachingStrategyLabel } from "../lib/teaching-contract";
import type { TeachingPlan } from "../types";

/** Exposure is not ability, completion, or a mandatory ladder to the answer. */
export default function HintLadder({ level, plan }: { level: number; plan?: TeachingPlan | null }) {
  const current = normalizeAssistanceLevel(level);
  const reasons = teachingReasonLabels(plan?.reason_codes || []);
  return <section className="rounded-2xl border border-[#deddd7] bg-white p-4 dark:border-slate-700 dark:bg-slate-900" aria-label="当前教学支持">
    <h2 className="text-sm font-semibold text-[var(--foreground)]">当前支持</h2>
    {plan ? <div className="mt-3 space-y-2">
      <p className="text-xs font-medium text-amber-700 dark:text-amber-400">{teachingStrategyLabel(plan.strategy)}</p>
      {plan.question_goal ? <p className="text-sm leading-6 text-[var(--foreground)]">{plan.question_goal}</p> : null}
      {reasons.map(reason => <p key={reason} className="text-xs leading-5 text-[var(--muted-foreground)]">{reason}</p>)}
    </div> : <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">提交题目后，这里会说明本轮要解决的小问题。</p>}
    <div className="mt-3 border-t border-[#eeece6] pt-3 dark:border-slate-800">
      <p className="text-xs text-[var(--muted-foreground)]">已展示内容</p>
      <p className="mt-1 text-sm text-[var(--foreground)]">{supportExposureLabel(current)}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">这是本题的帮助记录，不是能力进度。你可以直接选择所需支持或查看完整答案。</p>
    </div>
  </section>;
}
