"use client";

import {createContext, useCallback, useContext, useEffect, useSyncExternalStore, type ReactNode} from "react";
import {DEFAULT_LOCALE, translate, type Locale, type MessageParams} from "./messages";
import {readLocale, setLocale, subscribeLocale} from "./storage";
export {DEFAULT_LOCALE, LOCALE_STORAGE_KEY, LOCALE_CHANGE_EVENT, normalizeLocale, translate} from "./messages";
export type {Locale, MessageParams} from "./messages";
export {readLocale, setLocale} from "./storage";

const LocaleContext = createContext<Locale>(DEFAULT_LOCALE);

export function I18nProvider({children, initialLocale = DEFAULT_LOCALE}: {children: ReactNode; initialLocale?: Locale}) {
  const locale = useSyncExternalStore(subscribeLocale, readLocale, () => initialLocale);
  useEffect(() => {document.documentElement.lang = locale;}, [locale]);
  return <LocaleContext.Provider value={locale}>{children}</LocaleContext.Provider>;
}

export function useI18n() {
  const locale = useContext(LocaleContext);
  const t = useCallback((message: string, params?: MessageParams) => translate(locale, message, params), [locale]);
  return {locale, setLocale, t};
}
