"use client";

import { BookOpen, BrainCircuit, FilePlus2, FolderOpen, Loader2, Lightbulb, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ActiveOffer, AllowedAction, DiagnosisSummary, EvidenceSummary, MathTutorCommand, TeachingPlan } from "../types";
import { fetchDocuments, fetchMemories, importDocumentFile, nativePickAndImport } from "../desktop/lib/desktop-api";
import type { DesktopDocument, DesktopMemory } from "../desktop/types";
import { useToast } from "../desktop/components/ToastProvider";
import ActionBar from "./ActionBar";
import HintLadder from "./HintLadder";
import { DiagnosisNotice, EvidenceSummaryCard } from "./TeachingContext";

export type ToolView = "hints" | "documents" | "memory";
export default function TutorToolsPanel({ view, onClose, sessionId, level, plan, evidence, diagnosis, offer, allowed, actions, busy, disabled, onCommand }: { view: ToolView; onClose: () => void; sessionId: string; level: number; plan?: TeachingPlan | null; evidence?: EvidenceSummary | null; diagnosis?: DiagnosisSummary | null; offer?: ActiveOffer | null; allowed: string[]; actions?: AllowedAction[]; busy: boolean; disabled: boolean; onCommand: (command: MathTutorCommand, payload?: Record<string, string>) => void }) {
  const [documents, setDocuments] = useState<DesktopDocument[]>([]);
  const [memories, setMemories] = useState<DesktopMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      if (view === "documents") setDocuments(await fetchDocuments(sessionId));
      if (view === "memory") setMemories(await fetchMemories());
    } finally { setLoading(false); }
  }, [view, sessionId]);
  useEffect(() => { void refresh(); }, [refresh]);
  const add = async () => {
    try {
      const document = await nativePickAndImport(sessionId);
      if (document) { toast({ title: "资料已加入当前对话", description: `Tutor 可以从《${document.filename}》中检索内容。` }); await refresh(); }
    } catch { fileInput.current?.click(); }
  };
  const upload = async (file?: File) => {
    if (!file) return;
    try { const doc = await importDocumentFile(file, sessionId); toast({ title: "资料已加入当前对话", description: `《${doc.filename}》已经可以在本对话中使用。` }); await refresh(); }
    catch { toast({ title: "资料没有导入", description: "请检查文件类型、大小或文字内容后再试。", tone: "error" }); }
  };
  const title = view === "hints" ? "Tutor 支持" : view === "documents" ? "本对话资料" : "学习记忆";
  return <aside className="flex w-[320px] shrink-0 flex-col border-l border-[#e1dfd8] bg-[#f2f1ec] dark:border-slate-800 dark:bg-[#171c20]">
    <div className="flex h-16 items-center justify-between border-b border-[#e1dfd8] px-4 dark:border-slate-800"><div className="flex items-center gap-2">{view === "hints" ? <Lightbulb className="h-4 w-4 text-amber-600" /> : view === "documents" ? <FolderOpen className="h-4 w-4 text-blue-600" /> : <BrainCircuit className="h-4 w-4 text-violet-600" />}<h2 className="font-serif text-sm font-bold">{title}</h2></div><button type="button" onClick={onClose} aria-label="关闭工具栏" className="rounded-lg p-2 text-slate-500 hover:bg-white dark:hover:bg-slate-800"><X className="h-4 w-4" /></button></div>
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      {view === "hints" ? <div className="space-y-3"><HintLadder level={level} plan={plan} /><DiagnosisNotice diagnosis={diagnosis} /><ActionBar offer={offer} actions={actions} allowed={allowed} busy={busy} disabled={disabled} onCommand={onCommand} /><EvidenceSummaryCard evidence={evidence} /></div> : null}
      {view === "documents" ? <div className="space-y-3"><button type="button" onClick={add} className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-[#1d5fd1] text-sm font-semibold text-white hover:bg-[#174fab]"><FilePlus2 className="h-4 w-4" />添加资料</button><input ref={fileInput} type="file" className="hidden" accept=".txt,.md,.markdown,.tex,.pdf" onChange={(event) => void upload(event.target.files?.[0])} />{loading ? <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-slate-400" /> : documents.length ? documents.map((doc) => <div key={doc.document_id} className="rounded-xl border border-[#deddd7] bg-white p-3 dark:border-slate-700 dark:bg-slate-900"><p className="truncate text-sm font-medium">{doc.filename}</p><p className="mt-1 text-xs text-slate-500">{doc.status === "ready" ? `${doc.chunk_count} 个检索片段` : doc.error || "正在处理"}</p></div>) : <div className="py-8 text-center"><BookOpen className="mx-auto h-7 w-7 text-slate-300" /><p className="mt-2 text-sm text-slate-500">此对话尚未添加资料</p><p className="mt-1 text-xs leading-5 text-slate-400">资料只在当前对话内参与检索。</p></div>}</div> : null}
      {view === "memory" ? loading ? <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-slate-400" /> : memories.length ? <div className="space-y-2">{memories.slice(0, 12).map((item) => <div key={item.memory_id} className="rounded-xl border border-[#deddd7] bg-white p-3 text-sm dark:border-slate-700 dark:bg-slate-900"><p className="font-medium">{item.subject}</p><p className="mt-1 text-xs leading-5 text-slate-500">{item.predicate}</p></div>)}</div> : <p className="py-8 text-center text-sm text-slate-500">还没有可用的学习记忆。</p> : null}
    </div>
  </aside>;
}
