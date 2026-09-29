"use client";

import { Check, ChevronDown, CornerUpLeft, ListChecks } from "lucide-react";
import { useEffect, useRef } from "react";
import type { DiagnosisSummary, EvidenceSummary, ProblemContext } from "../types";
import { evidenceStatusLabel } from "../lib/teaching-contract";

const LIFECYCLE_LABELS: Record<string, string> = { ACTIVE: "辅导中", COMPLETED: "本题已完成", RESOLVED: "本题已完成", PAUSED: "已搁置", CLOSED: "已结束", ENDED: "已结束", SKIPPED: "已跳过", NEEDS_CLARIFICATION: "待补充题目" };

/** Source and goal come from the persisted context, not text-message parsing. */
export function CurrentProblem({ context }: { context?: ProblemContext | null }) {
  const disclosure = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const closeOutside = (event: PointerEvent | FocusEvent) => {
      if (event.target instanceof Node && !disclosure.current?.contains(event.target) && disclosure.current) disclosure.current.open = false;
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && disclosure.current?.open) {
        disclosure.current.open = false;
        disclosure.current.querySelector("summary")?.focus();
      }
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("focusin", closeOutside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("focusin", closeOutside);
      document.removeEventListener("keydown", escape);
    };
  }, []);
  if (!context) return null;
  const lifecycle = context.lifecycle.toUpperCase();
  const completeStep = ["completed", "verified", "resolved"].includes(context.current_subgoal?.status.toLowerCase() || "");
  return <details ref={disclosure} className="mt-context">
    <summary aria-label="当前题目与目标" className="mt-context-trigger">
      <ListChecks className="h-4 w-4 shrink-0" aria-hidden="true" />
      <span className="min-w-0"><span className="mt-context-label">当前题目</span><span className="mt-context-preview">{context.display_text || "待补充题目"}</span></span>
      <ChevronDown className="mt-context-chevron h-3.5 w-3.5 shrink-0" aria-hidden="true" />
    </summary>
    <section aria-label="题目与目标详情" className="mt-context-popover">
      <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]"><ListChecks className="h-3.5 w-3.5" aria-hidden="true" /><span>当前题目</span><span className="ml-auto rounded-full border border-[var(--border)] px-2 py-0.5">{LIFECYCLE_LABELS[lifecycle] || "当前任务"}</span></div>
      <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">{context.display_text || "请补充当前题目的完整要求。"}</p>
      {context.current_subgoal?.prompt_target ? <div className="mt-1 flex items-start gap-1.5 text-xs leading-5 text-[var(--primary-text)]">{completeStep ? <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" /> : <CornerUpLeft className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />}<span>{completeStep ? "已验证步骤：" : "当前小目标："}{context.current_subgoal.prompt_target}</span></div> : null}
    </section>
  </details>;
}

export function EvidenceSummaryCard({ evidence }: { evidence?: EvidenceSummary | null }) {
  if (!evidence) return null;
  const entries = [["独立作答", evidence.independent], ["受助作答", evidence.assisted], ["看答案后作答", evidence.post_solution], ["诊断作答", evidence.diagnostic], ["暂无法判断", evidence.ungradable]] as const;
  return <section aria-label="本题学习证据" className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4">
    <h2 className="text-sm font-semibold">本题学习证据</h2>
    <dl className="mt-3 space-y-2">{entries.map(([label, count]) => <div key={label} className="flex items-center justify-between gap-3 text-xs"><dt className="text-[var(--muted-foreground)]">{label}</dt><dd className="tabular-nums text-[var(--foreground)]">{count} 次</dd></div>)}</dl>
    <p className="mt-3 border-t border-[var(--border)] pt-3 text-xs leading-5 text-[var(--muted-foreground)]">{evidenceStatusLabel(evidence.status)}。观看答案不计作独立掌握。</p>
  </section>;
}

export function DiagnosisNotice({ diagnosis }: { diagnosis?: DiagnosisSummary | null }) {
  if (!diagnosis || !["active", "in_progress", "running"].includes(diagnosis.status.toLowerCase())) return null;
  return <section aria-label="可跳过的基础检查" className="rounded-2xl border border-[var(--primary-border)] bg-[var(--primary-soft)] p-4"><h2 className="text-sm font-semibold">了解当前基础</h2><p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">已作答 {diagnosis.answered ?? 0} / {diagnosis.question_count} 道，题量会根据实际回答调整。跳过不会记为错误。{diagnosis.can_skip ? "你可以随时跳过，回到当前辅导。" : ""}</p></section>;
}
