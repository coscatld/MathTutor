import type { Metadata } from 'next';
import { PracticeDesk } from '@/components/practice-desk';
import { absUrl, isLocale, type Locale } from '@/lib/site';

const titles = { zh: '在线试一道方程', en: 'Try an equation' };
const descriptions = {
  zh: '选一道题，写下你的解题步骤。核验在浏览器里完成，草稿只保留在当前页面。',
  en: 'Choose a problem and work through it. Your browser checks each step and keeps your draft on this page.',
};

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }): Promise<Metadata> {
  const { lang } = await params;
  const locale: Locale = isLocale(lang) ? lang : 'zh';
  return { title: titles[locale], description: descriptions[locale], alternates: { canonical: absUrl('/' + locale + '/demo/') } };
}

export default async function DemoPage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  return <div className="mt-container py-10 sm:py-16">
    <h1 className="mt-home-title text-4xl font-semibold tracking-tight sm:text-5xl">{titles[locale]}</h1>
    <p className="mt-3 mb-8 max-w-2xl text-lg leading-relaxed text-[var(--mt-muted)]">{descriptions[locale]}</p>
    <PracticeDesk locale={locale} />
  </div>;
}
