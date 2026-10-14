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
  purgeDocuments,
  purgeMemory,
  rebuildIndexes,
  recomputeLearningProfile,
} from "../lib/desktop-api";
import { DOCUMENT_STATUS_LABELS, MEMORY_TYPE_LABELS } from "../lib/labels";
import type { DesktopDocument, DesktopMemory, StudentSummary } from "../types";
import { memoryObjectText } from "./MemoryRow";
import { evidenceStatusLabel, projectEvidenceSummary } from "../../lib/teaching-contract";

/**
 * Show observed evidence, not an uncalibrated legacy mastery percentage.
 */
export function PrivacySummary({ summary }: { summary: StudentSummary }) {
  return (
    <div className="flex flex-col gap-3" aria-label="学习模型摘要">
      <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
        根据已经验证的作答记录生成。独立、受助和看答案后的作答分别记录，不把帮助次数当作掌握增长。
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
        <p className="text-sm text-[var(--muted-foreground)]">还没有练习记录，暂无知识点证据。</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {summary.skills.map((skill) => {
            const evidence = projectEvidenceSummary(skill.evidence_summary);
            return (
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
              <span className="flex flex-col items-end gap-1 text-xs leading-5 text-[var(--muted-foreground)]">
                <span>{evidence ? evidenceStatusLabel(skill.evidence_status || evidence.status) : "仍需独立检测"}</span>
                {evidence ? <><span>独立 {evidence.independent} 次 · 受助 {evidence.assisted} 次</span><span>看答案后 {evidence.post_solution} 次 · 暂无法判断 {evidence.ungradable} 次</span></> : <span>旧记录不足以区分作答前的帮助</span>}
              </span>
            </li>
          ); })}
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
        <span className="text-sm font-medium text-[var(--destructive)]">确认删除「{title}」？此操作无法撤销。</span>
        <span className="flex items-center gap-2">
          <button
            type="button"
            onClick={onCancelDelete}
            disabled={busy}
            className="mt-btn"
          >
            取消
          </button>
          <button
            type="button"
            onClick={onConfirmDelete}
            disabled={busy}
            className="mt-btn mt-btn-danger-solid"
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
        className="mt-btn mt-btn-danger"
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
  embedded?: boolean;
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
  embedded = false,
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
      className={embedded ? "w-full" : "fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"}
      role={embedded ? undefined : "dialog"}
      aria-modal={embedded ? undefined : true}
      aria-labelledby="privacy-title"
    >
      <div className={embedded ? "flex w-full flex-col" : "flex max-h-[calc(100vh-4rem)] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--card)] shadow-xl"}>
        <header className={embedded ? "flex items-start justify-between gap-2" : "flex items-center justify-between gap-2 border-b border-[var(--border)] px-5 py-3.5"}>
          {embedded ? <div>
            <h1 id="privacy-title" className="text-xl font-bold tracking-tight text-[var(--foreground)]">数据与隐私</h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">查看、导出或删除保存在这台电脑上的记忆、资料与学习记录。</p>
          </div> : <h1 id="privacy-title" className="flex items-center gap-2 text-lg font-semibold text-[var(--foreground)]">
            <ShieldCheck className="h-5 w-5 text-[var(--primary-text)]" aria-hidden="true" />
            数据与隐私
          </h1>}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="关闭"
              className="mt-btn mt-btn-ghost justify-center"
            >
              <X className="h-4 w-4" aria-hidden="true" />
            </button>
          )}
        </header>

        <div className={embedded ? "mt-5 flex flex-col gap-6" : "flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-4"}>
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
            <p className="flex items-center gap-2 py-8 text-sm text-[var(--muted-foreground)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              正在加载数据管理…
            </p>
          ) : (
            <>
              {/* Profile — read-only display */}
              {!embedded && <section className="flex flex-col gap-2" aria-label="我的资料">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <UserRound className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
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
              </section>}

              {/* Memories — delete with double confirm */}
              <section className="flex flex-col gap-2" aria-label="我的记忆">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <BrainCircuit className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
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
                  <FileText className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
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
              {!embedded && <section className="flex flex-col gap-2" aria-label="学习模型摘要">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <ShieldCheck className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
                  学习模型摘要
                </h2>
                {summary ? <PrivacySummary summary={summary} /> : null}
              </section>}

              {/* Data tools — non-destructive */}
              <section className="flex flex-col gap-2" aria-label="数据工具">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
                  <DatabaseZap className="h-4 w-4 text-[var(--primary-text)]" aria-hidden="true" />
                  数据工具
                </h2>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handleRebuildIndexes}
                    disabled={busyId !== null}
                    className="mt-btn"
                  >
                    {busyId === "rebuild-indexes" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <DatabaseZap className="h-4 w-4" aria-hidden="true" />}
                    重建检索索引
                  </button>
                  <button
                    type="button"
                    onClick={handleExport}
                    disabled={busyId !== null}
                    className="mt-btn"
                  >
                    {busyId === "export" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Download className="h-4 w-4" aria-hidden="true" />}
                    导出我的数据
                  </button>
                </div>
                <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
                  导出内容只包含你自己的资料、记忆与学习摘要，不含任何密钥或系统内部数据。
                </p>
              </section>

              <section aria-label="学习画像重算" className="rounded-xl border border-[var(--border)] p-4"><h2 className="font-medium">重新计算学习画像</h2><p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">根据有效学习事件重新计算画像与个人状态。检索索引重建只影响资料搜索。</p><button type="button" disabled={busyId !== null} className="mt-3 min-h-11 rounded-lg border border-[var(--border)] px-4 text-sm disabled:opacity-50" onClick={async () => { setBusyId("recompute"); try { await recomputeLearningProfile(); await load(); setMessage({kind:"ok", text:"已根据有效记录重新计算学习画像。"}); } catch { setMessage({kind:"error",text:"画像重算未完成，请稍后重试。"}); } finally {setBusyId(null);} }}>{busyId === "recompute" ? "正在计算…" : "重新计算学习画像"}</button></section>

              {/* Danger zone — every action confirms twice before sending */}
              <section className="flex flex-col gap-2" aria-label="危险操作">
                <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--destructive)]">
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
                    detail="将删除学习证据及其生成的画像和个性化状态。会话内容保留，但不会自动恢复已删除的画像。备份中的旧记录需要单独管理。"
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
                        "已删除学习记录及其生成的画像。",
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
