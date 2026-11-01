"use client";

import {useI18n} from "@/lib/i18n";
import { Compass, Eye } from "lucide-react";
import { normalizeAssistanceLevel } from "../lib/protocol";
import { supportExposureLabel, teachingReasonLabels, teachingStrategyLabel } from "../lib/teaching-contract";
import type { TeachingPlan } from "../types";

/** Exposure is not ability, completion, or a mandatory ladder to the answer. */
export default function HintLadder({ level, plan, discussion = false }: { level: number; plan?: TeachingPlan | null; discussion?: boolean }) {
  const {t} = useI18n();
  const current = normalizeAssistanceLevel(level);
  const reasons = teachingReasonLabels(plan?.reason_codes || []);
  return <section className="mt-support-goal" aria-label={t("当前教学支持")}>
    <div className="flex items-center gap-2 text-[var(--primary-text)]"><Compass className="h-4 w-4" aria-hidden="true" /><h2 className="text-xs font-semibold">{t("当前支持")}</h2></div>
    {plan ? <div className="mt-3 space-y-2">
      <p className="text-[17px] font-semibold leading-7">{t(plan.question_goal || teachingStrategyLabel(plan.strategy))}</p>
      {plan.question_goal ? <p className="mt-tool-badge inline-flex" data-tone="active">{t(teachingStrategyLabel(plan.strategy))}</p> : null}
      {reasons.map(reason => <p key={t(reason)} className="text-xs leading-5 text-[var(--muted-foreground)]">{t(reason)}</p>)}
    </div> : <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">{discussion ? t("本题已保存，可选择提示、概念讲解、同类示例或完整解答。") : t("提交题目后，这里会说明本轮要解决的小问题。")}</p>}
    <div className="mt-4 border-t border-[var(--primary-border)] pt-4">
      {discussion ? <p className="text-xs leading-5 text-[var(--muted-foreground)]">{t("讲解供学习参考，整题尚未自动核验，不计为独立作答或掌握证据。")}</p> : <>
      <p className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]"><Eye className="h-3.5 w-3.5" aria-hidden="true" />{t("已展示内容")}</p>
      <p className="mt-1 text-sm text-[var(--foreground)]">{t(supportExposureLabel(current))}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">{t("这是本题的帮助记录，不是能力进度。你可以直接选择所需支持；看过一次提示后可以查看完整答案。")}</p>
      </>}
    </div>
  </section>;
}
