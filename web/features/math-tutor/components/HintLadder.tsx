"use client";

import { HINT_LADDER_MAX, normalizeAssistanceLevel } from "../lib/protocol";

interface HintLadderProps {
  /** Current effective assistance level from the latest server event. */
  level: number;
}

const LEVEL_NAMES = ["第 1 级", "第 2 级", "第 3 级", "第 4 级", "第 5 级"];

/**
 * Visual ladder of the tutoring hint levels (1-5). Purely informational:
 * every value comes from the server's effective_assistance_level field.
 */
export default function HintLadder({ level }: HintLadderProps) {
  const current = normalizeAssistanceLevel(level);

  return (
    <section
      className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm"
      aria-label="提示等级阶梯"
    >
      <h2 className="mb-3 text-sm font-semibold text-[var(--foreground)]">
        提示阶梯
      </h2>
      <ol className="flex flex-col gap-1.5" aria-label={current > 0 ? `当前提示等级：第 ${current} 级` : "尚未使用提示"}>
        {Array.from({ length: HINT_LADDER_MAX }, (_, index) => {
          const step = index + 1;
          const active = current > 0 && step <= current;
          const isCurrent = step === current;
          return (
            <li
              key={step}
              className={`flex min-h-[36px] items-center gap-2.5 rounded-lg px-3 py-1.5 text-sm transition-colors duration-200 ${
                isCurrent
                  ? "bg-amber-500/15 font-semibold text-amber-800 dark:text-amber-300"
                  : active
                    ? "bg-amber-500/5 text-amber-700 dark:text-amber-400"
                    : "text-[var(--muted-foreground)]"
              }`}
              aria-current={isCurrent ? "step" : undefined}
            >
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                  isCurrent
                    ? "bg-amber-500 text-white"
                    : active
                      ? "bg-amber-500/25 text-amber-800 dark:text-amber-200"
                      : "bg-[var(--muted)] text-[var(--muted-foreground)]"
                }`}
                aria-hidden="true"
              >
                {step}
              </span>
              <span>{LEVEL_NAMES[index]}</span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
        提示会随着你的请求逐级递进，每级只比上一级多给一点帮助。
      </p>
    </section>
  );
}
