"use client";

import Link from "next/link";
import { Code2, FileOutput, FolderOpen, Loader2, LockKeyhole, Puzzle, RefreshCw, Trash2, Wand2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";

type Workspace = { workspace_id: string; name: string; readable: boolean; writable: boolean; expires: string };
type Catalog = { api_version: string; sdk: { registration: string; execution: string; sandbox: boolean; user_installation: boolean };
  skills: Array<{ id: string; name: string; description: string; enabled: boolean; source: string; activation?: string }>;
  tools: Array<{ name: string; title?: string; description: string; active: boolean; activation?: string; source: string; input_schema: unknown }>;
  workspaces: Workspace[] };
const prefix = "/api/v2/math-tutor/desktop/creator";
async function request<T>(path: string, body?: unknown, method?: string): Promise<T> {
  const response = await apiFetch(prefix + path, { method: method || (body === undefined ? "GET" : "POST"), headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!response.ok) { const value = await response.json().catch(() => ({})); throw new Error(typeof value.detail === "string" ? value.detail : "操作未完成，请重试。"); }
  return response.json() as Promise<T>;
}

export default function CreatorCapabilities({ section }: { section: "skills" | "extensions" }) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [directory, setDirectory] = useState("");
  const [writable, setWritable] = useState(false);
  const refresh = useCallback(async () => { setLoading(true); setError(""); try { setCatalog(await request<Catalog>("/catalog")); return true; } catch (e) { setCatalog(null); setError(e instanceof Error ? e.message : "扩展列表暂时无法读取。"); return false; } finally { setLoading(false); } }, []);
  useEffect(() => { void refresh(); }, [refresh]);
  const perform = async (action: () => Promise<void>) => { setBusy(true); setError(""); setNotice(""); try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成。"); } finally { setBusy(false); } };
  return <section className="space-y-5" aria-label={section === "skills" ? "教学技能管理" : "智能体能力扩展"}>
    <div className="mt-card flex items-start gap-4 p-5 sm:p-6"><span className="mt-tool-heading-icon">{section === "skills" ? <Wand2 className="h-5 w-5" aria-hidden="true" /> : <Puzzle className="h-5 w-5" aria-hidden="true" />}</span><div><h2 className="text-lg font-semibold">{section === "skills" ? "决定智能体如何教" : "让智能体能够做更多事"}</h2><p className="mt-2 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">{section === "skills" ? "教学技能提供讲解方法与工作流程。学习资料中的文字会作为参考内容，导入名为 SKILL.md 的文件不会自动启用技能。" : "工具扩展提供实际操作能力。下面展示当前应用已注册的工具；文件读写需要你另外选定可访问的文件夹。"}</p></div></div>
    {error && <div className="mt-knowledge-alert" role="alert"><p>{error}</p><button type="button" className="mt-btn min-h-11" disabled={busy} onClick={() => void refresh()}><RefreshCw className="h-4 w-4" aria-hidden="true" />重新读取</button></div>}
    {notice && <p role="status" className="text-sm leading-6 text-[var(--primary-text)]">{notice}</p>}
    {loading ? <p role="status" className="mt-tool-loading"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />正在读取已注册能力…</p> : catalog && <>
      {section === "skills" ? <div className="mt-creator-grid">{catalog.skills.map(skill => <article key={skill.id} className="mt-card space-y-3 p-5"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{skill.name}</h3><span className="mt-tool-badge" data-tone={skill.enabled ? "active" : undefined}>{skill.enabled ? skill.activation || "已加载" : "未启用"}</span></div><p className="text-sm leading-7 text-[var(--muted-foreground)]">{skill.description}</p><p className="text-xs text-[var(--muted-foreground)]">{skill.source === "builtin" ? "应用内置" : "由应用配置加载"}</p></article>)}</div> : <>
        <section className="mt-card space-y-5 p-5 sm:p-6" aria-label="文件读写文件夹">
          <div className="flex items-start gap-3"><FileOutput className="mt-1 h-5 w-5 shrink-0 text-[var(--primary-text)]" aria-hidden="true" /><div><h3 className="text-base font-semibold">文件读写</h3><p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">让智能体读取学习笔记，或把整理好的内容写成文件。仅限你选中的文件夹，支持 Markdown、TXT、JSON、CSV 和 TSV，每个文件最多 64 KB。</p></div></div>
          <div className="mt-creator-workspaces">{catalog.workspaces.map(workspace => <div className="mt-creator-workspace" key={workspace.workspace_id}><FolderOpen className="h-5 w-5 shrink-0 text-[var(--primary-text)]" aria-hidden="true" /><div className="min-w-0 flex-1"><p className="break-words text-sm font-medium">{workspace.name}</p><p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">{workspace.writable ? "允许读取与写入" : "仅允许读取"} · 本次运行有效</p></div><button type="button" className="mt-icon-button" aria-label={`撤销${workspace.name}的访问权限`} disabled={busy} onClick={() => void perform(async () => { await request(`/workspaces/${encodeURIComponent(workspace.workspace_id)}`, undefined, "DELETE"); if (await refresh()) setNotice("访问权限已撤销，后续工具调用无法继续访问此文件夹。"); })}><Trash2 className="h-4 w-4" aria-hidden="true" /></button></div>)}</div>
          {!catalog.workspaces.length && <p className="rounded-xl border border-dashed border-[var(--border)] px-4 py-3 text-sm leading-6 text-[var(--muted-foreground)]">尚未允许访问任何文件夹。文件工具不会出现在智能体可调用的列表里。</p>}
          <div className="space-y-3 border-t border-[var(--border)] pt-4"><div className="flex flex-wrap items-center gap-3"><button type="button" className="mt-btn min-h-11" disabled={busy} onClick={() => void perform(async () => { const value = await request<{ path: string | null; cancelled: boolean }>("/workspaces/pick", {}); if (value.path) setDirectory(value.path); })}><FolderOpen className="h-4 w-4" aria-hidden="true" />选择文件夹</button><p className="text-xs leading-5 text-[var(--muted-foreground)]">选择后确认访问方式，再添加授权。</p></div>
            <form className="space-y-3" onSubmit={event => { event.preventDefault(); void perform(async () => { await request("/workspaces", { path: directory.trim(), writable }); setDirectory(""); setWritable(false); if (await refresh()) setNotice("文件夹访问权限已添加，可返回对话让智能体使用文件工具。"); }); }}>
              <label className="mt-field">文件夹完整路径<input className="mt-input min-h-11" value={directory} maxLength={4096} onChange={event => setDirectory(event.target.value)} placeholder="选择文件夹，或手动输入完整路径" disabled={busy} required autoComplete="off" spellCheck={false} /></label>
              <label className="mt-scope-toggle"><input type="checkbox" className="mt-1 h-4 w-4 shrink-0 accent-[var(--primary)]" checked={writable} disabled={busy} onChange={event => setWritable(event.target.checked)} /><span><span className="block text-sm font-medium">同时允许创建与更新文本文件</span><span className="mt-1 block text-xs leading-5 text-[var(--muted-foreground)]">默认只读。更新已有文件必须核对原内容，避免覆盖尚未读取的修改。</span></span></label>
              <button className="mt-btn mt-btn-primary min-h-11" disabled={busy || !directory.trim()}>{busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <LockKeyhole className="h-4 w-4" aria-hidden="true" />}添加{writable ? "读写" : "只读"}授权</button>
            </form>
            <p className="text-xs leading-6 text-[var(--muted-foreground)]">授权在退出或重启应用后失效；恢复备份也不会恢复文件访问权限。学习资料范围与文件读写权限分别管理。</p>
            <p className="text-xs leading-6 text-[var(--muted-foreground)]">使用读取工具时，读取到的文件内容会提供给当前对话所配置的模型，用于完成你的请求。</p>
          </div>
        </section>
        <section aria-label="已注册工具" className="mt-creator-grid">{catalog.tools.map(tool => <article key={tool.name} className="mt-card min-w-0 space-y-3 p-5"><div className="flex flex-wrap items-start justify-between gap-2"><h3 className="break-words font-semibold">{tool.title || tool.name}</h3><span className="mt-tool-badge" data-tone={tool.active ? "active" : undefined}>{tool.activation || (tool.active ? "可用" : "未启用")}</span></div><p className="text-sm leading-7 text-[var(--muted-foreground)]">{tool.description}</p><details className="mt-knowledge-details"><summary><Code2 className="h-4 w-4" aria-hidden="true" />创作者接口</summary><pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-[var(--sidebar)] p-3 text-xs leading-6">{JSON.stringify({ name: tool.name, parameters: tool.input_schema }, null, 2)}</pre></details></article>)}</section>
      </>}
      <details className="mt-card p-5"><summary className="flex min-h-11 cursor-pointer items-center gap-2 text-sm font-medium"><Code2 className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />为 MathTutor 创建新能力</summary><div className="mt-3 space-y-3 text-sm leading-7 text-[var(--muted-foreground)]"><p>创作者可通过版本化 SDK 注册教学技能、工具参数与执行处理器。文件读写是可用示例，代码与离线运行示例随开源项目提供。</p><p>社区中的声明式教学插件可安装、配置和管理版本。Python SDK 处理器由可信应用启动配置加载，在应用进程中运行。</p><Link className="mt-btn min-h-11" href="/math-tutor/community?tab=plugins"><Puzzle className="h-4 w-4" aria-hidden="true" />管理社区插件</Link><code className="block break-all rounded-lg bg-[var(--sidebar)] px-3 py-2 text-xs">{catalog.api_version}</code></div></details>
    </>}
  </section>;
}
