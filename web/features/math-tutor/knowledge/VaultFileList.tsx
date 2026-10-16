"use client";

import { ChevronRight, FileText, Folder, FolderOpen } from "lucide-react";
import type { Note } from "./api";

export type VaultNote = Note & { provenance?: { relative_path?: string; relative_paths?: string[]; origin?: string } };

export function vaultPath(note: VaultNote): string {
  const value = note.provenance?.relative_path || note.title;
  const parts = value.replace(/\\/g, "/").split("/");
  return parts.some(part => !part || part === ".." || part.startsWith(".")) ? note.title : parts.join("/");
}

/** A document may have several imported locations sharing one body and version. */
export function vaultLocations(note: VaultNote): VaultNote[] {
  const paths = note.provenance?.relative_paths?.length ? note.provenance.relative_paths : [vaultPath(note)];
  const unique = [...new Set(paths.map(path => vaultPath({ ...note, provenance: { ...note.provenance, relative_path: path } })))];
  return unique.map(path => ({ ...note, provenance: { ...note.provenance, relative_path: path, relative_paths: unique } }));
}

export function vaultEntries(notes: VaultNote[], folder: string, query: string) {
  const locations = notes.flatMap(vaultLocations);
  const term = query.trim().toLocaleLowerCase();
  if (term) return { folders: [] as Array<{ name: string; path: string; count: number }>,
    files: locations.filter(note => `${vaultPath(note)} ${note.title} ${note.tags.join(" ")}`.toLocaleLowerCase().includes(term)) };
  const prefix = folder ? `${folder}/` : "";
  const folders = new Map<string, number>();
  const files: VaultNote[] = [];
  for (const note of locations) {
    const relative = vaultPath(note);
    if (!relative.startsWith(prefix)) continue;
    const remainder = relative.slice(prefix.length);
    if (remainder.includes("/")) {
      const name = remainder.split("/")[0];
      folders.set(name, (folders.get(name) || 0) + 1);
    } else files.push(note);
  }
  return { folders: [...folders].sort(([a], [b]) => a.localeCompare(b, "zh-CN"))
    .map(([name, count]) => ({ name, path: prefix + name, count })), files };
}

export default function VaultFileList({ notes, folder, query, name, selected, selectedPath, busy, onFolder, onOpen, onToggle }:
  { notes: VaultNote[]; folder: string; query: string; name: string; selected?: string; selectedPath?: string; busy: boolean;
    onFolder: (path: string) => void; onOpen: (note: VaultNote) => void; onToggle: (note: VaultNote) => void }) {
  const entries = vaultEntries(notes, folder, query);
  return <div className="min-w-0">
    <nav className="mt-vault-breadcrumbs" aria-label="资料文件夹路径">
      <button type="button" disabled={busy} onClick={() => onFolder("")}><FolderOpen className="h-4 w-4 shrink-0" aria-hidden="true" />{name}</button>
      {folder.split("/").filter(Boolean).map((part, index, all) => <span key={index} className="inline-flex min-w-0 items-center gap-1"><ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden="true" /><button type="button" disabled={busy} onClick={() => onFolder(all.slice(0, index + 1).join("/"))}>{part}</button></span>)}
    </nav>
    <ul className="mt-vault-files" aria-label="资料文件列表">
      {entries.folders.map(entry => <li key={`folder:${entry.path}`}><button type="button" className="mt-vault-folder" disabled={busy} onClick={() => onFolder(entry.path)}><Folder className="h-5 w-5 shrink-0 text-[var(--primary-text)]" aria-hidden="true" /><span className="min-w-0 flex-1 break-words text-left font-medium">{entry.name}</span><span className="text-xs text-[var(--muted-foreground)]">{entry.count} 份资料</span><ChevronRight className="h-4 w-4 shrink-0" aria-hidden="true" /></button></li>)}
      {entries.files.map(note => { const path = vaultPath(note); const active = selected === note.document_id && (!selectedPath || selectedPath === path); return <li key={`${note.document_id}:${path}`} className="mt-vault-file" data-selected={active}>
        <FileText className="mt-3 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" />
        <button type="button" className="mt-note-open min-h-11" disabled={busy} onClick={() => onOpen(note)} aria-current={active ? "true" : undefined}>
          <span className="block break-words text-sm font-medium">{path.split("/").at(-1) || note.title}</span>
          <span className="mt-1 block break-words text-xs leading-5 text-[var(--muted-foreground)]">{query && path !== note.title ? `${path} · ` : ""}v{note.version} · {note.editable ? "Markdown · 可编辑" : "导入文档"}{(note.provenance?.relative_paths?.length || 0) > 1 ? ` · 共享正文（${note.provenance!.relative_paths!.length} 个位置）` : ""}{note.tags.length ? ` · ${note.tags.join(" / ")}` : ""}</span>
        </button>
        <button type="button" className="mt-tool-badge min-h-11 shrink-0" data-tone={note.retrieval_enabled ? "active" : undefined} disabled={busy} onClick={() => onToggle(note)} aria-label={`${note.retrieval_enabled ? "停用" : "启用"}${note.title}的检索`}>{note.retrieval_enabled ? "检索已开" : "检索已关"}</button>
      </li>; })}
    </ul>
    {!entries.files.length && !entries.folders.length && <div className="mt-tool-empty"><FolderOpen className="mx-auto h-7 w-7 text-[var(--muted-foreground)]" aria-hidden="true" /><h3>{query ? "没有匹配的资料" : "这个文件夹还没有资料"}</h3><p>{query ? "试试资料名称、文件夹路径或标签。" : "导入共享题库、Markdown 文件夹，或在这里新建笔记。"}</p></div>}
  </div>;
}
