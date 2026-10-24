"use client";

import {useCallback, useEffect, useState} from "react";
import Link from "next/link";
import {useSearchParams} from "next/navigation";
import {ArrowRight, ArrowUpRight, BookOpen, RefreshCw, ScanLine} from "lucide-react";
import {fetchStudentSummary} from "../lib/desktop-api";
import type {StudentSummary, SkillSummary} from "../types";
import SkillEvidenceDrawer from "./SkillEvidenceDrawer";
import StageReviewPanel from "../../knowledge/StageReviewPanel";

export function SkillObservation({skill, onEvidence}: {skill: SkillSummary; onEvidence: () => void}) {
  return <article className="mt-card mt-observation-card p-5 sm:p-6">
    <p className="inline-flex items-center gap-1.5 rounded-md bg-[var(--primary-soft)] px-2 py-0.5 text-xs font-semibold text-[var(--primary-text)]">{skill.label}</p>
    <h3 className="mt-3 max-w-xl text-lg font-semibold leading-8 tracking-tight">{skill.observation || skill.evidence_status || "尚未检查"}</h3>
    <p className="mt-3 text-sm text-[var(--muted-foreground)]">{skill.evidence_count ? `依据 ${skill.evidence_count} 条作答记录。` : "完成相关的新题后，这里会展示学习观察。"}{skill.last_checked_at ? ` 最近检查：${new Date(skill.last_checked_at).toLocaleDateString("zh-CN")}。` : ""}</p>
    {(skill.evidence_count || 0) > 0 && <dl className="mt-evidence-breakdown">
      <div><dt>独立答对</dt><dd>{skill.counts?.independent?.correct ?? "待确认"}<span>{skill.counts?.independent ? " 次" : ""}</span></dd></div>
      <div><dt>受助答对</dt><dd>{skill.counts?.assisted?.correct ?? "待确认"}<span>{skill.counts?.assisted ? " 次" : ""}</span></dd></div>
      <div><dt>答案后答对</dt><dd>{skill.counts?.post_solution?.correct ?? "待确认"}<span>{skill.counts?.post_solution ? " 次" : ""}</span></dd></div>
    </dl>}
    <div className="mt-5 flex flex-wrap gap-3"><button type="button" onClick={onEvidence} className="mt-btn">查看依据</button><Link href={skill.next_href || "/math-tutor/offers"} className="mt-btn mt-btn-ghost text-[var(--primary-text)]">{skill.next_action || "查看推荐练习"}<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link></div>
    <details className="mt-3 text-sm text-[var(--muted-foreground)]"><summary className="cursor-pointer py-2">证据计数</summary><dl className="mt-2 grid grid-cols-2 gap-3">{Object.entries(skill.counts || {}).map(([key, value]) => <div key={key}><dt>{{independent:"独立作答", assisted:"受助作答", post_solution:"答案后作答", diagnostic:"诊断"}[key] || key}</dt><dd className="mt-1">答对 {value.correct} · 答错 {value.incorrect}</dd></div>)}</dl>{!!skill.joint_task_evidence && <p className="mt-2">另有 {skill.joint_task_evidence} 条联合题证据，需结合整题查看。</p>}</details>
  </article>;
}

export function LearningOverview({summary}: {summary: StudentSummary}) {
  const observed = summary.skills.filter(skill => (skill.evidence_count || 0) > 0).length;
  const supported = summary.coverage?.supported_skills ?? summary.skills.length;
  return <section className="mt-learning-overview" aria-labelledby="learning-overview-title">
    <div className="mt-learning-focus"><span className="mt-knowledge-icon"><ScanLine className="h-5 w-5" aria-hidden="true" /></span><div>
      <p className="mt-eyebrow">下一步学习</p><h2 id="learning-overview-title">{summary.has_independent_evidence ? "换一道新题，看看能否独立完成" : "先留下一次独立作答"}</h2>
      <p>{summary.has_independent_evidence ? "结合下方观察选择练习，用不同题目继续验证；一次答对还不足以说明长期掌握。" : "先写出自己的思路，需要时再看提示。系统会分别记录独立、提示后和答案后的表现。"}</p>
      <Link href={summary.has_independent_evidence ? "/math-tutor/offers" : "/math-tutor"} className="mt-btn mt-btn-primary mt-4">{summary.has_independent_evidence ? "查看推荐练习" : "开始一道题"}<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
    </div></div>
    <div className="mt-learning-coverage"><p className="text-sm font-medium">已观察的技能</p><p className="mt-learning-coverage-value">{observed}<span> / {supported}</span></p><p>表示作答记录的覆盖范围，不是掌握比例。</p><Link href="/onboarding/assessment" className="mt-learning-start-link">查看初评与练习起点<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link></div>
  </section>;
}

