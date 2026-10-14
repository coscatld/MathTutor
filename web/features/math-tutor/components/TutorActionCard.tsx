"use client";

import { AlertCircle } from "lucide-react";
import BrandMark from "@/components/common/BrandMark";
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
        className="mt-rise flex items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] px-4 py-3 shadow-[var(--shadow-xs)]"
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
      <div className="mt-tutor-avatar" aria-hidden="true">
        <BrandMark className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="mt-tutor-meta">
          <span className="mt-tutor-name">MathTutor</span>
          {label && <span className="mt-chip">{label}</span>}
          {level > 0 && <span className="mt-chip mt-chip-warn">已展示：{supportExposureLabel(level)}</span>}
        </div>
        <div className="mt-answer-text">
          <MarkdownRenderer content={message.text} enableMath />
          {message.status === "PARTIAL" && <div role="status" className="mt-3 border-l-2 border-[var(--border)] pl-3 text-sm leading-6 text-[var(--muted-foreground)]">这段还没讲完，末尾的公式和结论可能不完整。{onContinue ? <button type="button" className="ml-2 min-h-9 text-[var(--primary-text)] underline underline-offset-2" onClick={onContinue}>继续讲完</button> : "请接着查看后续回复。"}</div>}
          {message.status === "FAILED" && onRecover && <button type="button" className="mt-3 text-sm text-[var(--primary-text)] underline underline-offset-2" onClick={onRecover}>重新同步</button>}
        </div>
      </div>
    </div>
  );
}
