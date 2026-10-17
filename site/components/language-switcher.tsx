'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { Locale } from '@/lib/site';
import { t } from '@/lib/messages';

export function LanguageSwitcher({ locale }: { locale: Locale }) {
  const pathname = usePathname();
  const copy = t(locale);
  const nextLocale: Locale = copy.otherLocale;
  const href = pathname.replace(/^\/(zh|en)(?=\/|$)/, `/${nextLocale}`) || `/${nextLocale}/`;

  return (
    <Link
      href={href}
      className="inline-flex min-h-11 items-center px-2 text-sm"
      hrefLang={nextLocale === 'zh' ? 'zh-CN' : 'en'}
      aria-label={copy.langSwitch}
    >
      {copy.otherLocaleName}
    </Link>
  );
}
