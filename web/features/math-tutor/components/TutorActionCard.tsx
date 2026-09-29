"use client";

import { AlertCircle, GraduationCap } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { actionLabel, normalizeAssistanceLevel } from "../lib/protocol";
import type { TutorMessage } from "../types";
import { supportExposureLabel } from "../lib/teaching-contract";
import ImageAttachments from "./ImageAttachments";

/**
 * One tutor message. Shows the student-facing message plus the current
 * effective assistance level — never internal fields, IDs, or codes.
 * turn_error frames render as a distinct error card.
 */
export default function TutorActionCard({ message, onContinue, onRecover }: { message: TutorMessage; onContinue?: () => void; onRecover?: () => void }) {
  if (message.kind === "student") {
    return <div className="flex justify-end"><div className="mt-student-message"><ImageAttachments images={message.attachments || []} /><MarkdownRenderer content={message.text} enableMath /></div></div>;
  }
  if (message.kind === "error") {
    return (
      <div
        className="flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3"
        role="alert"
      >
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--muted-foreground)]" aria-hidden="true" />
        <div className="min-w-0 text-sm leading-relaxed text-[var(--foreground)]">
          {message.text}
          {onRecover && <button type="button" className="ml-3 underline underline-offset-2" onClick={onRecover}>重新同步</button>}
        </div>
      </div>
    );
  }

  const label = actionLabel(message.action);
  const level = normalizeAssistanceLevel(message.assistanceLevel);

  return (
    <div className="mt-tutor-message">
      <div
        className="mt-tutor-avatar"
        aria-hidden="true"
      >
        <GraduationCap className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          {label && (
            <span className="rounded-md bg-[var(--muted)] px-2 py-0.5 text-xs font-medium text-[var(--muted-foreground)]">
              {label}
            </span>
          )}
          {level > 0 && (
            <span className="rounded-md bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-amber-300">
              已展示：{supportExposureLabel(level)}
            </span>
          )}
        </div>
        <div className="mt-answer-text">
          <MarkdownRenderer content={message.text} enableMath />
          {message.status === "PARTIAL" && <div className="mt-3 text-sm text-[var(--muted-foreground)]">这次回答没有完整生成。{onContinue && <button className="ml-2 text-[var(--primary-text)] underline underline-offset-2" onClick={onContinue}>继续生成</button>}</div>}
          {message.status === "FAILED" && onRecover && <button type="button" className="mt-3 text-sm text-[var(--primary-text)] underline underline-offset-2" onClick={onRecover}>重新同步</button>}
        </div>
      </div>
    </div>
  );
}
