"use client";

import katex from "katex";
import { ArrowRight, CircleCheck } from "lucide-react";
import BrandMark from "@/components/common/BrandMark";

export const STARTER_PROBLEMS = [
  { label: "先练移项", text: "2x+3=7", kind: "一元一次方程", tex: "2x+3=7" },
  { label: "找齐两个根", text: "x^2-5x+6=0", kind: "一元二次方程", tex: "x^2-5x+6=0" },
  { label: "试试消元", text: "2x+y=7; x-y=2", kind: "二元一次方程组", tex: "\\begin{cases}2x+y=7\\\\x-y=2\\end{cases}" },
] as const;

// Static, trusted TeX: rendered once at module load.
const TYPESET = STARTER_PROBLEMS.map(problem => katex.renderToString(problem.tex, { throwOnError: false, output: "html" }));

export default function TutorWelcome({ disabled, onChoose }: { disabled: boolean; onChoose: (text: string) => void }) {
  return <section className="mt-tutor-welcome" aria-label="开始数学辅导">
    <div className="mt-welcome-field mt-paper" aria-hidden="true" />
    <div className="mt-empty-mark"><BrandMark className="h-6 w-6" /></div>
    <p className="mt-welcome-eyebrow"><CircleCheck className="h-3.5 w-3.5" aria-hidden="true" />每一步都会核验</p>
    <h2 className="mt-welcome-title">今天，我们从哪道题<em>开始</em>？</h2>
    <p className="mt-3 max-w-xl text-[15px] leading-7 text-[var(--muted-foreground)]">发来题目或写下你的第一步，我会陪你逐步检查。也可以先选一道题试试。</p>
    <div className="mt-starter-problems">
      {STARTER_PROBLEMS.map((problem, index) => <button key={problem.text} type="button" disabled={disabled} aria-label={`${problem.label}：${problem.kind} ${problem.text}`} className="mt-starter-problem mt-rise" onClick={() => { if (!disabled) onChoose(problem.text); }}>
        <span className="flex items-center justify-between gap-2"><span className="mt-starter-index">0{index + 1}</span><span className="mt-starter-arrow"><ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></span></span>
        <span className="mt-starter-equation" aria-hidden="true" dangerouslySetInnerHTML={{ __html: TYPESET[index] }} />
        <span className="mt-starter-label">{problem.label}</span>
        <span className="mt-starter-kind">{problem.kind}</span>
      </button>)}
    </div>
    <p className="mt-welcome-scope">目前能逐步核验计算、整式和三类方程。其他题目会说明核验范围，并提供相关练习。</p>
  </section>;
}
