"use client";
import Link from "next/link";
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
  useEffect(() => { void refresh().catch(e => setError(e.message)); }, [refresh]);
  useEffect(() => { if (cid) void api<Mount>(`/conversations/${encodeURIComponent(cid)}`).then(setMount).catch(e => setError(e.message)); }, [cid]);
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
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  const mayDiscard = () => !dirty || window.confirm("笔记有未保存修改，确认放弃这些修改？");
  const openNote = async (did: string) => {
    if (!mayDiscard()) return;
    const row = await api<Source>(`/sources/${did}`);
    setSource(row); setTitle(row.title); setBody(row.body || ""); setTags((row.tags || []).join(", ")); setDirty(false); op.current = "";
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
    setMount(await api<Mount>(`/conversations/${encodeURIComponent(target)}`)); setNotice("会话范围已保存；不会自动扩大范围或联网。");
    window.dispatchEvent(new Event("mathtutor-conversations-changed"));
  };
  const library = libraries.find(l => l.space_id === sid);
  return <div className="mt-page max-w-7xl text-[var(--foreground)]">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="mt-eyebrow">资料有归属，回答有出处</p><h1 className="mt-2">个人知识库</h1><p className="mt-3 max-w-2xl text-sm leading-7">课程库、个人库长期保存；会话资料只属于原会话。每个新会话都需要明确挂载。</p></div><Link className={button} onClick={e => { if (!mayDiscard()) e.preventDefault(); }} href={cid ? `/math-tutor?session=${encodeURIComponent(cid)}` : "/math-tutor"}>返回对话</Link></header>
    {error && <div role="alert" className="rounded-lg border border-red-500 p-3 text-[var(--destructive)]">{error}<button className={`${button} ml-3`} onClick={() => void perform(refresh)}>刷新重试</button></div>}
    <p role="status" className="text-sm" aria-live="polite">{busy ? "正在处理，请稍候…" : notice}</p>
    <div className="grid items-start gap-5 lg:grid-cols-[250px_minmax(0,1fr)]">
      <aside className={`${panel} space-y-4`} aria-label="知识库列表">
        <h2 className="text-lg font-semibold tracking-tight">我的知识库</h2>
        <ul className="space-y-2">{libraries.map(lib => <li key={lib.space_id}><button className={`${button} w-full text-left ${sid === lib.space_id ? "border-[var(--primary)] bg-[var(--muted)]" : ""}`} onClick={() => { if (mayDiscard()) { setSid(lib.space_id); setSource(null); setBody(""); setTitle(""); setDirty(false); } }} aria-pressed={sid === lib.space_id}>{lib.name}<span className="block text-xs text-[var(--muted-foreground)]">{{personal: "个人", course: "课程", session: "会话"}[lib.kind]} · {lib.enabled ? "可检索" : "已禁用"}</span></button></li>)}</ul>
        {!libraries.length && <p className="text-sm">还没有知识库。先建库，再导入两份笔记试试。</p>}
        <form className="space-y-2 border-t border-[var(--border)] pt-4" onSubmit={e => { e.preventDefault(); void perform(async () => { if (kind === "session") await updateMount(mount); const lib = await api<Library>("/libraries", {name, kind, conversation_id: kind === "session" ? cid : ""}); await refresh(); setSid(lib.space_id); setName(""); }); }}>
          <label className="block text-sm">知识库名称<input className={input} value={name} onChange={e => setName(e.target.value)} maxLength={120} required /></label>
          <label className="block text-sm">空间类型<select className={input} value={kind} onChange={e => setKind(e.target.value as Library["kind"])}><option value="personal">个人知识库</option><option value="course">课程知识库</option><option value="session" disabled={!cid}>会话资料</option></select></label>
          <button className={button} disabled={busy || !name.trim()}>创建知识库</button>
        </form>
      </aside>
      <div className="min-w-0 space-y-5">
        {cid && <section className={`${panel} space-y-3`} aria-label="会话挂载"><h2 className="text-lg font-semibold tracking-tight">当前会话 · 明确资料范围</h2>
          <fieldset><legend className="text-sm">挂载的知识库</legend><div className="mt-2 flex flex-wrap gap-2">{libraries.filter(l => l.enabled && (l.kind !== "session" || l.conversation_id === cid)).map(lib => <label key={lib.space_id} className={`${button} flex items-center gap-2`}><input type="checkbox" checked={mount.space_ids.includes(lib.space_id)} onChange={e => setMount({...mount, space_ids: e.target.checked ? [...mount.space_ids, lib.space_id] : mount.space_ids.filter(x => x !== lib.space_id)})} />{lib.name}</label>)}</div></fieldset>
          <div className="grid gap-3 sm:grid-cols-2"><label className="text-sm">对话模式<select className={input} value={mount.mode || "tutor"} onChange={e => setMount({...mount, mode: e.target.value as Mount["mode"]})}><option value="knowledge">知识库问答（不自动出题）</option><option value="tutor">原有数学辅导</option></select></label>
          <label className="text-sm">整理笔记保存到<select className={input} value={mount.save_space_id || ""} onChange={e => setMount({...mount, save_space_id: e.target.value})}><option value="">仅预览，不选保存库</option>{libraries.filter(l => l.enabled).map(l => <option key={l.space_id} value={l.space_id}>{l.name}</option>)}</select></label></div>
          <label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={mount.only_selected} onChange={e => setMount({...mount, only_selected: e.target.checked})} />仅所选资料（未选中任何资料时保持空范围）</label>
          {mount.only_selected && <fieldset><legend className="text-sm">先保存挂载，再选择其中的资料</legend>{mount.available_documents?.map(d => <label className="flex min-h-11 items-center gap-2 break-all text-sm" key={d.document_id}><input type="checkbox" disabled={!d.enabled} checked={mount.document_ids.includes(d.document_id)} onChange={e => setMount({...mount, document_ids: e.target.checked ? [...mount.document_ids, d.document_id] : mount.document_ids.filter(x => x !== d.document_id)})} />{d.title}{!d.enabled && "（不可检索）"}</label>)}</fieldset>}
          <details><summary className="min-h-11 cursor-pointer py-2 text-sm">工具兼容与仅提示</summary><label className="block text-sm">工具协议<select className={input} value={mount.tool_mode || "native"} onChange={e => setMount({...mount, tool_mode: e.target.value as Mount["tool_mode"]})}><option value="native">原生 tools（不支持时请选兼容）</option><option value="structured">结构化 JSON 兼容</option></select></label><label className="flex min-h-11 items-center gap-2 text-sm"><input type="checkbox" checked={mount.hints_only || false} onChange={e => setMount({...mount, hints_only: e.target.checked})} />仅提示：不读取可能含答案的资料</label></details>
          <button className={`${button} bg-[var(--primary)] text-[var(--primary-foreground)]`} disabled={busy} onClick={() => void perform(() => updateMount(mount))}>保存挂载与范围</button>
        </section>}
        {library && <section className={`${panel} space-y-4`} aria-label="知识库资料"><div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-semibold tracking-tight">{library.name}</h2><span className="text-sm">{notes.length} 份资料</span></div>
          <div className="flex flex-wrap gap-2"><input ref={files} type="file" multiple hidden accept=".md,.markdown,.txt,.tex,.pdf" onChange={e => { const picked = Array.from(e.target.files || []); e.target.value = ""; void perform(() => importFiles(picked)); }} /><input ref={folder} type="file" multiple hidden onChange={e => { const picked = Array.from(e.target.files || []); e.target.value = ""; void perform(() => importFiles(picked)); }} />
          <button className={button} disabled={busy} onClick={() => files.current?.click()}>导入文档</button><button className={button} disabled={busy} onClick={() => { folder.current?.setAttribute("webkitdirectory", ""); folder.current?.click(); }}>导入 Markdown 文件夹</button>
          <button className={button} disabled={busy} onClick={() => { if (mayDiscard()) { setSource(null); setTitle(""); setBody(""); setTags(""); setDirty(false); op.current = ""; } }}>新建 Markdown</button>
          <button className={button} disabled={busy} onClick={() => void perform(async () => { const res = await apiFetch(`${root}/libraries/${sid}/export`); if (!res.ok) throw new Error("导出失败。"); const url = URL.createObjectURL(await res.blob()); const a = document.createElement("a"); a.href = url; a.download = "knowledge.zip"; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); })}>导出 ZIP</button>
          <button className={button} disabled={busy} onClick={() => void perform(async () => { await api(`/libraries/${sid}/enabled`, {enabled: !library.enabled}, "PUT"); await refresh(); })}>{library.enabled ? "禁用检索" : "启用检索"}</button>
          <button className={`${button} text-[var(--destructive)]`} disabled={busy} onClick={() => { if (window.confirm("删除该库及其不被其他库保留的资料？正文、历史版本和索引将被删除，无法撤销。")) void perform(async () => { await api(`/libraries/${sid}`, undefined, "DELETE"); setSid(""); setSource(null); setBody(""); await refresh(); }); }}>删除知识库</button></div>
          <button className={button} disabled={busy || !library.enabled} onClick={() => void perform(async () => { const next = makeSessionId(); await updateMount({space_ids: [sid], document_ids: [], only_selected: false, mode: "knowledge", save_space_id: sid}, next); window.location.assign(`/math-tutor?session=${encodeURIComponent(next)}`); })}>新建会话并显式挂载此库</button>
          <label className="block text-sm">按标题或标签筛选<input className={input} value={filter} onChange={e => setFilter(e.target.value)} /></label>
          <ul className="divide-y divide-[var(--border)]">{notes.filter(n => `${n.title} ${n.tags.join(" ")}`.includes(filter)).map(n => <li className="flex flex-wrap items-center justify-between gap-2 py-2" key={n.document_id}><button className={`${button} min-w-0 break-all text-left`} onClick={() => void perform(() => openNote(n.document_id))}>{n.title}<span className="ml-2 text-xs">v{n.version} · {n.tags.join(" / ")}</span></button><button className={button} disabled={busy} onClick={() => void perform(async () => { const res = await apiFetch(`/api/v2/math-tutor/desktop/documents/${n.document_id}/retrieval`, {method: "PATCH", headers: {"Content-Type": "application/json"}, body: JSON.stringify({enabled: !n.retrieval_enabled})}); if (!res.ok) throw new Error("资料检索设置未保存。"); setNotes(await api<Note[]>(`/libraries/${sid}/notes`)); })}>{n.retrieval_enabled ? "禁用此资料" : "启用此资料"}</button></li>)}</ul>
        </section>}
        {(library || source) && <section className={`${panel} space-y-4`} aria-label={citation ? "引用原文" : "笔记编辑与预览"}>
          <h2 className="text-lg font-semibold tracking-tight">{citation ? "引用原文 · 版本与区间" : "Markdown 编辑与预览"}</h2>
          {source && <p className="break-all font-mono text-xs leading-6">{source.title} · v{source.version}{source.line_start && ` · L${source.line_start}–${source.line_end}`}<br />SHA256 {source.body_hash}</p>}
          {citation ? <pre className="whitespace-pre-wrap break-words rounded-lg bg-[var(--muted)] p-4 font-sans text-base leading-7">{body}</pre> : <>
            <label className="block text-sm">笔记标题<input className={input} value={title} onChange={e => { setTitle(e.target.value); setDirty(true); op.current = ""; }} /></label>
            <label className="block text-sm">标签（逗号分隔）<input className={input} value={tags} onChange={e => { setTags(e.target.value); setDirty(true); op.current = ""; }} /></label>
            <div className="grid gap-4 xl:grid-cols-2"><label className="min-w-0 text-sm">Markdown 正文<textarea className={`${input} mt-2 min-h-80 font-mono leading-6`} value={body} readOnly={Boolean(source && source.provenance?.format !== "markdown")} onChange={e => { setBody(e.target.value); setDirty(true); op.current = ""; }} /></label><div className="min-w-0"><h3 className="mb-2 text-sm">预览（不执行 HTML、插件或远程图片）</h3><MarkdownRenderer content={body || "在左侧填写笔记正文。"} /></div></div>
            <button className={`${button} bg-[var(--primary)] text-[var(--primary-foreground)]`} disabled={busy || !sid || !title.trim() || !body.trim() || Boolean(source && source.provenance?.format !== "markdown")} onClick={() => void perform(save)}>{source ? "保存新版本" : "保存新笔记"}</button>
            {source?.links?.length ? <p className="text-sm">链接到：{source.links.map(link => <button key={link} className={`${button} m-1`} onClick={() => { const target = notes.find(n => n.title.replace(/\.md$/, "") === link || n.title === link); if (target) void perform(() => openNote(target.document_id)); else setError("链接目标未在当前库找到，请导入或选择其所属库。"); }}>{link}</button>)}</p> : null}
            {source?.backlinks?.length ? <p className="text-sm">被引用：{source.backlinks.map(n => <button className={`${button} m-1`} key={n.document_id} onClick={() => void perform(() => openNote(n.document_id))}>{n.title}</button>)}</p> : null}
          </>}
        </section>}
        {drafts.length > 0 && <section className={`${panel} space-y-4`}><h2 className="text-lg font-semibold tracking-tight">整理草稿 · 预览与保存</h2>{drafts.map(d => <details key={d.draft_id} className="border-t border-[var(--border)] pt-3"><summary className="min-h-11 cursor-pointer py-2">{d.title}</summary><MarkdownRenderer content={d.markdown} /><button className={`${button} mt-3`} disabled={busy || !sid} onClick={() => void perform(async () => { await api(`/drafts/${d.draft_id}/save`, {space_id: sid}); setNotes(await api<Note[]>(`/libraries/${sid}/notes`)); setNotice("已保存到当前选择的库；重复保存不会新增副本。"); })}>保存新笔记到所选库</button></details>)}</section>}
      </div>
    </div>
  </div>;
}
