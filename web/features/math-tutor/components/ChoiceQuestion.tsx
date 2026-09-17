"use client";

import { useState } from "react";
import type { ChoiceSet } from "../types";

export default function ChoiceQuestion({choices, busy, onSubmit, allowUnsure = false}: {
  choices: ChoiceSet; busy: boolean; onSubmit: (id: string) => void; allowUnsure?: boolean;
}) {
  const [selected, setSelected] = useState("");
  return <form onSubmit={event => {event.preventDefault(); if (selected && !busy) onSubmit(selected);}}>
    <fieldset disabled={busy} className="space-y-3">
      <legend className="mb-3 text-sm font-semibold">选择一个答案</legend>
      {[...choices.options, ...(allowUnsure ? [{id: "unsure", text: "暂时不确定（不记为答错）"}] : [])].map(option => <label key={option.id} className={`flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border px-4 py-3 text-base transition-colors motion-reduce:transition-none ${selected === option.id ? "border-[var(--primary)] bg-[var(--muted)]" : "border-[var(--border)] bg-[var(--card)]"}`}>
        <input type="radio" name={`choice-${choices.version}`} value={option.id} checked={selected === option.id} onChange={() => setSelected(option.id)} className="h-4 w-4 shrink-0 accent-[var(--primary)] focus-visible:outline-2 focus-visible:outline-offset-4" />
        <span className="min-w-0 break-words">{option.id !== "unsure" && <span className="mr-3 font-mono font-semibold">{option.id}</span>}{option.text}</span>
      </label>)}
    </fieldset>
    <button type="submit" disabled={!selected || busy} className="mt-4 min-h-11 rounded-xl bg-[var(--primary)] px-6 py-3 text-sm font-semibold text-[var(--primary-foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50">{busy ? "正在保存…" : "提交选择"}</button>
  </form>;
}
