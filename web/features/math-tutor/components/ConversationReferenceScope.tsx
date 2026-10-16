"use client";

import { Check, ChevronRight, Library as LibraryIcon, Loader2, RefreshCw, Settings2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { knowledgeApi, mountConfiguration, type Library, type Mount, type ScopeDocument } from "../knowledge/api";
import { BEFORE_TUTOR_NAVIGATION, requestTutorNavigation } from "../lib/navigation-guard";

const configurationKey = (value: Mount) => JSON.stringify(mountConfiguration(value));
// Route changes keep only configuration IDs in this tab's memory; no document
// contents, titles, storage, or credentials are cached. A refresh clears it.
const scopeDrafts = new Map<string, Mount>();
export const scopeOriginLabel = (origin?: ScopeDocument["origin"]) => ({conversation: "当前对话", global: "总资料", library: "知识库"})[origin || "library"];

/** Removing a library must not leave hidden IDs in a strict document whitelist. */
export function selectScopeLibraries(current: Mount, spaceIds: string[]): Mount {
  const candidates = current.available_documents || [];
  const retained = new Set(candidates.filter(doc => doc.origin !== "library" || doc.space_ids?.some(id => spaceIds.includes(id))).map(doc => doc.document_id));
  return {...current, space_ids: spaceIds, document_ids: current.document_ids.filter(id => retained.has(id))};
}

export function useConversationReferenceScope(sessionId: string) {
  const [draft, setDraft] = useState<Mount | null>(null);
  const [saved, setSaved] = useState<Mount | null>(null);
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const [previewRevision, setPreviewRevision] = useState(0);
  const sequence = useRef(0);
  const loadSequence = useRef(0);
  const savingRef = useRef(false);
  const draftRef = useRef(draft);
  const savedRef = useRef(saved);
  draftRef.current = draft; savedRef.current = saved;
  const dirty = draft !== null && saved !== null && configurationKey(draft) !== configurationKey(saved);
  const draftKey = draft ? configurationKey(draft) : "";
  const savedKey = saved ? configurationKey(saved) : "";

  const refresh = useCallback(async () => {
    const request = ++loadSequence.current;
    ++sequence.current;
    setError(""); setPreviewError(""); setNotice("");
    if (!savedRef.current) setStatus("loading");
    try {
      const [libs, scope] = await Promise.all([knowledgeApi<Library[]>("/libraries"), knowledgeApi<Mount>(`/conversations/${encodeURIComponent(sessionId)}`)]);
      if (request !== loadSequence.current) return;
      mountConfiguration(scope);
      setLibraries(libs); setSaved(scope); setUnconfirmed(false); setStatus("ready");
      const previous = draftRef.current || scopeDrafts.get(sessionId);
      const previousSaved = savedRef.current;
      if (!previous || (previousSaved && configurationKey(previous) === configurationKey(previousSaved)) || configurationKey(previous) === configurationKey(scope)) {
        setDraft(scope); setPreviewing(false);
      } else {
        setDraft({...previous, available_documents: scope.available_documents, effective_document_ids: scope.effective_document_ids});
        setPreviewing(true); setPreviewRevision(revision => revision + 1);
      }
    } catch (cause) {
      if (request !== loadSequence.current) return;
      setError(cause instanceof Error ? cause.message : "回答参考范围暂时无法读取。");
      if (!savedRef.current) setStatus("failed");
      setPreviewing(false);
    }
  }, [sessionId]);

  useEffect(() => { void refresh(); return () => { loadSequence.current++; sequence.current++; }; }, [refresh]);
  useEffect(() => {
    const changed = (event: Event) => {
      const target = (event as CustomEvent<{sessionId?: string}>).detail?.sessionId;
      if (!savingRef.current && (!target || target === sessionId)) void refresh();
    };
    window.addEventListener("mathtutor-reference-scope-changed", changed);
    return () => window.removeEventListener("mathtutor-reference-scope-changed", changed);
  }, [refresh, sessionId]);
  useEffect(() => {
    if (!draft || status !== "ready" || draftKey === savedKey) { setPreviewing(false); return; }
    const request = ++sequence.current;
    let live = true;
    setPreviewing(true); setPreviewError("");
    const timer = window.setTimeout(() => {
      void knowledgeApi<Mount>(`/conversations/${encodeURIComponent(sessionId)}/preview`, mountConfiguration(draft)).then(scope => {
        mountConfiguration(scope);
        if (live && request === sequence.current) setDraft(current => current && configurationKey(current) === draftKey ? {...current, available_documents: scope.available_documents, effective_document_ids: scope.effective_document_ids} : current);
      }).catch(cause => { if (live && request === sequence.current) setPreviewError(cause instanceof Error ? cause.message : "无法预览这些资料，请重试。"); })
        .finally(() => { if (live && request === sequence.current) setPreviewing(false); });
    }, 120);
    return () => { live = false; window.clearTimeout(timer); };
  // Metadata updates do not request another preview of the same configuration.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, draftKey, savedKey, status, previewRevision]);

  useEffect(() => {
    if (!draft || !saved) return;
    if (dirty) {
      scopeDrafts.set(sessionId, mountConfiguration(draft));
    } else scopeDrafts.delete(sessionId);
  }, [sessionId, draftKey, savedKey, dirty, draft, saved]);

  useEffect(() => {
    if (!dirty && !saving && !unconfirmed) return;
    const unload = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    const guard = (event: Event) => {
      if (!window.confirm(saving || unconfirmed ? "资料范围正在保存或等待确认，确认离开？" : "对话资料的参考范围尚未应用，确认暂时离开？草案会在本次使用中保留。")) event.preventDefault();
    };
    const navigate = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!target || target.download || target.target === "_blank") return;
      const next = new URL(target.href, window.location.href);
      if (next.origin === window.location.origin && next.pathname === window.location.pathname && next.search === window.location.search) return;
      if (!requestTutorNavigation()) { event.preventDefault(); event.stopPropagation(); }
    };
    window.addEventListener("beforeunload", unload);
    window.addEventListener(BEFORE_TUTOR_NAVIGATION, guard);
    document.addEventListener("click", navigate, true);
    return () => { window.removeEventListener("beforeunload", unload); window.removeEventListener(BEFORE_TUTOR_NAVIGATION, guard); document.removeEventListener("click", navigate, true); };
  }, [dirty, saving, unconfirmed]);

  const edit = (value: Mount) => {
    if (savingRef.current || unconfirmed || status !== "ready") return;
    ++sequence.current; ++loadSequence.current;
    setDraft(configurationKey(value) === savedKey && saved ? saved : value); setError(""); setPreviewError(""); setNotice(""); setPreviewing(configurationKey(value) !== savedKey);
  };
  const save = async () => {
    if (!draft || status !== "ready" || savingRef.current || unconfirmed || previewing || previewError || error) return;
    const payload = mountConfiguration(draft);
    savingRef.current = true; setSaving(true); setError(""); setNotice("");
    let submitted = false;
    try {
      await knowledgeApi(`/conversations/${encodeURIComponent(sessionId)}`, payload, "PUT");
      submitted = true;
      const confirmed = await knowledgeApi<Mount>(`/conversations/${encodeURIComponent(sessionId)}`);
      if (configurationKey(confirmed) !== configurationKey(payload)) throw new Error("保存后读取的范围与提交内容不一致。");
      setSaved(confirmed); setDraft(confirmed); setUnconfirmed(false); setNotice("已应用，下一条消息将使用这个资料范围。");
      window.dispatchEvent(new Event("mathtutor-conversations-changed"));
      window.dispatchEvent(new CustomEvent("mathtutor-reference-scope-changed", {detail: {sessionId}}));
    } catch (cause) {
      setUnconfirmed(submitted);
      setError(submitted ? "设置已提交，但尚未确认当前范围。请重新读取后再继续对话。" : cause instanceof Error ? cause.message : "资料范围未保存，请重试。原有范围继续生效。");
    } finally { savingRef.current = false; setSaving(false); }
  };
  return {sessionId, draft, saved, libraries, status, previewing, previewError, error, saving, unconfirmed, notice, dirty, blocking: saving || unconfirmed, edit, save, refresh};
}

export type ConversationScopeController = ReturnType<typeof useConversationReferenceScope>;

export default function ConversationReferenceScope({controller, busy}: {controller: ConversationScopeController; busy: boolean}) {
  const {draft, saved, libraries, status, previewing, previewError, error, saving, unconfirmed, notice, dirty, edit, save, refresh} = controller;
  const disabled = busy || saving || unconfirmed || status !== "ready";
  const eligible = libraries.filter(lib => lib.enabled && (lib.kind !== "session" || lib.conversation_id === controller.sessionId));
  const displayedLibraries = libraries.filter(lib => (lib.enabled || draft?.space_ids.includes(lib.space_id)) && (lib.kind !== "session" || lib.conversation_id === controller.sessionId));
  const unavailableLibraries = (draft?.space_ids || []).filter(id => !displayedLibraries.some(lib => lib.space_id === id));
  const documents = draft?.available_documents || [];
  return <section aria-label="回答参考资料" className="space-y-4 rounded-2xl border border-[var(--primary-border)] bg-[var(--card)] p-4">
    <div className="flex flex-wrap items-start justify-between gap-2"><div><p className="mt-eyebrow">当前对话</p><h3 className="mt-1 text-sm font-semibold">回答可以参考哪些资料？</h3></div><span className="mt-tool-badge" data-tone={dirty || error || previewError ? "warning" : "active"}>{status === "loading" ? "读取中" : status === "failed" ? "尚未读取" : saving ? "正在应用" : unconfirmed ? "等待确认" : error ? "读取待重试" : previewError ? "预览失败" : dirty ? "尚未应用" : "已应用"}</span></div>
    <p className="text-xs leading-6 text-[var(--muted-foreground)]">在这里选择这次对话的资料。添加资料与开放整个知识库分别由你决定。</p>
    {status === "loading" ? <p role="status" className="mt-tool-loading"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在读取已保存的参考范围…</p> : null}
    {error ? <div role="alert" className="mt-tool-message text-[var(--destructive)]"><p className="text-xs leading-6">{error}</p><button type="button" className="mt-btn mt-btn-sm mt-2" disabled={saving} onClick={() => void refresh()}><RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />重新读取范围</button></div> : null}
    {draft && status === "ready" ? <>
      <fieldset disabled={disabled}><legend className="text-xs font-semibold">添加知识库</legend><div className="mt-2 grid gap-2">{displayedLibraries.map(lib => <label key={lib.space_id} className="mt-scope-choice !min-h-11 !gap-2 !p-3" data-selected={draft.space_ids.includes(lib.space_id)}><input type="checkbox" className="h-4 w-4 shrink-0 accent-[var(--primary)]" disabled={!lib.enabled && !draft.space_ids.includes(lib.space_id)} aria-label={lib.name} checked={draft.space_ids.includes(lib.space_id)} onChange={event => edit(selectScopeLibraries(draft, event.target.checked ? [...draft.space_ids, lib.space_id] : draft.space_ids.filter(id => id !== lib.space_id)))} /><LibraryIcon className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" /><span className="min-w-0 break-words text-xs leading-6">{lib.name}{!lib.enabled ? <span className="block text-[var(--muted-foreground)]">已停用，可取消选择</span> : null}</span></label>)}{unavailableLibraries.map(id => <label key={id} className="flex min-h-11 items-center gap-2 text-xs leading-6"><input type="checkbox" className="h-4 w-4 shrink-0 accent-[var(--primary)]" checked onChange={() => edit(selectScopeLibraries(draft, draft.space_ids.filter(item => item !== id)))} />已不可用的知识库（取消选择）</label>)}</div>{!displayedLibraries.length && !unavailableLibraries.length ? <p className="mt-2 text-xs leading-6 text-[var(--muted-foreground)]">还没有可选知识库；当前对话上传的文档仍可在下方选择。</p> : null}</fieldset>
      <fieldset disabled={disabled} className="space-y-3"><legend className="text-xs font-semibold">文档范围</legend><label className="flex min-h-11 cursor-pointer items-start gap-2 rounded-xl bg-[var(--sidebar)] p-3"><input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-[var(--primary)]" checked={draft.only_selected} onChange={event => edit({...draft, only_selected: event.target.checked})} /><span className="min-w-0 text-xs leading-6"><span className="font-medium">仅使用我勾选的文档</span><span className="block text-[var(--muted-foreground)]">{draft.only_selected ? "未勾选任何文档时，不参考文本资料。" : "当前上传、已共享总资料及所选库中可检索的文档都在范围内。"}</span></span></label>
        {previewing ? <p role="status" className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]"><Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />正在预览可选文档，尚未应用…</p> : null}
        {previewError ? <p role="alert" className="text-xs leading-6 text-[var(--destructive)]">{previewError}<button type="button" onClick={() => void refresh()} className="mt-btn mt-btn-sm mt-2">重试预览</button></p> : null}
        {!previewing && documents.length ? <ul className="divide-y divide-[var(--border)]">{documents.map(doc => <li key={doc.document_id}><label className="flex min-h-11 items-start gap-2 py-3"><input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-[var(--primary)]" aria-label={doc.title} aria-describedby={`scope-document-${doc.document_id}`} disabled={!draft.only_selected || (!doc.enabled && !draft.document_ids.includes(doc.document_id))} checked={draft.only_selected ? draft.document_ids.includes(doc.document_id) : doc.enabled} onChange={event => edit({...draft, document_ids: event.target.checked ? [...draft.document_ids, doc.document_id] : draft.document_ids.filter(id => id !== doc.document_id)})} /><span className="min-w-0 flex-1"><span className="block break-words text-xs leading-6">{doc.title}</span><span id={`scope-document-${doc.document_id}`} className="block text-[11px] leading-5 text-[var(--muted-foreground)]">{scopeOriginLabel(doc.origin)} · {doc.enabled ? draft.only_selected && !draft.document_ids.includes(doc.document_id) ? "未选入范围" : "已选入范围" : "暂不可检索"}</span></span></label></li>)}</ul> : !previewing ? <p className="text-xs leading-6 text-[var(--muted-foreground)]">还没有可选文本资料。上传文档或选择知识库后会显示在这里。</p> : null}
      </fieldset>
      <details className="mt-knowledge-details"><summary><Settings2 className="h-4 w-4" aria-hidden="true" />问答方式与高级设置<ChevronRight className="ml-auto h-4 w-4" aria-hidden="true" /></summary><fieldset disabled={disabled} className="space-y-4 pt-3"><label className="mt-field">对话方式<select className="mt-input min-h-11 h-auto py-2 text-sm" value={draft.mode || "tutor"} onChange={event => edit({...draft, mode: event.target.value as Mount["mode"]})}><option value="tutor">数学辅导 · 分步讲解与练习</option><option value="knowledge">资料问答 · 围绕所选资料回答</option></select></label><label className="mt-field">整理后的笔记保存到<select className="mt-input min-h-11 h-auto py-2 text-sm" value={draft.save_space_id || ""} onChange={event => edit({...draft, save_space_id: event.target.value})}><option value="">仅预览，暂不选择</option>{draft.save_space_id && !eligible.some(lib => lib.space_id === draft.save_space_id) ? <option value={draft.save_space_id}>原保存位置已不可用，请重新选择</option> : null}{eligible.map(lib => <option key={lib.space_id} value={lib.space_id}>{lib.name}</option>)}</select></label><label className="flex min-h-11 items-start gap-2 text-xs leading-6"><input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-[var(--primary)]" checked={draft.hints_only || false} onChange={event => edit({...draft, hints_only: event.target.checked})} /><span>仅提示：不读取可能含答案的资料</span></label><label className="mt-field">工具调用方式<select className="mt-input min-h-11 h-auto py-2 text-sm" value={draft.tool_mode || "native"} onChange={event => edit({...draft, tool_mode: event.target.value as Mount["tool_mode"]})}><option value="native">标准工具调用</option><option value="structured">JSON 兼容模式</option></select></label></fieldset></details>
      <div className="border-t border-[var(--border)] pt-3"><p className="text-xs leading-6 text-[var(--muted-foreground)]">{dirty ? `尚未应用修改。当前仍使用已保存范围（${saved?.effective_document_ids?.length ?? "—"} 份可检索资料）。` : `当前范围：${saved?.effective_document_ids?.length ?? documents.filter(doc => doc.enabled).length} 份可检索资料。`}</p><p className="mt-1 text-[11px] leading-5 text-[var(--muted-foreground)]">关闭面板会保留草案；应用后从下一条消息生效。范围只控制文本检索，已发送图片由视觉模型读取。</p><button type="button" className="mt-btn mt-btn-primary mt-3 min-h-11 w-full" disabled={disabled || !dirty || previewing || Boolean(previewError || error)} onClick={() => void save()}>{saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Check className="h-4 w-4" aria-hidden="true" />}{saving ? "正在应用…" : "应用到当前对话"}</button></div>
      {notice ? <p role="status" className="text-xs leading-6 text-[var(--primary-text)]">{notice}</p> : null}
    </> : null}
  </section>;
}
