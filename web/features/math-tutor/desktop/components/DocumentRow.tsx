"use client";

import { Check, FileText, Loader2, Pencil, RefreshCw, Trash2, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { formatBytes, formatDateTime, renameDocument, reparseDocument, setDocumentGlobal } from "../lib/desktop-api";
import { documentStatusLabel } from "../lib/labels";
import type { DesktopDocument } from "../types";

const STATUS_DOT: Record<string, string> = {
  ready: "bg-emerald-500",
  ready_with_warnings: "bg-amber-500",
  importing: "bg-[var(--primary)]",
  parsing: "bg-[var(--primary)]",
  needs_ocr: "bg-orange-500",
  failed: "bg-red-500",
};

function canToggleRetrieval(document: DesktopDocument): boolean {
  return (
    (document.status === "ready" || document.status === "ready_with_warnings") &&
    document.chunk_count > 0
  );
}

export default function DocumentRow({
  document,
  busy,
  onToggleRetrieval,
  onDelete,
  onUpdated,
}: {
  document: DesktopDocument;
  busy: boolean;
  onToggleRetrieval: (enabled: boolean) => Promise<void>;
  onDelete: () => Promise<void>;
  onUpdated: (doc: DesktopDocument) => void;
}) {
  const [busyReparse, setBusyReparse] = useState(false);
  const [scopeBusy, setScopeBusy] = useState(false);
  const [scopeError, setScopeError] = useState("");
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(document.filename);

  const handleReparse = async () => {
    setBusyReparse(true);
    try {
      onUpdated(await reparseDocument(document.document_id));
    } catch {
      // Silent: parent refresh surfaces the error state.
    } finally {
      setBusyReparse(false);
    }
  };

  return (
    <li className="mt-card flex flex-col gap-3 p-4">
      {scopeError ? <p role="alert" className="text-sm text-[var(--destructive)]">{scopeError}</p> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[var(--primary-soft)]">
            <FileText className="h-5 w-5 text-[var(--primary-text)]" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            {editing ? <div className="flex items-center gap-1"><input aria-label="资料名称" value={name} onChange={(event) => setName(event.target.value)} className="h-8 min-w-0 rounded-lg border border-[var(--primary-border)] bg-transparent px-2 text-sm outline-none" /><button type="button" aria-label="保存名称" onClick={async () => { if (!name.trim()) return; onUpdated(await renameDocument(document.document_id, name)); setEditing(false); }} className="rounded-md p-1 text-[var(--success)]"><Check className="h-4 w-4" /></button><button type="button" aria-label="取消重命名" onClick={() => { setName(document.filename); setEditing(false); }} className="rounded-md p-1 text-[var(--muted-foreground)]"><X className="h-4 w-4" /></button></div> : <div className="flex items-center gap-1"><p className="truncate text-sm font-medium text-[var(--foreground)]" title={document.filename}>{document.filename}</p><button type="button" onClick={() => setEditing(true)} aria-label={`重命名 ${document.filename}`} className="rounded p-1 text-[var(--muted-foreground)] hover:text-[var(--primary-text)]"><Pencil className="h-3.5 w-3.5" /></button></div>}
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--muted-foreground)]">
              <span className="inline-flex items-center gap-1">
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${STATUS_DOT[document.status] ?? "bg-[var(--muted-foreground)]"}`} aria-hidden="true" />
                {documentStatusLabel(document.status)}
              </span>
              {document.page_count > 0 ? <span>{document.page_count} 页</span> : null}
              <span>{document.chunk_count} 个分块</span>
              <span>{formatBytes(document.size_bytes)}</span>
              <span>{formatDateTime(document.created_at)}</span>
              {document.is_global ? <span>所有对话可检索</span> : document.conversation_ids?.length ? <span>关联 {document.conversation_ids.length} 个对话</span> : <span>未关联对话</span>}
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <button type="button" disabled={busy || scopeBusy} className="min-h-[44px] rounded-xl border border-[var(--border)] px-3 text-sm hover:bg-[var(--muted)] disabled:opacity-50" onClick={async () => {
            setScopeBusy(true); setScopeError("");
            try { onUpdated(await setDocumentGlobal(document.document_id, !document.is_global)); }
            catch { setScopeError("共享范围未保存，请重试。"); }
            finally { setScopeBusy(false); }
          }}>{scopeBusy ? "保存中…" : document.is_global ? "取消全局共享" : "设为总资料"}</button>
          {(document.status === "failed" || document.status === "needs_ocr") && (
            <button
              type="button"
              onClick={handleReparse}
              disabled={busyReparse || busy}
              className="mt-btn"
            >
              {busyReparse ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
              重新解析
            </button>
          )}
          <button
            type="button"
            onClick={() => onDelete()}
            disabled={busy}
            className="mt-btn mt-btn-danger"
            aria-label={`删除 ${document.filename}`}
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            删除
          </button>
        </div>
      </div>

      {document.error && (
        <p className="mt-note mt-note-danger flex items-start gap-2 px-3 py-2 text-sm">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {document.error}
        </p>
      )}

      {!document.error && document.parse_warning && (
        <p className="mt-note mt-note-warning flex items-start gap-2 px-3 py-2 text-sm">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {document.parse_warning}
        </p>
      )}

      <label className="flex min-h-[44px] cursor-pointer items-center gap-2.5 text-sm text-[var(--foreground)]">
        <input
          type="checkbox"
          checked={document.retrieval_enabled && canToggleRetrieval(document)}
          onChange={(e) => onToggleRetrieval(e.target.checked)}
          disabled={busy || !canToggleRetrieval(document)}
          className="h-4 w-4 cursor-pointer accent-[var(--primary)] disabled:cursor-not-allowed"
        />
        允许 Tutor 检索此资料
      </label>
    </li>
  );
}
