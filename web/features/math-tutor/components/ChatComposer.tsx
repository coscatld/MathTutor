"use client";
import { ImagePlus, Loader2, Paperclip, Send } from "lucide-react";
import { useRef, useState } from "react";
import { useChatAttachments } from "../hooks/useChatAttachments";
import { deliverDraft, type ChatAttachment } from "../lib/attachments";
import { useToast } from "../desktop/components/ToastProvider";
import ImageAttachments from "./ImageAttachments";
export default function ChatComposer({ busy, disabled, onSend, onAddMaterial, onCancel }: { busy: boolean; disabled: boolean; onSend: (text: string, attachments: ChatAttachment[]) => Promise<boolean>; onAddMaterial: () => void; onCancel?: () => void }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);
  const inFlight = useRef(false);
  const picker = useRef<HTMLInputElement>(null);
  const images = useChatAttachments();
  const toast = useToast();
  const locked = busy || sending || disabled;
  const submit = async () => {
    if ((!text.trim() && !images.attachments.length) || locked || inFlight.current) return;
    inFlight.current = true; setSending(true); setFailed(false);
    try {
      if (!await deliverDraft(text, images.attachments, onSend, () => { setText(""); images.clearAttachments(); })) {
        setFailed(true); toast({ title: "发送未完成，文字和图片已保留，可点击重试。", tone: "error" });
      }
    } catch (error) { setFailed(true); toast({ title: error instanceof Error ? error.message : "发送失败，请重试。", tone: "error" }); }
    finally { inFlight.current = false; setSending(false); }
  };
  return <div className="border-t border-[#e3e1da] bg-[#faf9f5] px-5 py-4 dark:border-slate-800 dark:bg-[#111619]">
    <div onDragEnter={locked ? undefined : images.onDragEnter} onDragLeave={images.onDragLeave} onDragOver={e => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }} onDrop={e => { if (locked) e.preventDefault(); else images.handleDrop(e); }} className={`relative mx-auto max-w-3xl rounded-2xl border bg-white p-2 shadow-[0_6px_24px_rgba(35,45,55,.07)] focus-within:border-[#7da4df] dark:bg-slate-900 ${images.dragging ? "border-blue-500 ring-2 ring-blue-200" : "border-[#d6d4cc] dark:border-slate-700"}`}>
      {images.dragging && <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-blue-50/95 text-sm text-blue-700">松开以上传图片</div>}
      <ImageAttachments images={images.attachments.map(a => ({ id: a.id, name: a.name, url: a.previewUrl }))} onRemove={images.removeAttachment} disabled={locked} />
      <textarea value={text} onChange={event => setText(event.target.value)} onPaste={images.handlePaste} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} rows={2} disabled={locked} aria-label="聊天输入" placeholder="输入题目、你的解法，或粘贴截图…" className="max-h-36 min-h-[52px] w-full resize-none bg-transparent px-3 py-2 text-[15px] leading-6 outline-none placeholder:text-slate-400" />
      <div className="flex items-center gap-1">
        <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={event => { images.addFiles(Array.from(event.target.files || [])); event.target.value = ""; }} />
        <button type="button" disabled={locked} onClick={() => picker.current?.click()} className="rounded-xl p-2.5 text-slate-500 hover:bg-slate-100 disabled:opacity-40 dark:hover:bg-slate-800" aria-label="上传图片"><ImagePlus className="h-5 w-5" /></button>
        <button type="button" onClick={onAddMaterial} className="rounded-xl p-2.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="为当前对话添加资料"><Paperclip className="h-5 w-5" /></button>
        <span className="flex-1" />
        {images.attachments.length > 0 && <span className="text-[11px] text-slate-400">{images.attachments.length}/4 · 发送时交给当前模型</span>}
        {busy && onCancel && <button type="button" onClick={onCancel} className="px-2 text-sm text-slate-500">停止生成</button>}
        <button type="button" onClick={() => void submit()} disabled={(!text.trim() && !images.attachments.length) || locked} className="flex h-10 min-w-10 items-center justify-center rounded-xl bg-[#1d5fd1] px-2 text-white hover:bg-[#174fab] disabled:cursor-not-allowed disabled:opacity-40" aria-label={failed ? "重试发送" : "发送"}>{sending || busy ? <Loader2 className="h-4 w-4 animate-spin" /> : failed ? "重试" : <Send className="h-4 w-4" />}</button>
      </div>
    </div>
    <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-400">Enter 发送 · Shift + Enter 换行 · 支持粘贴或拖入图片，每张最多 10 MB</p>
  </div>;
}
