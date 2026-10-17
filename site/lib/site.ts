export const SITE_NAME = 'MathTutor';
export const SITE_NAME_ZH = '数迹 MathTutor';
export const REPO_PATH = 'coscatld/MathTutor';
export const REPO_URL = `https://github.com/${REPO_PATH}`;
export const SITE_ORIGIN = 'https://coscatld.github.io';
export const BASE_PATH = '/MathTutor';
export const SITE_URL = `${SITE_ORIGIN}${BASE_PATH}`;
export const DEFAULT_LOCALE = 'zh' as const;
export const LOCALES = ['zh', 'en'] as const;
export type Locale = (typeof LOCALES)[number];

export const EDIT_BASE = `${REPO_URL}/blob/main/site/content/docs`;

export function isLocale(value: string): value is Locale {
  return (LOCALES as readonly string[]).includes(value);
}

export function withBase(path: string): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  if (normalized === '/') return `${BASE_PATH}/`;
  return `${BASE_PATH}${normalized}`;
}

export function absUrl(path = '/'): string {
  const normalized = path.startsWith('/') ? path : `/${path}`;
  if (normalized === '/') return `${SITE_URL}/`;
  return `${SITE_URL}${normalized}`;
}

export function localePath(locale: Locale, path = '/'): string {
  const rest = path === '/' ? '' : path.startsWith('/') ? path : `/${path}`;
  return `/${locale}${rest}`;
}
