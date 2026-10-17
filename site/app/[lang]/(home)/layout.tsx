import type { ReactNode } from 'react';
import { HomeLayout } from 'fumadocs-ui/layouts/home';
import { baseOptions } from '@/lib/layout.shared';
import { LanguageSwitcher } from '@/components/language-switcher';
import { isLocale } from '@/lib/site';
import { t } from '@/lib/messages';

export default async function Layout({
  params,
  children,
}: {
  params: Promise<{ lang: string }>;
  children: ReactNode;
}) {
  const { lang } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const copy = t(locale);
  const options = baseOptions(locale);

  return (
    <HomeLayout
      {...options}
      nav={{
        ...options.nav,
        children: <LanguageSwitcher locale={locale} />,
      }}
    >
      <a href="#main" className="skip-link">
        {copy.skip}
      </a>
      <div id="main">{children}</div>
      <p className="mt-container pb-10 text-sm leading-7 text-[var(--mt-muted)]">
        Apache-2.0. {copy.footer.deeptutor} {copy.footer.notLive}
      </p>
    </HomeLayout>
  );
}
