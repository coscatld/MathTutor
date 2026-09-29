"use client";

import { BookOpen, BrainCircuit, FilePlus2, FolderOpen, Loader2, Lightbulb, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ActiveOffer, AllowedAction, DiagnosisSummary, EvidenceSummary, MathTutorCommand, TeachingPlan } from "../types";
import { fetchConversationResources, fetchMemories, importDocumentFile, nativePickAndImport } from "../desktop/lib/desktop-api";
import type { DesktopDocument, DesktopMemory } from "../desktop/types";
import { useToast } from "../desktop/components/ToastProvider";
import ActionBar from "./ActionBar";
import HintLadder from "./HintLadder";
import ImageAttachments from "./ImageAttachments";
import { DiagnosisNotice, EvidenceSummaryCard } from "./TeachingContext";

export type ToolView = "hints" | "documents" | "memory";
export default function TutorToolsPanel({ view, onClose, sessionId, level, plan, evidence, diagnosis, offer, allowed, actions, busy, disabled, onCommand }: { view: ToolView; onClose: () => void; sessionId: string; level: number; plan?: TeachingPlan | null; evidence?: EvidenceSummary | null; diagnosis?: DiagnosisSummary | null; offer?: ActiveOffer | null; allowed: string[]; actions?: AllowedAction[]; busy: boolean; disabled: boolean; onCommand: (command: MathTutorCommand, payload?: Record<string, string>) => void }) {
  const [documents, setDocuments] = useState<DesktopDocument[]>([]);
  const [images, setImages] = useState<Array<{ id: string; name: string; url: string }>>([]);
  const [messageCount, setMessageCount] = useState(0);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);
  const [memories, setMemories] = useState<DesktopMemory[]>([]);
  const [loading, setLoading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const toast = useToast();
  const refresh = useCallback(async () => {
    const version = ++requestVersion.current;
    setLoading(true);
    setError("");
    try {
      if (view === "documents") {
        const result = await fetchConversationResources(sessionId);
        if (version !== requestVersion.current) return;
        setDocuments(result.documents); setImages(result.images); setMessageCount(result.message_count);
      }
      if (view === "memory") {
        const result = await fetchMemories();
        if (version === requestVersion.current) setMemories(result);
      }
    } catch { if (version === requestVersion.current) setError("资料暂时无法加载，请重试。"); }
    finally { if (version === requestVersion.current) setLoading(false); }
  }, [view, sessionId]);
  useEffect(() => { if (!busy) void refresh(); return () => { requestVersion.current++; }; }, [refresh, busy]);
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
  return <aside aria-label={title} className="mt-tools-panel" onKeyDown={event => { if (event.key === "Escape") onClose(); }}>
    <div className="flex h-16 items-center justify-between border-b border-[var(--border)] px-4"><div className="flex items-center gap-2">{view === "hints" ? <Lightbulb className="h-4 w-4 text-amber-600" /> : view === "documents" ? <FolderOpen className="h-4 w-4 text-[var(--primary-text)]" /> : <BrainCircuit className="h-4 w-4 text-[var(--primary-text)]" />}<h2 className="font-serif text-sm font-bold">{title}</h2></div><button type="button" onClick={onClose} aria-label="关闭工具栏" className="rounded-lg p-2 text-[var(--muted-foreground)] hover:bg-[var(--accent)]"><X className="h-4 w-4" /></button></div>
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      {error ? <div role="alert" className="mb-3 text-sm text-red-600">{error}<button type="button" onClick={() => void refresh()} className="ml-2 underline">重试</button></div> : null}
      {view === "documents" && !loading && !error ? <div className="mb-3 space-y-2 text-xs text-[var(--muted-foreground)]"><p>本对话已保存 {messageCount} 条记录 · {documents.length} 份文档 · {images.length} 张图片</p>{messageCount > 0 || documents.length > 0 ? <a className="inline-block rounded-lg border border-[var(--border)] px-3 py-2 font-medium text-[var(--primary-text)] focus-visible:ring-2" href={`/api/v2/math-tutor/desktop/conversations/${encodeURIComponent(sessionId)}/export`} download>导出完整资料夹</a> : null}<p>文档参与本对话检索；已发送图片保存在本机，通过视觉模型读取，不会自动 OCR。</p>{images.length ? <section aria-label="本对话图片"><h3 className="mt-3 font-semibold">已发送图片</h3><ImageAttachments images={images} /></section> : null}</div> : null}
      {view === "hints" ? <div className="space-y-3"><HintLadder level={level} plan={plan} /><DiagnosisNotice diagnosis={diagnosis} /><ActionBar offer={offer} actions={actions} allowed={allowed} busy={busy} disabled={disabled} onCommand={onCommand} /><EvidenceSummaryCard evidence={evidence} /></div> : null}
      {view === "documents" ? <div className="space-y-3"><button type="button" onClick={add} className="flex h-10 w-full items-center justify-center gap-2 rounded-xl bg-[var(--primary)] text-sm font-semibold text-white hover:bg-[var(--primary-hover)]"><FilePlus2 className="h-4 w-4" />添加资料</button><input ref={fileInput} type="file" className="hidden" accept=".txt,.md,.markdown,.tex,.pdf" onChange={(event) => void upload(event.target.files?.[0])} />{loading ? <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-[var(--muted-foreground)]" /> : documents.length ? documents.map((doc) => <div key={doc.document_id} className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3"><p className="truncate text-sm font-medium">{doc.filename}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">{(doc.status === "ready" || doc.status === "ready_with_warnings") ? `${doc.chunk_count} 个检索片段 · ${doc.retrieval_enabled ? "参与检索" : "检索已关闭"}` : doc.error || doc.parse_warning || "正在处理"}</p></div>) : <div className="py-8 text-center"><BookOpen className="mx-auto h-7 w-7 text-[var(--muted-foreground)]" /><p className="mt-2 text-sm text-[var(--muted-foreground)]">此对话尚未添加文档</p><p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">资料只在当前对话内参与检索。</p></div>}</div> : null}
      {view === "memory" ? loading ? <Loader2 className="mx-auto mt-8 h-5 w-5 animate-spin text-[var(--muted-foreground)]" /> : memories.length ? <div className="space-y-2">{memories.slice(0, 12).map((item) => <div key={item.memory_id} className="rounded-xl border border-[var(--border)] bg-[var(--card)] p-3 text-sm"><p className="font-medium">{item.subject}</p><p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">{item.predicate}</p></div>)}</div> : <p className="py-8 text-center text-sm text-[var(--muted-foreground)]">还没有可用的学习记忆。</p> : null}
    </div>
  </aside>;
}
