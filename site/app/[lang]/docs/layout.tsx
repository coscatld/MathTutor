import type { ReactNode } from 'react';
import { DocsLayout } from 'fumadocs-ui/layouts/docs';
import { baseOptions } from '@/lib/layout.shared';
import { LanguageSwitcher } from '@/components/language-switcher';
import { source } from '@/lib/source';
import { isLocale } from '@/lib/site';

export default async function Layout({
  params,
  children,
}: {
  params: Promise<{ lang: string }>;
  children: ReactNode;
}) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const options = baseOptions(locale);
  return (
    <DocsLayout
      {...options}
      nav={{
        ...options.nav,
        children: <LanguageSwitcher locale={locale} />,
      }}
      tree={source.getPageTree(locale)}
    >
      {children}
    </DocsLayout>
  );
}
