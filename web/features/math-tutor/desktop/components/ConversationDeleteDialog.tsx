"use client";

import { useEffect, useRef, useState } from "react";
import { Trash2 } from "lucide-react";

export default function ConversationDeleteDialog({ title, permanent = false, onCancel, onConfirm }: {
  title: string; permanent?: boolean; onCancel: () => void; onConfirm: () => Promise<void>;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, []);
  async function confirm() {
    setBusy(true); setError("");
    try { await onConfirm(); }
    catch (e) { setError(e instanceof Error ? e.message : "操作失败，请重试。"); setBusy(false); }
  }
  return <dialog ref={dialog} aria-labelledby="delete-conversation-title" aria-describedby="delete-conversation-copy"
    onCancel={e => { e.preventDefault(); if (!busy) onCancel(); }}
    className="mt-card m-auto w-[calc(100%-2rem)] max-w-md p-6 text-[var(--foreground)] shadow-xl backdrop:bg-black/35">
    <Trash2 aria-hidden="true" className="mb-4 h-6 w-6 text-[var(--muted-foreground)]" />
    <h2 id="delete-conversation-title" className="text-lg font-semibold">{permanent ? "彻底删除此对话？" : "将此对话移入垃圾桶？"}</h2>
    <p className="mt-2 break-words text-sm font-medium">{title}</p>
    <div id="delete-conversation-copy" className="mt-3 space-y-2 text-sm leading-6 text-[var(--muted-foreground)]">
      {permanent ? <>
        <p>聊天记录和仅属于此对话的文件、图片将被删除，无法从垃圾桶恢复。</p>
        <p>总资料、其他对话共用的附件、学习记录与已有备份不会删除。学习记录请在“我的数据”中管理。</p>
      </> : <>
        <p>本地记录不会删除，将会保存到垃圾桶。你可以随时恢复对话和关联资料。</p>
        <p className="text-xs">如果要彻底删除：设置&gt;垃圾桶</p>
      </>}
    </div>
    {error ? <p role="alert" className="mt-3 text-sm text-[var(--destructive)]">{error}</p> : null}
    <div className="mt-6 flex justify-end gap-3">
      <button autoFocus type="button" disabled={busy} onClick={onCancel} className="mt-btn min-h-11 px-4">取消</button>
      <button type="button" disabled={busy} onClick={() => void confirm()} className="mt-btn mt-btn-danger-solid min-h-11 px-4">{busy ? "处理中…" : permanent ? "彻底删除" : "移入垃圾桶"}</button>
    </div>
  </dialog>;
}
