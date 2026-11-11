"use client";

import {useCallback, useEffect, useId, useRef, useState} from "react";
import {ArrowRight, RefreshCw} from "lucide-react";
import {useI18n} from "@/lib/i18n";
import {ApiError} from "@/lib/api-error";
import {
  learningLoopRequest, LOOP_PHASE_LABELS,
  type LearningLoop, type LoopAction, type LoopDomain, type LoopEntry, type LoopFeedback, type LoopRequest,
} from "../lib/learning-loop";

const FEEDBACK_LABELS: Record<LoopFeedback["kind"], string> = {
  recorded: "已记录这次作答，继续下一题。",
  correct: "这题答对了。",
  incorrect: "这题还需要再练习。",
  unknown: "暂时无法识别答案，请填写整数、小数或分数。",
  help: "解法已打开，这题记为受助练习。",
};

export function LearningLoopCard({entry, busy, onAction}: {
  entry: LoopEntry; busy: boolean; onAction: (action: LoopAction, body: LoopRequest) => Promise<boolean>;
}) {
  const {t, locale} = useI18n();
  const episode = entry.episode;
  const question = episode?.question;
  const [answer, setAnswer] = useState("");
  const [inputError, setInputError] = useState(false);
  const inputId = useId();
  const answerInput = useRef<HTMLInputElement>(null);
  const questionHeading = useRef<HTMLHeadingElement>(null);
  const feedbackHeading = useRef<HTMLHeadingElement>(null);
  const previousQuestion = useRef(question?.probe_id);
  useEffect(() => {
    if (previousQuestion.current !== question?.probe_id) {
      setAnswer(""); setInputError(false);
      if (episode?.feedback && episode.feedback.kind !== "recorded") feedbackHeading.current?.focus();
      else if (question) questionHeading.current?.focus();
      previousQuestion.current = question?.probe_id;
    }
  }, [question?.probe_id, question, episode?.feedback]);
  const feedback = episode?.feedback;
  const english = locale === "en";
  const label = english ? entry.label_en : entry.label_zh;
  const due = episode?.due_at ? new Date(episode.due_at) : null;
  const dueText = due && Number.isFinite(due.getTime()) ? due.toLocaleString(locale, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  }) : "";
  const act = async (action: "answer" | "help") => {
    if (!episode || !question || busy) return;
    if (action === "answer" && !answer.trim()) {
      setInputError(true); answerInput.current?.focus(); return;
    }
    const ok = await onAction(action, {
      domain: entry.domain, episode_id: episode.episode_id, probe_id: question.probe_id,
      ...(action === "answer" ? {answer} : {}),
    });
    if (ok && action === "answer") setInputError(false);
  };
  return <article aria-label={label} className="mt-card min-w-0 p-5 sm:p-6">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <h3 className="text-lg font-semibold">{label}</h3>
      <span className="rounded-md bg-[var(--primary-soft)] px-3 py-1 text-sm text-[var(--primary-text)]">
        {t(episode ? LOOP_PHASE_LABELS[episode.phase] : "尚未开始")}
      </span>
    </div>
    {!episode && <div className="mt-4">
      <p className="leading-7 text-[var(--muted-foreground)]">{t("先用最多三道小题检查作答，再安排独立练习。")}</p>
      <button type="button" className="mt-btn mt-btn-primary mt-4 min-h-11" disabled={busy}
        onClick={() => void onAction("start", {domain: entry.domain})}>{t("开始检查")}<ArrowRight aria-hidden="true" className="h-4 w-4" /></button>
    </div>}
    {episode && <div className="mt-4 space-y-5">
      {episode.diagnostic.label_zh && <div className="rounded-lg bg-[var(--muted)] p-4">
        <p className="font-medium">{t("当前观察")}</p>
        <p className="mt-1 break-words leading-7">{english ? episode.diagnostic.label_en : episode.diagnostic.label_zh}</p>
      </div>}
      {feedback && <div id={`${inputId}-feedback`} role="status" aria-live="polite" className="border-l-2 border-[var(--primary-border)] pl-4">
        <h4 ref={feedbackHeading} tabIndex={-1} className="font-medium focus-visible:outline">{t("本次结果")}</h4>
        {feedback.statement && <p className="mt-1 break-words font-mono">{feedback.statement}</p>}
        <p className="mt-1 leading-7">{t(FEEDBACK_LABELS[feedback.kind])}</p>
        {feedback.answer !== undefined && <p className="mt-1 break-words font-medium">{t("答案：{answer}", {answer: feedback.answer})}</p>}
        {(english ? feedback.explanation_en : feedback.explanation_zh) && <p className="mt-1 leading-7 text-[var(--muted-foreground)]">
          {english ? feedback.explanation_en : feedback.explanation_zh}
        </p>}
        {feedback.kind === "correct" && feedback.independent === false &&
          <p className="mt-1 leading-7">{t("参考解法后的答对已保存，接着用新题独立检查。")}</p>}
      </div>}
      {question && <form onSubmit={event => {event.preventDefault(); void act("answer");}} aria-busy={busy}>
        {episode.phase === "diagnose" && <p className="mb-2 text-sm text-[var(--muted-foreground)]">
          {t("检查题 {number} / 3", {number: Math.min(3, episode.diagnostic.answered + 1)})}
        </p>}
        <h4 ref={questionHeading} tabIndex={-1} className="rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--primary)]">
          <span className="block leading-7">{english ? question.prompt_en : question.prompt_zh}</span>
          <span className="mt-paper mt-3 block break-words rounded-lg border border-[var(--border)] px-4 py-5 font-mono text-xl leading-9">{question.statement}</span>
        </h4>
        <label htmlFor={inputId} className="mb-2 mt-4 block font-medium">{t("填写数值答案")}</label>
        <input ref={answerInput} id={inputId} className="mt-input min-h-11 w-full text-base"
          value={answer} onChange={event => {setAnswer(event.target.value); setInputError(false);}}
          onBlur={() => {if (answer.length > 0 && !answer.trim()) setInputError(true);}}
          disabled={busy} maxLength={48} autoComplete="off" spellCheck={false}
          aria-invalid={inputError || feedback?.kind === "unknown" || undefined}
          aria-describedby={inputError ? `${inputId}-error` : feedback?.kind === "unknown" ? `${inputId}-feedback` : undefined} />
        {inputError && <p id={`${inputId}-error`} role="alert" className="mt-2 text-[var(--destructive)]">{t("请先填写答案。")}</p>}
        <div className="mt-4 flex flex-wrap gap-3">
          <button className="mt-btn mt-btn-primary min-h-11" type="submit" disabled={busy}>{t(busy ? "正在保存…" : "提交答案")}</button>
          <button className="mt-btn min-h-11 whitespace-normal text-left" type="button" disabled={busy}
            onClick={() => void act("help")}>{t("看解法（计为受助练习）")}</button>
        </div>
      </form>}
      {episode.phase === "waiting" && <div>
        <p className="font-medium">{episode.can_start ? t("已到复习时间") : t("下次复习：{date}", {date: dueText})}</p>
        <p className="mt-2 leading-7 text-[var(--muted-foreground)]">{t("到时再用新题检查。错过时间也可以继续。")}</p>
        {episode.can_start && <button type="button" disabled={busy} className="mt-btn mt-btn-primary mt-4 min-h-11"
          onClick={() => void onAction("start", {domain: entry.domain})}>{t("开始复习")}</button>}
      </div>}
      {episode.phase === "complete" && <p className="leading-7">{t("已经留下本轮的延迟复习与结构变化题记录。")}</p>}
      {episode.phase === "exhausted" && <p className="leading-7">{t("当前可用的新题已经完成，已有记录会保留。")}</p>}
      <div className="border-t border-[var(--border)] pt-4">
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div><dt className="text-sm text-[var(--muted-foreground)]">{t("独立练习记录")}</dt><dd className="mt-1 text-lg tabular-nums">{episode.evidence.independent_practice}</dd></div>
          <div><dt className="text-sm text-[var(--muted-foreground)]">{t("延迟复习记录")}</dt><dd className="mt-1 text-lg tabular-nums">{episode.evidence.delayed_review}</dd></div>
          <div><dt className="text-sm text-[var(--muted-foreground)]">{t("结构变化记录")}</dt><dd className="mt-1 text-lg tabular-nums">{episode.evidence.structural_transfer}</dd></div>
        </dl>
        <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{t("这些记录分别说明本轮作答，不代表永久掌握。")}</p>
      </div>
    </div>}
  </article>;
}

