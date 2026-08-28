"use client";

import { AlertCircle, GraduationCap } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { actionLabel, normalizeAssistanceLevel } from "../lib/protocol";
import type { TutorMessage } from "../types";

/**
 * One tutor message. Shows the student-facing message plus the current
 * effective assistance level — never internal fields, IDs, or codes.
 * turn_error frames render as a distinct error card.
 */
export default function TutorActionCard({ message }: { message: TutorMessage }) {
  if (message.kind === "error") {
    return (
      <div
        className="flex items-start gap-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 dark:border-red-900 dark:bg-red-950/40"
        role="alert"
      >
        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
        <div className="min-w-0 text-sm leading-relaxed text-red-800 dark:text-red-200">
          {message.text}
        </div>
      </div>
    );
  }

  const label = actionLabel(message.action);
  const level = normalizeAssistanceLevel(message.assistanceLevel);

  return (
    <div className="flex items-start gap-3">
      <div
        className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-[#2563EB]/10"
        aria-hidden="true"
      >
        <GraduationCap className="h-4 w-4 text-[#1D4ED8] dark:text-blue-400" />
      </div>
      <div className="min-w-0 flex-1 rounded-2xl rounded-tl-sm border border-[var(--border)] bg-[var(--card)] px-4 py-3 shadow-sm">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          {label && (
            <span className="rounded-full bg-[var(--muted)] px-2 py-0.5 text-xs font-medium text-[var(--muted-foreground)]">
              {label}
            </span>
          )}
          {level > 0 && (
            <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-800 dark:text-amber-300">
              第 {level} 级提示
            </span>
          )}
        </div>
        <div className="text-[15px] leading-relaxed text-[var(--foreground)]">
          <MarkdownRenderer content={message.text} enableMath />
        </div>
      </div>
    </div>
  );
}
