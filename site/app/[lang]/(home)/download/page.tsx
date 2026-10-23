import type { Metadata } from 'next';
import { Apple, Monitor } from 'lucide-react';
import { CURRENT_ASSETS, CURRENT_VERSION, LINUX_STATUS, RELEASE_URL } from '@/lib/releases';
import { t } from '@/lib/messages';
import { absUrl, isLocale, type Locale } from '@/lib/site';

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }): Promise<Metadata> {
  const { lang } = await params;
  const locale: Locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).downloadPage;
  return {
    title: copy.title,
    description: copy.intro,
    alternates: { canonical: absUrl(`/${locale}/download/`) },
  };
}

export default async function DownloadPage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).downloadPage;

  return (
    <div className="mt-container py-16">
      <p className="text-sm font-medium text-[var(--mt-blue)]">{CURRENT_VERSION}</p>
      <h1 className="mt-2 text-4xl font-semibold tracking-tight">{copy.title}</h1>
      <p className="mt-4 max-w-3xl text-lg leading-8 text-[var(--mt-muted)]">{copy.intro}</p>

      <div className="mt-10 grid gap-5 md:grid-cols-2">
        {CURRENT_ASSETS.map((asset) => {
          const Icon = asset.id === 'macos-arm64' ? Apple : Monitor;
          return (
            <article key={asset.id} className="rounded-2xl border border-[var(--mt-border)] bg-[var(--mt-card)] p-6">
              <Icon className="size-5 text-[var(--mt-blue)]" aria-hidden="true" />
              <h2 className="mt-3 text-xl font-semibold">
                {asset.os} · {asset.arch}
              </h2>
              <p className="mt-2 text-sm text-[var(--mt-muted)]">{asset.filename}</p>
              <a
                href={asset.url}
                className="mt-5 inline-flex min-h-11 items-center rounded-full bg-[var(--mt-blue)] px-5 text-[var(--mt-on-blue)]"
              >
                {locale === 'zh' ? '下载' : 'Download'}
              </a>
              <p className="mt-4 text-sm leading-7">{locale === 'zh' ? asset.notes : asset.notesEn}</p>
            </article>
          );
        })}
      </div>

      <section className="mt-8 rounded-2xl border border-dashed border-[var(--mt-border)] p-6">
        <h2 className="text-lg font-semibold">{copy.linuxTitle}</h2>
        <p className="mt-2 max-w-3xl text-sm leading-7 text-[var(--mt-muted)]">
          {locale === 'zh' ? LINUX_STATUS.reasonZh : LINUX_STATUS.reasonEn}
        </p>
      </section>

      <section className="mt-8 grid gap-4 md:grid-cols-2">
        <article className="rounded-2xl border border-[var(--mt-border)] p-6">
          <h2 className="font-semibold">{copy.unsignedTitle}</h2>
          <p className="mt-2 text-sm leading-7 text-[var(--mt-muted)]">{copy.unsignedBody}</p>
        </article>
        <article className="rounded-2xl border border-[var(--mt-border)] p-6">
          <h2 className="font-semibold">{copy.notes}</h2>
          <ul className="mt-2 list-disc space-y-2 pl-5 text-sm leading-7">
            <li>
              <a href={RELEASE_URL} className="underline">
                {copy.releases}
              </a>
            </li>
            <li>
              <a
                href="https://github.com/coscatld/MathTutor/blob/main/docs/MACOS_INSTALLATION.md"
                className="underline"
              >
                {copy.macGuide}
              </a>
            </li>
            <li>
              <a
                href="https://github.com/coscatld/MathTutor/blob/main/docs/RELEASE_0.7.0.md"
                className="underline"
              >
                Release Notes 0.7.0
              </a>
            </li>
          </ul>
        </article>
      </section>
    </div>
  );
}
