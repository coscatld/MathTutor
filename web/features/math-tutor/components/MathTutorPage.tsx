"use client";

import { GraduationCap, MessageSquareHeart, PlusCircle } from "lucide-react";
import { useMathTutorSession } from "../hooks/useMathTutorSession";
import { allowsAttempt } from "../lib/protocol";
import type { MathTutorCommand } from "../types";
import ActionBar from "./ActionBar";
import AttemptComposer from "./AttemptComposer";
import ConnectionStatus from "./ConnectionStatus";
import HintLadder from "./HintLadder";
import ProblemCard from "./ProblemCard";
import ProblemComposer from "./ProblemComposer";
import TutorActionCard from "./TutorActionCard";

/**
 * Guided math tutoring workspace (student-facing, Chinese UI).
 *
 * Layout: problem area + tutor messages + answer area on the left, and the
 * hint ladder + server-granted actions on the right. All capabilities come
 * from allowed_next_inputs — this page maintains NO second state machine.
 */
export default function MathTutorPage() {
  const { state, send, newProblem, reconnect } = useMathTutorSession();

  const busy = state.pendingCommand !== null;
  const connected = state.connectionStatus === "connected";
  const blocked = !connected || busy;

  const attemptAllowed = allowsAttempt(state.allowedNextInputs);
  const clarifyCommand: MathTutorCommand | null = state.allowedNextInputs.includes(
    "clarify_problem",
  )
    ? "clarify_problem"
    : state.allowedNextInputs.includes("clarify_attempt")
      ? "clarify_attempt"
      : null;

  const handleCommand = (command: MathTutorCommand) => {
    send(command);
  };

  return (
    <div className="mx-auto flex h-full min-h-0 w-full max-w-[1200px] flex-col gap-4 p-4 md:p-6">
      {/* Header */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <div
            className="flex h-10 w-10 items-center justify-center rounded-xl bg-[#2563EB]/10"
            aria-hidden="true"
          >
            <GraduationCap className="h-5 w-5 text-[#1D4ED8] dark:text-blue-400" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-[var(--foreground)] sm:text-xl">
              数学辅导
            </h1>
            <p className="text-xs text-[var(--muted-foreground)] sm:text-sm">
              一步一步来，我不会直接告诉你答案。
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          {state.problemActive && (
            <button
              type="button"
              onClick={newProblem}
              className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
            >
              <PlusCircle className="h-4 w-4" aria-hidden="true" />
              新题目
            </button>
          )}
          <ConnectionStatus
            status={state.connectionStatus}
            note={state.connectionNote}
            onReconnect={reconnect}
          />
        </div>
      </header>

      {/* Workspace */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        {/* Left: problem + conversation + answer */}
        <div className="flex min-h-0 flex-col gap-4">
          {state.problemActive && state.problemLatex ? (
            <ProblemCard latex={state.problemLatex} />
          ) : (
            <ProblemComposer
              disabled={!connected}
              busy={busy}
              onSubmit={(text) => send("submit_problem", { text })}
            />
          )}

          <div
            className="flex min-h-[200px] flex-1 flex-col gap-3 overflow-y-auto rounded-2xl border border-[var(--border)] bg-[var(--background)]/40 p-4"
            role="log"
            aria-live="polite"
            aria-label="辅导对话"
          >
            {state.messages.length === 0 ? (
              <div className="flex h-full min-h-[160px] flex-col items-center justify-center gap-2 text-center">
                <MessageSquareHeart
                  className="h-8 w-8 text-[var(--muted-foreground)]"
                  aria-hidden="true"
                />
                <p className="text-sm text-[var(--muted-foreground)]">
                  提交一道题目，辅导就从这里开始。
                </p>
              </div>
            ) : (
              state.messages.map((message) => (
                <TutorActionCard key={message.id} message={message} />
              ))
            )}
          </div>

          {attemptAllowed && (
            <AttemptComposer
              disabled={!connected}
              busy={busy}
              onSubmit={(answer) => send("submit_attempt", { answer })}
            />
          )}
          {!attemptAllowed && clarifyCommand && (
            <AttemptComposer
              disabled={!connected}
              busy={busy}
              heading="补充说明"
              placeholder="刚才的意思可以再说清楚一点吗？"
              submitLabel="发送说明"
              helperText="辅导老师没太理解你的意思，请再解释一下。"
              onSubmit={(text) => send(clarifyCommand, { text })}
            />
          )}
        </div>

        {/* Right: hint ladder + server-granted actions */}
        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto pb-1">
          <HintLadder level={state.assistanceLevel} />
          <ActionBar
            allowed={state.allowedNextInputs}
            busy={busy}
            disabled={!connected}
            onCommand={handleCommand}
          />
        </div>
      </div>
    </div>
  );
}
