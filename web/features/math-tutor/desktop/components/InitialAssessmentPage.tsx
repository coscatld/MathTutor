"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpenCheck } from "lucide-react";
import ChoiceQuestion from "../../components/ChoiceQuestion";
import { assessmentRequest, type InitialAssessment } from "../lib/initial-assessment";

export default function InitialAssessmentPage() {
  const router = useRouter();
  const [data, setData] = useState<InitialAssessment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const heading = useRef<HTMLHeadingElement>(null);
  const load = useCallback(async () => {
    setError("");
    try {setData(await assessmentRequest());} catch (reason) {setError(reason instanceof Error ? reason.message : "加载失败，请重试。");}
  }, []);
  useEffect(() => {void load();}, [load]);
  useEffect(() => {heading.current?.focus();}, [data?.answered, data?.status]);
  const act = async (action: string, body?: object) => {
    setBusy(true); setError("");
    try {
      const next = await assessmentRequest(action, body);
      if (action === "skip") router.replace("/math-tutor"); else setData(next);
    } catch (reason) {setError(reason instanceof Error ? reason.message : "保存失败，请重试。");}
    finally {setBusy(false);}
  };
  const question = data?.question;
  return <main className="h-dvh overflow-y-auto bg-[var(--background)] px-5 py-8 text-[var(--foreground)] sm:py-12">
    <div className="mx-auto max-w-2xl">
      <div className="mb-8 flex items-center gap-2 text-sm font-semibold text-[var(--primary)]"><BookOpenCheck className="h-5 w-5" aria-hidden="true" />MathTutor · 学习起点</div>
      <h1 ref={heading} tabIndex={-1} className="font-serif text-3xl font-bold leading-tight focus:outline-none">{data?.status === "completed" ? "从适合你的练习开始" : "先用几道小题认识你"}</h1>
      <p className="mt-3 text-base leading-7 text-[var(--muted-foreground)]">10 道单选题，覆盖当前支持的五类数学题。不确定就直接选“不确定”；不计时，也不会给你贴能力标签。</p>
      {error && <div role="alert" className="mt-5 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4"><p>{error}</p><button onClick={() => void load()} className="mt-2 min-h-11 underline">重新同步进度</button></div>}
      {!data && !error && <p role="status" className="mt-6">正在读取初评进度…</p>}
      {question && <section className="mt-7 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-8" aria-label="初评题目">
        <div className="flex flex-wrap justify-between gap-2 text-sm text-[var(--muted-foreground)]"><span>{question.skill_label}</span><span>第 {data!.answered + 1} / {data!.total} 题</span></div>
        <progress className="mt-3 h-2 w-full accent-[var(--primary)]" value={data!.answered} max={data!.total} aria-label="初评进度" />
        <h2 className="my-6 break-words font-mono text-xl leading-8">{question.statement}</h2>
        <ChoiceQuestion key={question.choices.version} choices={question.choices} busy={busy} allowUnsure onSubmit={option_id => void act("answer", {run_id: data!.run_id, index: question.index, option_id, version: question.choices.version})} />
        <p className="mt-4 text-xs leading-6 text-[var(--muted-foreground)]">提交后自动保存。首次选择不能改写，刷新后可继续。</p>
      </section>}
      {data?.status === "completed" && data.result && <section className="mt-7 space-y-4" aria-label="初评结果">
        <p className="rounded-xl border border-[var(--border)] p-4 text-sm leading-7">{data.result.notice}</p>
        {data.result.skills.map(skill => <div key={skill.skill_id} className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-5"><h2 className="font-semibold">{skill.label}</h2><p className="mt-2 text-sm">{skill.observation} · 练习难度 {skill.starting_difficulty}/5</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">已判定 {skill.observed} 题，答对 {skill.correct} 题，不确定 {skill.unknown} 题</p></div>)}
        <Link className="inline-flex min-h-11 items-center rounded-xl bg-[var(--primary)] px-6 py-3 font-semibold text-[var(--primary-foreground)]" href="/math-tutor">开始学习</Link>
      </section>}
      {data?.status === "not_started" && <button disabled={busy} onClick={() => void act("start")} className="mt-6 min-h-11 rounded-xl bg-[var(--primary)] px-6 text-[var(--primary-foreground)]">开始初评</button>}
      {data?.status === "skipped" && <p className="mt-6">已跳过初评。后续将根据练习中的真实作答逐步调整。<Link href="/math-tutor" className="ml-2 underline">进入学习</Link></p>}
      {question && <button disabled={busy} className="mt-5 min-h-11 px-2 text-sm text-[var(--muted-foreground)] underline underline-offset-4 disabled:opacity-50" onClick={() => void act("skip", {run_id: data?.run_id})}>跳过初评，先开始学习</button>}
      <p className="mt-8 text-xs leading-6 text-[var(--muted-foreground)]">当前初评使用可解释规则选择练习起点；DKT 目标域模型仍在验证，不用于能力定级。答题记录保存在本地，可在隐私设置中删除学习记录。</p>
    </div>
  </main>;
}
