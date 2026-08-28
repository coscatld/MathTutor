"use client";

import { BrainCircuit, DatabaseZap, Download, FileText, Loader2, LockKeyhole, ShieldCheck, Trash2, UserRound, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  deleteDocument,
  deleteEducationalHistory,
  deleteMemory,
  DesktopApiError,
  fetchDocuments,
  fetchMemories,
  fetchStudentExport,
  fetchStudentSummary,
  formatBytes,
  masteryLevelLabel,
  purgeDocuments,
  purgeMemory,
  rebuildIndexes,
} from "../lib/desktop-api";
import { DOCUMENT_STATUS_LABELS, MEMORY_TYPE_LABELS } from "../lib/labels";
import type { DesktopDocument, DesktopMemory, StudentSummary } from "../types";
import { memoryObjectText } from "./MemoryRow";

/**
 * Read-only student-model summary. The mastery values are a projection for
 * display only — this component deliberately has NO edit affordances
 * (invariant: mastery must never be directly editable by the student).
 */
export function PrivacySummary({ summary }: { summary: StudentSummary }) {
  return (
    <div className="flex flex-col gap-3" aria-label="学习模型摘要">
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        由系统根据你的练习记录自动生成，仅供查看，不可直接修改。
      </p>
      <dl className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">累计练习次数</dt>
          <dd className="text-sm font-medium text-[var(--foreground)]">{summary.total_attempts}</dd>
        </div>
        <div className="flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">活跃错误概念</dt>
          <dd className="text-sm font-medium text-[var(--foreground)]">{summary.active_misconceptions}</dd>
        </div>
      </dl>
      {summary.skills.length === 0 ? (
        <p className="text-sm text-[var(--muted-foreground)]">还没有练习记录，暂无技能掌握数据。</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {summary.skills.map((skill) => (
            <li
              key={skill.code}
              className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2"
            >
              <span className="flex min-w-0 flex-col">
                <span className="text-sm font-medium text-[var(--foreground)]">{skill.label}</span>
                {skill.grade_band ? (
                  <span className="text-xs text-[var(--muted-foreground)]">学段：{skill.grade_band}</span>
                ) : null}
              </span>
              <span className="text-sm text-[var(--foreground)]">
                {skill.mastery === null ? (
                  <span className="text-[var(--muted-foreground)]">暂无数据</span>
                ) : (
                  <>
                    <span className="font-semibold">{Math.round(skill.mastery * 100)}%</span>
                    <span className="ml-1.5 text-xs text-[var(--muted-foreground)]">{masteryLevelLabel(skill.mastery)}</span>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Per-item delete with inline double confirmation: the first click asks,
 * the second click (确认删除) actually deletes. The destructive request is
 * only ever sent from the confirm state.
 */
export function ConfirmableDelete({
  title,
  detail,
  confirming,
  busy,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  title: string;
  detail: string;
  confirming: boolean;
  busy: boolean;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  if (confirming) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium text-red-700 dark:text-red-400">确认删除「{title}」？此操作无法撤销。</span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCancelDelete}
            disabled={busy}
            className="inline-flex min-h-[40px] cursor-pointer items-center rounded-lg border border-[var(--border)] px-3 text-sm font-medium text-[var(--muted-foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirmDelete}
            disabled={busy}
            className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg bg-red-600 px-3 text-sm font-medium text-white transition-colors duration-200 hover:bg-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Trash2 className="h-4 w-4" aria-hidden="true" />}
            确认删除
          </button>
        </span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium text-[var(--foreground)]">{title}</span>
        <span className="truncate text-xs text-[var(--muted-foreground)]">{detail}</span>
      </span>
      <button
        type="button"
        onClick={onAskDelete}
        disabled={busy}
        aria-label={`删除 ${title}`}
        className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-sm font-medium text-[var(--muted-foreground)] transition-colors duration-200 hover:bg-[var(--muted)] hover:text-red-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50 dark:hover:text-red-400"
      >
        <Trash2 className="h-4 w-4" aria-hidden="true" />
        删除
      </button>
    </div>
  );
}

interface Props {
  /** Injectable fetchers — tests pass fakes. */
  fetchMemoriesFn?: typeof fetchMemories;
  fetchDocumentsFn?: typeof fetchDocuments;
  fetchStudentSummaryFn?: typeof fetchStudentSummary;
  deleteMemoryFn?: typeof deleteMemory;
  deleteDocumentFn?: typeof deleteDocument;
  purgeDocumentsFn?: typeof purgeDocuments;
  purgeMemoryFn?: typeof purgeMemory;
  deleteHistoryFn?: typeof deleteEducationalHistory;
  rebuildIndexesFn?: typeof rebuildIndexes;
  fetchExportFn?: typeof fetchStudentExport;
  onClose?: () => void;
}

/**
 * 我的数据：profile 只读展示 + 我的记忆 + 我的资料文档（逐条删除均需
 * 二次确认）+ Student Model 只读摘要 + 数据工具（重建索引 / 导出）+
 * 危险操作区（清空文档 / 清空记忆 / 删除学习记录，全部二次确认）。
 * 删除复用现有 desktop bridge 端点（与 DocumentsPanel / MemoryPanel
 * 同一套契约）。无任何 mastery 编辑入口。
 */
export default function PrivacyPanel({
  fetchMemoriesFn = fetchMemories,
  fetchDocumentsFn = fetchDocuments,
  fetchStudentSummaryFn = fetchStudentSummary,
  deleteMemoryFn = deleteMemory,
  deleteDocumentFn = deleteDocument,
  purgeDocumentsFn = purgeDocuments,
  purgeMemoryFn = purgeMemory,
  deleteHistoryFn = deleteEducationalHistory,
  rebuildIndexesFn = rebuildIndexes,
  fetchExportFn = fetchStudentExport,
  onClose,
}: Props) {
  const [memories, setMemories] = useState<DesktopMemory[]>([]);
  const [documents, setDocuments] = useState<DesktopDocument[]>([]);
  const [summary, setSummary] = useState<StudentSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirmMemoryId, setConfirmMemoryId] = useState<string | null>(null);
  const [confirmDocId, setConfirmDocId] = useState<string | null>(null);
  const [confirmDanger, setConfirmDanger] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [memoryList, documentList, summaryData] = await Promise.all([
        fetchMemoriesFn(),
        fetchDocumentsFn(),
        fetchStudentSummaryFn(),
      ]);
      setMemories(memoryList);
      setDocuments(documentList);
      setSummary(summaryData);
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "读取数据失败，请稍后再试。",
      });
    } finally {
      setLoading(false);
    }
  }, [fetchMemoriesFn, fetchDocumentsFn, fetchStudentSummaryFn]);

  useEffect(() => {
    load().catch(() => undefined);
  }, [load]);

  const handleDeleteMemory = async (memory: DesktopMemory) => {
    setBusyId(memory.memory_id);
    try {
      await deleteMemoryFn(memory.memory_id);
      setMemories((list) => list.filter((m) => m.memory_id !== memory.memory_id));
      setConfirmMemoryId(null);
      setMessage({ kind: "ok", text: "已删除这条记忆。" });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "删除失败，请稍后再试。",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleDeleteDocument = async (doc: DesktopDocument) => {
    setBusyId(doc.document_id);
    try {
      await deleteDocumentFn(doc.document_id);
      setDocuments((list) => list.filter((d) => d.document_id !== doc.document_id));
      setConfirmDocId(null);
      setMessage({ kind: "ok", text: `已删除「${doc.filename}」` });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "删除失败，请稍后再试。",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleDanger = async (key: string, run: () => Promise<void>, okText: string) => {
    setBusyId(key);
    try {
      await run();
      setConfirmDanger(null);
      setMessage({ kind: "ok", text: okText });
      await load();
    } catch (err) {
      setConfirmDanger(null);
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "操作失败，请稍后再试。",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleRebuildIndexes = async () => {
    setBusyId("rebuild-indexes");
    try {
      const result = await rebuildIndexesFn();
      const rebuilt = Object.values(result.documents).filter((d) => d.status === "rebuilt").length;
      setMessage({
        kind: "ok",
        text:
          rebuilt > 0
            ? `已重建 ${rebuilt} 份资料的检索索引。`
            : "当前未配置向量模型，检索索引暂不可用（词法检索不受影响）。",
      });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "重建索引失败，请稍后再试。",
      });
    } finally {
      setBusyId(null);
    }
  };

  const handleExport = async () => {
    setBusyId("export");
    try {
      const body = await fetchExportFn();
      const blob = new Blob([JSON.stringify(body, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `mathtutor-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage({ kind: "ok", text: "已导出我的数据（JSON 文件）。" });
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "导出失败，请稍后再试。",
      });
    } finally {
      setBusyId(null);
    }
  };

  const gradeBand = summary?.skills.find((s) => s.grade_band)?.grade_band ?? null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="privacy-title"
    >
      <div className="flex max-h-[calc(100vh-4rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl">
        <header className="flex items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-3.5">
          <h1 id="privacy-title" className="flex items-center gap-2 text-lg font-semibold text-[var(--foreground)]">
            <ShieldCheck className="h-5 w-5 text-[#2563EB]" aria-hidden="true" />
            我的数据
          </h1>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="inline-flex min-h-[40px] min-w-[40px] cursor-pointer items-center justify-center rounded-lg text-[var(--muted-foreground)] transition-colors duration-200 hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-4">
          {message && (
            <p
              role="status"
              className={`rounded-xl px-3 py-2 text-sm ${
                message.kind === "ok"
                  ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-400"
                  : "bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-400"
              }`}
            >
              {message.text}
            </p>
          )}

          {loading ? (
            <p className="flex items-center gap-2 py-8 text-sm text-[var(--muted-foreground)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              正在加载我的数据…
            </p>
          ) : (
            <>
              {/* Profile — read-only display */}
              <section className="flex flex-col gap-2" aria-label="我的资料">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <UserRound className="h-4 w-4 text-[#2563EB]" aria-hidden="true" />
                  我的资料
                </h2>
                <dl className="grid grid-cols-1 gap-2 sm:grid-cols-3">
                  <div className="flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
                    <dt className="text-xs text-[var(--muted-foreground)]">学段</dt>
                    <dd className="text-sm font-medium text-[var(--foreground)]">{gradeBand ?? "—"}</dd>
                  </div>
                  <div className="flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
                    <dt className="text-xs text-[var(--muted-foreground)]">累计练习次数</dt>
                    <dd className="text-sm font-medium text-[var(--foreground)]">{summary?.total_attempts ?? 0}</dd>
                  </div>
                  <div className="flex flex-col gap-0.5 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
                    <dt className="text-xs text-[var(--muted-foreground)]">活跃错误概念</dt>
                    <dd className="text-sm font-medium text-[var(--foreground)]">{summary?.active_misconceptions ?? 0}</dd>
                  </div>
                </dl>
                <p className="flex items-center gap-1.5 text-xs text-[var(--muted-foreground)]">
                  <LockKeyhole className="h-3.5 w-3.5" aria-hidden="true" />
                  以上资料由系统自动生成，只读展示。
                </p>
              </section>

              {/* Memories — delete with double confirm */}
              <section className="flex flex-col gap-2" aria-label="我的记忆">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <BrainCircuit className="h-4 w-4 text-[#2563EB]" aria-hidden="true" />
                  我的记忆
                </h2>
                {memories.length === 0 ? (
                  <p className="text-sm text-[var(--muted-foreground)]">还没有记忆。</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {memories.map((memory) => (
                      <li key={memory.memory_id} className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5">
                        <ConfirmableDelete
                          title={`${MEMORY_TYPE_LABELS[memory.memory_type] ?? memory.memory_type}：${memory.predicate}`}
                          detail={memoryObjectText(memory)}
                          confirming={confirmMemoryId === memory.memory_id}
                          busy={busyId === memory.memory_id}
                          onAskDelete={() => setConfirmMemoryId(memory.memory_id)}
                          onCancelDelete={() => setConfirmMemoryId(null)}
                          onConfirmDelete={() => handleDeleteMemory(memory)}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Documents — delete with double confirm */}
              <section className="flex flex-col gap-2" aria-label="我的资料文档">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <FileText className="h-4 w-4 text-[#2563EB]" aria-hidden="true" />
                  我的资料文档
                </h2>
                {documents.length === 0 ? (
                  <p className="text-sm text-[var(--muted-foreground)]">还没有学习资料。</p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {documents.map((doc) => (
                      <li key={doc.document_id} className="rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5">
                        <ConfirmableDelete
                          title={doc.filename}
                          detail={`${DOCUMENT_STATUS_LABELS[doc.status] ?? doc.status} · ${formatBytes(doc.size_bytes)}`}
                          confirming={confirmDocId === doc.document_id}
                          busy={busyId === doc.document_id}
                          onAskDelete={() => setConfirmDocId(doc.document_id)}
                          onCancelDelete={() => setConfirmDocId(null)}
                          onConfirmDelete={() => handleDeleteDocument(doc)}
                        />
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* Student model summary — strictly read-only */}
              <section className="flex flex-col gap-2" aria-label="学习模型摘要">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <ShieldCheck className="h-4 w-4 text-[#2563EB]" aria-hidden="true" />
                  学习模型摘要
                </h2>
                {summary ? <PrivacySummary summary={summary} /> : null}
              </section>

              {/* Data tools — non-destructive */}
              <section className="flex flex-col gap-2" aria-label="数据工具">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <DatabaseZap className="h-4 w-4 text-[#2563EB]" aria-hidden="true" />
                  数据工具
                </h2>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handleRebuildIndexes}
                    disabled={busyId !== null}
                    className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-sm font-medium text-[var(--muted-foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busyId === "rebuild-indexes" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <DatabaseZap className="h-4 w-4" aria-hidden="true" />}
                    重建检索索引
                  </button>
                  <button
                    type="button"
                    onClick={handleExport}
                    disabled={busyId !== null}
                    className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-sm font-medium text-[var(--muted-foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {busyId === "export" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Download className="h-4 w-4" aria-hidden="true" />}
                    导出我的数据
                  </button>
                </div>
                <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                  导出内容只包含你自己的资料、记忆与学习摘要，不含任何密钥或系统内部数据。
                </p>
              </section>

              {/* Danger zone — every action confirms twice before sending */}
              <section className="flex flex-col gap-2" aria-label="危险操作">
                <h2 className="flex items-center gap-2 text-base font-semibold text-red-700 dark:text-red-400">
                  <Trash2 className="h-4 w-4" aria-hidden="true" />
                  危险操作
                </h2>
                <div className="flex flex-col gap-2 rounded-xl border border-red-200 bg-red-50/60 p-3 dark:border-red-950 dark:bg-red-950/20">
                  <ConfirmableDelete
                    title="清空全部资料文档"
                    detail="删除你导入的所有学习资料及其内容，无法撤销。"
                    confirming={confirmDanger === "purge-documents"}
                    busy={busyId === "purge-documents"}
                    onAskDelete={() => setConfirmDanger("purge-documents")}
                    onCancelDelete={() => setConfirmDanger(null)}
                    onConfirmDelete={() =>
                      handleDanger(
                        "purge-documents",
                        async () => {
                          await purgeDocumentsFn();
                        },
                        "已清空全部资料文档。",
                      )
                    }
                  />
                  <ConfirmableDelete
                    title="清空全部记忆"
                    detail="删除你的全部个人记忆，无法撤销。"
                    confirming={confirmDanger === "purge-memory"}
                    busy={busyId === "purge-memory"}
                    onAskDelete={() => setConfirmDanger("purge-memory")}
                    onCancelDelete={() => setConfirmDanger(null)}
                    onConfirmDelete={() =>
                      handleDanger(
                        "purge-memory",
                        async () => {
                          await purgeMemoryFn();
                        },
                        "已清空全部记忆。",
                      )
                    }
                  />
                  <ConfirmableDelete
                    title="删除学习记录"
                    detail="删除全部练习结果与学习模型（会话记录保留），模型将从零开始。"
                    confirming={confirmDanger === "educational-history"}
                    busy={busyId === "educational-history"}
                    onAskDelete={() => setConfirmDanger("educational-history")}
                    onCancelDelete={() => setConfirmDanger(null)}
                    onConfirmDelete={() =>
                      handleDanger(
                        "educational-history",
                        async () => {
                          await deleteHistoryFn();
                        },
                        "已删除学习记录，学习模型已重置。",
                      )
                    }
                  />
                </div>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
