"use client";

import Link from "next/link";
import { ArrowDownToLine, ArrowUpRight, BookOpen, BrainCircuit, Check, FileText, FolderOpen, Image, Library, Lightbulb, Loader2, Plus, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ActiveOffer, AllowedAction, DiagnosisSummary, EvidenceSummary, MathTutorCommand, TeachingPlan } from "../types";
import { confirmMemory, fetchConversationResources, fetchMemories, importDocumentFile, nativePickAndImport, toggleMemoryRetrieval } from "../desktop/lib/desktop-api";
import { documentStatusLabel, memorySourceLabel, memoryTypeLabel } from "../desktop/lib/labels";
import type { DesktopDocument, DesktopMemory } from "../desktop/types";
import { memoryObjectText } from "../desktop/components/MemoryRow";
import { useToast } from "../desktop/components/ToastProvider";
import ActionBar from "./ActionBar";
import HintLadder from "./HintLadder";
import ImageAttachments from "./ImageAttachments";
import { DiagnosisNotice, EvidenceSummaryCard } from "./TeachingContext";

export type ToolView = "hints" | "documents" | "memory";

export function memoryAvailability(memory: DesktopMemory) {
  if (memory.source_type === "MODEL_INFERRED") return "待你确认";
  return memory.retrieval_enabled ? "允许用于辅导" : "已停用";
}

export function ToolMemoryCard({ memory, busy, onToggle, onConfirm }: { memory: DesktopMemory; busy: boolean; onToggle: () => void; onConfirm: () => void }) {
  const inferred = memory.source_type === "MODEL_INFERRED";
  const value = memoryObjectText(memory);
  return <li className="mt-tool-item">
    <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-xs font-medium text-[var(--muted-foreground)]">{memoryTypeLabel(memory.memory_type)}</span><span className="mt-tool-badge" data-tone={inferred ? "warning" : memory.retrieval_enabled ? "active" : undefined}>{memoryAvailability(memory)}</span></div>
    <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">{value ? (memory.predicate && !["内容", "偏好"].includes(memory.predicate) ? `${memory.predicate}：${value}` : value) : memory.predicate}</p>
    <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-3"><span className="text-xs text-[var(--muted-foreground)]">{memorySourceLabel(memory.source_type)}</span>{inferred ? <button type="button" disabled={busy} onClick={onConfirm} className="mt-btn mt-btn-sm"><Check className="h-3.5 w-3.5" aria-hidden="true" />确认这条记忆</button> : <label className="flex min-h-9 cursor-pointer items-center gap-2 text-xs"><input type="checkbox" className="h-4 w-4 accent-[var(--primary)]" disabled={busy} checked={memory.retrieval_enabled} onChange={onToggle} />允许用于辅导</label>}</div>
  </li>;
}

function PanelEmpty({ view }: { view: "documents" | "memory" }) {
  const Icon = view === "documents" ? BookOpen : BrainCircuit;
  return <div className="mt-tool-empty"><span className="mt-tool-empty-icon"><Icon className="h-6 w-6" aria-hidden="true" /></span><h3>{view === "documents" ? "把参考资料放在手边" : "从你的学习偏好开始"}</h3><p>{view === "documents" ? "添加讲义、课堂笔记或题目文档，让回答可以参考你的资料。" : "记下你喜欢的讲解方式与学习目标，相关内容会在后续辅导时供 Tutor 参考。"}</p>{view === "memory" ? <Link className="mt-btn mt-4" href="/math-tutor/memory"><Plus className="h-4 w-4" aria-hidden="true" />添加第一条记忆</Link> : null}</div>;
}

