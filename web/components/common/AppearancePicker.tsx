"use client";

import { Check } from "lucide-react";
import { useEffect, useState } from "react";
import { readTheme, setTheme, THEME_CHANGE_EVENT, THEME_OPTIONS, type ThemeId } from "@/lib/theme";

const PREVIEW_CLASS: Record<Exclude<ThemeId, "system">, string> = {
  paper: "theme-paper",
  night: "dark",
  sepia: "theme-paper theme-sepia",
  starry: "dark theme-glass",
};

function Mini({ theme }: { theme: Exclude<ThemeId, "system"> }) {
  return <span className={`mt-mini ${PREVIEW_CLASS[theme]}`}>
    <span className="mt-mini-side"><i /><i /><i /><i /></span>
    <span className="mt-mini-main">
      <span className="mt-mini-bubble" />
      <span className="mt-mini-line" style={{ width: "86%" }} />
      <span className="mt-mini-line" style={{ width: "64%" }} />
      <span className="mt-mini-slip mt-paper" />
      <span className="mt-mini-composer" />
    </span>
  </span>;
}

/** Radio group of appearance styles with live miniature previews. */
export default function AppearancePicker() {
  const [current, setCurrent] = useState<ThemeId>("system");
  useEffect(() => {
    setCurrent(readTheme());
    const sync = (event: Event) => setCurrent((event as CustomEvent<ThemeId>).detail);
    window.addEventListener(THEME_CHANGE_EVENT, sync);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, sync);
  }, []);
  const choose = (id: ThemeId) => { setCurrent(id); setTheme(id); };
  const move = (event: React.KeyboardEvent, index: number) => {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = THEME_OPTIONS[(index + step + THEME_OPTIONS.length) % THEME_OPTIONS.length];
    choose(next.id);
    (event.currentTarget.parentElement?.children[THEME_OPTIONS.indexOf(next)] as HTMLElement | undefined)?.focus();
  };
  return <div role="radiogroup" aria-label="页面风格" className="mt-theme-grid">
    {THEME_OPTIONS.map((option, index) => {
      const selected = option.id === current;
      return <button key={option.id} type="button" role="radio" aria-checked={selected} tabIndex={selected ? 0 : -1} onClick={() => choose(option.id)} onKeyDown={event => move(event, index)} className="mt-theme-option">
        <span className="mt-theme-preview" aria-hidden="true">
          {option.id === "system"
            ? <span className="mt-theme-preview-split"><span style={{ clipPath: "inset(0 50% 0 0)", position: "absolute", inset: 0 }}><Mini theme="paper" /></span><span style={{ clipPath: "inset(0 0 0 50%)", position: "absolute", inset: 0 }}><Mini theme="night" /></span></span>
            : <Mini theme={option.id} />}
        </span>
        {selected ? <span className="mt-theme-check"><Check className="h-3 w-3" strokeWidth={3} aria-hidden="true" /></span> : null}
        <span className="px-1 pb-1">
          <span className="block text-sm font-semibold">{option.label}</span>
          <span className="mt-0.5 block text-xs leading-5 text-[var(--muted-foreground)]">{option.description}</span>
        </span>
      </button>;
    })}
  </div>;
}
