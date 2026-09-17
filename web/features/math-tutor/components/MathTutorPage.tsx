"use client";

import { ArrowDown, BrainCircuit, FolderOpen, GraduationCap, Lightbulb, PanelRightClose } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useConversationScroll } from "../hooks/useConversationScroll";
import { useMathTutorSession } from "../hooks/useMathTutorSession";
import { makeSessionId } from "../lib/protocol";
import Tooltip from "../desktop/components/Tooltip";
import ChatComposer from "./ChatComposer";
import ChoiceQuestion from "./ChoiceQuestion";
import ConnectionStatus from "./ConnectionStatus";
import TutorActionCard from "./TutorActionCard";
import TutorToolsPanel, { type ToolView } from "./TutorToolsPanel";
import { CurrentProblem } from "./TeachingContext";

export default function MathTutorPage() {
  const search = useSearchParams();
  const router = useRouter();
  const generated = useMemo(() => makeSessionId(), []);
  const sessionId = search.get("session")?.trim() || generated;
  useEffect(() => { if (!search.get("session")) router.replace(`/math-tutor?session=${encodeURIComponent(sessionId)}`); }, [router, search, sessionId]);
  return <TutorConversation key={sessionId} sessionId={sessionId} />;
}

function TutorConversation({ sessionId }: { sessionId: string }) {
  const { state, send, sendMessage, reconnect, recover } = useMathTutorSession(sessionId);
  const [tool, setTool] = useState<ToolView | null>(null);
  const scroll = useConversationScroll(state.messages, state.pendingCommand);
  const busy = state.pendingCommand !== null;
  const connected = state.connectionStatus === "connected";
  const toggleTool = (next: ToolView) => setTool((current) => current === next ? null : next);
  return <div className="mt-conversation">
    <section className="mt-chat-column">
      <header className="mt-chat-header">
        <div className="mt-header-context"><CurrentProblem context={state.problemContext} /></div>
        <div className="mt-header-title"><GraduationCap className="h-4 w-4" aria-hidden="true" /><h1 className="font-serif text-base font-bold">Tutor</h1></div>
        <div className="mt-header-actions"><ConnectionStatus status={state.connectionStatus} note={state.connectionNote} onReconnect={reconnect} />
          <Tooltip label="教学提示" disabled={tool === "hints"}><button type="button" aria-label="当前教学支持与可用操作" onClick={() => toggleTool("hints")} aria-pressed={tool === "hints"} className={`rounded-lg p-2.5 ${tool === "hints" ? "bg-amber-100 text-amber-700 dark:bg-amber-950" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`}><Lightbulb className="h-4 w-4" aria-hidden="true" /></button></Tooltip>
          <Tooltip label="对话资料" disabled={tool === "documents"}><button type="button" aria-label="当前对话的学习资料" onClick={() => toggleTool("documents")} aria-pressed={tool === "documents"} className={`rounded-lg p-2.5 ${tool === "documents" ? "bg-blue-100 text-blue-700 dark:bg-blue-950" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`}><FolderOpen className="h-4 w-4" aria-hidden="true" /></button></Tooltip>
          <Tooltip label="学习记忆" disabled={tool === "memory"}><button type="button" aria-label="查看 Tutor 使用的学习记忆" onClick={() => toggleTool("memory")} aria-pressed={tool === "memory"} className={`rounded-lg p-2.5 ${tool === "memory" ? "bg-violet-100 text-violet-700 dark:bg-violet-950" : "text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"}`}><BrainCircuit className="h-4 w-4" aria-hidden="true" /></button></Tooltip>
          {tool ? <Tooltip label="收起"><button type="button" aria-label="收起右侧工具" onClick={() => setTool(null)} className="rounded-lg p-2.5 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"><PanelRightClose className="h-4 w-4" aria-hidden="true" /></button></Tooltip> : null}
        </div>
      </header>
      <div className="mt-reading-region">
      <div ref={scroll.viewport} onScroll={scroll.onScroll} role="log" aria-live="polite" aria-label="辅导对话" tabIndex={0} data-chat-scroll-root="true" className="mt-chat-log">
        <div ref={scroll.content} className="mt-reading-width flex flex-col gap-7">
          {state.messages.length === 0 ? <div className="flex min-h-[52vh] flex-col items-center justify-center text-center"><div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-[#e5ecf7] text-[#1d5fd1] dark:bg-blue-950"><GraduationCap className="h-7 w-7" /></div><h2 className="mt-5 font-serif text-2xl font-bold">今天想一起解决什么？</h2><p className="mt-2 max-w-md text-sm leading-6 text-slate-500">直接输入题目、你的解题步骤，或者问一个概念。需要时，可从输入框旁把资料加入当前对话。</p></div> : state.messages.map((message) => <TutorActionCard key={message.id} message={message} onRecover={message.id === state.messages[state.messages.length - 1]?.id && !state.pendingCommand ? recover : undefined} onContinue={message.id === state.messages[state.messages.length - 1]?.id && !state.pendingCommand ? () => send("send_message", { text: "继续" }) : undefined} />)}
          {busy ? <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--primary)]" />Tutor 正在思考下一步…</div> : null}
          {state.problemContext?.choices && state.allowedNextInputs.includes("submit_attempt") && <section aria-label="选择题练习" className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5"><h2 className="mb-3 font-serif text-lg">选择题练习</h2><p className="mb-4 break-words">{state.problemContext.display_text}</p><ChoiceQuestion key={`${state.cycleId}:${state.problemContext.choices.version}`} choices={state.problemContext.choices} busy={busy || !connected} onSubmit={choice_id => send("submit_attempt", {choice_id, choice_version: state.problemContext?.choices?.version ?? ""})} /></section>}
        </div>
      </div>
      {scroll.away ? <button type="button" onClick={scroll.toLatest} className="mt-jump-latest"><ArrowDown className="h-4 w-4" aria-hidden="true" />回到最新</button> : null}
      </div>
      <ChatComposer onCancel={() => send("cancel_turn")} busy={busy} disabled={!connected} onSend={sendMessage} onAddMaterial={() => setTool("documents")} />
    </section>
    {tool ? <TutorToolsPanel view={tool} onClose={() => setTool(null)} sessionId={sessionId} level={state.assistanceLevel} plan={state.teachingPlan} evidence={state.evidenceSummary} diagnosis={state.diagnosis} offer={state.activeOffer} actions={state.allowedActions} allowed={state.allowedNextInputs} busy={busy} disabled={!connected} onCommand={(command, payload) => send(command, payload)} /> : null}
  </div>;
}
