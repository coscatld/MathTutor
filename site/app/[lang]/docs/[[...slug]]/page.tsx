import { notFound } from 'next/navigation';
import type { Metadata } from 'next';
import { createRelativeLink } from 'fumadocs-ui/mdx';
import { DocsBody, DocsDescription, DocsPage, DocsTitle } from 'fumadocs-ui/layouts/docs/page';
import { getMDXComponents } from '@/components/mdx';
import { ReaderPaths } from '@/components/reader-paths';
import { source } from '@/lib/source';
import { EDIT_BASE, SITE_NAME, absUrl, isLocale } from '@/lib/site';

export async function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ lang: string; slug?: string[] }>;
}): Promise<Metadata> {
  const { lang, slug } = await params;
  const page = source.getPage(slug, lang);
  if (!page) notFound();
  const path = `/${lang}/docs/${(slug ?? []).join('/')}`.replace(/\/$/, '') + '/';
  return {
    title: page.data.title,
    description: page.data.description,
    alternates: {
      canonical: absUrl(path),
    },
    openGraph: {
      title: `${page.data.title} · ${SITE_NAME}`,
      description: page.data.description,
      url: absUrl(path),
    },
  };
}

export default async function Page({
  params,
}: {
  params: Promise<{ lang: string; slug?: string[] }>;
}) {
  const { lang, slug } = await params;
  const locale = isLocale(lang) ? lang : 'zh';
  const page = source.getPage(slug, locale);
  if (!page) notFound();
  const MDX = page.data.body;
  const githubPath = String(page.path ?? '').replace(/^\//, '');

  return (
    <DocsPage toc={page.data.toc} full={page.data.full}>
      <p className="mt-doc-kicker">
        {locale === 'zh'
          ? slug?.[0] === 'developer' ? '开发者手册' : slug?.[0] === 'user' ? '使用指南' : 'MATHTUTOR / 使用与共建'
          : slug?.[0] === 'developer' ? 'DEVELOPER HANDBOOK' : slug?.[0] === 'user' ? 'USER GUIDE' : 'MATHTUTOR / DOCUMENTATION'}
      </p>
      <DocsTitle>{page.data.title}</DocsTitle>
      <DocsDescription>{page.data.description}</DocsDescription>
      {!slug?.length && <ReaderPaths locale={locale} />}
      <DocsBody className="mt-doc-body">
        <MDX
          components={getMDXComponents({
            a: createRelativeLink(source, page),
          })}
        />
      </DocsBody>
      <p className="text-fd-muted-foreground mt-10 text-sm">
        <a href={`${EDIT_BASE}/${githubPath}`} rel="noreferrer" target="_blank">
          {locale === 'zh' ? '在 GitHub 上编辑本文' : 'Edit this page on GitHub'}
        </a>
      </p>
    </DocsPage>
  );
}
