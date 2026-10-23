import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';
import { localePath, type Locale } from '@/lib/site';

/** Task-based entry points shared by the home page and documentation. */
export function ReaderPaths({ locale }: { locale: Locale }) {
  const paths = locale === 'zh' ? [
    { title: '开始第一次数学练习', body: '安装、配置，再试一道题。', href: '/docs/user/quick-start', tag: '初次使用' },
    { title: '读懂自己的学习记录', body: '分清独立作答、受助表现与下一步。', href: '/docs/user/learning-evidence', tag: '学习与教学' },
    { title: '运行源码，参与共建', body: '从开发环境、模块边界与测试开始。', href: '/docs/developer/development-setup', tag: '开发者' },
  ] : [
    { title: 'Try your first practice', body: 'Install, configure, and work through a problem.', href: '/docs/user/quick-start', tag: 'GET STARTED' },
    { title: 'Understand your progress', body: 'Read independent and assisted work, then choose a next step.', href: '/docs/user/learning-evidence', tag: 'LEARNING' },
    { title: 'Run it. Build with us.', body: 'Start with the environment, module boundaries, and tests.', href: '/docs/developer/development-setup', tag: 'DEVELOPERS' },
  ];
  return (
    <nav className="mt-reader-paths not-prose" aria-label={locale === 'zh' ? '按目标阅读' : 'Choose a reading path'}>
      {paths.map((path, index) => (
        <Link key={path.href} href={localePath(locale, path.href)} className="mt-reader-path">
          <span className="mt-reader-index">0{index + 1} / {path.tag}</span>
          <span className="mt-reader-title">{path.title}<ArrowUpRight size={18} aria-hidden="true" /></span>
          <span className="mt-reader-description">{path.body}</span>
        </Link>
      ))}
    </nav>
  );
}
