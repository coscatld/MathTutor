"use client";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight, BookOpen, Check, ChevronRight, Download, FilePlus2, FileText, FolderInput, Layers3, Library as LibraryIcon, Loader2, Plus, Search, Settings2, ShieldCheck, Trash2, Upload } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { apiFetch } from "@/lib/api";
import { makeSessionId } from "../lib/protocol";
import { knowledgeApi as api, root, type Library, type Note, type Source, type Mount, type Draft } from "./api";

const input = "mt-input min-h-11 h-auto py-2 text-base";
const button = "mt-btn min-h-11";
const panel = "mt-card min-w-0 p-4 sm:p-5";

export default function KnowledgeWorkbench() {
  const search = useSearchParams();
  const cid = search.get("conversation") || "";
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [sid, setSid] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [mount, setMount] = useState<Mount>({space_ids: [], document_ids: [], only_selected: false, mode: "knowledge"});
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Library["kind"]>("personal");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [filter, setFilter] = useState("");
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [mountDirty, setMountDirty] = useState(false);
  const [mountStatus, setMountStatus] = useState<"loading" | "ready" | "failed">(cid ? "loading" : "ready");
  const folder = useRef<HTMLInputElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const op = useRef("");
  const citation = Boolean(search.get("source") && cid && search.get("version"));
  const refresh = useCallback(async () => {
    const [libs, ds] = await Promise.all([api<Library[]>("/libraries"), api<Draft[]>("/drafts")]);
    setLibraries(libs); setDrafts(ds);
  }, []);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成，输入已保留。"); }
    finally { setBusy(false); }
  };
  const retryLoad = async () => {
    await refresh();
    if (cid && mountStatus !== "ready") {
      const value = await api<Mount>(`/conversations/${encodeURIComponent(cid)}`);
      setMount(value); setMountDirty(false); setMountStatus("ready");
    }
  };
  useEffect(() => { void refresh().catch(e => setError(e.message)); }, [refresh]);
  useEffect(() => {
    if (!cid) return;
    let live = true;
    setMountStatus("loading");
    void api<Mount>(`/conversations/${encodeURIComponent(cid)}`).then(value => { if (live) { setMount(value); setMountDirty(false); setMountStatus("ready"); } }).catch(e => { if (live) { setError(e.message); setMountStatus("failed"); } });
    return () => { live = false; };
  }, [cid]);
  useEffect(() => {
    let live = true;
    if (sid) void api<Note[]>(`/libraries/${sid}/notes`).then(rows => { if (live) setNotes(rows); }).catch(e => { if (live) setError(e.message); });
    else setNotes([]);
    return () => { live = false; };
  }, [sid]);
  useEffect(() => {
    const did = search.get("source");
    if (!did) return;
    const params = new URLSearchParams();
    if (citation) for (const key of ["conversation", "version", "start", "end"]) params.set(key, search.get(key) || "");
    let live = true;
    void api<Source>(`/sources/${encodeURIComponent(did)}?${params}`).then(row => {
      if (live) { setSource(row); setTitle(row.title); setBody(row.body || row.text || ""); setTags((row.tags || []).join(", ")); setDirty(false); }
    }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [search, citation]);
  useEffect(() => {
    if (!dirty && !mountDirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty, mountDirty]);
  const mayDiscard = () => !dirty || window.confirm("笔记有未保存修改，确认放弃这些修改？");
  const mayLeave = () => (!dirty && !mountDirty) || window.confirm(dirty && mountDirty ? "笔记和回答范围有未保存修改，确认离开？" : mountDirty ? "回答范围有未保存修改，确认离开？" : "笔记有未保存修改，确认离开？");
  const openNote = async (did: string) => {
    if (!mayDiscard()) return;
    const row = await api<Source>(`/sources/${did}`);
    setSource(row); setTitle(row.title); setBody(row.body || row.text || ""); setTags((row.tags || []).join(", ")); setDirty(false); op.current = "";
  };
  const importFiles = async (picked: File[]) => {
    if (!sid) throw new Error("先选择目标知识库。");
    if (picked.length > 100) throw new Error("一次最多导入 100 个明确选择的文件。");
    let done = 0, skipped = 0;
    for (const file of picked) {
      const relative = file.webkitRelativePath || file.name;
      if (relative.split("/").some(p => p.startsWith(".") || p === "..")) { skipped++; continue; }
      if (file.name.toLowerCase().endsWith(".md")) {
        if (file.size > 1024 * 1024) throw new Error("Markdown 正文最多 1 MiB。");
        const importedBody = await file.text();
        let previous: Source | null = null;
        for (const note of notes.filter(n => n.editable && n.title === file.name)) {
          const candidate = await api<Source>(`/sources/${note.document_id}`);
          if (candidate.provenance?.relative_path === relative) { previous = candidate; break; }
        }
        if (previous && previous.body !== importedBody && !window.confirm(`${relative} 有外部修改。保存为 v${previous.version + 1}？旧版本保留；版本冲突时拒绝覆盖。`)) { skipped++; continue; }
        if (!previous || previous.body !== importedBody) await api(`/libraries/${sid}/notes`, {title: file.name, body: importedBody,
          tags: previous?.tags || [], operation_id: crypto.randomUUID(), relative_path: relative,
          document_id: previous?.document_id || null, expected_version: previous?.version || null});
      } else if (file.webkitRelativePath) { skipped++; continue; }
      else {
        const form = new FormData(); form.append("file", file);
        const res = await apiFetch(`${root}/libraries/${sid}/imports`, {method: "POST", body: form});
        if (!res.ok) throw new Error((await res.json()).detail || "文件导入失败。");
      }
      done++;
    }
    setNotes(await api<Note[]>(`/libraries/${sid}/notes`)); setNotice(`已导入 ${done} 份；忽略 ${skipped} 个非 Markdown / 隐藏文件。不会运行插件。`);
  };
  const save = async () => {
    if (!sid) throw new Error("先选择笔记所属知识库。");
    if (source && !window.confirm(`保存为 v${source.version + 1}？原版本保留；若版本已变化则拒绝覆盖。`)) return;
    if (!op.current) op.current = crypto.randomUUID();
    const result = await api<{document_id: string}>(`/libraries/${sid}/notes`, {title, body, tags: tags.split(/[,，]/).map(t => t.trim()).filter(Boolean), operation_id: op.current,
      document_id: source?.document_id || null, expected_version: source?.version || null});
    setDirty(false); setSource(await api<Source>(`/sources/${result.document_id}`)); op.current = "";
    setNotes(await api<Note[]>(`/libraries/${sid}/notes`)); setNotice("笔记已保存，可在显式挂载此库的会话中检索。");
  };
  const updateMount = async (value: Mount, target = cid) => {
    const {available_documents: _available, ...payload} = value;
    await api(`/conversations/${encodeURIComponent(target)}`, payload, "PUT");
    setMount(await api<Mount>(`/conversations/${encodeURIComponent(target)}`)); setMountDirty(false); setNotice("会话范围已保存；不会自动扩大范围或联网。");
    window.dispatchEvent(new Event("mathtutor-conversations-changed"));
  };
  const library = libraries.find(l => l.space_id === sid);
  const eligibleLibraries = libraries.filter(l => l.enabled && (l.kind !== "session" || l.conversation_id === cid));
  const selectedLibraries = eligibleLibraries.filter(l => mount.space_ids.includes(l.space_id));
  const filteredNotes = notes.filter(n => `${n.title} ${n.tags.join(" ")}`.toLocaleLowerCase().includes(filter.toLocaleLowerCase()));
  const editMount = (value: Mount) => { setMount(value); setMountDirty(true); };
  const kindLabel = (value: Library["kind"]) => ({personal: "个人知识库", course: "课程知识库", session: "会话资料"})[value];
  return <div className="mt-page mt-knowledge-page text-[var(--foreground)]">
    <header className="flex flex-wrap items-end justify-between gap-5">
      <div><p className="mt-eyebrow flex items-center gap-2"><LibraryIcon className="h-3.5 w-3.5" aria-hidden="true" />资料与回答，清晰连接</p><h1 className="mt-3">知识库与问答范围</h1><p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">整理你的学习资料，决定这次对话可以参考什么。</p></div>
      <Link className={button} onClick={e => { if (!mayLeave()) e.preventDefault(); }} href={cid ? `/math-tutor?session=${encodeURIComponent(cid)}` : "/math-tutor"}><ArrowLeft className="h-4 w-4" aria-hidden="true" />返回对话</Link>
    </header>
    {error && <div role="alert" className="mt-knowledge-alert"><p>{error}</p><button className={button} onClick={() => void perform(retryLoad)}>刷新重试</button></div>}
    {(busy || notice) && <p role="status" className="flex items-center gap-2 text-sm text-[var(--primary-text)]" aria-live="polite">{busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Check className="h-4 w-4" aria-hidden="true" />}{busy ? "正在处理，请稍候…" : notice}</p>}
    {cid ? <section className="mt-scope-card" aria-label="会话挂载">
      <div className="mt-scope-heading"><div className="flex items-center gap-3"><span className="mt-knowledge-icon"><ShieldCheck className="h-5 w-5" aria-hidden="true" /></span><div><p className="mt-eyebrow">当前对话</p><h2 className="mt-1 text-lg font-semibold">回答可以参考哪些资料？</h2></div></div><span className="mt-tool-badge" data-tone={mountDirty ? "warning" : "active"}>{mountStatus === "loading" ? "正在读取范围…" : mountStatus === "failed" ? "范围尚未读取" : mountDirty ? "有未保存的范围修改" : "当前已保存范围"}</span></div>
      <div className="mt-scope-content">
        <div className="min-w-0 space-y-5">
          <fieldset><legend className="text-sm font-semibold">选择知识库</legend><p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">只参考你为当前对话选中的库。</p><div className="mt-3 grid gap-2 sm:grid-cols-2">{eligibleLibraries.map(lib => <label key={lib.space_id} className="mt-scope-choice" data-selected={mount.space_ids.includes(lib.space_id)}><input type="checkbox" className="h-4 w-4 shrink-0 accent-[var(--primary)]" disabled={busy || mountStatus !== "ready"} checked={mount.space_ids.includes(lib.space_id)} onChange={e => editMount({...mount, space_ids: e.target.checked ? [...mount.space_ids, lib.space_id] : mount.space_ids.filter(x => x !== lib.space_id)})} /><span className="min-w-0"><span className="block break-words text-sm font-medium">{lib.name}</span><span className="mt-0.5 block text-xs text-[var(--muted-foreground)]">{kindLabel(lib.kind)}</span></span></label>)}</div>{!eligibleLibraries.length && <p className="mt-3 rounded-xl border border-dashed border-[var(--border)] p-4 text-sm leading-6 text-[var(--muted-foreground)]">还没有可选知识库。先在下方创建一个，再导入你的资料。</p>}</fieldset>
          <div className="grid gap-4 sm:grid-cols-2"><label className="mt-field">对话方式<select className={input} disabled={busy || mountStatus !== "ready"} value={mount.mode || "tutor"} onChange={e => editMount({...mount, mode: e.target.value as Mount["mode"]})}><option value="knowledge">资料问答 · 围绕所选资料回答</option><option value="tutor">数学辅导 · 分步讲解与练习</option></select></label><label className="mt-field">整理后的笔记保存到<select className={input} disabled={busy || mountStatus !== "ready"} value={mount.save_space_id || ""} onChange={e => editMount({...mount, save_space_id: e.target.value})}><option value="">仅预览，暂不选择</option>{eligibleLibraries.map(l => <option key={l.space_id} value={l.space_id}>{l.name}</option>)}</select></label></div>
          <label className="mt-scope-toggle"><input type="checkbox" className="h-4 w-4 shrink-0 accent-[var(--primary)]" disabled={busy || mountStatus !== "ready"} checked={mount.only_selected} onChange={e => editMount({...mount, only_selected: e.target.checked})} /><span><span className="block text-sm font-medium">进一步限定到指定文档</span><span className="mt-1 block text-xs leading-5 text-[var(--muted-foreground)]">开启后，只参考下方选中的文档；未选文档时保持空范围。</span></span></label>
          {mount.only_selected && <fieldset className="mt-selected-documents"><legend className="px-1 text-xs font-medium text-[var(--muted-foreground)]">先保存知识库选择，再勾选其中的文档</legend>{mount.available_documents?.length ? mount.available_documents.map(d => <label className="flex min-h-11 items-start gap-2 py-2 text-sm" key={d.document_id}><input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-[var(--primary)]" disabled={busy || mountStatus !== "ready" || !d.enabled} checked={mount.document_ids.includes(d.document_id)} onChange={e => editMount({...mount, document_ids: e.target.checked ? [...mount.document_ids, d.document_id] : mount.document_ids.filter(x => x !== d.document_id)})} /><span className="break-words">{d.title}{!d.enabled && <span className="text-xs text-[var(--muted-foreground)]">（不可检索）</span>}</span></label>) : <p className="py-3 text-sm text-[var(--muted-foreground)]">尚无可选文档。请导入资料并保存知识库选择。</p>}</fieldset>}
        </div>
        <div className="mt-scope-summary"><div><h3 className="text-sm font-semibold">本次范围预览</h3><p className="mt-3 text-3xl font-semibold tabular-nums">{mountStatus === "ready" ? selectedLibraries.length : "—"}<span className="ml-2 text-xs font-normal text-[var(--muted-foreground)]">个知识库</span></p><p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{mountStatus === "loading" ? "正在读取已保存的资料范围…" : mountStatus === "failed" ? "暂时无法读取，请刷新后重试。" : selectedLibraries.length ? selectedLibraries.map(l => l.name).join("、") : "尚未选择知识库"}</p><p className="mt-3 border-t border-[var(--border)] pt-3 text-xs leading-6 text-[var(--muted-foreground)]">{mount.only_selected ? `仅指定文档 · 已选 ${mount.document_ids.length} 份` : "使用所选库中允许检索的文档"}。每个新对话都需要单独选择资料范围。</p></div><button className={`${button} mt-btn-primary mt-5 w-full`} disabled={busy || mountStatus !== "ready"} onClick={() => void perform(() => updateMount(mount))}><Check className="h-4 w-4" aria-hidden="true" />保存挂载与范围</button></div>
      </div>
      <details className="mt-knowledge-details"><summary><Settings2 className="h-4 w-4" aria-hidden="true" />问答与模型兼容设置<ChevronRight className="ml-auto h-4 w-4" aria-hidden="true" /></summary><div className="grid gap-4 pt-4 sm:grid-cols-2"><label className="mt-field">工具调用方式<select className={input} disabled={busy || mountStatus !== "ready"} value={mount.tool_mode || "native"} onChange={e => editMount({...mount, tool_mode: e.target.value as Mount["tool_mode"]})}><option value="native">标准工具调用</option><option value="structured">JSON 兼容模式</option></select></label><label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" className="h-4 w-4 shrink-0 accent-[var(--primary)]" disabled={busy || mountStatus !== "ready"} checked={mount.hints_only || false} onChange={e => editMount({...mount, hints_only: e.target.checked})} />仅提示：不读取可能含答案的资料</label></div></details>
    </section> : <div className="mt-tool-message flex items-start gap-3"><ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-[var(--primary-text)]" aria-hidden="true" /><p className="text-sm leading-7">这里管理长期保存的资料。选中知识库后，可直接新建一段使用这些资料的对话。</p></div>}
    <div className="mt-knowledge-layout">
      <aside className="mt-knowledge-sidebar" aria-label="知识库列表"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">我的知识库</h2><span className="text-xs tabular-nums text-[var(--muted-foreground)]">{libraries.length}</span></div><ul className="mt-4 space-y-2">{libraries.map(lib => <li key={lib.space_id}><button className="mt-library-choice" disabled={busy} onClick={() => { if (mayDiscard()) { setSid(lib.space_id); setSource(null); setBody(""); setTitle(""); setTags(""); setDirty(false); } }} aria-pressed={sid === lib.space_id}><LibraryIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><span className="min-w-0 flex-1"><span className="block break-words font-medium">{lib.name}</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">{kindLabel(lib.kind)} · {lib.enabled ? "可检索" : "已停用"}</span></span>{sid === lib.space_id ? <ChevronRight className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : null}</button></li>)}</ul>{!libraries.length && <p className="my-4 text-sm leading-6 text-[var(--muted-foreground)]">把讲义和笔记分类保存，从第一个知识库开始。</p>}
        <details className="mt-create-library" open={!libraries.length || undefined}><summary><Plus className="h-4 w-4" aria-hidden="true" />创建知识库</summary><form className="mt-3 space-y-3" onSubmit={e => { e.preventDefault(); void perform(async () => { if (kind === "session") await updateMount(mount); const lib = await api<Library>("/libraries", {name, kind, conversation_id: kind === "session" ? cid : ""}); await refresh(); setSid(lib.space_id); setName(""); }); }}><label className="mt-field">名称<input className={input} value={name} onChange={e => setName(e.target.value)} placeholder="例如：高一数学笔记" maxLength={120} required /></label><label className="mt-field">保存位置<select className={input} value={kind} onChange={e => setKind(e.target.value as Library["kind"])}><option value="personal">个人知识库</option><option value="course">课程知识库</option><option value="session" disabled={!cid}>仅当前会话</option></select></label><button className={`${button} w-full`} disabled={busy || !name.trim()}><Plus className="h-4 w-4" aria-hidden="true" />创建知识库</button></form></details>
      </aside>
      <div className="min-w-0 space-y-5">
        {library ? <section className={`${panel} space-y-5`} aria-label="知识库资料"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="mt-eyebrow">{kindLabel(library.kind)}</p><h2 className="mt-2 break-words text-xl font-semibold">{library.name}</h2><p className="mt-2 text-xs text-[var(--muted-foreground)]">{notes.length} 份资料 · {library.enabled ? "允许在已选对话中检索" : "知识库检索已停用"}</p></div><button className={`${button} text-[var(--primary-text)]`} disabled={busy || !library.enabled} onClick={() => void perform(async () => { const next = makeSessionId(); await updateMount({space_ids: [sid], document_ids: [], only_selected: false, mode: "knowledge", save_space_id: sid}, next); window.location.assign(`/math-tutor?session=${encodeURIComponent(next)}`); })}>用此库开始对话<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></button></div>
          <div className="flex flex-wrap gap-2"><input ref={files} type="file" multiple hidden accept=".md,.markdown,.txt,.tex,.pdf" onChange={e => { const picked = Array.from(e.target.files || []); e.target.value = ""; void perform(() => importFiles(picked)); }} /><input ref={folder} type="file" multiple hidden onChange={e => { const picked = Array.from(e.target.files || []); e.target.value = ""; void perform(() => importFiles(picked)); }} /><button className={`${button} mt-btn-primary`} disabled={busy} onClick={() => files.current?.click()}><Upload className="h-4 w-4" aria-hidden="true" />导入文档</button><button className={button} disabled={busy} onClick={() => { if (mayDiscard()) { setSource(null); setTitle(""); setBody(""); setTags(""); setDirty(false); op.current = ""; } }}><FilePlus2 className="h-4 w-4" aria-hidden="true" />新建笔记</button><button className={button} disabled={busy} onClick={() => { folder.current?.setAttribute("webkitdirectory", ""); folder.current?.click(); }}><FolderInput className="h-4 w-4" aria-hidden="true" />导入笔记文件夹</button></div>
          <label className="mt-search-field"><Search className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" /><span className="sr-only">按标题或标签筛选</span><input value={filter} onChange={e => setFilter(e.target.value)} placeholder="搜索资料标题或标签" /></label>
          {filteredNotes.length ? <ul className="divide-y divide-[var(--border)]">{filteredNotes.map(n => <li className="mt-knowledge-note" key={n.document_id}><FileText className="mt-1 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" /><button className="mt-note-open" disabled={busy} onClick={() => void perform(() => openNote(n.document_id))}><span className="block break-words text-sm font-medium">{n.title}</span><span className="mt-1 block text-xs leading-5 text-[var(--muted-foreground)]">v{n.version} · {n.editable ? "可编辑笔记" : "导入文档"}{n.tags.length ? ` · ${n.tags.join(" / ")}` : ""}</span></button><button className="mt-tool-badge min-h-9 shrink-0" data-tone={n.retrieval_enabled ? "active" : undefined} disabled={busy} onClick={() => void perform(async () => { const res = await apiFetch(`/api/v2/math-tutor/desktop/documents/${n.document_id}/retrieval`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({enabled: !n.retrieval_enabled})}); if (!res.ok) throw new Error("资料检索设置未保存。"); setNotes(await api<Note[]>(`/libraries/${sid}/notes`)); })} aria-label={`${n.retrieval_enabled ? "停用" : "启用"}${n.title}的检索`}>{n.retrieval_enabled ? "检索已开" : "检索已关"}</button></li>)}</ul> : <div className="mt-tool-empty"><BookOpen className="mx-auto h-7 w-7 text-[var(--muted-foreground)]" aria-hidden="true" /><h3>{notes.length ? "没有匹配的资料" : "资料准备好，就能开始提问"}</h3><p>{notes.length ? "试试更短的关键词，或清空搜索条件。" : "导入一份讲义，或写下今天的课堂笔记。"}</p></div>}
          <details className="mt-knowledge-details"><summary><Settings2 className="h-4 w-4" aria-hidden="true" />知识库选项<ChevronRight className="ml-auto h-4 w-4" aria-hidden="true" /></summary><div className="flex flex-wrap gap-2 pt-4"><button className={button} disabled={busy} onClick={() => void perform(async () => { const res = await apiFetch(`${root}/libraries/${sid}/export`); if (!res.ok) throw new Error("导出失败。"); const url = URL.createObjectURL(await res.blob()); const a = document.createElement("a"); a.href = url; a.download = "knowledge.zip"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); })}><Download className="h-4 w-4" aria-hidden="true" />导出 ZIP</button><button className={button} disabled={busy} onClick={() => void perform(async () => { await api(`/libraries/${sid}/enabled`, {enabled: !library.enabled}, "PUT"); await refresh(); })}>{library.enabled ? "停用整个知识库检索" : "启用知识库检索"}</button><button className={`${button} mt-btn-danger`} disabled={busy} onClick={() => { if (window.confirm("删除该库及其不被其他库保留的资料？正文、历史版本和索引将被删除，无法撤销。")) void perform(async () => { await api(`/libraries/${sid}`, undefined, "DELETE"); setSid(""); setSource(null); setBody(""); await refresh(); }); }}><Trash2 className="h-4 w-4" aria-hidden="true" />删除知识库</button></div></details>
        </section> : !source ? <section className={`${panel} mt-knowledge-welcome`}><span className="mt-tool-empty-icon"><Layers3 className="h-7 w-7" aria-hidden="true" /></span><h2>给学习资料一个清楚的位置</h2><p>选择一个知识库，查看资料、整理笔记，或开始一段有据可查的对话。</p><div className="mt-knowledge-steps"><span><b>01</b> 建立知识库</span><span><b>02</b> 放入学习资料</span><span><b>03</b> 选择回答范围</span></div></section> : null}
        {(library || source) && <section className={`${panel} space-y-5`} aria-label={citation ? "引用原文" : "笔记编辑与预览"}><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="flex items-center gap-2 text-base font-semibold"><FileText className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />{citation ? "引用原文" : source ? "查看与编辑笔记" : "写一份新笔记"}</h2>{dirty && <span className="mt-tool-badge" data-tone="warning">未保存</span>}</div>
          {source && <details className="mt-knowledge-details"><summary>版本与出处<ChevronRight className="ml-auto h-4 w-4" aria-hidden="true" /></summary><p className="break-all pt-3 font-mono text-xs leading-6">{source.title} · v{source.version}{source.line_start && ` · L${source.line_start}–${source.line_end}`}<br />SHA256 {source.body_hash}</p></details>}
          {citation ? <pre className="whitespace-pre-wrap break-words rounded-xl bg-[var(--paper)] p-4 font-sans text-base leading-7">{body}</pre> : <><div className="grid gap-4 sm:grid-cols-2"><label className="mt-field">笔记标题<input className={input} value={title} placeholder="给笔记起个名字" onChange={e => { setTitle(e.target.value); setDirty(true); op.current = ""; }} /></label><label className="mt-field">标签<span className="sr-only">（逗号分隔）</span><input className={input} value={tags} placeholder="函数、错题，用逗号分隔" onChange={e => { setTags(e.target.value); setDirty(true); op.current = ""; }} /></label></div>
            <div className="grid gap-4 xl:grid-cols-2"><label className="mt-field min-w-0">Markdown 正文<textarea className={`${input} min-h-64 font-mono leading-7`} value={body} placeholder="记录知识点、推导过程或复习问题…" readOnly={Boolean(source && source.provenance?.format !== "markdown")} onChange={e => { setBody(e.target.value); setDirty(true); op.current = ""; }} /></label><div className="mt-note-preview min-w-0"><h3 className="mb-3 text-xs font-semibold text-[var(--muted-foreground)]">阅读预览</h3><MarkdownRenderer content={body || "你的笔记会显示在这里。"} /></div></div><div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs leading-5 text-[var(--muted-foreground)]">{source && source.provenance?.format !== "markdown" ? "导入文档以原文查看；你可以新建笔记整理内容。" : "每次保存保留历史版本；预览不执行 HTML、插件或远程图片。"}</p><button className={`${button} mt-btn-primary`} disabled={busy || !sid || !title.trim() || !body.trim() || Boolean(source && source.provenance?.format !== "markdown")} onClick={() => void perform(save)}><Check className="h-4 w-4" aria-hidden="true" />{source ? "保存新版本" : "保存新笔记"}</button></div>
            {source?.links?.length ? <p className="text-sm">链接到：{source.links.map(link => <button key={link} className={`${button} m-1`} onClick={() => { const target = notes.find(n => n.title.replace(/\.md$/, "") === link || n.title === link); if (target) void perform(() => openNote(target.document_id)); else setError("链接目标未在当前库找到，请导入或选择其所属库。"); }}>{link}</button>)}</p> : null}{source?.backlinks?.length ? <p className="text-sm">被引用：{source.backlinks.map(n => <button className={`${button} m-1`} key={n.document_id} onClick={() => void perform(() => openNote(n.document_id))}>{n.title}</button>)}</p> : null}
          </>}
        </section>}
        {drafts.length > 0 && <section className={`${panel} space-y-4`}><h2 className="text-base font-semibold">待整理的笔记草稿</h2><p className="text-sm leading-6 text-[var(--muted-foreground)]">先预览，再决定是否保存到所选知识库。</p>{drafts.map(d => <details key={d.draft_id} className="mt-knowledge-details"><summary>{d.title}<ChevronRight className="ml-auto h-4 w-4 shrink-0" aria-hidden="true" /></summary><div className="py-4"><MarkdownRenderer content={d.markdown} /></div><button className={button} disabled={busy || !sid} onClick={() => void perform(async () => { await api(`/drafts/${d.draft_id}/save`, {space_id: sid}); setNotes(await api<Note[]>(`/libraries/${sid}/notes`)); setNotice("已保存到当前选择的库；重复保存不会新增副本。"); })}><Plus className="h-4 w-4" aria-hidden="true" />保存新笔记到所选库</button></details>)}</section>}
      </div>
    </div>
  </div>;
}
