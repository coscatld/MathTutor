import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';
import { localePath, type Locale } from '@/lib/site';

/** Task-based entry points shared by the home page and documentation. */
export function ReaderPaths({ locale }: { locale: Locale }) {
  const paths = locale === 'zh' ? [
    { title: '开始第一次数学练习', body: '安装、配置，再试一道题。', href: '/docs/user/quick-start' },
    { title: '读懂自己的学习记录', body: '分清独立作答、受助表现与下一步。', href: '/docs/user/learning-evidence' },
    { title: '从一个问题找资料', body: '比较百科与教材中的解释，查看引用和原文。', href: '/docs/user/knowledge-exploration' },
  ] : [
    { title: 'Try your first practice', body: 'Install, configure, and work through a problem.', href: '/docs/user/quick-start' },
    { title: 'Understand your progress', body: 'Read independent and assisted work, then choose a next step.', href: '/docs/user/learning-evidence' },
    { title: 'Explore a question', body: 'Compare explanations in reference works and textbooks, then follow the sources.', href: '/docs/user/knowledge-exploration' },
  ];
  return (
    <nav className="mt-reader-paths not-prose" aria-label={locale === 'zh' ? '按目标阅读' : 'Choose a reading path'}>
      {paths.map((path) => (
        <Link key={path.href} href={localePath(locale, path.href)} className="mt-reader-path">
          <span className="mt-reader-title">{path.title}<ArrowUpRight size={18} aria-hidden="true" /></span>
          <span className="mt-reader-description">{path.body}</span>
        </Link>
      ))}
    </nav>
  );
}
