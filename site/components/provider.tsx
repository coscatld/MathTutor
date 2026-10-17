'use client';

import { RootProvider } from 'fumadocs-ui/provider/next';
import { i18nProvider } from 'fumadocs-ui/i18n';
import type { ReactNode } from 'react';
import SearchDialog from '@/components/search';
import { translations } from '@/lib/layout.shared';

export function AppProvider({
  lang,
  children,
}: {
  lang: string;
  children: ReactNode;
}) {
  return (
    <RootProvider
      i18n={i18nProvider(translations, lang)}
      search={{ SearchDialog }}
      theme={{
        enabled: true,
        defaultTheme: 'system',
      }}
    >
      {children}
    </RootProvider>
  );
}
