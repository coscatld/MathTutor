import type { Metadata } from 'next';
import { roadmapGroups } from '@/lib/roadmap';
import { t } from '@/lib/messages';
import { absUrl, isLocale, type Locale } from '@/lib/site';

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }): Promise<Metadata> {
  const { lang } = await params;
  const locale: Locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).roadmapPage;
  return {
    title: copy.title,
    description: copy.intro,
    alternates: { canonical: absUrl(`/${locale}/roadmap/`) },
  };
}

export default async function RoadmapPage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).roadmapPage;
  const groups = roadmapGroups(locale);

  return (
    <div className="mt-container py-16">
      <h1 className="text-4xl font-semibold tracking-tight">{copy.title}</h1>
      <p className="mt-4 max-w-3xl text-lg leading-8 text-[var(--mt-muted)]">{copy.intro}</p>
      <div className="mt-10 grid gap-6 md:grid-cols-3">
        {(
          [
            ['completed', copy.completed, groups.completed],
            ['inProgress', copy.inProgress, groups.inProgress],
            ['planned', copy.planned, groups.planned],
          ] as const
        ).map(([key, title, items]) => (
          <section key={key} className="rounded-2xl border border-[var(--mt-border)] bg-[var(--mt-card)] p-6">
            <h2 className="text-lg font-semibold">{title}</h2>
            <ul className="mt-4 list-disc space-y-3 pl-5 text-sm leading-7 text-[var(--mt-muted)]">
              {items.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
