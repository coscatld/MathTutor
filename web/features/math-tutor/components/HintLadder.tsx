"use client";

import { Compass, Eye } from "lucide-react";
import { normalizeAssistanceLevel } from "../lib/protocol";
import { supportExposureLabel, teachingReasonLabels, teachingStrategyLabel } from "../lib/teaching-contract";
import type { TeachingPlan } from "../types";

/** Exposure is not ability, completion, or a mandatory ladder to the answer. */
export default function HintLadder({ level, plan }: { level: number; plan?: TeachingPlan | null }) {
  const current = normalizeAssistanceLevel(level);
  const reasons = teachingReasonLabels(plan?.reason_codes || []);
  return <section className="mt-support-goal" aria-label="当前教学支持">
    <div className="flex items-center gap-2 text-[var(--primary-text)]"><Compass className="h-4 w-4" aria-hidden="true" /><h2 className="text-xs font-semibold">当前支持</h2></div>
    {plan ? <div className="mt-3 space-y-2">
      <p className="text-[17px] font-semibold leading-7">{plan.question_goal || teachingStrategyLabel(plan.strategy)}</p>
      {plan.question_goal ? <p className="mt-tool-badge inline-flex" data-tone="active">{teachingStrategyLabel(plan.strategy)}</p> : null}
      {reasons.map(reason => <p key={reason} className="text-xs leading-5 text-[var(--muted-foreground)]">{reason}</p>)}
    </div> : <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">提交题目后，这里会说明本轮要解决的小问题。</p>}
    <div className="mt-4 border-t border-[var(--primary-border)] pt-4">
      <p className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]"><Eye className="h-3.5 w-3.5" aria-hidden="true" />已展示内容</p>
      <p className="mt-1 text-sm text-[var(--foreground)]">{supportExposureLabel(current)}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">这是本题的帮助记录，不是能力进度。你可以直接选择所需支持；看过一次提示后可以查看完整答案。</p>
    </div>
  </section>;
}
