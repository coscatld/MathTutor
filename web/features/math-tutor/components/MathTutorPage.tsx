"use client";

import { BrainCircuit, FolderOpen, GraduationCap, Lightbulb, PanelRightClose } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMathTutorSession } from "../hooks/useMathTutorSession";
import { makeSessionId } from "../lib/protocol";
import Tooltip from "../desktop/components/Tooltip";
import ChatComposer from "./ChatComposer";
import ConnectionStatus from "./ConnectionStatus";
import TutorActionCard from "./TutorActionCard";
import TutorToolsPanel, { type ToolView } from "./TutorToolsPanel";

export default function MathTutorPage() {
  const search = useSearchParams();
  const router = useRouter();
  const generated = useMemo(() => makeSessionId(), []);
  const sessionId = search.get("session")?.trim() || generated;
  useEffect(() => { if (!search.get("session")) router.replace(`/math-tutor?session=${encodeURIComponent(sessionId)}`); }, [router, search, sessionId]);
  return <TutorConversation key={sessionId} sessionId={sessionId} />;
}

function TutorConversation({ sessionId }: { sessionId: string }) {
  const { state, send, reconnect } = useMathTutorSession(sessionId);
  const [tool, setTool] = useState<ToolView | null>(null);
  const logEnd = useRef<HTMLDivElement>(null);
  useEffect(() => { logEnd.current?.scrollIntoView({ behavior: "smooth" }); }, [state.messages, state.pendingCommand]);
  const busy = state.pendingCommand !== null;
  const connected = state.connectionStatus === "connected";
  const submitText = (text: string) => {
    send("send_message", { text });
  };
  const toggleTool = (next: ToolView) => setTool((current) => current === next ? null : next);
  return <div className="flex h-full min-h-0 bg-[#faf9f5] dark:bg-[#111619]">
    <section className="flex min-w-0 flex-1 flex-col">
      <header className="relative flex h-16 shrink-0 items-center justify-end border-b border-[#e3e1da] px-5 dark:border-slate-800">
        <div className="pointer-events-none absolute left-1/2 flex min-w-0 -translate-x-1/2 items-center gap-2 text-center"><div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#e1ebfa] text-[#1d5fd1] dark:bg-blue-950"><GraduationCap className="h-4 w-4" /></div><div className="min-w-0"><h1 className="truncate font-serif text-base font-bold">Tutor</h1><p className="hidden text-xs text-slate-500 xl:block">一起拆解问题，理解比答案更重要</p></div></div>
        <div className="flex items-center gap-1"><ConnectionStatus status={state.connectionStatus} note={state.connectionNote} onReconnect={reconnect} />
          <Tooltip label="渐进提示与可用操作"><button type="button" onClick={() => toggleTool("hints")} aria-pressed={tool === "hints"} className={`rounded-lg p-2.5 ${tool === "hints" ? "bg-amber-100 text-amber-700 dark:bg-amber-950" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`}><Lightbulb className="h-4 w-4" /></button></Tooltip>
          <Tooltip label="当前对话的学习资料"><button type="button" onClick={() => toggleTool("documents")} aria-pressed={tool === "documents"} className={`rounded-lg p-2.5 ${tool === "documents" ? "bg-blue-100 text-blue-700 dark:bg-blue-950" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`}><FolderOpen className="h-4 w-4" /></button></Tooltip>
          <Tooltip label="查看 Tutor 使用的学习记忆"><button type="button" onClick={() => toggleTool("memory")} aria-pressed={tool === "memory"} className={`rounded-lg p-2.5 ${tool === "memory" ? "bg-violet-100 text-violet-700 dark:bg-violet-950" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`}><BrainCircuit className="h-4 w-4" /></button></Tooltip>
          {tool ? <Tooltip label="收起右侧工具"><button type="button" onClick={() => setTool(null)} className="rounded-lg p-2.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><PanelRightClose className="h-4 w-4" /></button></Tooltip> : null}
        </div>
      </header>
      <div role="log" aria-live="polite" aria-label="辅导对话" className="min-h-0 flex-1 overflow-y-auto px-5 py-8">
        <div className="mx-auto flex max-w-3xl flex-col gap-5">
          {state.messages.length === 0 ? <div className="flex min-h-[52vh] flex-col items-center justify-center text-center"><div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#e5ecf7] text-[#1d5fd1] dark:bg-blue-950"><GraduationCap className="h-7 w-7" /></div><h2 className="mt-5 font-serif text-2xl font-bold">今天想一起解决什么？</h2><p className="mt-2 max-w-md text-sm leading-6 text-slate-500">直接输入题目、你的解题步骤，或者问一个概念。需要时，可从输入框旁把资料加入当前对话。</p></div> : state.messages.map((message) => <TutorActionCard key={message.id} message={message} onContinue={message.id === state.messages[state.messages.length - 1]?.id && !state.pendingCommand ? () => send("send_message", { text: "继续" }) : undefined} />)}
          {busy ? <div className="flex items-center gap-2 text-xs text-slate-400"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#1d5fd1]" />Tutor 正在思考下一步…</div> : null}<div ref={logEnd} />
        </div>
      </div>
      <ChatComposer onCancel={() => send("cancel_turn")} busy={busy} disabled={!connected} onSend={submitText} onAddMaterial={() => setTool("documents")} />
    </section>
    {tool ? <TutorToolsPanel view={tool} onClose={() => setTool(null)} sessionId={sessionId} level={state.assistanceLevel} allowed={state.allowedNextInputs} busy={busy} disabled={!connected} onCommand={(command) => send(command)} /> : null}
  </div>;
}
