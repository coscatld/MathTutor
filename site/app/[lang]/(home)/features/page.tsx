import {
  ClipboardCheck,
  Image as ImageIcon,
  MessagesSquare,
  Monitor,
  Repeat,
  Search,
  ShieldCheck,
} from 'lucide-react';
import type { Metadata } from 'next';
import { StatusBadge } from '@/components/status-badge';
import { featureCopy, features, type Feature } from '@/lib/features';
import { t } from '@/lib/messages';
import { absUrl, isLocale, type Locale } from '@/lib/site';

const icons = {
  shield: ShieldCheck,
  messages: MessagesSquare,
  clipboard: ClipboardCheck,
  repeat: Repeat,
  search: Search,
  image: ImageIcon,
  monitor: Monitor,
};

export async function generateMetadata({ params }: { params: Promise<{ lang: string }> }): Promise<Metadata> {
  const { lang } = await params;
  const locale: Locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).featuresPage;
  return {
    title: copy.title,
    description: copy.intro,
    alternates: { canonical: absUrl(`/${locale}/features/`) },
  };
}

function Card({ feature, locale }: { feature: Feature; locale: Locale }) {
  const Icon = icons[feature.icon];
  const copy = featureCopy(feature, locale);
  const labels =
    locale === 'zh'
      ? { problem: '解决什么问题', how: '如何实现', visible: '用户可以看到什么', limits: '支持范围与限制' }
      : { problem: 'Problem', how: 'How it works', visible: 'What users see', limits: 'Scope and limits' };
  return (
    <article className="rounded-2xl border border-[var(--mt-border)] bg-[var(--mt-card)] p-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <Icon className="size-5 text-[var(--mt-blue)]" aria-hidden="true" />
          <h2 className="text-xl font-semibold">{copy.name}</h2>
        </div>
        <StatusBadge status={feature.status} locale={locale} />
      </div>
      <dl className="mt-5 grid gap-4">
        {(['problem', 'how', 'visible', 'limits'] as const).map((key) => (
          <div key={key}>
            <dt className="text-sm font-medium text-[var(--mt-blue)]">{labels[key]}</dt>
            <dd className="mt-1 text-sm leading-7 text-[var(--mt-muted)]">{copy[key]}</dd>
          </div>
        ))}
      </dl>
    </article>
  );
}

export default async function FeaturesPage({ params }: { params: Promise<{ lang: string }> }) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale).featuresPage;
  return (
    <div className="mt-container py-16">
      <h1 className="text-4xl font-semibold tracking-tight">{copy.title}</h1>
      <p className="mt-4 max-w-3xl text-lg leading-8 text-[var(--mt-muted)]">{copy.intro}</p>
      <div className="mt-10 grid gap-5">
        {features.map((feature) => (
          <Card key={feature.id} feature={feature} locale={locale} />
        ))}
      </div>
    </div>
  );
}
