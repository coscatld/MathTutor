"use client";
import { ArrowUp, ImagePlus, Loader2, Paperclip } from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useChatAttachments } from "../hooks/useChatAttachments";
import { deliverDraft, type ChatAttachment } from "../lib/attachments";
import { useToast } from "../desktop/components/ToastProvider";
import ImageAttachments from "./ImageAttachments";
export default function ChatComposer({ busy, disabled, onSend, onSendAttempt, attemptMode = false, onExitAttempt, onAddMaterial, onCancel, focusRequest = 0, placeholder = "输入问题，或粘贴截图…" }: { busy: boolean; disabled: boolean; onSend: (text: string, attachments: ChatAttachment[]) => Promise<boolean>; onSendAttempt?: (text: string) => Promise<boolean>; attemptMode?: boolean; onExitAttempt?: () => void; onAddMaterial: () => void; onCancel?: () => void; focusRequest?: number; placeholder?: string }) {
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [failed, setFailed] = useState(false);
  const inFlight = useRef(false);
  const picker = useRef<HTMLInputElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (focusRequest > 0) input.current?.focus(); }, [focusRequest]);
  useLayoutEffect(() => {
    const node = input.current;
    if (!node) return;
    const resize = () => { node.style.height = "0px"; node.style.height = `${node.scrollHeight}px`; };
    resize();
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width !== lastWidth) { lastWidth = width; resize(); }
    });
    let lastWidth = node.getBoundingClientRect().width;
    observer.observe(node);
    return () => observer.disconnect();
  }, [text]);
  const images = useChatAttachments();
  useEffect(() => { if (attemptMode && images.attachments.length) onExitAttempt?.(); }, [attemptMode, images.attachments.length, onExitAttempt]);
  const toast = useToast();
  const locked = busy || sending || disabled;
  const submit = async () => {
    if ((!text.trim() && !images.attachments.length) || locked || inFlight.current) return;
    inFlight.current = true; setSending(true); setFailed(false);
    try {
      if (!await deliverDraft(text, images.attachments, (draft, attachments) => attemptMode && !attachments.length && onSendAttempt ? onSendAttempt(draft) : onSend(draft, attachments), () => { setText(""); images.clearAttachments(); })) {
        setFailed(true); toast({ title: "发送未完成，文字和图片已保留，可点击重试。", tone: "error" });
      }
    } catch (error) { setFailed(true); toast({ title: error instanceof Error ? error.message : "发送失败，请重试。", tone: "error" }); }
    finally { inFlight.current = false; setSending(false); }
  };
  return <div className="mt-composer">
    {attemptMode ? <div className="mt-composer-mode" role="status"><span>正在写本题步骤 · 发送后检查这一步</span><button type="button" disabled={locked} onClick={onExitAttempt}>改为提问</button></div> : null}
    <div onDragEnter={locked ? undefined : images.onDragEnter} onDragLeave={images.onDragLeave} onDragOver={e => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); }} onDrop={e => { if (locked) e.preventDefault(); else images.handleDrop(e); }} className={`mt-composer-box relative ${images.dragging ? "ring-2 ring-[var(--ring)]" : ""}`}>
      {images.dragging && <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-[24px] bg-[var(--primary-soft)] text-sm text-[var(--primary-text)]">松开以上传图片</div>}
      <ImageAttachments images={images.attachments.map(a => ({ id: a.id, name: a.name, url: a.previewUrl }))} onRemove={images.removeAttachment} disabled={locked} />
      <textarea ref={input} value={text} onChange={event => setText(event.target.value)} onPaste={images.handlePaste} onKeyDown={event => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); } }} rows={1} disabled={locked} aria-label="聊天输入" aria-describedby="composer-help" placeholder={attemptMode ? "写本题的一步等式或答案，例如 2x=4…" : placeholder} className="mt-composer-input" />
      <div className="flex items-center gap-1">
        <input ref={picker} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={event => { images.addFiles(Array.from(event.target.files || [])); event.target.value = ""; }} />
        <button type="button" disabled={locked} onClick={() => picker.current?.click()} className="mt-icon-button p-2" aria-label="上传图片"><ImagePlus className="h-5 w-5" /></button>
        <button type="button" onClick={onAddMaterial} className="mt-icon-button p-2" aria-label="为当前对话添加资料"><Paperclip className="h-5 w-5" /></button>
        <span className="flex-1" />
        {images.attachments.length > 0 && <span className="text-[11px] text-[var(--muted-foreground)]">{images.attachments.length}/4 · 发送时交给当前模型</span>}
        {busy && onCancel && <button type="button" onClick={onCancel} className="min-h-9 rounded-full px-3 text-sm text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]">停止生成</button>}
        <button type="button" onClick={() => void submit()} disabled={(!text.trim() && !images.attachments.length) || locked} className="mt-send-button" aria-label={failed ? "重试发送" : attemptMode ? "提交本题步骤" : "发送"}>{sending || busy ? <Loader2 className="h-4 w-4 animate-spin" /> : failed ? "重试" : <ArrowUp className="h-[18px] w-[18px]" strokeWidth={2.25} />}</button>
      </div>
    </div>
    <p id="composer-help" className="mt-composer-help">{attemptMode ? <><kbd>Enter</kbd> 提交步骤 · <kbd>Shift</kbd> + <kbd>Enter</kbd> 换行 · 添加图片会改为图片提问</> : <><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd> + <kbd>Enter</kbd> 换行 · 粘贴 / 拖入图片，每张最多 10 MB</>}</p>
  </div>;
}
