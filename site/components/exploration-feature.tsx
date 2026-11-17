import Link from 'next/link';
import { ArrowRight } from 'lucide-react';
import { localePath, type Locale } from '@/lib/site';

const content = {
  zh: {
    label: '知识探索 · 源码预览',
    title: '带着一个疑问，读出自己的理解。',
    body: '从知乎中的数学解释出发，保留作者、原始链接与检索片段。把不同说法放在一起读，再写下理解，用一个小问题决定下一步。',
    steps: [
      ['提出问题', '保留你的疑问与学习目标，主动搜索相关解释。'],
      ['对照来源', '回到原文查看条件；可选 AI 整理来源，选择阅读重点。'],
      ['自己试一试', '保存思考，完成理解检查，获得最多三步的学习建议。'],
    ],
    availability: '当前通过源码体验。已发布的桌面安装包尚不包含知识探索。',
    action: '了解知识探索与配置方法',
  },
  en: {
    label: 'Knowledge exploration · Source preview',
    title: 'Start with a question. Build your own understanding.',
    body: 'Explore mathematical explanations from Zhihu with authors, original links, and search excerpts kept in view. Read perspectives side by side, write your reflection, and try a small check before choosing what comes next.',
    steps: [
      ['Ask a question', 'Keep your question and learning goal as the starting point.'],
      ['Read the sources', 'Check conditions in the original. Optionally ask AI to select excerpts and a reading focus.'],
      ['Try it yourself', 'Save a reflection, take an understanding check, and get a plan of up to three steps.'],
    ],
    availability: 'Available from source. Published desktop installers do not yet include knowledge exploration.',
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
          <p className="mt-3 max-w-xl leading-7 text-[var(--mt-muted)]">{copy.availability}</p>
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
