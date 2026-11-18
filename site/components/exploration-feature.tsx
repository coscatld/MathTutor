import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { localePath, type Locale } from '@/lib/site';

const content = {
  zh: {
    label: '知乎知识探索',
    title: '带着一个疑问，读出自己的理解。',
    body: '在原聊天中结合知乎解释概念、对照不同观点。打开引用，查看片段和原文；再结合自己的作答记录选择下一份资料。',
    steps: [
      ['提出问题', '在聊天中开启联网，询问概念、例子或学习顺序。'],
      ['对照来源', '区分资料解释、作者观点与 AI 推导，查看逐项来源。'],
      ['自己试一试', '根据作答证据检查前置知识，也可开启后台资料发现。'],
    ],
    action: '了解知识探索与配置方法',
  },
  en: {
    label: 'Explore with Zhihu',
    title: 'Start with a question. Build your own understanding.',
    body: 'Bring Zhihu explanations and viewpoints into the existing chat, and follow citations to the original answers. Use your attempts and current goal to choose what to read next.',
    steps: [
      ['Ask a question', 'Enable Online in chat to ask about concepts, examples, or learning order.'],
      ['Read the sources', 'Distinguish source explanations, author views, and AI inference with per-claim evidence.'],
      ['Try it yourself', 'Check prerequisites using your recorded attempts, or opt in to background resource discovery.'],
    ],
    action: 'Explore the workflow and setup',
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
