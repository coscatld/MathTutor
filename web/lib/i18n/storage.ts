import {DEFAULT_LOCALE, LOCALE_CHANGE_EVENT, LOCALE_STORAGE_KEY, normalizeLocale, type Locale} from "./messages";

let sessionLocale: Locale | null = null;
export function readLocale(): Locale {
  if (typeof window === "undefined") return DEFAULT_LOCALE;
  if (sessionLocale) return sessionLocale;
  try {return normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY));}
  catch {return DEFAULT_LOCALE;}
}

export function setLocale(locale: Locale): boolean {
  if (typeof window === "undefined") return false;
  const next = normalizeLocale(locale);
  let persisted = true;
  try {window.localStorage.setItem(LOCALE_STORAGE_KEY, next); sessionLocale = null;}
  catch {sessionLocale = next; persisted = false;}
  document.documentElement.lang = next;
  window.dispatchEvent(new Event(LOCALE_CHANGE_EVENT));
  return persisted;
}

export function subscribeLocale(listener: () => void) {
  const storage = (event: StorageEvent) => {
    if (event.key === LOCALE_STORAGE_KEY || event.key === null) {sessionLocale = null; listener();}
  };
  window.addEventListener(LOCALE_CHANGE_EVENT, listener);
  window.addEventListener("storage", storage);
  return () => {window.removeEventListener(LOCALE_CHANGE_EVENT, listener); window.removeEventListener("storage", storage);};
}
