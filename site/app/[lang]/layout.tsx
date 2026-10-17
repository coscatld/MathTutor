import type { ReactNode } from 'react';
import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { AppProvider } from '@/components/provider';
import { HtmlLang } from '@/components/html-lang';
import { LOCALES, SITE_NAME, SITE_URL, absUrl, isLocale, type Locale } from '@/lib/site';
import { t } from '@/lib/messages';

export function generateStaticParams() {
  return LOCALES.map((lang) => ({ lang }));
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string }>;
}): Promise<Metadata> {
  const { lang } = await params;
  const locale: Locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale);
  const title =
    locale === 'zh'
      ? '数迹 MathTutor——不止于解答，更关注真正掌握'
      : 'MathTutor — Beyond Answers, Toward Real Understanding';
  const description = copy.hero.subtitle;
  const url = absUrl(`/${locale}/`);
  return {
    metadataBase: new URL(SITE_URL),
    title: {
      default: title,
      template: `%s · ${SITE_NAME}`,
    },
    description,
    alternates: {
      canonical: url,
      languages: {
        'zh-CN': absUrl('/zh/'),
        en: absUrl('/en/'),
      },
    },
    openGraph: {
      type: 'website',
      siteName: SITE_NAME,
      title,
      description,
      url,
      images: [{ url: absUrl('/og.png'), width: 1200, height: 630, alt: SITE_NAME }],
      locale: copy.htmlLang,
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description,
      images: [absUrl('/og.png')],
    },
    icons: {
      icon: [{ url: `${SITE_URL}/favicon.svg`, type: 'image/svg+xml' }],
    },
  };
}

export default async function LocaleLayout({
  params,
  children,
}: {
  params: Promise<{ lang: string }>;
  children: ReactNode;
}) {
  const { lang } = await params;
  if (!isLocale(lang)) notFound();
  const copy = t(lang);

  return (
    <AppProvider lang={lang}>
      <HtmlLang lang={copy.htmlLang} />
      <div lang={copy.htmlLang} className="flex min-h-screen flex-col">
        {children}
      </div>
    </AppProvider>
  );
}
