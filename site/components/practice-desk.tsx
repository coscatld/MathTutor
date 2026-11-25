'use client';

import { useId, useState, type FormEvent } from 'react';
import { ArrowRight, Check, CornerDownLeft, Lightbulb } from 'lucide-react';
import { checkPractice, practiceExamples, type CheckedStep } from '@/lib/practice';
import type { Locale } from '@/lib/site';

const copy = {
  zh: {
    pick: '选择例题', topics: ['移项', '分数解', '负系数'], sheet: '解方程', input: '你的步骤',
    instructions: '每行写一步，也可以直接输入 x 的值。支持整数、分数、小数和一次项的加减。',
    placeholder: '在这里写第一步…', submit: '核验步骤', hint: '看提示', hide: '收起提示',
    feedback: '逐行反馈', empty: '写下第一步后，你可以在这里核对它是否保留了原方程的解。',
    equivalent: '这一步保持了原方程的解。继续把 x 单独留在一边。',
    solved: '这个值满足原方程，已经解出 x。',
    changed: '从这一行开始，解集发生了变化。检查等号两边的运算和符号，再试一次。',
    unreadable: '这一行超出了体验页的核验范围。可将一次式写成 2x+3 这样的形式，每次最多核验 12 步。',
    line: '第', suffix: '行', withHelp: '本题已看过提示', independent: '本题独立完成', aria: '解题草稿',
  },
  en: {
    pick: 'Choose a problem', topics: ['Move a term', 'Fractional answer', 'Negative coefficient'], sheet: 'Solve for x', input: 'Your steps',
    instructions: 'Write one step per line, or enter the value of x. Use sums or differences of linear terms, integers, fractions and decimals.',
    placeholder: 'Write your first step…', submit: 'Check steps', hint: 'Get a hint', hide: 'Hide hint',
    feedback: 'Step feedback', empty: 'Write a step to check whether it preserves the solution of the original equation.',
    equivalent: 'This step preserves the solution. Keep working until x is on its own.',
    solved: 'This value satisfies the original equation. You have solved for x.',
    changed: 'The solution set changes here. Check the operation and sign on each side, then try again.',
    unreadable: 'This line is outside the demo’s range. Use linear terms such as 2x+3 and submit up to 12 steps at once.',
    line: 'Line ', suffix: '', withHelp: 'Hint used for this problem', independent: 'Solved independently', aria: 'Equation workspace',
  },
} as const;

type Worksheet = { draft: string; results: CheckedStep[]; hintOpen: boolean; usedHint: boolean };
const blank: Worksheet = { draft: '', results: [], hintOpen: false, usedHint: false };

export function PracticeDesk({ locale }: { locale: Locale }) {
  const t = copy[locale];
  const [selected, setSelected] = useState(0);
  const [worksheets, setWorksheets] = useState<Record<number, Worksheet>>({});
  const { draft, results, hintOpen, usedHint } = worksheets[selected] ?? blank;
  function update(patch: Partial<Worksheet>) {
    setWorksheets(all => ({ ...all, [selected]: { ...(all[selected] ?? blank), ...patch } }));
  }
  const inputId = useId(), hintId = useId();
  const example = practiceExamples[selected];
  const complete = results.at(-1)?.status === 'solved';

  function check(event: FormEvent) {
    event.preventDefault();
    update({ results: checkPractice(draft, example) });
  }

  return <section aria-label={t.aria}>
    <fieldset className="flex flex-wrap gap-2 pb-6">
      <legend className="mb-2 font-medium">{t.pick}</legend>
      {t.topics.map((topic, index) =>
        <button key={topic} type="button" aria-pressed={index === selected} onClick={() => setSelected(index)}
          className="min-h-11 rounded-full border border-[var(--mt-border)] px-4 font-medium hover:border-[var(--mt-blue)] aria-pressed:border-[var(--mt-blue)] aria-pressed:bg-[var(--mt-blue)] aria-pressed:text-[var(--mt-on-blue)]">{topic}</button>)}
    </fieldset>
    <div className="grid overflow-hidden rounded-2xl border border-[var(--mt-border)] bg-[var(--mt-paper)] md:grid-cols-[3fr_2fr]">
      <form onSubmit={check} className="min-w-0 p-5 sm:p-8">
        <h2 className="text-sm font-semibold text-[var(--mt-blue)]">{t.sheet}</h2>
        <p className="my-4 font-serif text-4xl tracking-tight sm:text-5xl" aria-live="polite">{example.equation}</p>
        <label htmlFor={inputId} className="mt-8 block font-semibold">{t.input}</label>
        <p id={inputId + '-format'} className="my-2 leading-relaxed text-[var(--mt-muted)]">{t.instructions}</p>
        <textarea id={inputId} aria-describedby={inputId + '-format'} value={draft} onChange={event => update({ draft: event.target.value, results: [] })}
          rows={4} maxLength={2000} spellCheck={false} autoCapitalize="off" autoComplete="off" placeholder={t.placeholder}
          className="w-full resize-y rounded-xl border border-[var(--mt-border)] bg-[var(--mt-card)] p-4 font-mono text-lg leading-relaxed" />
        <div className="mt-4 flex flex-wrap gap-3">
          <button type="submit" disabled={!draft.trim()} className="inline-flex min-h-11 items-center gap-2 rounded-full bg-[var(--mt-blue)] px-5 font-medium text-[var(--mt-on-blue)] disabled:opacity-50">{t.submit}<ArrowRight size={16} aria-hidden="true" /></button>
          <button type="button" aria-controls={hintId} aria-expanded={hintOpen} onClick={() => update({ hintOpen: !hintOpen, usedHint: true })}
            className="inline-flex min-h-11 items-center gap-2 rounded-full border border-[var(--mt-border)] px-4"><Lightbulb size={16} aria-hidden="true" />{hintOpen ? t.hide : t.hint}</button>
        </div>
        <p id={hintId} hidden={!hintOpen} className="mt-4 leading-relaxed">{example.hint[locale]}</p>
      </form>
      <section aria-label={t.feedback} className="min-w-0 border-t border-[var(--mt-border)] bg-[var(--mt-card)] p-5 sm:p-8 md:border-t-0 md:border-l">
        <h2 className="flex items-center gap-2 font-semibold"><CornerDownLeft aria-hidden="true" size={18} />{t.feedback}</h2>
        <div aria-live="polite" aria-atomic="true">
          {results.length === 0 ? <p className="mt-4 leading-relaxed text-[var(--mt-muted)]">{t.empty}</p> :
            <ol className="mt-4 space-y-4">{results.map(row => <li key={row.line} className="border-l-2 border-[var(--mt-blue)] pl-3">
              <span className="text-sm text-[var(--mt-muted)]">{t.line}{row.line}{t.suffix}</span>
              <code className="my-1 block break-all text-base">{row.expression}</code>
              <p className="leading-relaxed">{t[row.status]}</p>
            </li>)}</ol>}
          {complete && <p className="mt-5 flex items-center gap-2 font-medium"><Check size={18} aria-hidden="true" />{usedHint ? t.withHelp : t.independent}</p>}
        </div>
      </section>
    </div>
  </section>;
}