export default function LearningLoopPanel() {
  const {t, locale} = useI18n();
  const [data, setData] = useState<LearningLoop | null>(null);
  const [selected, setSelected] = useState<LoopDomain>("fraction_addition");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const saving = useRef(false);
  const sequence = useRef(0);
  const mounted = useRef(true);
  const pending = useRef<{fingerprint: string; requestId: string} | null>(null);
  const errorBox = useRef<HTMLDivElement>(null);
  const load = useCallback(async (signal?: AbortSignal) => {
    if (saving.current) return;
    const version = ++sequence.current;
    setLoading(true); setError("");
    try {
      const next = await learningLoopRequest(undefined, undefined, signal);
      if (mounted.current && sequence.current === version) setData(next);
    } catch (reason) {
      if (!signal?.aborted && mounted.current && sequence.current === version) setError("概念复查暂时无法同步，请重试。");
    } finally {
      if (mounted.current && sequence.current === version) setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    void load(controller.signal);
    return () => {mounted.current = false; ++sequence.current; controller.abort();};
  }, [load]);
  useEffect(() => {if (error) errorBox.current?.focus();}, [error]);
  const act = async (action: LoopAction, body: LoopRequest) => {
    if (saving.current || loading) return false;
    saving.current = true; setBusy(true); setError("");
    const version = ++sequence.current;
    if (action !== "start") {
      const fingerprint = JSON.stringify([action, body]);
      if (pending.current?.fingerprint !== fingerprint) pending.current = {fingerprint, requestId: crypto.randomUUID()};
      body = {...body, request_id: pending.current.requestId};
    }
    try {
      const next = await learningLoopRequest(action, body);
      if (mounted.current && sequence.current === version) {setData(next); pending.current = null;}
      return true;
    } catch (reason) {
      if (mounted.current && sequence.current === version) setError(reason instanceof ApiError && reason.status === 409
        ? "进度已更新，请刷新后继续。" : "保存未确认，保留了你的答案。可以重试或同步进度。");
      return false;
    } finally {
      saving.current = false;
      if (mounted.current && sequence.current === version) setBusy(false);
    }
  };
  const entry = data?.domains.find(row => row.domain === selected) || data?.domains[0];
  return <section aria-labelledby="learning-loop-title" className="space-y-4">
    <div className="flex items-start justify-between gap-4">
      <div><h2 id="learning-loop-title" className="mt-section-title">{t("概念复查")}</h2>
        <p className="mt-2 max-w-2xl leading-7 text-[var(--muted-foreground)]">{t("先辨别作答模式，再用间隔复习和结构变化题继续检查。")}</p></div>
      <button type="button" className="mt-btn mt-btn-icon shrink-0" disabled={busy || loading} aria-label={t("同步进度")}
        onClick={() => void load()}><RefreshCw className="h-4 w-4" aria-hidden="true" /></button>
    </div>
    {error && <div ref={errorBox} tabIndex={-1} role="alert" className="rounded-lg border border-[var(--border)] bg-[var(--muted)] p-4 focus-visible:outline">
      <p>{t(error)}</p><button type="button" disabled={busy || loading} className="mt-btn mt-3 min-h-11" onClick={() => void load()}>{t("同步进度")}</button>
    </div>}
    {loading && !data && <p role="status">{t("正在加载概念复查…")}</p>}
    {data && <div role="group" aria-label={t("选择复查内容")} className="flex flex-wrap gap-3">
      {data.domains.map(row => <button key={row.domain} type="button" disabled={busy || loading}
        aria-pressed={row.domain === entry?.domain} onClick={() => setSelected(row.domain)}
        className="mt-btn min-h-11 aria-pressed:border-[var(--primary-border)] aria-pressed:bg-[var(--primary-soft)] aria-pressed:text-[var(--primary-text)]">
        {locale === "en" ? row.label_en : row.label_zh}
        {row.episode?.phase === "waiting" && row.episode.can_start && <span className="text-sm"> · {t("已到复习时间")}</span>}
      </button>)}
    </div>}
    {data?.domains.map(row => <div key={row.domain} hidden={row.domain !== entry?.domain}>
      <LearningLoopCard entry={row} busy={busy || loading} onAction={act} />
    </div>)}
  </section>;
}
