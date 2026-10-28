"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import BrandMark from "@/components/common/BrandMark";
import ChoiceQuestion from "../../components/ChoiceQuestion";
import { assessmentRequest, type InitialAssessment } from "../lib/initial-assessment";

export default function InitialAssessmentPage() {
  const router = useRouter();
  const [data, setData] = useState<InitialAssessment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const saving = useRef(false);
  const requestVersion = useRef(0);
  const load = useCallback(async () => {
    const version = ++requestVersion.current;
    setError("");
    try {const next = await assessmentRequest(); if (version === requestVersion.current) setData(next);}
    catch (reason) {if (version === requestVersion.current) setError(reason instanceof Error ? reason.message : "加载失败，请重试。");}
  }, []);
  useEffect(() => {void load();}, [load]);
  useEffect(() => {heading.current?.focus();}, [data?.answered, data?.status]);
  const act = async (action: string, body?: object) => {
    if (saving.current) return;
    saving.current = true;
    ++requestVersion.current;
    setBusy(true); setError("");
    try {
      const next = await assessmentRequest(action, body);
      if (action === "skip") router.replace("/math-tutor"); else setData(next);
    } catch (reason) {setError(reason instanceof Error ? reason.message : "保存失败，请重试。");}
    finally {saving.current = false; setBusy(false);}
  };
  const question = data?.question;
  return <main className="relative h-dvh overflow-y-auto bg-[var(--background)] px-5 py-8 text-[var(--foreground)] sm:py-14">
    <div className="mt-onboarding-field mt-paper pointer-events-none absolute inset-x-0 top-0 h-[520px]" aria-hidden="true" />
    <div className="mt-rise relative mx-auto max-w-2xl">
      <div className="mb-10 flex items-center gap-2.5"><span className="mt-brand-mark"><BrandMark /></span><span className="mt-wordmark">Math<span>Tutor</span></span><span className="ml-1 rounded-full border border-[var(--border)] bg-[var(--card)] px-2.5 py-0.5 text-xs font-medium text-[var(--muted-foreground)]">学习起点</span></div>
      <h1 ref={heading} tabIndex={-1} className="text-[32px] font-bold leading-tight tracking-[-0.03em] focus:outline-none">{data?.status === "completed" ? "从适合你的练习开始" : "先用几道小题认识你"}</h1>
      <p className="mt-3 text-base leading-7 text-[var(--muted-foreground)]">10 道单选题，覆盖当前支持的五类数学题。不确定就直接选“不确定”；不计时，也不会给你贴能力标签。</p>
      {error && <div role="alert" className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4"><p>{error}</p><button disabled={busy} onClick={() => void load()} className="mt-2 min-h-11 underline">重新同步进度</button></div>}
      {!data && !error && <p role="status" className="mt-6">正在读取初评进度…</p>}
      {question && <section className="mt-card mt-8 p-5 shadow-[var(--shadow-lg)] sm:p-8" aria-label="初评题目">
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm text-[var(--muted-foreground)]"><span className="rounded-md bg-[var(--primary-soft)] px-2 py-0.5 text-xs font-semibold text-[var(--primary-text)]">{question.skill_label}</span><span className="tabular-nums">第 <b className="font-semibold text-[var(--foreground)]">{data!.answered + 1}</b> / {data!.total} 题</span></div>
        <div className="mt-progress mt-4" role="progressbar" aria-label="初评进度" aria-valuemin={0} aria-valuemax={data!.total} aria-valuenow={data!.answered}><span style={{ width: `${(data!.answered / Math.max(1, data!.total)) * 100}%` }} /></div>
        <h2 className="mt-paper -mx-5 my-6 break-words border-y border-[var(--border)] px-5 py-6 text-[22px] font-medium leading-9 sm:-mx-8 sm:px-8">{question.statement}</h2>
        <ChoiceQuestion key={question.choices.version} choices={question.choices} busy={busy} allowUnsure onSubmit={option_id => void act("answer", {run_id: data!.run_id, index: question.index, option_id, version: question.choices.version})} />
        <p className="mt-4 text-xs leading-6 text-[var(--muted-foreground)]">提交后自动保存。首次选择不能改写，刷新后可继续。</p>
      </section>}
      {data?.status === "completed" && data.result && <section className="mt-7 space-y-4" aria-label="初评结果">
        <p className="mt-card p-4 text-sm leading-7">{data.result.notice}</p>
        {data.result.skills.map(skill => <div key={skill.skill_id} className="mt-card p-5"><h2 className="font-semibold">{skill.label}</h2><p className="mt-2 text-sm">{skill.observation} · 练习难度 {skill.starting_difficulty}/5</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">已判定 {skill.observed} 题，答对 {skill.correct} 题，不确定 {skill.unknown} 题</p></div>)}
        <Link className="mt-btn mt-btn-primary min-h-11 px-6" href="/math-tutor">开始学习</Link>
      </section>}
      {data?.status === "not_started" && <button disabled={busy} onClick={() => void act("start")} className="mt-btn mt-btn-primary mt-6 min-h-11 px-6">开始初评</button>}
      {data?.compatibility_notice && <p className="mt-card mt-6 p-4 text-sm leading-7">{data.compatibility_notice}</p>}
      {data?.status === "skipped" && <section className="mt-card mt-6 space-y-4 p-5" aria-label="暂缓的初评">
        <p className="text-sm leading-7">已暂缓初评，保留已完成的 {data.answered} / {data.total} 题。继续学习不会清除这些记录。</p>
        <div className="flex flex-wrap gap-3">
          {data.can_resume && <button disabled={busy} className="mt-btn mt-btn-primary min-h-11 px-6" onClick={() => void act("resume", {run_id: data.run_id, version: data.assessment_version})}>{busy ? "正在恢复…" : "继续初评"}</button>}
          <Link href="/math-tutor" className="mt-btn min-h-11 px-6">进入学习</Link>
        </div>
      </section>}
      {data && ["pending", "in_progress"].includes(data.status) && <button disabled={busy} className="mt-5 min-h-11 px-2 text-sm text-[var(--muted-foreground)] underline underline-offset-4 disabled:opacity-50" onClick={() => void act("skip", {run_id: data.run_id})}>暂缓初评，先开始学习</button>}
      <p className="mt-8 text-xs leading-6 text-[var(--muted-foreground)]">当前初评使用可解释规则选择练习起点；DKT 目标域模型仍在验证，不用于能力定级。答题记录保存在本地，可在隐私设置中删除学习记录。</p>
    </div>
  </main>;
}
