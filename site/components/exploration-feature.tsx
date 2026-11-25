import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { localePath, type Locale } from '@/lib/site';

const content = {
  zh: {
    label: '从不同来源读数学',
    title: '带着一个疑问，读出自己的理解。',
    body: '查一个概念，读百科里的定义，再看教材怎样使用它。每条摘录保留出处，你也可以在本机检索自己的讲义。',
    steps: [
      ['提出问题', '打开知识探索，输入要弄清楚的术语或问题。'],
      ['对照来源', '对照百科、教材或社区问答，回到原文检查公式和前提。'],
      ['自己试一试', '记下你的理解，再用一道新题检查这个方法适用的条件。'],
    ],
    action: '阅读知识探索指南',
  },
  en: {
    label: 'Mathematics across sources',
    title: 'Start with a question. Build your own understanding.',
    body: 'Look up a definition, then see how a textbook uses it. Follow each excerpt to the source, or search your own lecture notes on your device.',
    steps: [
      ['Ask a question', 'Open Knowledge Exploration and enter a term or a question.'],
      ['Read the sources', 'Compare an encyclopedia, a textbook, or a community explanation. Check formulas and conditions in the original.'],
      ['Try it yourself', 'Write down your interpretation and try it on a new problem.'],
    ],
    action: 'Read the exploration guide',
  },
} as const;

export function ExplorationFeature({ locale }: { locale: Locale }) {
  const copy = content[locale];
  return (
    <section className="border-b border-[var(--mt-border)]" aria-labelledby="exploration-title">
      <div className="mt-container grid gap-10 py-16 lg:grid-cols-[1.1fr_0.9fr] lg:gap-16">
        <div>
          <p className="text-sm font-medium text-[var(--mt-blue)]">{copy.label}</p>
          <h2 id="exploration-title" className="mt-home-title mt-4 max-w-xl text-3xl font-semibold tracking-tight md:text-4xl">{copy.title}</h2>
          <p className="mt-5 max-w-xl leading-8 text-[var(--mt-muted)]">{copy.body}</p>
          <Link href={localePath(locale, '/docs/user/knowledge-exploration')} className="mt-5 inline-flex min-h-11 items-center gap-2 font-medium text-[var(--mt-blue)] hover:underline">
            {copy.action}<ArrowRight className="size-4 shrink-0" aria-hidden="true" />
          </Link>
        </div>
        <ol className="divide-y divide-[var(--mt-border)] border-y border-[var(--mt-border)]">
          {copy.steps.map(([title, body], index) => (
            <li key={title} className="grid grid-cols-[2rem_1fr] gap-4 py-6">
              <span className="pt-1 text-sm font-medium text-[var(--mt-blue)]">{String(index + 1).padStart(2, '0')}</span>
              <div>
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="mt-2 leading-7 text-[var(--mt-muted)]">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}
