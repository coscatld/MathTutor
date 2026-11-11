import {workspaceEnglish} from "./messages-workspace";
import {settingsEnglish} from "./messages-settings";
import {knowledgeEnglish} from "./messages-knowledge";
import {learningEnglish} from "./messages-learning";
import {loopEnglish} from "./messages-loop";

export type Locale = "zh-CN" | "en";
export type MessageParams = Record<string, string | number>;
export const DEFAULT_LOCALE: Locale = "zh-CN";
export const LOCALE_STORAGE_KEY = "mathtutor-language";
export const LOCALE_CHANGE_EVENT = "mathtutor-language-change";
export const englishMessages: Readonly<Record<string, string>> = {
  ...workspaceEnglish, ...settingsEnglish, ...knowledgeEnglish, ...learningEnglish, ...loopEnglish,
};

export function normalizeLocale(value: unknown): Locale {
  return value === "en" ? "en" : DEFAULT_LOCALE;
}

/** UI copy only. Never pass user notes, problem statements or chat content. */
export function translate(locale: Locale, message: string, params?: MessageParams): string {
  const translated = Object.prototype.hasOwnProperty.call(englishMessages, message) ? englishMessages[message] : undefined;
  const template = locale === "en" && typeof translated === "string" ? translated : message;
  return template.replace(/\{([A-Za-z][A-Za-z0-9_]*)\}/g, (original, key: string) =>
    params && Object.prototype.hasOwnProperty.call(params, key) ? String(params[key]) : original);
}

export const LOCALE_BOOT_SCRIPT = `(function(){try{document.documentElement.lang=localStorage.getItem(${JSON.stringify(LOCALE_STORAGE_KEY)})==="en"?"en":"zh-CN"}catch(e){document.documentElement.lang="zh-CN"}})();`;