export default function TutorToolsPanel({ view, onClose, sessionId, level, plan, evidence, diagnosis, offer, allowed, actions, busy, disabled, onCommand }: { view: ToolView; onClose: (restoreFocus?: boolean) => void; sessionId: string; level: number; plan?: TeachingPlan | null; evidence?: EvidenceSummary | null; diagnosis?: DiagnosisSummary | null; offer?: ActiveOffer | null; allowed: string[]; actions?: AllowedAction[]; busy: boolean; disabled: boolean; onCommand: (command: MathTutorCommand, payload?: Record<string, string>) => void }) {
  const [documents, setDocuments] = useState<DesktopDocument[]>([]);
  const [images, setImages] = useState<Array<{ id: string; name: string; url: string }>>([]);
  const [messageCount, setMessageCount] = useState(0);
  const [error, setError] = useState("");
  const requestVersion = useRef(0);
  const [memories, setMemories] = useState<DesktopMemory[]>([]);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [mutating, setMutating] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const toast = useToast();
  const refresh = useCallback(async () => {
    if (view === "hints") { setLoading(false); return; }
    const version = ++requestVersion.current;
    setLoading(true); setError("");
    try {
      if (view === "documents") {
        const result = await fetchConversationResources(sessionId);
        if (version !== requestVersion.current) return;
        setDocuments(result.documents); setImages(result.images); setMessageCount(result.message_count);
      } else {
        const result = await fetchMemories();
        if (version === requestVersion.current) setMemories(result);
      }
    } catch { if (version === requestVersion.current) setError(view === "memory" ? "学习记忆暂时无法加载。" : "对话资料暂时无法加载。"); }
    finally { if (version === requestVersion.current) setLoading(false); }
  }, [view, sessionId]);
  useEffect(() => { if (!busy) void refresh(); return () => { requestVersion.current++; }; }, [refresh, busy]);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [view]);
  useEffect(() => {
    const protectFocus = (event: FocusEvent) => {
      const surface = panel.current;
      const target = event.target;
      if (!surface || !(target instanceof HTMLElement) || surface.contains(target) || getComputedStyle(surface).position !== "absolute") return;
      const focused = target.getBoundingClientRect();
      const bounds = surface.getBoundingClientRect();
      if (focused.width > 0 && focused.height > 0 && focused.left < bounds.right && focused.right > bounds.left && focused.top < bounds.bottom && focused.bottom > bounds.top) onClose(false);
    };
    document.addEventListener("focusin", protectFocus);
    return () => document.removeEventListener("focusin", protectFocus);
  }, [onClose]);
  useEffect(() => {
    const conversation = panel.current?.closest<HTMLElement>(".mt-conversation");
    const composer = conversation?.querySelector<HTMLElement>(".mt-composer");
    if (!conversation || !composer || typeof ResizeObserver === "undefined") return;
    const measure = () => conversation.style.setProperty("--tools-composer-height", `${Math.ceil(composer.getBoundingClientRect().height) + 8}px`);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(composer); observer.observe(conversation);
    return () => { observer.disconnect(); conversation.style.removeProperty("--tools-composer-height"); };
  }, []);
  const imported = async (document: DesktopDocument) => {
    const ready = ["ready", "ready_with_warnings"].includes(document.status);
    toast({ title: "资料已加入当前对话", description: ready ? `《${document.filename}》已就绪。` : `《${document.filename}》已导入，可在下方查看处理状态。` });
    await refresh();
  };
  const add = async () => {
    setImporting(true);
    try { const document = await nativePickAndImport(sessionId); if (document) await imported(document); }
    catch { fileInput.current?.click(); }
    finally { setImporting(false); }
  };
  const upload = async (file?: File) => {
    if (!file) return;
    setImporting(true);
    try { await imported(await importDocumentFile(file, sessionId)); }
    catch { toast({ title: "资料没有导入", description: "请检查文件类型、大小或文字内容后再试。", tone: "error" }); }
    finally { setImporting(false); }
  };
  const changeMemory = async (memory: DesktopMemory, confirm = false) => {
    setMutating(memory.memory_id);
    try {
      const updated = confirm ? await confirmMemory(memory.memory_id) : await toggleMemoryRetrieval(memory.memory_id, !memory.retrieval_enabled);
      setMemories(list => list.map(item => item.memory_id === updated.memory_id ? updated : item));
    } catch { toast({ title: "记忆设置未保存", description: "请稍后重试，原有设置已保留。", tone: "error" }); }
    finally { setMutating(null); }
  };
  const title = view === "hints" ? "教学提示" : view === "documents" ? "对话资料" : "学习记忆";
  const Icon = view === "hints" ? Lightbulb : view === "documents" ? FolderOpen : BrainCircuit;
  const eligibleMemories = memories.filter(memory => memory.retrieval_enabled && memory.source_type !== "MODEL_INFERRED").length;
  return <aside id="tutor-tools" ref={panel} aria-label={title} className="mt-tools-panel" onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); onClose(); } }}>
    <header className="mt-tools-heading"><div className="flex min-w-0 items-center gap-3"><span className="mt-tool-heading-icon"><Icon className="h-[18px] w-[18px]" aria-hidden="true" /></span><div><p className="text-[11px] leading-4 text-[var(--muted-foreground)]">学习工作台</p><h2 ref={heading} tabIndex={-1} className="text-[15px] font-semibold tracking-tight">{title}</h2></div></div><button type="button" onClick={() => onClose()} aria-label="关闭工具栏" className="mt-icon-button"><X className="h-[18px] w-[18px]" aria-hidden="true" /></button></header>
    <div className="mt-tools-body">
      {error ? <div role="alert" className="mt-tool-message text-[var(--destructive)]"><p>{error}</p><button type="button" onClick={() => void refresh()} className="mt-btn mt-btn-sm mt-2"><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />重新加载</button></div> : null}
      {view === "hints" ? <div className="space-y-4"><p className="mt-tools-intro">看清这一轮的目标，选择适合自己的帮助。</p><HintLadder level={level} plan={plan} /><DiagnosisNotice diagnosis={diagnosis} /><ActionBar offer={offer} actions={actions} allowed={allowed} busy={busy} disabled={disabled} onCommand={onCommand} /><EvidenceSummaryCard evidence={evidence} /></div> : null}
      {view === "documents" ? <div className="space-y-5">
        <div><p className="mt-tools-intro">当前对话的文档与图片，集中保存在这里。</p><button type="button" onClick={() => void add()} disabled={importing} className="mt-btn mt-btn-primary mt-4 min-h-11 w-full">{importing ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}{importing ? "正在导入…" : "添加学习资料"}</button><p className="mt-2 text-center text-[11px] leading-5 text-[var(--muted-foreground)]">PDF · Markdown · TXT · LaTeX</p><input ref={fileInput} type="file" className="hidden" accept=".txt,.md,.markdown,.tex,.pdf" onChange={event => { void upload(event.target.files?.[0]); event.target.value = ""; }} /></div>
        {loading ? <p role="status" className="mt-tool-loading"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在读取对话资料…</p> : !error ? <>
          <dl className="mt-tool-stats"><div><dt>文档</dt><dd>{documents.length}</dd></div><div><dt>图片</dt><dd>{images.length}</dd></div><div><dt>对话记录</dt><dd>{messageCount}</dd></div></dl>
          {documents.length ? <section aria-label="本对话文档"><h3 className="mt-tool-section-title"><FileText className="h-4 w-4" aria-hidden="true" />参考文档</h3><ul className="mt-3 space-y-3">{documents.map(doc => {
            const ready = ["ready", "ready_with_warnings"].includes(doc.status);
            return <li key={doc.document_id} className="mt-tool-item"><p className="break-words text-sm font-medium leading-6">{doc.filename}</p><div className="mt-2 flex flex-wrap items-center gap-2"><span className="mt-tool-badge" data-tone={ready && doc.retrieval_enabled ? "active" : ["failed", "needs_ocr"].includes(doc.status) ? "warning" : undefined}>{documentStatusLabel(doc.status)}</span><span className="text-xs text-[var(--muted-foreground)]">{ready ? `${doc.chunk_count} 个片段 · ${doc.retrieval_enabled ? "允许检索" : "检索已关闭"}` : "尚未参与检索"}</span></div>{doc.error || doc.parse_warning ? <p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">{doc.error || doc.parse_warning}</p> : null}</li>;
          })}</ul></section> : <PanelEmpty view="documents" />}
          {images.length ? <section aria-label="本对话图片"><h3 className="mt-tool-section-title"><Image className="h-4 w-4" aria-hidden="true" />已发送图片</h3><div className="mt-3"><ImageAttachments images={images} /></div><p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">图片由视觉模型读取，尚不支持自动文字检索。</p></section> : null}
          {messageCount > 0 || documents.length > 0 || images.length > 0 ? <a className="mt-btn min-h-11 w-full" href={`/api/v2/math-tutor/desktop/conversations/${encodeURIComponent(sessionId)}/export`} download><ArrowDownToLine className="h-4 w-4" aria-hidden="true" />导出完整资料夹</a> : null}
        </> : null}
        <Link href={`/math-tutor/knowledge?conversation=${encodeURIComponent(sessionId)}`} className="mt-tool-link"><Library className="h-4 w-4" aria-hidden="true" /><span>管理知识库与问答范围</span><ArrowUpRight className="ml-auto h-4 w-4 shrink-0" aria-hidden="true" /></Link><p className="text-xs leading-5 text-[var(--muted-foreground)]">在知识库中设置回答可参考的资料；添加文档不会自动开放其他对话的资料。</p>
      </div> : null}
      {view === "memory" ? <div className="space-y-5"><div className="mt-tool-message"><p className="text-sm font-medium">偏好与目标，让辅导更合拍</p><p className="mt-2 text-xs leading-5 text-[var(--muted-foreground)]">使用已配置模型辅导时，Tutor 可参考与当前问题相关的已启用记忆。AI 推测需要先由你确认。</p></div>{loading ? <p role="status" className="mt-tool-loading"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在读取学习记忆…</p> : !error ? <>{memories.length ? <><div className="flex items-center justify-between gap-2"><h3 className="mt-tool-section-title">已保存 {memories.length} 条</h3><span className="text-xs text-[var(--muted-foreground)]">{eligibleMemories} 条允许用于辅导</span></div><ul className="space-y-3">{memories.map(memory => <ToolMemoryCard key={memory.memory_id} memory={memory} busy={mutating !== null} onToggle={() => void changeMemory(memory)} onConfirm={() => void changeMemory(memory, true)} />)}</ul></> : <PanelEmpty view="memory" />}</> : null}<Link href="/math-tutor/memory" className="mt-tool-link"><BrainCircuit className="h-4 w-4" aria-hidden="true" /><span>添加、编辑与管理记忆</span><ArrowUpRight className="ml-auto h-4 w-4 shrink-0" aria-hidden="true" /></Link><p className="text-xs leading-5 text-[var(--muted-foreground)]">允许参考不代表本轮已使用，也不等同于知识掌握度。离线基础辅导暂不按文字偏好调整。</p></div> : null}
    </div>
  </aside>;
}
