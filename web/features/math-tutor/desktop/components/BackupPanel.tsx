"use client";

import { Archive, BadgeCheck, DatabaseBackup, Loader2, RotateCcw, ShieldAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createBackup,
  DesktopApiError,
  fetchBackups,
  formatBytes,
  formatDateTime,
  restoreBackup,
  sortBackups,
  verifyBackup,
} from "../lib/desktop-api";
import { BACKUP_INTEGRITY_LABELS } from "../lib/labels";
import type { BackupRecord, BackupsList } from "../types";

interface Props {
  /** Injectable fetchers — tests pass fakes. */
  fetchBackupsFn?: typeof fetchBackups;
  createBackupFn?: typeof createBackup;
  verifyBackupFn?: typeof verifyBackup;
  restoreBackupFn?: typeof restoreBackup;
}

/**
 * Restore confirmation dialog (second confirmation). The consequence copy is
 * explicit and fixed: the restore overwrites current data and restarts the
 * app — the request is only sent from here, after the user's second click.
 */
export function RestoreConfirmDialog({
  backup,
  busy,
  onConfirm,
  onCancel,
}: {
  backup: BackupRecord;
  busy: boolean;
  onConfirm: (recoveryKey?: string) => void;
  onCancel: () => void;
}) {
  const [recoveryKey, setRecoveryKey] = useState("");
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="restore-confirm-title"
      aria-describedby="restore-confirm-desc"
    >
      <div className="mt-card flex w-full max-w-md flex-col gap-3 p-5 shadow-xl">
        <h2 id="restore-confirm-title" className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
          <ShieldAlert className="h-5 w-5 text-[var(--destructive)]" aria-hidden="true" />
          确认恢复备份？
        </h2>
        <p id="restore-confirm-desc" className="text-sm leading-relaxed text-[var(--foreground)]">
          将用备份「{backup.path}」恢复数据。恢复会<strong>覆盖当前数据</strong>，且恢复完成后
          <strong>应用将重新启动</strong>。此操作无法撤销。
        </p>
        <label className="block text-xs text-[var(--muted-foreground)]">
          恢复密钥（只有提示「需要恢复密钥」时才填写）
          <input value={recoveryKey} onChange={event => setRecoveryKey(event.target.value.trim())} disabled={busy}
            className="mt-input mt-1 font-mono text-xs" placeholder="不填" autoComplete="off" spellCheck={false} />
        </label>
        <div className="flex flex-wrap justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="mt-btn"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => onConfirm(recoveryKey || undefined)}
            disabled={busy}
            className="mt-btn mt-btn-danger-solid"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RotateCcw className="h-4 w-4" aria-hidden="true" />}
            {busy ? "恢复中…" : "确认恢复"}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * 设置 → 数据备份。Restore is strictly double-confirmed: the first click
 * only opens the confirmation dialog; the request goes out on the second
 * click inside the dialog. Backup paths shown here are file/relative names
 * only (backend contract), never user-sensitive full paths.
 */
