"use client";

import { KeyRound, Loader2, Lock, LockOpen } from "lucide-react";
import { useEffect, useState } from "react";
import { DesktopApiError, fetchEncryption, revealRecoveryKey, saveEncryption, type EncryptionStatus } from "../lib/desktop-api";

/**
 * Opt-in database encryption. Switching only records the wish; the conversion
 * runs at the next start after a verified copy, and a failure keeps the data
 * as it was. Backups are encrypted whenever the system key store is available.
 */
export default function EncryptionPanel({ fetchFn = fetchEncryption }: { fetchFn?: typeof fetchEncryption }) {
  const [status, setStatus] = useState<EncryptionStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [recoveryKey, setRecoveryKey] = useState("");
  useEffect(() => { void fetchFn().then(setStatus).catch(() => setMessage("加密状态读取失败。")); }, [fetchFn]);
  if (!status) return <section className="mt-card p-5 text-sm text-[var(--muted-foreground)]">{message || "正在读取加密状态…"}</section>;
  const encrypted = status.mode === "encrypted";
  const wantOn = status.pending ? status.pending === "encrypt" : encrypted;
  const toggle = async () => {
    setBusy(true); setMessage("");
    try {
      const next = await saveEncryption(!wantOn);
      setStatus(next);
      setMessage(next.pending ? "已记录，重新启动应用后生效；转换前会先校验数据，失败时保持原样。" : "已取消待生效的更改。");
    } catch (error) {
      setMessage(error instanceof DesktopApiError ? error.message : "没有保存，请稍后重试。");
    } finally { setBusy(false); }
  };
  const showKey = async () => {
    setBusy(true); setMessage("");
    try { setRecoveryKey((await revealRecoveryKey()).recovery_key); }
    catch (error) { setMessage(error instanceof DesktopApiError ? error.message : "无法读取恢复密钥。"); }
    finally { setBusy(false); }
  };
  return <section className="mt-card flex flex-col gap-3 p-5" aria-label="数据加密">
    <h2 className="flex items-center gap-2 text-base font-semibold">{encrypted ? <Lock className="h-5 w-5 text-[var(--primary-text)]" aria-hidden="true" /> : <LockOpen className="h-5 w-5 text-[var(--muted-foreground)]" aria-hidden="true" />}数据加密</h2>
    <p className="text-sm leading-6 text-[var(--muted-foreground)]">
      开启后，本机学习数据库用 SQLCipher 加密，密钥保存在系统钥匙串 / 凭据管理器里，换一台电脑或删除钥匙串条目后无法直接打开。
      {status.backups_encrypted ? "备份文件始终加密；请保存好恢复密钥，钥匙串丢失时恢复备份需要它。" : ""}
    </p>
    <p className="text-sm">当前：<strong>{encrypted ? "已加密" : "未加密"}</strong>{status.pending ? <span className="ml-2 text-[var(--muted-foreground)]">（重启后将{status.pending === "encrypt" ? "加密" : "解除加密"}）</span> : null}</p>
    {!status.available ? <p className="text-xs text-[var(--muted-foreground)]">{status.reason}</p> : null}
    <div className="flex flex-wrap gap-2">
      <button type="button" className="mt-btn" disabled={busy || (!status.available && !encrypted)} onClick={toggle}>
        {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}{wantOn ? "关闭数据库加密" : "开启数据库加密"}
      </button>
      {status.backups_encrypted ? <button type="button" className="mt-btn" disabled={busy} onClick={showKey}><KeyRound className="h-4 w-4" aria-hidden="true" />显示恢复密钥</button> : null}
    </div>
    {recoveryKey ? <p className="break-all rounded-lg border border-[var(--border)] p-3 font-mono text-xs" aria-label="恢复密钥">{recoveryKey}</p> : null}
    {message ? <p role="status" className="text-xs leading-5 text-[var(--muted-foreground)]">{message}</p> : null}
  </section>;
}
