"use client";
import { ArrowUpRight, Check, ChevronRight, Download, FilePlus2, FileText, FolderInput, FolderOpen, Layers3, Library as LibraryIcon, Loader2, Plus, Search, Settings2, Trash2, Upload, Wand2 } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { apiFetch } from "@/lib/api";
import { makeSessionId } from "../lib/protocol";
import { requestTutorNavigation } from "../lib/navigation-guard";
import { knowledgeApi as api, root, mountConfiguration, knowledgeSection, type KnowledgeSection, type Library, type Source, type Mount, type Draft } from "./api";

import { useUnsavedNavigation } from "../hooks/useUnsavedNavigation";
import VaultFileList, { vaultPath, type VaultNote } from "./VaultFileList";
import TeachingSkills from "./TeachingSkills";
import ReferenceJourney from "./ReferenceJourney";

const input = "mt-input min-h-11 h-auto py-2 text-base";
const button = "mt-btn min-h-11";
const panel = "mt-card min-w-0 p-4 sm:p-5";

export default function KnowledgeWorkbench() {
  const search = useSearchParams();
  const cid = search.get("conversation") || "";
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [sid, setSid] = useState("");
  const linkedLibrary = search.get("library") || "", appliedLibrary = useRef("");
  const [notes, setNotes] = useState<VaultNote[]>([]);
  const [source, setSource] = useState<Source | null>(null);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const requestedSection = search.get("tab");
  const [section, setSection] = useState<KnowledgeSection>(knowledgeSection(requestedSection));
  useEffect(() => { setSection(knowledgeSection(requestedSection)); }, [requestedSection]);
  const [currentFolder, setCurrentFolder] = useState("");
  const [relativePath, setRelativePath] = useState("");
  const [previousPath, setPreviousPath] = useState("");
  const packInput = useRef<HTMLInputElement>(null);
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
  const folder = useRef<HTMLInputElement>(null);
  const files = useRef<HTMLInputElement>(null);
  const op = useRef("");
  const citation = Boolean(search.get("source") && cid && search.get("version"));
  const refresh = useCallback(async () => {
    const [libs, ds] = await Promise.all([api<Library[]>("/libraries"), api<Draft[]>("/drafts")]);
    setLibraries(libs); setDrafts(ds);
  }, []);
  useEffect(() => { if (linkedLibrary && linkedLibrary !== appliedLibrary.current && libraries.some(library => library.space_id === linkedLibrary)) {appliedLibrary.current = linkedLibrary; setSid(linkedLibrary);} }, [linkedLibrary, libraries]);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError(""); setNotice("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成，输入已保留。"); }
    finally { setBusy(false); }
  };
  const retryLoad = async () => { await refresh(); };
  useEffect(() => { void refresh().catch(e => setError(e.message)); }, [refresh]);
  useEffect(() => {
    let live = true;
    if (sid) void api<VaultNote[]>(`/libraries/${sid}/notes`).then(rows => { if (live) setNotes(rows); }).catch(e => { if (live) setError(e.message); });
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
      if (live) { setSource(row); setTitle(row.title); setBody(row.body || row.text || ""); setTags((row.tags || []).join(", ")); setRelativePath(row.provenance?.relative_path || ""); setPreviousPath(row.provenance?.relative_path || ""); setDirty(false); op.current = ""; }
    }).catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [search, citation]);
  useUnsavedNavigation(dirty ? "笔记有未保存修改，离开将放弃这些修改。" : "");
  const mayDiscard = () => !dirty || window.confirm("笔记有未保存修改，确认放弃这些修改？");
  const openNote = async (did: string, selectedPath?: string) => {
    if (!mayDiscard()) return;
    const row = await api<Source>(`/sources/${did}`);
    const path = selectedPath ?? notes.find(note => note.document_id === did)?.provenance?.relative_path ?? row.provenance?.relative_path ?? "";
    setSource(row); setTitle(row.title); setBody(row.body || row.text || ""); setTags((row.tags || []).join(", ")); setRelativePath(path); setPreviousPath(path); setDirty(false); op.current = "";
  };
  const importFiles = async (picked: File[]) => {
    if (!sid) throw new Error("先选择目标知识库。");
    if (picked.length > 100) throw new Error("一次最多导入 100 个明确选择的文件。");
    let done = 0, skipped = 0;
    for (const file of picked) {
      const relative = file.webkitRelativePath || file.name;
      if (relative.split("/").some(p => p.startsWith(".") || p === "..")) { skipped++; continue; }
      if (/\.(md|markdown)$/i.test(file.name)) {
        if (file.size > 1024 * 1024) throw new Error("Markdown 正文最多 1 MiB。");
        const importedBody = await file.text();
        let previous: Source | null = null;
        for (const note of notes.filter(n => n.editable && (n.provenance?.relative_paths?.includes(relative) || n.provenance?.relative_path === relative))) {
          const candidate = await api<Source>(`/sources/${note.document_id}`);
          previous = candidate; break;
        }
        if (previous && previous.body !== importedBody && !window.confirm(`${relative} 有外部修改。保存为 v${previous.version + 1}？旧版本保留；版本冲突时拒绝覆盖。`)) { skipped++; continue; }
        if (!previous || previous.body !== importedBody) await api(`/libraries/${sid}/notes`, {title: file.name, body: importedBody,
          tags: previous?.tags || [], operation_id: crypto.randomUUID(), relative_path: relative,
          previous_relative_path: previous ? relative : undefined,
          document_id: previous?.document_id || null, expected_version: previous?.version || null});
      } else if (file.webkitRelativePath) { skipped++; continue; }
      else {
        const form = new FormData(); form.append("file", file);
        const res = await apiFetch(`${root}/libraries/${sid}/imports`, {method: "POST", body: form});
        if (!res.ok) throw new Error((await res.json()).detail || "文件导入失败。");
      }
      done++;
    }
    setNotes(await api<VaultNote[]>(`/libraries/${sid}/notes`)); setNotice(`已导入 ${done} 份；忽略 ${skipped} 个非 Markdown / 隐藏文件。不会运行插件。`);
  };
  const save = async () => {
    if (!sid) throw new Error("先选择笔记所属知识库。");
    if (source && !window.confirm(`保存为 v${source.version + 1}？原版本保留；若版本已变化则拒绝覆盖。`)) return;
    if (!op.current) op.current = crypto.randomUUID();
    const result = await api<{document_id: string}>(`/libraries/${sid}/notes`, {title, body, tags: tags.split(/[,，]/).map(t => t.trim()).filter(Boolean), operation_id: op.current,
      document_id: source?.document_id || null, expected_version: source?.version || null, relative_path: relativePath,
      previous_relative_path: source && previousPath ? previousPath : undefined});
    const [updated, rows] = await Promise.all([api<Source>(`/sources/${result.document_id}`), api<VaultNote[]>(`/libraries/${sid}/notes`)]);
    const savedPath = relativePath || rows.find(note => note.document_id === result.document_id)?.provenance?.relative_path || "";
    setSource(updated); setNotes(rows); setRelativePath(savedPath); setPreviousPath(savedPath); setDirty(false); op.current = "";
    setNotice("笔记已保存，可在显式挂载此库的会话中检索。");
  };
  const configureConversation = async (value: Mount, target: string) => {
    await api(`/conversations/${encodeURIComponent(target)}`, mountConfiguration(value), "PUT");
    window.dispatchEvent(new Event("mathtutor-conversations-changed"));
  };
  const importPack = async (file?: File) => {
    if (!file || !mayDiscard()) return;
    await perform(async () => {
      const form = new FormData(); form.append("file", file);
      const response = await apiFetch("/api/v2/math-tutor/desktop/content/question-packs/import", { method: "POST", body: form });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "题库没有导入，请检查文件格式。");
      await refresh(); setSid(result.space_id); setFilter(""); setCurrentFolder(""); setSource(null); setTitle(""); setBody(""); setTags(""); setRelativePath(""); setPreviousPath(""); setDirty(false); op.current = "";
      setNotice(`已导入 ${result.imported_count} 份可编辑资料。尚未加入当前对话的参考范围。${(result.warnings || []).join(" ")}`);
    });
  };
  const library = libraries.find(l => l.space_id === sid);
  const kindLabel = (value: Library["kind"]) => ({personal: "个人资料库", course: "课程与题库", session: "会话资料"})[value];
  return <div className="mt-page mt-knowledge-page text-[var(--foreground)]">
    <header className="flex flex-wrap items-end justify-between gap-5">
      <div><p className="mt-eyebrow flex items-center gap-2"><LibraryIcon className="h-3.5 w-3.5" aria-hidden="true" />有出处的学习参考</p><h1 className="mt-3">知识库</h1><p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">整理、编辑与分享题库和笔记，为数学讲解提供可追溯的参考。资料由你选择，每次引用都有原文可查。</p></div>
      <div className="flex flex-wrap gap-2"><input ref={packInput} type="file" hidden accept=".json,.zip" onChange={e => { const file = e.target.files?.[0]; e.target.value = ""; void importPack(file); }} /><button type="button" className={`${button} mt-btn-primary`} disabled={busy} onClick={() => packInput.current?.click()}><Upload className="h-4 w-4" aria-hidden="true" />导入共享题库</button></div>
    </header>
    {error && <div role="alert" className="mt-knowledge-alert"><p>{error}</p><button className={button} onClick={() => void perform(retryLoad)}>刷新重试</button></div>}
    {(busy || notice) && <p role="status" className="flex items-center gap-2 text-sm text-[var(--primary-text)]" aria-live="polite">{busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Check className="h-4 w-4" aria-hidden="true" />}{busy ? "正在处理，请稍候…" : notice}</p>}
    <nav className="mt-vault-tabs" aria-label="知识库内容类型">{([{id: "files", label: "题库与笔记", icon: FolderOpen}, {id: "skills", label: "教学技能", icon: Wand2}] as const).map(item => <button type="button" key={item.id} aria-pressed={section === item.id} onClick={() => setSection(item.id)}><item.icon className="h-4 w-4 shrink-0" aria-hidden="true" />{item.label}</button>)}</nav>
    {section === "files" ? <>
    <ReferenceJourney conversationId={cid} />
    <div className={`mt-knowledge-layout${!library && !source && !drafts.length ? " mt-knowledge-layout-empty" : ""}`}>
      <aside className="mt-knowledge-sidebar" aria-label="知识库列表"><div className="flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">我的知识库</h2><span className="text-xs tabular-nums text-[var(--muted-foreground)]">{libraries.length}</span></div><ul className="mt-4 space-y-2">{libraries.map(lib => <li key={lib.space_id}><button className="mt-library-choice" disabled={busy} onClick={() => { if (mayDiscard()) { setSid(lib.space_id); setFilter(""); setCurrentFolder(""); setRelativePath(""); setPreviousPath(""); setSource(null); setBody(""); setTitle(""); setTags(""); setDirty(false); op.current = ""; } }} aria-pressed={sid === lib.space_id}><LibraryIcon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /><span className="min-w-0 flex-1"><span className="block break-words font-medium">{lib.name}</span><span className="mt-1 block text-xs text-[var(--muted-foreground)]">{kindLabel(lib.kind)} · {lib.enabled ? "可检索" : "已停用"}</span></span>{sid === lib.space_id ? <ChevronRight className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : null}</button></li>)}</ul>{!libraries.length && <p className="my-4 text-sm leading-6 text-[var(--muted-foreground)]">把讲义和笔记分类保存，从第一个知识库开始。</p>}
        <details className="mt-create-library" open={!libraries.length || undefined}><summary><Plus className="h-4 w-4" aria-hidden="true" />创建知识库</summary><form className="mt-3 space-y-3" onSubmit={e => { e.preventDefault(); if (!mayDiscard()) return; void perform(async () => { if (kind === "session") { const current = await api<Mount>(`/conversations/${encodeURIComponent(cid)}`); await configureConversation(current, cid); } const lib = await api<Library>("/libraries", {name, kind, conversation_id: kind === "session" ? cid : ""}); await refresh(); setSid(lib.space_id); setFilter(""); setCurrentFolder(""); setSource(null); setTitle(""); setBody(""); setTags(""); setRelativePath(""); setPreviousPath(""); setDirty(false); op.current = ""; setName(""); }); }}><label className="mt-field">名称<input className={input} value={name} onChange={e => setName(e.target.value)} placeholder="例如：高一数学笔记" maxLength={120} required /></label><label className="mt-field">保存位置<select className={input} value={kind} onChange={e => setKind(e.target.value as Library["kind"])}><option value="personal">个人知识库</option><option value="course">课程知识库</option><option value="session" disabled={!cid}>仅当前会话</option></select></label><button className={`${button} w-full`} disabled={busy || !name.trim()}><Plus className="h-4 w-4" aria-hidden="true" />创建知识库</button></form></details>
      </aside>
      <div className="mt-knowledge-main">
        {library ? <section className={`${panel} space-y-5`} aria-label="知识库资料"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="mt-eyebrow">{kindLabel(library.kind)}</p><h2 className="mt-2 break-words text-xl font-semibold">{library.name}</h2><p className="mt-2 text-xs text-[var(--muted-foreground)]">{notes.length} 份资料 · {library.enabled ? "允许在已选对话中检索" : "知识库检索已停用"}</p></div><button className={`${button} text-[var(--primary-text)]`} disabled={busy || !library.enabled} onClick={() => void perform(async () => { if (!requestTutorNavigation()) return; const next = makeSessionId(); await configureConversation({space_ids: [sid], document_ids: [], only_selected: false, mode: "knowledge", save_space_id: sid}, next); window.location.assign(`/math-tutor?session=${encodeURIComponent(next)}`); })}>用此库开始对话<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></button></div>
          <div className="flex flex-wrap gap-2"><input ref={files} type="file" multiple hidden accept=".md,.markdown,.txt,.tex,.pdf" onChange={e => { const picked = Array.from(e.target.files || []); e.target.value = ""; void perform(() => importFiles(picked)); }} /><input ref={folder} type="file" multiple hidden onChange={e => { const picked = Array.from(e.target.files || []); e.target.value = ""; void perform(() => importFiles(picked)); }} /><button className={`${button} mt-btn-primary`} disabled={busy} onClick={() => files.current?.click()}><Upload className="h-4 w-4" aria-hidden="true" />导入文档</button><button className={button} disabled={busy} onClick={() => { if (mayDiscard()) { setSource(null); setTitle(""); setBody(""); setTags(""); setRelativePath(currentFolder ? `${currentFolder}/新笔记.md` : ""); setPreviousPath(""); setDirty(false); op.current = ""; } }}><FilePlus2 className="h-4 w-4" aria-hidden="true" />新建笔记</button><button className={button} disabled={busy} onClick={() => { folder.current?.setAttribute("webkitdirectory", ""); folder.current?.click(); }}><FolderInput className="h-4 w-4" aria-hidden="true" />导入笔记文件夹</button></div>
          <label className="mt-search-field"><Search className="h-4 w-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" /><span className="sr-only">按标题、文件夹或标签筛选</span><input value={filter} onChange={e => setFilter(e.target.value)} placeholder="搜索资料、文件夹或标签" /></label>
          <VaultFileList notes={notes} folder={currentFolder} query={filter} name={library.name} selected={source?.document_id} selectedPath={previousPath} busy={busy} onFolder={setCurrentFolder} onOpen={note => void perform(() => openNote(note.document_id, vaultPath(note)))} onToggle={note => void perform(async () => { const response = await apiFetch(`/api/v2/math-tutor/desktop/documents/${note.document_id}/retrieval`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({enabled: !note.retrieval_enabled})}); if (!response.ok) throw new Error("资料检索设置未保存。"); setNotes(await api<VaultNote[]>(`/libraries/${sid}/notes`)); })} />
          <details className="mt-knowledge-details"><summary><Settings2 className="h-4 w-4" aria-hidden="true" />知识库选项<ChevronRight className="ml-auto h-4 w-4" aria-hidden="true" /></summary><div className="flex flex-wrap gap-2 pt-4"><button className={button} disabled={busy} onClick={() => void perform(async () => { const res = await apiFetch(`/api/v2/math-tutor/desktop/content/libraries/${sid}/export`); if (!res.ok) throw new Error("导出失败。"); const url = URL.createObjectURL(await res.blob()); const a = document.createElement("a"); a.href = url; a.download = "mathtutor-vault.zip"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); })}><Download className="h-4 w-4" aria-hidden="true" />导出共享资料库</button><button className={button} disabled={busy} onClick={() => void perform(async () => { await api(`/libraries/${sid}/enabled`, {enabled: !library.enabled}, "PUT"); await refresh(); })}>{library.enabled ? "停用整个知识库检索" : "启用知识库检索"}</button><button className={`${button} mt-btn-danger`} disabled={busy} onClick={() => { if (window.confirm("删除该库及其不被其他库保留的资料？正文、历史版本和索引将被删除，无法撤销。")) void perform(async () => { await api(`/libraries/${sid}`, undefined, "DELETE"); setSid(""); setSource(null); setBody(""); await refresh(); }); }}><Trash2 className="h-4 w-4" aria-hidden="true" />删除知识库</button></div></details>
        </section> : !source ? <section className={`${panel} mt-knowledge-welcome`}><span className="mt-tool-empty-icon"><Layers3 className="h-7 w-7" aria-hidden="true" /></span><h2>给学习资料一个清楚的位置</h2><p>选择左侧资料库，逐份查看与编辑，或导入其他人分享的题库。Markdown 文件夹层级会保留。</p><div className="mt-knowledge-steps"><span><b>01</b> 建立知识库</span><span><b>02</b> 放入学习资料</span><span><b>03</b> 编辑与分享</span></div></section> : null}
        {(library || source) && <section className={`${panel} space-y-5`} aria-label={citation ? "引用原文" : "笔记编辑与预览"}><div className="flex flex-wrap items-center justify-between gap-3"><h2 className="flex items-center gap-2 text-base font-semibold"><FileText className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />{citation ? "引用原文" : source ? "查看与编辑笔记" : "写一份新笔记"}</h2>{dirty && <span className="mt-tool-badge" data-tone="warning">未保存</span>}</div>
          {source && <details className="mt-knowledge-details"><summary>版本与出处<ChevronRight className="ml-auto h-4 w-4" aria-hidden="true" /></summary><p className="break-all pt-3 font-mono text-xs leading-6">{source.title} · v{source.version}{source.line_start && ` · L${source.line_start}–${source.line_end}`}<br />SHA256 {source.body_hash}</p></details>}
          {!citation && source && (notes.find(note => note.document_id === source.document_id)?.provenance?.relative_paths?.length || 0) > 1 && <p className="mt-tool-message text-sm leading-7">这份笔记位于多个文件夹，共用正文、版本与检索状态。修改正文会同步到所有位置；修改文件位置只移动当前打开的这一处。</p>}
          {citation ? <pre className="whitespace-pre-wrap break-words rounded-xl bg-[var(--paper)] p-4 font-sans text-base leading-7">{body}</pre> : <><div className="grid gap-4 sm:grid-cols-2"><label className="mt-field">笔记标题<input className={input} value={title} placeholder="给笔记起个名字" onChange={e => { setTitle(e.target.value); setDirty(true); op.current = ""; }} /></label><label className="mt-field">标签<span className="sr-only">（逗号分隔）</span><input className={input} value={tags} placeholder="函数、错题，用逗号分隔" onChange={e => { setTags(e.target.value); setDirty(true); op.current = ""; }} /></label></div>
            <label className="mt-field">文件位置<input className={input} value={relativePath} maxLength={512} placeholder={title ? `${title.replace(/[\\/]/g, "-").replace(/\.md$/, "")}.md` : "例如：高二/导数/课堂练习.md"} readOnly={Boolean(source && source.provenance?.format !== "markdown")} onChange={e => { setRelativePath(e.target.value); setDirty(true); op.current = ""; }} /><span className="text-xs font-normal leading-5 text-[var(--muted-foreground)]">资料库内的相对路径；保存时保留文件夹，不能访问系统目录。</span></label>
            <div className="grid gap-4 xl:grid-cols-2"><label className="mt-field min-w-0">Markdown 正文<textarea className={`${input} min-h-64 font-mono leading-7`} value={body} placeholder="记录知识点、推导过程或复习问题…" readOnly={Boolean(source && source.provenance?.format !== "markdown")} onChange={e => { setBody(e.target.value); setDirty(true); op.current = ""; }} /></label><div className="mt-note-preview min-w-0"><h3 className="mb-3 text-xs font-semibold text-[var(--muted-foreground)]">阅读预览</h3><MarkdownRenderer content={body || "你的笔记会显示在这里。"} /></div></div><div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs leading-5 text-[var(--muted-foreground)]">{source && source.provenance?.format !== "markdown" ? "导入文档以原文查看；你可以新建笔记整理内容。" : "每次保存保留历史版本；预览不执行 HTML、插件或远程图片。"}</p><button className={`${button} mt-btn-primary`} disabled={busy || !sid || !title.trim() || !body.trim() || Boolean(source && source.provenance?.format !== "markdown")} onClick={() => void perform(save)}><Check className="h-4 w-4" aria-hidden="true" />{source ? "保存新版本" : "保存新笔记"}</button></div>
            {source?.links?.length ? <p className="text-sm">链接到：{source.links.map(link => <button key={link} className={`${button} m-1`} onClick={() => { const target = notes.find(n => n.title.replace(/\.md$/, "") === link || n.title === link); if (target) void perform(() => openNote(target.document_id)); else setError("链接目标未在当前库找到，请导入或选择其所属库。"); }}>{link}</button>)}</p> : null}{source?.backlinks?.length ? <p className="text-sm">被引用：{source.backlinks.map(n => <button className={`${button} m-1`} key={n.document_id} onClick={() => void perform(() => openNote(n.document_id))}>{n.title}</button>)}</p> : null}
          </>}
        </section>}
        {drafts.length > 0 && <section className={`${panel} space-y-4`}><h2 className="text-base font-semibold">待整理的笔记草稿</h2><p className="text-sm leading-6 text-[var(--muted-foreground)]">先预览，再决定是否保存到所选知识库。</p>{drafts.map(d => <details key={d.draft_id} className="mt-knowledge-details"><summary>{d.title}<ChevronRight className="ml-auto h-4 w-4 shrink-0" aria-hidden="true" /></summary><div className="py-4"><MarkdownRenderer content={d.markdown} /></div><button className={button} disabled={busy || !sid} onClick={() => void perform(async () => { await api(`/drafts/${d.draft_id}/save`, {space_id: sid}); setNotes(await api<VaultNote[]>(`/libraries/${sid}/notes`)); setNotice("已保存到当前选择的库；重复保存不会新增副本。"); })}><Plus className="h-4 w-4" aria-hidden="true" />保存新笔记到所选库</button></details>)}</section>}
      </div>
    </div>
    </> : <TeachingSkills />}
  </div>;
}
