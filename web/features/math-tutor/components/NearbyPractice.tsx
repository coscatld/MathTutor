"use client";

import { ArrowRight } from "lucide-react";

export default function NearbyPractice({ problem, disabled, onChoose }: { problem?: { text: string; problem_type: string; relation: string } | null; disabled: boolean; onChoose: (text: string) => void }) {
  if (!problem?.text.trim()) return null;
  return <section aria-label="相关的可核验练习" className="mt-student-step">
    <h2 className="text-sm font-semibold">先练一道相关的基础题</h2>
    <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{problem.relation}</p>
    <p className="mt-3 whitespace-pre-wrap break-words font-mono text-base">{problem.text}</p>
    <div className="mt-student-step-actions"><button type="button" className="mt-step-button mt-step-button-primary" disabled={disabled} onClick={() => { if (!disabled) onChoose(`换题：${problem.text}`); }}>练这道题<ArrowRight className="h-4 w-4" aria-hidden="true" /></button></div>
  </section>;
}
