import type { MetadataRoute } from 'next';
import { source } from '@/lib/source';
import { LOCALES, SITE_URL, absUrl } from '@/lib/site';

const marketing = ['', '/features', '/download', '/architecture', '/roadmap', '/docs'];

export const dynamic = 'force-static';

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date('2026-10-17');
  const entries: MetadataRoute.Sitemap = [
    {
      url: `${SITE_URL}/`,
      lastModified: now,
      alternates: { languages: { 'zh-CN': absUrl('/zh/'), en: absUrl('/en/') } },
    },
  ];

  for (const locale of LOCALES) {
    for (const path of marketing) {
      entries.push({
        url: absUrl(`/${locale}${path}/`),
        lastModified: now,
        alternates: {
          languages: {
            'zh-CN': absUrl(`/zh${path}/`),
            en: absUrl(`/en${path}/`),
          },
        },
      });
    }
    for (const page of source.getPages(locale)) {
      entries.push({
        url: absUrl(page.url.endsWith('/') ? page.url : `${page.url}/`),
        lastModified: now,
      });
    }
  }

  return entries;
}
