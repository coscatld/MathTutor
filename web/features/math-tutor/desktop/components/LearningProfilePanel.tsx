"use client";

import {useCallback, useEffect, useState} from "react";
import Link from "next/link";
import {useSearchParams} from "next/navigation";
import {ArrowUpRight, BookOpen, RefreshCw} from "lucide-react";
import {fetchStudentSummary} from "../lib/desktop-api";
import type {StudentSummary, SkillSummary} from "../types";
import SkillEvidenceDrawer from "./SkillEvidenceDrawer";

export function SkillObservation({skill, onEvidence}: {skill: SkillSummary; onEvidence: () => void}) {
  return <article className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5 sm:p-6">
    <p className="text-xs font-medium text-[var(--muted-foreground)]">{skill.label}</p>
    <h2 className="mt-3 max-w-xl font-serif text-lg font-semibold leading-8">{skill.observation || skill.evidence_status || "尚未检查"}</h2>
    <p className="mt-3 text-sm text-[var(--muted-foreground)]">{skill.evidence_count ? `依据 ${skill.evidence_count} 条作答记录。` : "完成相关的新题后，这里会展示学习观察。"}{skill.last_checked_at ? ` 最近检查：${new Date(skill.last_checked_at).toLocaleDateString("zh-CN")}。` : ""}</p>
    <div className="mt-5 flex flex-wrap gap-3"><button type="button" onClick={onEvidence} className="min-h-11 rounded-lg border border-[var(--border)] px-4 text-sm focus-visible:outline-2 focus-visible:outline-[var(--ring)]">查看依据</button><Link href={skill.next_href || "/math-tutor/offers"} className="inline-flex min-h-11 items-center gap-1 rounded-lg px-3 text-sm font-medium text-[var(--primary)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]">{skill.next_action || "查看推荐练习"}<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link></div>
    <details className="mt-3 text-sm text-[var(--muted-foreground)]"><summary className="cursor-pointer py-2">证据计数</summary><dl className="mt-2 grid grid-cols-2 gap-3">{Object.entries(skill.counts || {}).map(([key, value]) => <div key={key}><dt>{{independent:"独立作答", assisted:"受助作答", post_solution:"答案后作答", diagnostic:"诊断"}[key] || key}</dt><dd className="mt-1">答对 {value.correct} · 答错 {value.incorrect}</dd></div>)}</dl>{!!skill.joint_task_evidence && <p className="mt-2">另有 {skill.joint_task_evidence} 条联合题证据，需结合整题查看。</p>}</details>
  </article>;
}

export default function LearningProfilePanel() {
  const query = useSearchParams();
  const cycle = query.get("cycle") || undefined;
  const [summary, setSummary] = useState<StudentSummary | null>(null);
  const [error, setError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<{title:string; skillId?:string; cycleId?:string} | null>(null);
  const load = useCallback(async () => {
    setLoading(true); setError(false);
    try { setSummary(await fetchStudentSummary()); } catch { setError(true); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (cycle) setSelected({title:"本次学习记录", cycleId:cycle}); }, [cycle]);
  const observed = summary?.skills.filter(s => (s.evidence_count || 0) > 0) || [];
  const unchecked = summary?.skills.filter(s => !s.evidence_count) || [];
  return <div className="mt-page">
    <header className="flex items-start justify-between gap-5"><div><p className="text-xs font-semibold tracking-widest text-[var(--primary)]">从作答中了解自己</p><h1 className="mt-2 font-serif text-3xl font-bold">学习画像</h1><p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">每条观察都来自本设备上的可核验记录。查看依据，决定下一步练什么。</p></div><button type="button" onClick={() => void load()} disabled={loading} aria-label="刷新学习画像" className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-[var(--border)] focus-visible:outline-2 focus-visible:outline-[var(--ring)]"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`} aria-hidden="true" /></button></header>
    {loading && !summary && <p role="status" className="py-10">正在读取学习观察…</p>}
    <Link href="/onboarding/assessment" className="inline-flex min-h-11 items-center text-sm text-[var(--primary)] underline underline-offset-4">查看初评与练习起点</Link>
    {error && <p role="alert" className="rounded-xl bg-[var(--muted)] p-4">画像暂时无法加载。<button className="ml-2 min-h-11 underline" onClick={() => void load()}>重新加载</button></p>}
    {summary && <>
      {!summary.has_independent_evidence && <section className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6"><BookOpen className="mb-3 h-6 w-6 text-[var(--primary)]" aria-hidden="true" /><h2 className="font-serif text-xl font-semibold">{summary.has_conversations ? "已有问答，独立作答还待观察" : "从一道新题开始"}</h2><p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">{summary.has_conversations ? "你已有问答记录，但目前还没有足够的独立作答证据。图片讨论和聊天次数不会自动转为能力判断。完成一道可核验的新题后，这里会展示新的学习观察。" : "带着当前题目开始学习，或完成一道可核验的新题。画像会随着你的作答逐步形成。"}</p><Link href="/math-tutor" className="mt-4 inline-flex min-h-11 items-center rounded-lg bg-[var(--primary)] px-4 text-sm font-medium text-[var(--primary-foreground)]">开始当前题目</Link></section>}
      <div className="flex items-center justify-between gap-3 text-sm"><h2 className="font-semibold">已有的学习观察</h2><p className="text-[var(--muted-foreground)]">本版本支持 {summary.coverage?.supported_skills || summary.skills.length} 个技能</p></div>
      <div className="grid gap-4 lg:grid-cols-2">{observed.map(skill => <SkillObservation key={skill.code} skill={skill} onEvidence={() => setSelected({title:skill.label, skillId:skill.code})} />)}</div>
      {!!unchecked.length && <details className="rounded-xl border border-[var(--border)] p-5"><summary className="cursor-pointer font-medium">尚未检查的技能 · {unchecked.length}</summary><ul className="mt-4 grid gap-3 text-sm text-[var(--muted-foreground)] sm:grid-cols-2">{unchecked.map(skill => <li key={skill.code}>{skill.label} · 尚未检查</li>)}</ul></details>}
    </>}
    {selected && <SkillEvidenceDrawer {...selected} onClose={() => setSelected(null)} onChanged={() => void load()} />}
  </div>;
}
