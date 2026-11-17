"use client";

import { useEffect, useState } from "react";
import { useI18n } from "@/lib/i18n";
import { productClass } from "@/styles/product-classes";
import type { CheckPrompt, ExplorationView } from "./api";

export function IndependentCheck({ check, busy, onRespond, onExplain }: {
  check: CheckPrompt; busy: boolean; onRespond: (answer: string) => void; onExplain: () => void;
}) {
  const { t } = useI18n();
  const [answer, setAnswer] = useState("");
  useEffect(() => setAnswer(""), [check.check_id]);
  return <form onSubmit={event => { event.preventDefault(); if (answer.trim() && !busy) onRespond(answer.trim()); }}
    className="mt-7 border-t border-[var(--border)] pt-6" aria-labelledby="check-title">
    <h3 id="check-title" className="text-base font-semibold">{t(check.purpose === "transfer" ? "换个情境试一试" : "独立想一题")}</h3>
    <fieldset disabled={busy} className="mt-3 min-w-0">
      <legend className="whitespace-pre-wrap break-words text-base leading-7">{check.prompt}</legend>
      {check.response_type === "choice" ? <div className="mt-4 space-y-2">{(check.choices ?? []).map(choice =>
        <label key={choice.id} className={`flex min-h-11 cursor-pointer items-start gap-3 rounded-lg border p-3 ${answer === choice.id ? "border-[var(--primary)] bg-[var(--primary-soft)]" : "border-[var(--border)]"}`}>
          <input type="radio" name={`check-${check.check_id}`} value={choice.id} checked={answer === choice.id}
            onChange={() => setAnswer(choice.id)} className="mt-1 h-4 w-4 shrink-0 accent-[var(--primary)]" />
          <span className="min-w-0 whitespace-pre-wrap break-words leading-6">{choice.text}</span>
        </label>)}</div> : <label className="mt-4 block text-sm font-medium">
        {t("你的答案")}
        <input value={answer} onChange={event => setAnswer(event.target.value)} inputMode="decimal" maxLength={240}
          autoComplete="off" className={productClass("mt-input mt-2 min-h-11 w-full text-base")} />
      </label>}
    </fieldset>
    <div className="mt-4 flex flex-wrap items-center gap-2">
      <button type="submit" disabled={busy || !answer.trim()} className={productClass("mt-btn mt-btn-primary min-h-11 px-4")}>{t("提交回答")}</button>
      <button type="button" onClick={onExplain} disabled={busy} className={productClass("mt-btn min-h-11 px-3")}>{t("查看解释")}</button>
    </div>
    <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{t("查看解释会记录为辅助学习，并换一道题。")}</p>
  </form>;
}

export function LearningFeedback({ view }: { view: ExplorationView }) {
  const { t } = useI18n();
  if (!view.last_check || !view.last_feedback) return null;
  return <section className="mt-6 rounded-lg border border-[var(--border)] p-4" aria-label={t("上一题反馈")} aria-live="polite">
    <p className="text-sm font-semibold">{t(view.last_correctness === "explanation" ? "上一题解释 · 已记录辅助学习" : "上一题反馈")}</p>
    <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6 text-[var(--muted-foreground)]">{view.last_check.prompt}</p>
    <p className="mt-3 whitespace-pre-wrap break-words leading-7">{view.last_feedback}</p>
  </section>;
}

const evidenceLabels: Record<ExplorationView["learning"]["evidence_state"], string> = {
  unknown: "从阅读开始，用回答检验理解。",
  assisted_only: "已有辅助学习记录，可以换题独立尝试。",
  needs_check: "这次回答还有疑点，先检查条件。",
  mixed_observations: "回答表现不一致，换个例子再判断。",
  independent_observed: "已有独立作答证据，可以继续迁移练习。",
};

export default function LearningPanel({ view, busy, onRespond, onExplain }: {
  view: ExplorationView; busy: boolean; onRespond: (answer: string) => void; onExplain: () => void;
}) {
  const { t } = useI18n();
  return <aside aria-labelledby="learning-title" className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-6">
    <p className="text-sm font-medium text-[var(--primary-text)]">{t("从阅读到理解")}</p>
    <h2 id="learning-title" className="mt-2 text-xl font-semibold tracking-tight">{t("接下来，走一小步")}</h2>
    <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t(evidenceLabels[view.learning.evidence_state])}</p>
    <ol className="mt-5 space-y-5">{view.learning.steps.slice(0, 3).map((step, index) => <li key={step.step_id} className="flex gap-3">
      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--primary-soft)] text-sm font-semibold text-[var(--primary-text)]" aria-hidden="true">{index + 1}</span>
      <div className="min-w-0"><h3 className="break-words font-medium leading-6">{step.title}</h3><p className="mt-1 break-words text-sm leading-6 text-[var(--muted-foreground)]">{step.reason}</p></div>
    </li>)}</ol>
    <LearningFeedback view={view} />
    {view.learning.check ? <IndependentCheck key={view.learning.check.check_id} check={view.learning.check} busy={busy} onRespond={onRespond} onExplain={onExplain} />
      : <p className="mt-6 border-t border-[var(--border)] pt-5 text-sm leading-7 text-[var(--muted-foreground)]">{t("暂时没有更多预设检查题。用自己的话记录理解和仍待解决的问题。")}</p>}
  </aside>;
}