export function ItemErrorObservations({summary, onEvidence}: {
  summary: StudentSummary;
  onEvidence: (cycleId: string) => void;
}) {
  const observations = summary.item_error_observations || [];
  if (!observations.length) return null;
  return <section className="mt-card p-5 sm:p-6" aria-labelledby="item-error-observations-title">
    <h2 id="item-error-observations-title" className="mt-section-title">整题错误观察</h2>
    <p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">这些作答涉及多个技能，具体技能待定位。记录中的错误线索用于复盘，不代表相关技能都存在问题。</p>
    <details className="mt-4">
      <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium">查看 {observations.length} 条整题观察</summary>
      <ul className="mt-2 divide-y divide-[var(--border)]">
        {observations.map(observation => <li key={`${observation.event_id}:${observation.rule_id}`} className="py-4">
          <div className="flex flex-col items-start justify-between gap-3 sm:flex-row">
            <div className="min-w-0 flex-1"><h3 className="break-words font-medium">{observation.label}</h3>
              <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{observation.status === "corrected_later" ? "该题后来答对，技能仍待独立检验。" : "具体技能待定位，请结合整题作答查看。"}</p>
            </div>
            <button type="button" className="mt-btn min-h-11 shrink-0" onClick={() => onEvidence(observation.cycle_id)} aria-label={`查看${observation.label}的整题记录`}>查看本题记录</button>
          </div>
        </li>)}
      </ul>
    </details>
  </section>;
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
    <header className="flex items-start justify-between gap-5"><div><p className="mt-eyebrow">从作答中了解自己</p><h1 className="mt-2">学习画像</h1><p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">看清已经完成的作答、用过的帮助，以及下一道值得尝试的题。每条观察都可以追溯到具体记录。</p></div><button type="button" onClick={() => void load()} disabled={loading} aria-label="刷新学习画像" className="mt-btn mt-btn-icon shrink-0"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`} aria-hidden="true" /></button></header>
    {loading && !summary && <p role="status" className="py-10">正在读取学习观察…</p>}
    {error && <p role="alert" className="rounded-xl bg-[var(--muted)] p-4">画像暂时无法加载。<button className="ml-2 min-h-11 underline" onClick={() => void load()}>重新加载</button></p>}
    {summary && <>
      <LearningOverview summary={summary} />
      <section aria-labelledby="learning-observations-title"><div className="mb-4 flex flex-wrap items-center justify-between gap-3 text-sm"><h2 id="learning-observations-title" className="mt-section-title">已有的学习观察</h2><p className="text-[var(--muted-foreground)]">独立与受助表现分开记录</p></div>
      {observed.length ? <div className="grid gap-4 lg:grid-cols-2">{observed.map(skill => <SkillObservation key={skill.code} skill={skill} onEvidence={() => setSelected({title:skill.label, skillId:skill.code})} />)}</div> : <div className="mt-profile-empty"><BookOpen className="h-5 w-5 shrink-0 text-[var(--primary-text)]" aria-hidden="true" /><p>{summary.has_conversations ? "已有问答，作答证据还待积累。聊天次数、上传资料和说“懂了”不会自动形成学习观察。" : "还没有可展示的作答记录。完成可核验的题目后，这里会显示观察和下一步建议。"}</p></div>}</section>
      <ItemErrorObservations summary={summary} onEvidence={cycleId => setSelected({title:"整题错误观察", cycleId})} />
      {!!unchecked.length && <details className="mt-card p-5"><summary className="cursor-pointer font-medium">尚未检查的技能 · {unchecked.length}</summary><ul className="mt-4 grid gap-3 text-sm text-[var(--muted-foreground)] sm:grid-cols-2">{unchecked.map(skill => <li key={skill.code}>{skill.label} · 尚未检查</li>)}</ul></details>}
    </>}
    <StageReviewPanel />
    {selected && <SkillEvidenceDrawer {...selected} onClose={() => setSelected(null)} onChanged={() => void load()} />}
  </div>;
}
