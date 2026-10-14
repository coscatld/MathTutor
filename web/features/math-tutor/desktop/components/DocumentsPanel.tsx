"use client";

import { FilePlus2, FolderOpen, Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteDocument,
  DesktopApiError,
  fetchDocuments,
  fetchEmbeddingSettings,
  importDocumentFile,
  nativePickAndImport,
  toggleDocumentRetrieval,
  setDocumentGlobal,
  fetchDocumentDestinations,
} from "../lib/desktop-api";
import type { DesktopDocument, EmbeddingSettings } from "../types";
import DocumentRow from "./DocumentRow";
import DocumentGroups from "./DocumentGroups";
import EmbeddingStatusBadge from "./EmbeddingStatusBadge";
import { useToast } from "./ToastProvider";

/**
 * 我的资料 — user documents. Entry paths are strictly user-initiated:
 * native picker (Electron shell) with a browser file-input fallback. The
 * picker flow never scans user directories — only the file the user picks.
 */
export default function DocumentsPanel({
  fetchDocumentsFn = fetchDocuments,
  fetchEmbeddingSettingsFn = fetchEmbeddingSettings,
  nativePickAndImportFn = nativePickAndImport,
  importDocumentFileFn = importDocumentFile,
}: {
  fetchDocumentsFn?: typeof fetchDocuments;
  fetchEmbeddingSettingsFn?: typeof fetchEmbeddingSettings;
  nativePickAndImportFn?: typeof nativePickAndImport;
  importDocumentFileFn?: typeof importDocumentFile;
}) {
  const [destinations, setDestinations] = useState<Array<{conversation_id: string; title: string}>>([]);
  const [destination, setDestination] = useState("");
  const [documents, setDocuments] = useState<DesktopDocument[]>([]);
  const [embeddingSettings, setEmbeddingSettings] = useState<EmbeddingSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [picking, setPicking] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [nextDocuments, nextEmbedding, nextDestinations] = await Promise.all([
        fetchDocumentsFn(),
        fetchEmbeddingSettingsFn().catch(() => null),
        fetchDocumentDestinations().catch(() => []),
      ]);
      setDocuments(nextDocuments);
      setDestinations(nextDestinations);
      setEmbeddingSettings(nextEmbedding);
      setMessage(null);
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "读取资料列表失败，请稍后再试。",
      });
    } finally {
      setLoading(false);
    }
  }, [fetchDocumentsFn, fetchEmbeddingSettingsFn]);

  useEffect(() => {
    refresh().catch(() => undefined);
  }, [refresh]);

  const handleNativePick = async () => {
    setPicking(true);
    setMessage(null);
    try {
      const doc = await nativePickAndImportFn(destination && destination !== "global" ? destination : undefined);
      if (doc && destination === "global") await setDocumentGlobal(doc.document_id, true);
      if (doc) {
        toast({ title: "资料已导入", description: `《${doc.filename}》已经可以管理与检索。` });
        await refresh();
      }
    } catch (err) {
      // Shell absent → fall back to the browser file input.
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "无法打开文件选择器。",
      });
      fileInputRef.current?.click();
    } finally {
      setPicking(false);
    }
  };

  const handleFileChosen = async (file: File | null) => {
    if (!file) return;
    setPicking(true);
    setMessage(null);
    try {
      const doc = await importDocumentFileFn(file, destination && destination !== "global" ? destination : undefined);
      if (destination === "global") await setDocumentGlobal(doc.document_id, true);
      toast({ title: "资料已导入", description: `《${doc.filename}》已经可以管理与检索。` });
      await refresh();
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "导入失败，请稍后再试。",
      });
    } finally {
      setPicking(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const handleToggle = async (doc: DesktopDocument, enabled: boolean) => {
    setBusyId(doc.document_id);
    try {
      const updated = await toggleDocumentRetrieval(doc.document_id, enabled);
      setDocuments((list) => list.map((d) => (d.document_id === updated.document_id ? { ...d, ...updated } : d)));
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "更新失败，请稍后再试。",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (doc: DesktopDocument) => {
    setBusyId(doc.document_id);
    try {
      await deleteDocument(doc.document_id);
      setDocuments((list) => list.filter((d) => d.document_id !== doc.document_id));
      toast({ title: "资料已删除", description: `《${doc.filename}》不会再被检索或召回。` });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "删除失败，请稍后再试。",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleUpdated = (doc: DesktopDocument) => {
    setDocuments((list) => list.map((d) => (d.document_id === doc.document_id ? { ...d, ...doc } : d)));
  };

  return (
    <div className="mt-page">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mt-eyebrow flex items-center gap-1.5"><FolderOpen className="h-3.5 w-3.5" aria-hidden="true" />资料有归属，检索有边界</p>
          <h1 className="mt-2">我的资料</h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">
            按对话管理资料。总资料可供你的所有对话按需检索，其他对话的专属文件不会混入。
          </p>
          {embeddingSettings ? <span className="mt-2 block"><EmbeddingStatusBadge settings={embeddingSettings} /></span> : null}
        </div>
        <label className="flex flex-col gap-1 text-xs text-[var(--muted-foreground)]">新资料保存到
          <select aria-label="新资料保存到" value={destination} onChange={e => setDestination(e.target.value)} className="min-h-[44px] max-w-[240px] rounded-xl border border-[var(--border)] bg-[var(--card)] px-3 text-sm text-[var(--foreground)]">
            <option value="">未归类（不跨对话检索）</option><option value="global">总资料（所有对话）</option>
            {Array.from(new Map([...destinations.map(d => [d.conversation_id, d.title] as const), ...documents.flatMap(d => (d.conversation_ids || []).map(id => [id, d.conversation_titles?.[id] || "未命名对话"] as const))])).map(([id,title]) => <option key={id} value={id}>{title}</option>)}
          </select>
        </label>
        <button
          type="button"
          onClick={handleNativePick}
          disabled={picking}
          className="mt-btn mt-btn-primary"
        >
          {picking ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <FilePlus2 className="h-4 w-4" aria-hidden="true" />}
          {picking ? "正在导入…" : "添加资料"}
        </button>
        {/* Browser fallback picker (only opened on explicit click above). */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.md,.markdown,.tex,.pdf,text/plain,text/markdown,application/pdf"
          className="hidden"
          aria-hidden="true"
          tabIndex={-1}
          onChange={(e) => handleFileChosen(e.target.files?.[0] ?? null)}
        />
      </header>

      {message && (
        <p
          role="status"
          className={`rounded-xl px-3 py-2 text-sm ${
            message.kind === "ok"
              ? "bg-emerald-50 text-[var(--success)] dark:bg-emerald-950/40"
              : "bg-red-50 text-[var(--destructive)] dark:bg-red-950/40"
          }`}
        >
          {message.text}
        </p>
      )}

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          正在加载资料…
        </p>
      ) : documents.length === 0 && destinations.length === 0 ? (
        <div className="mt-card flex flex-col items-center gap-2 border-dashed px-6 py-12 text-center">
          <FolderOpen className="h-8 w-8 text-[var(--muted-foreground)]" aria-hidden="true" />
          <p className="text-sm font-medium text-[var(--foreground)]">还没有学习资料</p>
          <p className="max-w-sm text-sm leading-relaxed text-[var(--muted-foreground)]">
            点击右上角「添加资料」选择文件。资料只会按你选择的文件导入，不会扫描你的电脑文件夹。
          </p>
        </div>
      ) : (
        <DocumentGroups documents={documents} conversations={destinations} renderDocument={(doc) => (
            <DocumentRow
              key={doc.document_id}
              document={doc}
              busy={busyId === doc.document_id}
              onToggleRetrieval={(enabled) => handleToggle(doc, enabled)}
              onDelete={() => handleDelete(doc)}
              onUpdated={handleUpdated}
            />
          )} />
      )}
    </div>
  );
}
