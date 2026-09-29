"use client";

import { ArrowDown, BrainCircuit, FolderOpen, GraduationCap, Library, Lightbulb, PanelRightClose } from "lucide-react";
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
import Link from "next/link";

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
    <section className="mt-chat-column" data-empty={state.messages.length === 0 ? "true" : undefined}>
      <header className="mt-chat-header">
        <div className="mt-header-context"><CurrentProblem context={state.problemContext} /></div>
        <div className="mt-header-title"><h1 className="text-[15px] font-semibold text-[var(--foreground)]">数学辅导</h1></div>
        <div className="mt-header-actions"><ConnectionStatus status={state.connectionStatus} note={state.connectionNote} onReconnect={reconnect} />
          <Tooltip label="教学提示" disabled={tool === "hints"}><button type="button" aria-label="当前教学支持与可用操作" onClick={() => toggleTool("hints")} aria-pressed={tool === "hints"} className="mt-icon-button"><Lightbulb className="h-4 w-4" aria-hidden="true" /></button></Tooltip>
          <Tooltip label="对话资料" disabled={tool === "documents"}><button type="button" aria-label="当前对话的学习资料" onClick={() => toggleTool("documents")} aria-pressed={tool === "documents"} className="mt-icon-button"><FolderOpen className="h-4 w-4" aria-hidden="true" /></button></Tooltip>
          <Tooltip label="学习记忆" disabled={tool === "memory"}><button type="button" aria-label="查看 Tutor 使用的学习记忆" onClick={() => toggleTool("memory")} aria-pressed={tool === "memory"} className="mt-icon-button"><BrainCircuit className="h-4 w-4" aria-hidden="true" /></button></Tooltip>
          <Tooltip label="知识库与问答范围"><Link href={`/math-tutor/knowledge?conversation=${encodeURIComponent(sessionId)}`} aria-label="知识库与问答范围" className="mt-icon-button"><Library className="h-4 w-4" aria-hidden="true" /></Link></Tooltip>
          {tool ? <Tooltip label="收起"><button type="button" aria-label="收起右侧工具" onClick={() => setTool(null)} className="mt-icon-button"><PanelRightClose className="h-4 w-4" aria-hidden="true" /></button></Tooltip> : null}
        </div>
      </header>
      <div className="mt-reading-region">
      <div ref={scroll.viewport} onScroll={scroll.onScroll} role="log" aria-live="polite" aria-label="辅导对话" tabIndex={0} data-chat-scroll-root="true" className="mt-chat-log">
        <div ref={scroll.content} className="mt-reading-width flex flex-col gap-7">
          {state.messages.length === 0 ? <div className="flex flex-col items-center text-center"><div className="mt-empty-mark"><GraduationCap className="h-6 w-6" aria-hidden="true" /></div><h2 className="mt-4 text-2xl font-semibold tracking-tight">今天想一起解决什么题？</h2><p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted-foreground)] [text-wrap:balance]">输入题目、写下你的解题步骤，或问一个概念。我会用分级提示陪你一步步想清楚。</p><p className="mt-3 text-xs text-[var(--muted-foreground)]">知识库问答需显式挂载，不会自动使用其他会话的附件。可从右上角<Library className="mx-1 inline h-3.5 w-3.5 align-[-2px]" aria-label="知识库" />管理问答范围。</p></div> : state.messages.map((message) => <TutorActionCard key={message.id} message={message} onRecover={message.id === state.messages[state.messages.length - 1]?.id && !state.pendingCommand ? recover : undefined} onContinue={message.id === state.messages[state.messages.length - 1]?.id && !state.pendingCommand ? () => send("send_message", { text: "继续" }) : undefined} />)}
          {busy ? <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)]"><span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--primary)]" />Tutor 正在思考下一步…</div> : null}
          {state.problemContext?.choices && state.allowedNextInputs.includes("submit_attempt") && <section aria-label="选择题练习" className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-5"><h2 className="mb-3 text-base font-semibold">选择题练习</h2><p className="mb-4 break-words">{state.problemContext.display_text}</p><ChoiceQuestion key={`${state.cycleId}:${state.problemContext.choices.version}`} choices={state.problemContext.choices} busy={busy || !connected} onSubmit={choice_id => send("submit_attempt", {choice_id, choice_version: state.problemContext?.choices?.version ?? ""})} /></section>}
        </div>
      </div>
      {scroll.away ? <button type="button" onClick={scroll.toLatest} className="mt-jump-latest"><ArrowDown className="h-4 w-4" aria-hidden="true" />回到最新</button> : null}
      </div>
      <ChatComposer onCancel={() => send("cancel_turn")} busy={busy} disabled={!connected} onSend={sendMessage} onAddMaterial={() => setTool("documents")} />
    </section>
    {tool ? <TutorToolsPanel view={tool} onClose={() => setTool(null)} sessionId={sessionId} level={state.assistanceLevel} plan={state.teachingPlan} evidence={state.evidenceSummary} diagnosis={state.diagnosis} offer={state.activeOffer} actions={state.allowedActions} allowed={state.allowedNextInputs} busy={busy} disabled={!connected} onCommand={(command, payload) => send(command, payload)} /> : null}
  </div>;
}
