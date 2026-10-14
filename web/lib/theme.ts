/**
 * Appearance styles. The choice is a non-sensitive display preference, so it
 * lives in localStorage here — outside features/math-tutor/desktop, whose
 * source invariant forbids browser storage for credentials.
 */
export type ThemeId = "system" | "paper" | "night" | "sepia" | "starry";

export interface ThemeOption {
  id: ThemeId;
  label: string;
  description: string;
}

export const THEME_OPTIONS: readonly ThemeOption[] = [
  { id: "system", label: "跟随系统", description: "白天纸墨，夜间夜读，随系统自动切换" },
  { id: "paper", label: "纸墨", description: "白色画布与墨蓝强调，清晰专注" },
  { id: "night", label: "夜读", description: "深石墨底色，夜间学习不刺眼" },
  { id: "sepia", label: "暖纸", description: "练习本般的米色纸张，减少蓝光" },
  { id: "starry", label: "星夜", description: "深紫星空与半透明面板" },
];

export const THEME_STORAGE_KEY = "mathtutor-appearance";
export const THEME_CHANGE_EVENT = "mathtutor-appearance-change";
const MANAGED_CLASSES = ["dark", "theme-sepia", "theme-glass", "theme-snow"];
const THEME_CLASSES: Record<Exclude<ThemeId, "system">, string[]> = {
  paper: [],
  night: ["dark"],
  sepia: ["theme-sepia"],
  starry: ["dark", "theme-glass"],
};

function isThemeId(value: unknown): value is ThemeId {
  return THEME_OPTIONS.some(option => option.id === value);
}

export function readTheme(): ThemeId {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeId(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

export function resolveTheme(theme: ThemeId, prefersDark: boolean): Exclude<ThemeId, "system"> {
  return theme === "system" ? (prefersDark ? "night" : "paper") : theme;
}

export function applyTheme(theme: ThemeId): void {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const root = document.documentElement;
  root.classList.remove(...MANAGED_CLASSES);
  root.classList.add(...THEME_CLASSES[resolveTheme(theme, prefersDark)]);
  root.dataset.theme = theme;
}

export function setTheme(theme: ThemeId): void {
  try { window.localStorage.setItem(THEME_STORAGE_KEY, theme); } catch { /* private mode: apply for this session only */ }
  // A cross-fade between styles, skipped when motion is reduced.
  const root = document.documentElement;
  if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    root.classList.add("theme-transition");
    window.setTimeout(() => root.classList.remove("theme-transition"), 420);
  }
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent(THEME_CHANGE_EVENT, { detail: theme }));
}

/** Runs before first paint so a stored style never flashes the default. */
export const THEME_BOOT_SCRIPT = `(function(){try{var k=${JSON.stringify(THEME_STORAGE_KEY)},t=localStorage.getItem(k)||"system",m=window.matchMedia("(prefers-color-scheme: dark)"),c=${JSON.stringify(THEME_CLASSES)},r=document.documentElement;function a(){var id=t==="system"?(m.matches?"night":"paper"):t;r.classList.remove("dark","theme-sepia","theme-glass","theme-snow");(c[id]||[]).forEach(function(n){r.classList.add(n)});r.dataset.theme=t}a();m.addEventListener("change",function(){t=localStorage.getItem(k)||"system";if(t==="system")a()})}catch(e){}})();`;
