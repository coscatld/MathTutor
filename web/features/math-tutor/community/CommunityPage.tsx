"use client";

import Link from "next/link";
import {useSearchParams} from "next/navigation";
import {Check, FileUp, FolderInput, FolderOpen, Library, Loader2, Puzzle, RefreshCw, Upload} from "lucide-react";
import {useCallback, useEffect, useRef, useState} from "react";
import {apiFetch} from "@/lib/api";
import {requestTutorNavigation} from "../lib/navigation-guard";
import {knowledgeApi, type Library as PersonalLibrary} from "../knowledge/api";
import {communityApi, communityRoot, notifyPluginsChanged, type PluginRecord} from "./api";
import {communityView, documentPath, prepareDocuments, type CommunityView} from "./imports";
import PluginWorkbench from "./PluginWorkbench";

type ImportResult = {kind: "plugin" | "question-pack"; plugin?: PluginRecord; space_id?: string; name?: string; imported_count?: number; warnings?: string[]; detail?: unknown};

export default function CommunityPage() {
  const requested = useSearchParams().get("tab"), [view, setView] = useState<CommunityView>(communityView(requested));
  const [plugins, setPlugins] = useState<PluginRecord[]>([]), [libraries, setLibraries] = useState<PersonalLibrary[]>([]);
  const [loading, setLoading] = useState(true), [busy, setBusy] = useState(false), [loadError, setLoadError] = useState(""), [error, setError] = useState(""), [notice, setNotice] = useState(""), [warnings, setWarnings] = useState<string[]>([]), [receipt, setReceipt] = useState<ImportResult | null>(null);
  const filesInput = useRef<HTMLInputElement>(null), folderInput = useRef<HTMLInputElement>(null), pluginInput = useRef<HTMLInputElement>(null), working = useRef(false), readVersion = useRef(0);
  const documentOperation = useRef<{key: string; id: string} | null>(null), pluginOperation = useRef<{key: string; id: string} | null>(null);
  // A manual tab choice remains in place until the URL query changes.
  useEffect(() => {const next = communityView(requested); if (next !== view) {setLoading(true); setView(next);}}, [requested]);
  const loadLibraries = useCallback(async () => {
    const version = ++readVersion.current; setLoading(true); setLoadError("");
    try { const rows = await knowledgeApi<PersonalLibrary[]>("/libraries"); if (version === readVersion.current) setLibraries(rows); }
    catch (cause) { if (version === readVersion.current) {setLibraries([]); setLoadError(cause instanceof Error ? cause.message : "个人资料暂时无法读取。");} }
    finally { if (version === readVersion.current) setLoading(false); }
  }, []);
  const loadPlugins = useCallback(async () => {
    const version = ++readVersion.current; setLoading(true); setLoadError("");
    try { const rows = (await communityApi<{items: PluginRecord[]}>("/plugins")).items; if (version === readVersion.current) setPlugins(rows); }
    catch (cause) { if (version === readVersion.current) {setPlugins([]); setLoadError(cause instanceof Error ? cause.message : "已安装的插件暂时无法读取。");} }
    finally { if (version === readVersion.current) setLoading(false); }
  }, []);
  useEffect(() => { void (view === "documents" ? loadLibraries() : loadPlugins()); }, [view, loadLibraries, loadPlugins]);
  const action = async (work: () => Promise<void>) => {
    if (working.current) return;
    working.current = true; setBusy(true); setError(""); setNotice("");
    try { await work(); } catch (cause) { setError(cause instanceof Error ? cause.message : "操作未完成，请重试。"); }
    finally { working.current = false; setBusy(false); }
  };
  const updatePlugin = (record: PluginRecord) => {setPlugins(current => current.some(item => item.plugin.id === record.plugin.id) ? current.map(item => item.plugin.id === record.plugin.id ? record : item) : [...current, record]); notifyPluginsChanged();};
  const readImport = async (path: string, body: FormData) => {
    const response = await apiFetch(communityRoot + path, {method: "POST", body}), value = await response.json() as ImportResult;
    if (!response.ok) throw new Error(typeof value.detail === "string" ? value.detail : "文件没有导入，请检查后重试。");
    return value;
  };
  const importDocuments = async (selected: File[], folder = false) => {
    if (!selected.length) return;
    await action(async () => {
      const {files, skipped} = prepareDocuments(selected, folder), key = files.map(file => `${documentPath(file)}:${file.size}:${file.lastModified}`).join("|");
      if (documentOperation.current?.key !== key) documentOperation.current = {key, id: crypto.randomUUID()};
      const body = new FormData(); files.forEach(file => body.append("files", file, documentPath(file))); body.append("operation_id", documentOperation.current.id);
      const result = await readImport("/documents/import", body);
      if (result.kind !== "question-pack" || !result.space_id) throw new Error("资料未完成导入，请重新尝试。");
      documentOperation.current = null; setReceipt(result); setWarnings([...(result.warnings || []), ...(skipped ? [`已跳过 ${skipped} 个非文本或隐藏文件。`] : [])]); setNotice("学习资料已导入你的知识库。"); await loadLibraries();
    });
  };
  const importPlugin = async (file?: File) => {
    if (!file) return;
    await action(async () => {
      if (file.size > 32 * 1024 * 1024) throw new Error("文件有些大，请选择小于 32 MB 的插件。");
      const key = `${file.name}:${file.size}:${file.lastModified}`;
      if (pluginOperation.current?.key !== key) pluginOperation.current = {key, id: crypto.randomUUID()};
      const body = new FormData(); body.append("file", file); body.append("operation_id", pluginOperation.current.id);
      const result = await readImport("/plugins/import", body);
      if (result.kind !== "plugin" || !result.plugin) throw new Error("插件未完成导入，请重新尝试。");
      updatePlugin(result.plugin); pluginOperation.current = null; setWarnings(result.warnings || []); setNotice(result.plugin.enabled ? "插件已导入，可以直接使用。" : "插件已导入。确认需要使用的资料后，点击启用即可。"); await loadPlugins();
    });
  };
  const chooseView = (next: CommunityView) => {if (busy || next === view || !requestTutorNavigation()) return; setLoading(true); setView(next); setError(""); setNotice(""); setWarnings([]);};
  return <div className="mt-page community-page">
    <header className="community-header"><div><p className="mt-eyebrow"><Upload aria-hidden="true" />导入资料与插件</p><h1>社区</h1><p>管理自己导入的学习资料与插件。</p></div></header>
    <nav className="community-tabs" aria-label="社区内容"><button type="button" aria-pressed={view === "documents"} disabled={busy} onClick={() => chooseView("documents")}><FolderOpen className="h-4 w-4" aria-hidden="true" />发现资源</button><button type="button" aria-pressed={view === "plugins"} disabled={busy} onClick={() => chooseView("plugins")}><Puzzle className="h-4 w-4" aria-hidden="true" />我的插件</button></nav>
    {view === "documents" ? <section className="community-import" aria-label="导入学习资料"><span className="community-import-icon"><FolderInput aria-hidden="true" /></span><div><h2>导入自己的学习资料</h2><p className="community-muted mt-2">可以选择学习笔记、文本资料或已有题库，也可以一次导入整个笔记文件夹。</p></div><div className="community-actions"><input ref={filesInput} type="file" hidden multiple accept=".md,.markdown,.txt,.zip,.mathtutor,.json" onChange={event => {void importDocuments(Array.from(event.target.files || [])); event.target.value = "";}} /><input ref={folderInput} type="file" hidden multiple onChange={event => {void importDocuments(Array.from(event.target.files || []), true); event.target.value = "";}} /><button type="button" className="mt-btn mt-btn-primary min-h-11" disabled={busy} onClick={() => filesInput.current?.click()}><FileUp className="h-4 w-4" aria-hidden="true" />导入文件</button><button type="button" className="mt-btn min-h-11" disabled={busy} onClick={() => {folderInput.current?.setAttribute("webkitdirectory", ""); folderInput.current?.click();}}><FolderInput className="h-4 w-4" aria-hidden="true" />导入文件夹</button></div></section> : <section className="community-import" aria-label="导入插件"><span className="community-import-icon"><Puzzle aria-hidden="true" /></span><div><h2>导入下载的插件</h2><p className="community-muted mt-2">选择插件文件即可导入。代码插件只应从你信任的作者处获取，导入后需要另行确认启用。</p></div><input ref={pluginInput} type="file" hidden accept=".mtplugin,.mathtutor,.json,.py,.ts,.zip" onChange={event => {void importPlugin(event.target.files?.[0]); event.target.value = "";}} /><button type="button" className="mt-btn mt-btn-primary min-h-11" disabled={busy} onClick={() => pluginInput.current?.click()}><Upload className="h-4 w-4" aria-hidden="true" />导入插件</button></section>}
    {error ? <p role="alert" className="community-alert">{error}</p> : null}
    {notice || busy ? <p role="status" className="community-notice">{busy ? <><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在处理，请稍候…</> : <><Check className="h-4 w-4" aria-hidden="true" />{notice}</>}</p> : null}
    {warnings.map((warning, index) => <p key={index} role="status" className="community-muted">{warning}</p>)}
    {view === "documents" && receipt ? <section className="community-import-receipt" aria-label="资料导入结果"><div><h3>{receipt.name || "学习资料已导入"}</h3>{typeof receipt.imported_count === "number" ? <p className="community-muted mt-2">已导入 {receipt.imported_count} 份资料</p> : null}</div><Link href={`/math-tutor/knowledge?library=${encodeURIComponent(receipt.space_id || "")}`} className="mt-btn min-h-11"><Library className="h-4 w-4" aria-hidden="true" />查看导入的资料</Link></section> : null}
    {loadError ? <div role="alert" className="community-alert"><p>{loadError}</p><button type="button" className="mt-btn min-h-11" disabled={loading || busy} onClick={() => void (view === "documents" ? loadLibraries() : loadPlugins())}><RefreshCw className="h-4 w-4" aria-hidden="true" />重新读取</button></div> : loading ? <p role="status" className="mt-tool-loading"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在读取{view === "documents" ? "个人资料" : "已安装插件"}…</p> : view === "plugins" ? <PluginWorkbench records={plugins} busy={busy} action={action} update={updatePlugin} reload={loadPlugins} /> : <section className="community-stack" aria-label="个人资料"><h2>我的学习资料</h2>{libraries.length ? <ul className="community-library-list">{libraries.map(library => <li key={library.space_id}><div><h3>{library.name}</h3><p className="community-muted mt-1">{library.kind === "session" ? "对话资料" : library.kind === "course" ? "课程与题库" : "个人笔记"}</p></div><Link href={`/math-tutor/knowledge?library=${encodeURIComponent(library.space_id)}`} className="mt-btn min-h-11">打开资料</Link></li>)}</ul> : <div className="community-empty"><FolderOpen aria-hidden="true" /><h3>还没有导入学习资料</h3><p>选择自己的文件或笔记文件夹，导入后会显示在这里。</p></div>}</section>}
  </div>;
}
