"use client";

import { ArrowRight, GraduationCap } from "lucide-react";

export const STARTER_PROBLEMS = [
  { label: "先练移项", text: "2x+3=7", kind: "一元一次方程" },
  { label: "找齐两个根", text: "x^2-5x+6=0", kind: "一元二次方程" },
  { label: "试试消元", text: "2x+y=7; x-y=2", kind: "二元一次方程组" },
] as const;

export default function TutorWelcome({ disabled, onChoose }: { disabled: boolean; onChoose: (text: string) => void }) {
  return <section className="mt-tutor-welcome" aria-label="开始数学辅导">
    <div className="mt-empty-mark"><GraduationCap className="h-6 w-6" aria-hidden="true" /></div>
    <h2 className="mt-4 text-2xl font-semibold tracking-tight">今天，我们从哪道题开始？</h2>
    <p className="mt-2 max-w-xl text-sm leading-6 text-[var(--muted-foreground)]">发来题目或写下你的第一步，我会陪你逐步检查。也可以先选一道题试试。</p>
    <div className="mt-starter-problems">
      {STARTER_PROBLEMS.map(problem => <button key={problem.text} type="button" disabled={disabled} className="mt-starter-problem" onClick={() => { if (!disabled) onChoose(problem.text); }}>
        <span className="flex items-center justify-between gap-2 text-sm font-semibold"><span>{problem.label}</span><ArrowRight className="h-4 w-4" aria-hidden="true" /></span>
        <span className="mt-3 block whitespace-pre-wrap break-words font-mono text-base">{problem.text.replace("^2", "²").replace("; ", "\n")}</span>
        <span className="mt-3 block text-xs text-[var(--muted-foreground)]">{problem.kind}</span>
      </button>)}
    </div>
    <p className="mt-4 text-xs leading-5 text-[var(--muted-foreground)]">目前能逐步核验计算、整式和三类方程。其他题目会说明核验范围，并提供相关练习。</p>
  </section>;
}