export default function BackupPanel({
  fetchBackupsFn = fetchBackups,
  createBackupFn = createBackup,
  verifyBackupFn = verifyBackup,
  restoreBackupFn = restoreBackup,
}: Props) {
  const [list, setList] = useState<BackupsList | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"backup" | "verify" | "restore" | null>(null);
  const [busyPath, setBusyPath] = useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = useState<BackupRecord | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setList(await fetchBackupsFn());
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "读取备份列表失败，请稍后再试。",
      });
    } finally {
      setLoading(false);
    }
  }, [fetchBackupsFn]);

  useEffect(() => {
    refresh().catch(() => undefined);
  }, [refresh]);

  const backups = useMemo(() => (list ? sortBackups(list.backups) : []), [list]);
  const latest = backups.length > 0 ? backups[0] : null;

  const handleBackup = async () => {
    setBusy("backup");
    setMessage(null);
    try {
      const result = await createBackupFn();
      if (result.ok) {
        setMessage({ kind: "ok", text: `备份完成：${result.backup.path}` });
      } else {
        setMessage({ kind: "error", text: result.message });
      }
      await refresh();
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "备份失败，请稍后再试。",
      });
    } finally {
      setBusy(null);
    }
  };

  const handleVerify = async (backup: BackupRecord) => {
    setBusy("verify");
    setBusyPath(backup.path);
    setMessage(null);
    try {
      const result = await verifyBackupFn(backup.path);
      if (result.ok) {
        setMessage({ kind: "ok", text: `备份「${backup.path}」校验通过。` });
      } else {
        setMessage({ kind: "error", text: result.message });
      }
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "校验失败，请稍后再试。",
      });
    } finally {
      setBusy(null);
      setBusyPath(null);
    }
  };

  const handleRestoreConfirmed = async (recoveryKey?: string) => {
    if (!confirmRestore) return;
    const backup = confirmRestore;
    setBusy("restore");
    setMessage(null);
    try {
      const result = await restoreBackupFn(backup.path, recoveryKey);
      if (result.ok) {
        setConfirmRestore(null);
        setMessage({
          kind: "ok",
          text: result.message || `恢复完成，应用即将重新启动。`,
        });
      } else {
        setConfirmRestore(null);
        setMessage({ kind: "error", text: result.message });
      }
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "恢复失败，请稍后再试。",
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="mt-card flex flex-col gap-4 p-5" aria-label="数据备份">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-base font-semibold text-[var(--foreground)]">
            <DatabaseBackup className="h-5 w-5 text-[var(--primary-text)]" aria-hidden="true" />
            数据备份
          </h2>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            备份保存在本机应用数据目录中，可用于恢复练习记录、学习资料与记忆。
          </p>
        </div>
        <button
          type="button"
          onClick={handleBackup}
          disabled={busy !== null}
          className="mt-btn mt-btn-primary"
        >
          {busy === "backup" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Archive className="h-4 w-4" aria-hidden="true" />}
          {busy === "backup" ? "备份中…" : "立即备份"}
        </button>
      </div>

      {/* Status summary */}
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">上次备份</dt>
          <dd className="text-sm font-medium text-[var(--foreground)]">
            {latest ? formatDateTime(latest.created_at) : "暂无备份"}
          </dd>
        </div>
        <div className="flex flex-col gap-1 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">备份状态</dt>
          <dd className="text-sm font-medium text-[var(--foreground)]">
            {latest ? BACKUP_INTEGRITY_LABELS[latest.integrity] ?? latest.integrity : "—"}
          </dd>
        </div>
        <div className="flex flex-col gap-1 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">备份目录</dt>
          <dd className="break-all text-sm font-medium text-[var(--foreground)]">{list?.backup_dir ?? "—"}</dd>
        </div>
        <div className="flex flex-col gap-1 rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
          <dt className="text-xs text-[var(--muted-foreground)]">保留策略</dt>
          <dd className="text-sm font-medium text-[var(--foreground)]">
            {list ? `自动保留最近 ${list.policy.retention_limit} 份` : "—"}
          </dd>
        </div>
      </dl>

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
        <p className="flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          正在加载备份…
        </p>
      ) : backups.length === 0 ? (
        <p className="rounded-xl border border-dashed border-[var(--border)] px-4 py-8 text-center text-sm text-[var(--muted-foreground)]">
          还没有备份。点击「立即备份」创建第一份数据备份。
        </p>
      ) : (
        <ul className="flex flex-col gap-2">
          {backups.map((backup) => (
            <li
              key={backup.path}
              className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 py-2.5"
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="flex flex-wrap items-center gap-2 text-sm font-medium text-[var(--foreground)]">
                  <span className="break-all">{backup.path}</span>
                  <span
                    className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${
                      backup.integrity === "ok"
                        ? "border-emerald-200 bg-emerald-50 text-[var(--success)] dark:border-emerald-900 dark:bg-emerald-950/40"
                        : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)]"
                    }`}
                  >
                    <BadgeCheck className="h-3 w-3" aria-hidden="true" />
                    {BACKUP_INTEGRITY_LABELS[backup.integrity] ?? backup.integrity}
                  </span>
                </span>
                <span className="text-xs text-[var(--muted-foreground)]">
                  {formatDateTime(backup.created_at)} · {formatBytes(backup.size_bytes)} · 校验值 {backup.sha256_prefix}…
                </span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => handleVerify(backup)}
                  disabled={busy !== null}
                  className="mt-btn"
                >
                  {busy === "verify" && busyPath === backup.path ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <BadgeCheck className="h-4 w-4" aria-hidden="true" />}
                  验证
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmRestore(backup)}
                  disabled={busy !== null}
                  className="mt-btn mt-btn-danger"
                >
                  <RotateCcw className="h-4 w-4" aria-hidden="true" />
                  恢复
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {confirmRestore && (
        <RestoreConfirmDialog
          backup={confirmRestore}
          busy={busy === "restore"}
          onConfirm={handleRestoreConfirmed}
          onCancel={() => setConfirmRestore(null)}
        />
      )}
    </section>
  );
}
