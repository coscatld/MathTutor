"use client";

import { FileText, Loader2, RefreshCw, Trash2, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { formatBytes, formatDateTime, reparseDocument } from "../lib/desktop-api";
import { documentStatusLabel } from "../lib/labels";
import type { DesktopDocument } from "../types";

const STATUS_DOT: Record<string, string> = {
  ready: "bg-emerald-500",
  ready_with_warnings: "bg-amber-500",
  importing: "bg-blue-500",
  parsing: "bg-blue-500",
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
    <li className="flex flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#2563EB]/10">
            <FileText className="h-5 w-5 text-[#2563EB]" aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-[var(--foreground)]" title={document.filename}>
              {document.filename}
            </p>
            <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-[var(--muted-foreground)]">
              <span className="inline-flex items-center gap-1">
                <span className={`inline-block h-1.5 w-1.5 rounded-full ${STATUS_DOT[document.status] ?? "bg-[var(--muted-foreground)]"}`} aria-hidden="true" />
                {documentStatusLabel(document.status)}
              </span>
              {document.page_count > 0 ? <span>{document.page_count} 页</span> : null}
              <span>{document.chunk_count} 个分块</span>
              <span>{formatBytes(document.size_bytes)}</span>
              <span>{formatDateTime(document.created_at)}</span>
            </p>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {(document.status === "failed" || document.status === "needs_ocr") && (
            <button
              type="button"
              onClick={handleReparse}
              disabled={busyReparse || busy}
              className="inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {busyReparse ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
              重新解析
            </button>
          )}
          <button
            type="button"
            onClick={() => onDelete()}
            disabled={busy}
            className="inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm font-medium text-red-600 transition-colors duration-200 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            aria-label={`删除 ${document.filename}`}
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            删除
          </button>
        </div>
      </div>

      {document.error && (
        <p className="flex items-start gap-2 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          {document.error}
        </p>
      )}

      {!document.error && document.parse_warning && (
        <p className="flex items-start gap-2 rounded-xl bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-400">
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
          className="h-4 w-4 cursor-pointer accent-[#2563EB] disabled:cursor-not-allowed"
        />
        参与个性化回忆（用于生成针对性练习）
      </label>
    </li>
  );
}
