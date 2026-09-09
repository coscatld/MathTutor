"use client";

import { Loader2, Paperclip, Send } from "lucide-react";
import { useState } from "react";

export default function ChatComposer({ busy, disabled, onSend, onAddMaterial, onCancel }: { busy: boolean; disabled: boolean; onSend: (text: string) => void; onAddMaterial: () => void; onCancel?: () => void }) {
  const [text, setText] = useState("");
  const submit = () => { const value = text.trim(); if (!value || busy || disabled) return; onSend(value); setText(""); };
  return <div className="border-t border-[#e3e1da] bg-[#faf9f5] px-5 py-4 dark:border-slate-800 dark:bg-[#111619]">
    <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-[#d6d4cc] bg-white p-2 shadow-[0_6px_24px_rgba(35,45,55,.07)] focus-within:border-[#7da4df] dark:border-slate-700 dark:bg-slate-900">
      <button type="button" onClick={onAddMaterial} className="mb-0.5 rounded-xl p-2.5 text-slate-500 hover:bg-slate-100 hover:text-[#1d5fd1] dark:hover:bg-slate-800" aria-label="为当前对话添加资料"><Paperclip className="h-5 w-5" /></button>
      <textarea value={text} onChange={(event) => setText(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); submit(); } }} rows={1} disabled={disabled || busy} placeholder="输入题目、你的解法，或问一个数学问题…" className="max-h-36 min-h-[42px] flex-1 resize-none bg-transparent px-1 py-2.5 text-[15px] leading-5 outline-none placeholder:text-slate-400" />
      {busy && onCancel && <button type="button" onClick={onCancel} className="px-2 text-sm text-slate-500">停止生成</button>}
      <button type="button" onClick={submit} disabled={!text.trim() || busy || disabled} className="mb-0.5 flex h-10 w-10 items-center justify-center rounded-xl bg-[#1d5fd1] text-white hover:bg-[#174fab] disabled:cursor-not-allowed disabled:opacity-40" aria-label="发送">{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}</button>
    </div>
    <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-slate-400">Enter 发送 · Shift + Enter 换行 · Tutor 会按步骤引导，不会越过答案披露规则</p>
  </div>;
}
