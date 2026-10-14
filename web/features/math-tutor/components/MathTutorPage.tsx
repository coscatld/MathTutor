"use client";

import { ArrowDown, BrainCircuit, FolderOpen, Library, Lightbulb, PanelRightClose } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useConversationScroll } from "../hooks/useConversationScroll";
import { useMathTutorSession } from "../hooks/useMathTutorSession";
import { makeSessionId } from "../lib/protocol";
import { attemptBindingIsCurrent, currentAttemptBinding, type AttemptBinding } from "../lib/attempt";
import Tooltip from "../desktop/components/Tooltip";
import ChatComposer from "./ChatComposer";
import ChoiceQuestion from "./ChoiceQuestion";
import ConnectionStatus from "./ConnectionStatus";
import TutorActionCard from "./TutorActionCard";
import TutorToolsPanel, { type ToolView } from "./TutorToolsPanel";
import { CurrentProblem } from "./TeachingContext";
import StudentNextStep from "./StudentNextStep";
import TutorWelcome from "./TutorWelcome";
import NearbyPractice from "./NearbyPractice";
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
  const { state, send, sendMessage, sendAttempt, reconnect, recover } = useMathTutorSession(sessionId);
  const [tool, setTool] = useState<ToolView | null>(null);
  const [composeFocus, setComposeFocus] = useState(0);
  const [attemptBinding, setAttemptBinding] = useState<AttemptBinding | null>(null);
  const choices = useRef<HTMLElement>(null);
  const scroll = useConversationScroll(state.messages, state.pendingCommand);
  const busy = state.pendingCommand !== null;
  const connected = state.connectionStatus === "connected";
  const attemptMode = attemptBindingIsCurrent(attemptBinding, state);
  useEffect(() => { if (attemptBinding && !attemptMode) setAttemptBinding(null); }, [attemptBinding, attemptMode]);
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
          {state.messages.length === 0 ? <TutorWelcome disabled={busy || !connected} onChoose={text => send("send_message", { text })} /> : state.messages.map((message) => <TutorActionCard key={message.id} message={message} onRecover={message.id === state.messages[state.messages.length - 1]?.id && !state.pendingCommand ? recover : undefined} onContinue={message.id === state.messages[state.messages.length - 1]?.id && !state.pendingCommand ? () => send("send_message", { text: "继续" }) : undefined} />)}
          {busy ? <div className="mt-thinking"><span className="mt-thinking-dots" aria-hidden="true"><i /><i /><i /></span>Tutor 正在思考下一步…</div> : null}
          {state.problemContext?.choices && state.allowedNextInputs.includes("submit_attempt") && <section ref={choices} aria-label="选择题练习" className="mt-card mt-rise p-5"><h2 className="mb-3 text-base font-semibold">选择题练习</h2><p className="mb-4 break-words">{state.problemContext.display_text}</p><ChoiceQuestion key={`${state.cycleId}:${state.problemContext.choices.version}`} choices={state.problemContext.choices} busy={busy || !connected} onSubmit={choice_id => send("submit_attempt", {choice_id, choice_version: state.problemContext?.choices?.version ?? ""})} /></section>}
          {state.messages.length > 0 ? <StudentNextStep context={state.problemContext} plan={state.teachingPlan} evidence={state.evidenceSummary} offer={state.activeOffer} actions={state.allowedActions} allowed={state.allowedNextInputs} busy={busy} disabled={!connected} onCommand={(command, payload) => send(command, payload)} onWrite={() => { if (state.problemContext?.choices) choices.current?.querySelector<HTMLInputElement>('input[type="radio"]:not(:disabled)')?.focus(); else { setAttemptBinding(currentAttemptBinding(state)); setComposeFocus(current => current + 1); } }} /> : null}
          <NearbyPractice problem={state.recoveryProblem} disabled={busy || !connected} onChoose={text => send("send_message", { text })} />
        </div>
      </div>
      {scroll.away ? <button type="button" onClick={scroll.toLatest} className="mt-jump-latest"><ArrowDown className="h-4 w-4" aria-hidden="true" />回到最新</button> : null}
      </div>
      <ChatComposer attemptMode={attemptMode} onExitAttempt={() => setAttemptBinding(null)} onSendAttempt={text => attemptBinding ? sendAttempt(text, attemptBinding) : Promise.resolve(false)} focusRequest={composeFocus} placeholder={state.problemContext?.lifecycle.toUpperCase() === "ACTIVE" ? "写下这一步，或告诉我哪里卡住了…" : undefined} onCancel={() => send("cancel_turn")} busy={busy} disabled={!connected} onSend={sendMessage} onAddMaterial={() => setTool("documents")} />
    </section>
    {tool ? <TutorToolsPanel view={tool} onClose={() => setTool(null)} sessionId={sessionId} level={state.assistanceLevel} plan={state.teachingPlan} evidence={state.evidenceSummary} diagnosis={state.diagnosis} offer={state.activeOffer} actions={state.allowedActions} allowed={state.allowedNextInputs} busy={busy} disabled={!connected} onCommand={(command, payload) => send(command, payload)} /> : null}
  </div>;
}
