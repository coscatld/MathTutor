import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { i18n } from '@/lib/i18n';
import { uiTranslations } from 'fumadocs-ui/i18n';
import { BrandMark } from '@/components/brand-mark';
import { REPO_URL } from '@/lib/site';
import { t, type Messages } from '@/lib/messages';

const zhUi = {
  'Search(search trigger)': '搜索文档',
  'Search(search dialog)': '搜索文档',
  'No results found(search dialog)': '没有匹配的文档',
  'On this page(table of contents)': '本页目录',
  'No Headings(table of contents)': '本页没有标题',
  'Last updated on(page footer)': '最后更新',
  'Choose a language(language switcher)': '选择语言',
  'Next Page(pagination)': '下一篇',
  'Previous Page(pagination)': '上一篇',
  'Toggle Theme(theme switcher)(aria-label)': '切换颜色主题',
  'Edit on GitHub(edit page)': '在 GitHub 上编辑',
  displayName: '简体中文',
};

export const translations = i18n
  .translations()
  .extend(uiTranslations())
  .preset('zh', { name: 'zh', value: zhUi });

function navTitle(copy: Messages) {
  return (
    <span className="inline-flex items-center gap-2 font-semibold">
      <BrandMark className="size-5" />
      <span>MathTutor</span>
      <span className="text-fd-muted-foreground font-normal hidden sm:inline">
        {copy.localeName === '简体中文' ? '数迹' : ''}
      </span>
    </span>
  );
}

export function baseOptions(locale: string): BaseLayoutProps {
  const copy = t(locale === 'en' ? 'en' : 'zh');
  return {
    nav: {
      title: navTitle(copy),
      url: `/${locale}`,
    },
    githubUrl: REPO_URL,
    links: [
      { type: 'main', text: copy.nav.features, url: `/${locale}/features` },
      { type: 'main', text: copy.nav.download, url: `/${locale}/download` },
      { type: 'main', text: copy.nav.architecture, url: `/${locale}/architecture` },
      { type: 'main', text: copy.nav.roadmap, url: `/${locale}/roadmap` },
      { type: 'main', text: copy.nav.docs, url: `/${locale}/docs` },
    ],
  };
}
