"use client";

import { BookCheck, ChevronRight, Loader2, Play, RefreshCw, Search, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { makeSessionId, wrapLatexForDisplay } from "../../lib/protocol";
import type { BankPointDetail, LearnerSettings, LearnerStage, QuestionBank } from "../../lib/question-bank-types";
import { fetchBankPoint, fetchLearnerSettings, fetchQuestionBank, saveLearnerSettings } from "../lib/desktop-api";
import {
  buildDemoLaunch,
  buildPracticeLaunch,
  difficultyStars,
  filterBankTerms,
  STAGES,
  stageLabel,
  tutorLaunchHref,
  type TutorLaunch,
} from "../lib/question-bank";

type StageOption = { stage: LearnerStage; label: string; grades: number[] };

function stageOptions(learner: LearnerSettings | null): StageOption[] {
  return learner?.stages?.length ? learner.stages : STAGES;
}

/** First run: the learner has not chosen a stage yet. */
export function StageFirstRun({ stages = STAGES, saving = false, error = "", onPick }: { stages?: StageOption[]; saving?: boolean; error?: string; onPick: (stage: LearnerStage) => void }) {
  return <section aria-labelledby="bank-first-run" className="mt-card mt-paper p-6">
    <BookCheck className="mb-3 h-6 w-6 text-[var(--primary-text)]" aria-hidden="true" />
    <h2 id="bank-first-run" className="text-xl font-semibold tracking-tight">先选择你的学段</h2>
    <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">题库按人教版教材顺序整理。选好学段后，只显示这一学段的册目；之后可以在 设置 → 学段 中修改。</p>
    <ul className="mt-5 grid gap-3 sm:grid-cols-3">{stages.map(item => <li key={item.stage}>
      <button type="button" disabled={saving} aria-label={`选择学段：${item.label}`} onClick={() => onPick(item.stage)} className="mt-choice w-full justify-center font-semibold">{item.label}</button>
    </li>)}</ul>
    {saving ? <p role="status" className="mt-3 flex items-center gap-2 text-sm text-[var(--muted-foreground)]"><Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />正在保存学段…</p> : null}
    {error ? <p role="alert" className="mt-3 text-sm text-[var(--destructive)]">{error}</p> : null}
  </section>;
}

/** Temporary stage switcher — does not change the saved setting. */
export function StageSwitcher({ stages = STAGES, value, onChange }: { stages?: StageOption[]; value: LearnerStage | null; onChange: (stage: LearnerStage) => void }) {
  return <div role="group" aria-label="临时查看其他学段" className="inline-flex rounded-xl border border-[var(--border)] bg-[var(--muted)] p-1">
    {stages.map(item => <button key={item.stage} type="button" aria-pressed={value === item.stage} onClick={() => onChange(item.stage)}
      className={`min-h-9 rounded-lg px-4 text-sm ${value === item.stage ? "bg-[var(--card)] font-semibold text-[var(--primary-text)] shadow-sm" : "text-[var(--muted-foreground)] hover:text-[var(--foreground)]"}`}>{item.label}</button>)}
  </div>;
}

/** Terms (in `order`) → units → knowledge points with badges. */
export function QuestionBankTree({ bank, query = "", selected = null, openTerm = null, onSelect }: { bank: QuestionBank; query?: string; selected?: string | null; openTerm?: string | null; onSelect: (code: string) => void }) {
  const terms = filterBankTerms(bank.terms, query);
  const searching = query.trim() !== "";
  if (!terms.length) return <p className="py-8 text-sm text-[var(--muted-foreground)]">{searching ? "没有找到匹配的知识点。" : "这个学段暂时没有册目。"}</p>;
  return <ol aria-label="学期" className="space-y-3">{terms.map((term, index) => <li key={term.code}>
    <details open={searching || (openTerm ? openTerm === term.code : index === 0)} className="mt-card group">
      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-2 px-4 py-3">
        <ChevronRight className="h-4 w-4 shrink-0 text-[var(--muted-foreground)] transition-transform group-open:rotate-90" aria-hidden="true" />
        <span className="font-semibold">{term.label}</span>
        <span className="ml-auto truncate text-xs text-[var(--muted-foreground)]">{term.book}</span>
      </summary>
      <ol aria-label={`${term.label} 单元`} className="space-y-4 border-t border-[var(--border)] px-4 py-4">{term.units.map(unit => <li key={unit.code}>
        <h3 className="mt-section-title">{unit.title}</h3>
        <ul aria-label={`${unit.title} 知识点`} className="mt-2 space-y-1">{unit.points.map(point => {
          const empty = point.problem_count === 0 && point.demo_count === 0;
          return <li key={point.code}>
            <button type="button" aria-current={selected === point.code ? "true" : undefined} aria-label={`查看知识点：${point.title}`} onClick={() => onSelect(point.code)}
              className={`flex min-h-10 w-full flex-wrap items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm hover:bg-[var(--accent)] ${selected === point.code ? "bg-[var(--primary-soft)] text-[var(--primary-text)]" : ""}`}>
              <span className="min-w-0 flex-1">{point.title}</span>
              {point.problem_count > 0 ? <span className="mt-chip">{point.problem_count} 题</span> : null}
              {point.demo_count > 0 ? <span className="mt-chip">演示</span> : null}
              {empty ? <span className="text-xs text-[var(--muted-foreground)]">暂无可核验题目</span> : null}
            </button>
          </li>;
        })}</ul>
      </li>)}</ol>
    </details>
  </li>)}</ol>;
}

/** Selected knowledge point: verified problems, demos, or the honest note. */
export function PointDetail({ detail, busy = false, onLaunch }: { detail: BankPointDetail; busy?: boolean; onLaunch: (launch: TutorLaunch) => void }) {
  const { point, problems, demos, note } = detail;
  return <section aria-labelledby="bank-point-title" className="mt-card p-5">
    <p className="text-xs text-[var(--muted-foreground)]">{point.term} · {point.unit}</p>
    <h2 id="bank-point-title" className="mt-1 text-lg font-semibold tracking-tight">{point.title}</h2>
    {problems.length ? <>
      <h3 className="mt-section-title mt-5">练习题</h3>
      <ol aria-label="练习题" className="mt-2 space-y-3">{problems.map((problem, index) => <li key={problem.id} className="rounded-xl border border-[var(--border)] p-3">
        <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]">
          <span>第 {index + 1} 题</span>
          <span aria-label={`难度 ${problem.difficulty}`} className="text-[var(--warning,#b7791f)]">{difficultyStars(problem.difficulty)}</span>
        </div>
        <div className="overflow-x-auto py-1"><MarkdownRenderer content={wrapLatexForDisplay(problem.display_latex || problem.text)} enableMath /></div>
        <button type="button" disabled={busy} aria-label={`开始练习：${problem.text}`} onClick={() => onLaunch(buildPracticeLaunch(problem))} className="mt-btn mt-btn-primary mt-btn-sm"><Play className="h-4 w-4" aria-hidden="true" />开始练习</button>
      </li>)}</ol>
    </> : null}
    {demos.length ? <>
      <h3 className="mt-section-title mt-5">数形结合演示</h3>
      <ul aria-label="演示" className="mt-2 space-y-2">{demos.map(demo => <li key={demo.request} className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] p-3">
        <div className="min-w-0 flex-1"><p className="text-sm font-medium">{demo.title}</p><p className="text-xs text-[var(--muted-foreground)]">{demo.request}</p></div>
        <button type="button" disabled={busy} aria-label={`看演示：${demo.title}`} onClick={() => onLaunch(buildDemoLaunch(demo))} className="mt-btn mt-btn-sm"><Sparkles className="h-4 w-4" aria-hidden="true" />看演示</button>
      </li>)}</ul>
    </> : null}
    {!problems.length && !demos.length ? <p className="mt-4 rounded-xl bg-[var(--muted)] p-4 text-sm leading-6 text-[var(--muted-foreground)]">{note || "这个知识点暂无可核验题目，可以把题目发给 Tutor 讲解"}</p> : null}
  </section>;
}

