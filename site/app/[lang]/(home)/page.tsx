import Link from 'next/link';
import {
  ArrowRight,
  BookOpen,
  Download,
  Github,
  Lock,
  Route,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';
import { JsonLd } from '@/components/json-ld';
import { ScreenshotFrame } from '@/components/screenshot-frame';
import { ReaderPaths } from '@/components/reader-paths';
import { isLocale, localePath } from '@/lib/site';
import { t } from '@/lib/messages';

const whyIcons = [ShieldCheck, Sparkles, Route, BookOpen, Lock];

export default async function HomePage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale);

  return (
    <div>
      <JsonLd />
      <section className="mt-editorial-hero border-b border-[var(--mt-border)]">
        <div className="mt-container grid items-center gap-12 py-16 lg:grid-cols-[1.1fr_0.9fr] lg:py-24">
          <div className="mt-arrive">
            <p className="text-sm font-medium tracking-wide text-[var(--mt-blue)]">{copy.hero.eyebrow}</p>
            <h1 className="mt-home-title mt-5 max-w-3xl text-4xl font-semibold tracking-tight md:text-6xl">
              {copy.hero.title}
            </h1>
            <p className="mt-5 max-w-2xl text-lg leading-8 text-[var(--mt-muted)]">{copy.hero.subtitle}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href={localePath(locale, '/docs/user/quick-start')}
                className="inline-flex min-h-11 items-center gap-2 rounded-full bg-[var(--mt-blue)] px-5 text-[var(--mt-on-blue)]"
              >
                {copy.hero.getStarted}
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
              <Link
                href={localePath(locale, '/docs')}
                className="inline-flex min-h-11 items-center rounded-full border border-[var(--mt-border)] bg-[var(--mt-card)] px-5"
              >
                {copy.hero.documentation}
              </Link>
              <Link
                href={localePath(locale, '/download')}
                className="inline-flex min-h-11 items-center gap-2 rounded-full border border-[var(--mt-border)] px-5"
              >
                <Download className="size-4" aria-hidden="true" />
                {copy.hero.download}
              </Link>
              <a
                href="https://github.com/coscatld/MathTutor"
                className="inline-flex min-h-11 items-center gap-2 rounded-full px-5"
                rel="noreferrer"
                target="_blank"
              >
                <Github className="size-4" aria-hidden="true" />
                {copy.hero.github}
              </a>
            </div>
          </div>
          <div className="mt-preview-panel mt-arrive">
          <div className="mt-preview-caption"><span>{locale === 'zh' ? '一张白纸，一次新的尝试' : 'A fresh page. A new attempt.'}</span><span>{locale === 'zh' ? '数学练习' : 'MATH PRACTICE'}</span></div>
          <ScreenshotFrame
            src="/screenshots/teaching-desktop.png"
            alt={locale === 'zh' ? 'MathTutor 教学对话界面' : 'MathTutor teaching conversation'}
            priority
          />
          <p className="mt-preview-note">{locale === 'zh' ? '先试一试 → 获得提示 → 再独立完成' : 'Try → Get a hint → Solve independently'}</p>
          </div>
        </div>
      </section>

      <section className="mt-container py-12" aria-labelledby="reading-paths-title">
        <div className="mb-5 flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="reading-paths-title" className="text-xl font-semibold">{locale === 'zh' ? '从你现在要做的事开始' : 'Start with what you want to do'}</h2>
          <Link className="text-sm text-[var(--mt-blue)] hover:underline" href={localePath(locale, '/docs')}>{locale === 'zh' ? '浏览全部文档 →' : 'Explore the documentation →'}</Link>
        </div>
        <ReaderPaths locale={locale} />
      </section>

      <section className="mt-container py-16">
        <h2 className="text-2xl font-semibold">{copy.loopTitle}</h2>
        <ol className="mt-8 grid gap-4 md:grid-cols-4">
          {copy.loop.map((item, index) => (
            <li key={item.title} className="mt-learning-step border-t border-[var(--mt-border)] py-5 pr-5">
              <span className="text-sm font-medium text-[var(--mt-blue)]">{String(index + 1).padStart(2, '0')}</span>
              <h3 className="mt-2 text-lg font-semibold">{item.title}</h3>
              <p className="mt-2 text-sm leading-7 text-[var(--mt-muted)]">{item.body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="border-y border-[var(--mt-border)] bg-[var(--mt-card)]">
        <div className="mt-container py-16">
          <h2 className="text-2xl font-semibold">{copy.whyTitle}</h2>
          <div className="mt-8 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {copy.why.map((item, index) => {
              const Icon = whyIcons[index] ?? ShieldCheck;
              return (
                <article key={item.title} className="rounded-2xl border border-[var(--mt-border)] p-5">
                  <Icon className="size-5 text-[var(--mt-blue)]" aria-hidden="true" />
                  <h3 className="mt-3 font-semibold">{item.title}</h3>
                  <p className="mt-2 text-sm leading-7 text-[var(--mt-muted)]">{item.body}</p>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="mt-container grid gap-6 py-16 md:grid-cols-2">
        <ScreenshotFrame
          src="/screenshots/knowledge-desktop.png"
          alt={locale === 'zh' ? '知识库与资料工作台' : 'Knowledge workbench'}
        />
        <ScreenshotFrame
          src="/screenshots/question-bank.png"
          alt={locale === 'zh' ? '课程题库' : 'Course question bank'}
        />
        <p className="text-sm text-[var(--mt-muted)] md:col-span-2">{copy.screenshotCaption}</p>
      </section>

      <section className="border-t border-[var(--mt-border)]">
        <div className="mt-container flex flex-col gap-4 py-16 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-2xl font-semibold">{copy.ctaTitle}</h2>
            <p className="mt-2 max-w-2xl text-[var(--mt-muted)] leading-7">{copy.ctaBody}</p>
          </div>
          <Link
            href={localePath(locale, '/download')}
            className="inline-flex min-h-11 items-center rounded-full bg-[var(--mt-blue)] px-5 text-[var(--mt-on-blue)]"
          >
            {copy.hero.download}
          </Link>
        </div>
      </section>
    </div>
  );
}
