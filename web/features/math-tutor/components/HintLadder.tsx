"use client";

import { HINT_LADDER_MAX, normalizeAssistanceLevel } from "../lib/protocol";

interface HintLadderProps {
  /** Current effective assistance level from the latest server event. */
  level: number;
}

const LEVEL_NAMES = ["方向", "方法", "下一步", "校正", "完整解答"];

/**
 * Visual ladder of the tutoring hint levels (1-5). Purely informational:
 * every value comes from the server's effective_assistance_level field.
 */
export default function HintLadder({ level }: HintLadderProps) {
  const current = normalizeAssistanceLevel(level);

  return (
    <section
      className="rounded-2xl border border-[#deddd7] bg-white p-4 dark:border-slate-700 dark:bg-slate-900"
      aria-label="提示等级阶梯"
    >
      <h2 className="mb-3 text-sm font-semibold text-[var(--foreground)]">
        提示阶梯
      </h2>
      <div className="mb-3 flex items-center gap-2"><div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800"><div className="h-full rounded-full bg-amber-500 transition-[width]" style={{ width: `${current * 20}%` }} /></div><span className="text-xs font-semibold text-amber-700">L{current}</span></div>
      <ol className="flex flex-col gap-1" aria-label={current > 0 ? `当前提示等级：第 ${current} 级` : "尚未使用提示"}>
        {Array.from({ length: HINT_LADDER_MAX }, (_, index) => {
          const step = index + 1;
          const active = current > 0 && step <= current;
          const isCurrent = step === current;
          return (
            <li
              key={step}
              className={`flex min-h-[30px] items-center gap-2 rounded-lg px-2 py-1 text-xs transition-colors duration-200 ${
                isCurrent
                  ? "bg-amber-500/15 font-semibold text-amber-800 dark:text-amber-300"
                  : active
                    ? "bg-amber-500/5 text-amber-700 dark:text-amber-400"
                    : "text-[var(--muted-foreground)]"
              }`}
              aria-current={isCurrent ? "step" : undefined}
            >
              <span
                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-bold ${
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
              <span>L{step} · {LEVEL_NAMES[index]}</span>
            </li>
          );
        })}
      </ol>
      <p className="mt-2.5 text-xs leading-relaxed text-[var(--muted-foreground)]">
        每次只多给一点帮助，直到你真正需要完整解答。
      </p>
    </section>
  );
}