export interface QuestionBankPanelProps {
  fetchLearnerFn?: typeof fetchLearnerSettings;
  saveLearnerFn?: typeof saveLearnerSettings;
  fetchBankFn?: typeof fetchQuestionBank;
  fetchPointFn?: typeof fetchBankPoint;
  /** Navigation hook for tests; defaults to router.push. */
  navigate?: (href: string) => void;
}

export default function QuestionBankPanel({
  fetchLearnerFn = fetchLearnerSettings,
  saveLearnerFn = saveLearnerSettings,
  fetchBankFn = fetchQuestionBank,
  fetchPointFn = fetchBankPoint,
  navigate,
}: QuestionBankPanelProps) {
  const router = useRouter();
  const [learner, setLearner] = useState<LearnerSettings | null>(null);
  const [view, setView] = useState<LearnerStage | null>(null);
  const [bank, setBank] = useState<QuestionBank | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [savingStage, setSavingStage] = useState(false);
  const [stageError, setStageError] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<BankPointDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [launching, setLaunching] = useState(false);

  const loadLearner = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const result = await fetchLearnerFn();
      setLearner(result); setView(result.stage);
      if (!result.stage) setLoading(false);
    } catch { setError("学段设置暂时无法读取，请重试。"); setLoading(false); }
  }, [fetchLearnerFn]);
  useEffect(() => { void loadLearner(); }, [loadLearner]);

  const loadBank = useCallback(async (stage: LearnerStage) => {
    setLoading(true); setError("");
    try { setBank(await fetchBankFn(stage)); } catch { setError("题库暂时无法加载，请重试。"); } finally { setLoading(false); }
  }, [fetchBankFn]);
  useEffect(() => { if (view) void loadBank(view); }, [view, loadBank]);

  const select = async (code: string) => {
    setSelected(code); setDetail(null); setDetailError(""); setDetailLoading(true);
    try { setDetail(await fetchPointFn(code)); } catch { setDetailError("这个知识点暂时无法打开，请重试。"); } finally { setDetailLoading(false); }
  };
  const pickStage = async (stage: LearnerStage) => {
    setSavingStage(true); setStageError("");
    try { const saved = await saveLearnerFn(stage, null); setLearner(saved); setView(saved.stage ?? stage); }
    catch { setStageError("学段没有保存，请重试。"); } finally { setSavingStage(false); }
  };
  const launch = (next: TutorLaunch) => {
    setLaunching(true);
    const href = tutorLaunchHref(next, makeSessionId());
    if (navigate) navigate(href); else router.push(href);
  };
  const changeView = (stage: LearnerStage) => { setView(stage); setSelected(null); setDetail(null); setQuery(""); };

  const stages = stageOptions(learner);
  const openTerm = bank && learner?.grade && view === learner.stage ? bank.terms.find(term => term.grade === learner.grade)?.code ?? null : null;
  const retry = () => { if (view) void loadBank(view); else void loadLearner(); };

  return <div className="mt-page">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="mt-eyebrow">按教材顺序练习</p>
        <h1 className="mt-2">题库</h1>
        <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">当前学段：<strong className="text-[var(--foreground)]">{stageLabel(learner?.stage)}</strong>{view && learner?.stage && view !== learner.stage ? `（正在临时查看${stageLabel(view)}）` : ""} · <Link href="/math-tutor/settings?section=stage" className="text-[var(--primary)]">在 设置 → 学段 中修改</Link></p>
      </div>
      {learner?.stage ? <div className="flex items-center gap-2"><StageSwitcher stages={stages} value={view} onChange={changeView} /><button type="button" aria-label="刷新题库" disabled={loading} onClick={retry} className="mt-btn mt-btn-icon"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`} aria-hidden="true" /></button></div> : null}
    </header>
    {error ? <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl bg-[var(--muted)] p-4"><span>{error}</span><button type="button" onClick={retry} className="mt-btn mt-btn-sm">重试</button></div> : null}
    {learner && !learner.stage && !view ? <StageFirstRun stages={stages} saving={savingStage} error={stageError} onPick={stage => void pickStage(stage)} /> : null}
    {loading && !bank && !error ? <p role="status" className="flex items-center gap-2 py-10 text-sm text-[var(--muted-foreground)]"><Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />正在加载题库…</p> : null}
    {bank && view ? <>
      {bank.source_note ? <p className="-mt-2 text-xs text-[var(--muted-foreground)]">{bank.source_note}</p> : null}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(320px,400px)] lg:items-start">
        <div className="min-w-0 space-y-4">
          <label className="relative block">
            <span className="sr-only">搜索知识点</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" aria-hidden="true" />
            <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索知识点" className="mt-input pl-9" />
          </label>
          <QuestionBankTree key={`${view}:${query.trim() ? "q" : ""}`} bank={bank} query={query} selected={selected} openTerm={openTerm} onSelect={code => void select(code)} />
        </div>
        <aside aria-label="知识点详情" className="min-w-0 lg:sticky lg:top-4">
          {detailLoading ? <p role="status" className="mt-card flex items-center gap-2 p-5 text-sm text-[var(--muted-foreground)]"><Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />正在准备已验证的题目…</p>
            : detailError ? <p role="alert" className="mt-card p-5 text-sm">{detailError}</p>
            : detail ? <PointDetail detail={detail} busy={launching} onLaunch={launch} />
            : <p className="mt-card mt-paper border-dashed p-5 text-sm leading-6 text-[var(--muted-foreground)]">选择一个知识点，查看已验证的练习题和演示。</p>}
        </aside>
      </div>
    </> : null}
  </div>;
}
