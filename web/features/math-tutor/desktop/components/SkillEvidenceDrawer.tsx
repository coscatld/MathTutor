"use client";

import {useCallback, useEffect, useRef, useState} from "react";
import Link from "next/link";
import {X} from "lucide-react";
import {excludeLearningEvidence, fetchLearningEvidence} from "../lib/desktop-api";
import type {LearningEvidence} from "../types";

const RESULTS: Record<string,string> = {correct:"答对", incorrect:"答错", partial:"部分完成", unknown:"暂无法核验"};
const KINDS: Record<string,string> = {independent:"独立作答", assisted:"受助作答", post_solution:"看过答案后的作答", unknown:"帮助来源待确认"};
const button = "min-h-11 rounded-lg px-3 text-sm font-medium focus-visible:outline-2 focus-visible:outline-[var(--ring)] disabled:opacity-50";

export default function SkillEvidenceDrawer({title, skillId, cycleId, onClose, onChanged}: {
  title: string; skillId?: string; cycleId?: string; onClose: () => void; onChanged: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [rows, setRows] = useState<LearningEvidence[]>([]);
  const [cursor, setCursor] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async (next?: number) => {
    setLoading(true); setError("");
    try {
      const page = await fetchLearningEvidence({skill_id: skillId, cycle_id: cycleId, cursor: next});
      setRows(previous => next ? [...previous, ...page.items] : page.items); setCursor(page.next_cursor);
    } catch { setError("学习记录暂时无法加载，请重试。"); }
    finally { setLoading(false); }
  }, [skillId, cycleId]);
  useEffect(() => { dialog.current?.showModal(); void load(); }, [load]);
  const exclude = async (id: string) => {
    setBusy(id); setError("");
    try { await excludeLearningEvidence(id); setConfirm(null); await load(); onChanged(); }
    catch { setError("这条记录暂时无法排除，请重试。"); }
    finally { setBusy(null); }
  };
  return <dialog ref={dialog} onClose={onClose} aria-labelledby="evidence-title"
    className="m-auto max-h-[85vh] w-[min(42rem,calc(100%-2rem))] overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 text-[var(--foreground)] shadow-xl backdrop:bg-black/40">
    <header className="mb-5 flex items-center justify-between gap-4"><div><p className="text-xs text-[var(--muted-foreground)]">学习依据</p><h2 id="evidence-title" className="mt-1 font-serif text-xl font-bold">{title}</h2></div><button className={button} aria-label="关闭学习依据" onClick={() => dialog.current?.close()}><X className="h-5 w-5" aria-hidden="true" /></button></header>
    {error && <p role="alert">{error}<button className={button} onClick={() => void load()}>重试</button></p>}
    {!rows.length && !loading && !error && <p className="py-8 text-[var(--muted-foreground)]">尚无可展示的作答记录。</p>}
    <ol className="divide-y divide-[var(--border)]">{rows.map(row => <li key={row.event_id} className="py-5">
      <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--muted-foreground)]"><time>{new Date(row.occurred_at).toLocaleString("zh-CN")}</time><span>{row.excluded ? "已排除判定" : KINDS[row.evidence_kind] || "待确认"}</span></div>
      <p className="mt-2 whitespace-pre-wrap break-words font-medium">{row.problem_text}</p>
      {row.student_response && <p className="mt-2 whitespace-pre-wrap break-words text-sm">你的作答：{row.student_response}</p>}
      <p className="mt-2 text-sm">核验：{RESULTS[row.correctness || "unknown"] || "待确认"}{row.completion_scope !== "full_problem" ? "（步骤记录）" : ""}</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">{row.session_id ? <Link className={`${button} inline-flex items-center text-[var(--primary)]`} href={`/math-tutor?session=${encodeURIComponent(row.session_id)}`}>回到原题</Link> : <span className="text-xs text-[var(--muted-foreground)]">原会话不可打开</span>}
      {!row.excluded && <button className={button} disabled={busy !== null} onClick={() => setConfirm(row.event_id)}>这条记录有问题</button>}</div>
      {row.excluded && <p className="mt-2 text-xs text-[var(--muted-foreground)]">此判定不再用于画像或训练；曾经作答的顺序保留。</p>}
      {confirm === row.event_id && <div className="mt-3 rounded-xl bg-[var(--muted)] p-3"><p className="text-sm leading-6">排除这次判定后，画像会重新计算。同题再答不会因此变成首次作答。</p><div className="mt-2 flex gap-2"><button className={`${button} text-red-700 dark:text-red-300`} disabled={busy !== null} onClick={() => void exclude(row.event_id)}>{busy ? "正在排除…" : "排除这次判定"}</button><button className={button} disabled={busy !== null} onClick={() => setConfirm(null)}>取消</button></div></div>}
    </li>)}</ol>
    {loading && <p role="status" className="py-4 text-sm">正在加载学习记录…</p>}
    {cursor && <button className={button} disabled={loading} onClick={() => void load(cursor)}>查看更多</button>}
  </dialog>;
}
