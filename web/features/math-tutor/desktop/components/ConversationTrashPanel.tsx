"use client";

import { useCallback, useEffect, useState } from "react";
import { RotateCcw, Trash2 } from "lucide-react";
import ConversationDeleteDialog from "./ConversationDeleteDialog";
import { conversationAction, fetchTrash, type TrashedConversation } from "../lib/conversation-trash";

export default function ConversationTrashPanel() {
  const [items, setItems] = useState<TrashedConversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState("");
  const [target, setTarget] = useState<TrashedConversation | null>(null);
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try { setItems(await fetchTrash()); }
    catch (e) { setError(e instanceof Error ? e.message : "加载失败"); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    void refresh();
    window.addEventListener("mathtutor-conversations-changed", refresh);
    return () => window.removeEventListener("mathtutor-conversations-changed", refresh);
  }, [refresh]);
  async function restore(item: TrashedConversation) {
    setBusy(item.conversation_id); setError(""); setStatus("");
    try {
      await conversationAction(item.conversation_id, "restore");
      setItems(rows => rows.filter(row => row.conversation_id !== item.conversation_id));
      setStatus("对话已恢复，可在侧栏继续查看。");
    } catch (e) { setError(e instanceof Error ? e.message : "恢复失败"); }
    finally { setBusy(""); }
  }
  return <section aria-labelledby="conversation-trash-heading">
    <h2 id="conversation-trash-heading" className="flex items-center gap-2 font-serif text-xl font-bold"><Trash2 className="h-5 w-5" aria-hidden="true" />垃圾桶</h2>
    <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">已删除的对话保留在本机，不会自动清空。恢复后，聊天记录与关联资料会重新出现。</p>
    {error ? <div role="alert" className="mt-4 text-sm text-[var(--destructive)]">{error}<button type="button" onClick={() => void refresh()} className="ml-3 min-h-11 underline">重新加载</button></div> : null}
    <p role="status" className="mt-3 text-sm text-[var(--muted-foreground)]">{status || (loading ? "正在加载垃圾桶…" : "")}</p>
    {!loading && !error && !items.length ? <div className="mt-5 rounded-xl border border-dashed border-[var(--border)] p-8 text-center text-sm text-[var(--muted-foreground)]">垃圾桶是空的</div> : null}
    <ul className="mt-4 space-y-3">{items.map(item => <li key={item.conversation_id} className="flex flex-wrap items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--card)] p-4">
      <div className="min-w-0 flex-1 basis-40"><p className="break-words text-sm font-medium">{item.title || "对话"}</p><p className="mt-1 text-xs text-[var(--muted-foreground)]">移入时间：{new Date(item.trashed_at).toLocaleString("zh-CN")}</p></div>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={!!busy} onClick={() => void restore(item)} className="flex min-h-11 items-center gap-2 rounded-lg border border-[var(--border)] px-3 text-sm hover:bg-[var(--muted)] disabled:opacity-50"><RotateCcw className="h-4 w-4" aria-hidden="true" />{busy === item.conversation_id ? "恢复中…" : "恢复"}</button>
        <button type="button" disabled={!!busy} onClick={() => setTarget(item)} className="min-h-11 rounded-lg px-3 text-sm text-[var(--destructive)] hover:bg-[var(--muted)] disabled:opacity-50">彻底删除</button>
      </div>
    </li>)}</ul>
    {target ? <ConversationDeleteDialog title={target.title} permanent onCancel={() => setTarget(null)} onConfirm={async () => {
      await conversationAction(target.conversation_id, "purge");
      setItems(rows => rows.filter(row => row.conversation_id !== target.conversation_id));
      setTarget(null); setStatus("对话已彻底删除。");
      return "deleted";
    }} /> : null}
  </section>;
}
