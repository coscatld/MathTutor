"use client";

import { Check, Moon, Monitor, Palette, Sparkles, Sun, SunMedium } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { readTheme, setTheme, THEME_CHANGE_EVENT, THEME_OPTIONS, type ThemeId } from "@/lib/theme";

const ICONS: Record<ThemeId, typeof Sun> = { system: Monitor, paper: Sun, night: Moon, sepia: SunMedium, starry: Sparkles };

/** Compact style menu for the sidebar footer. */
export default function ThemeQuickSwitch({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<ThemeId>("system");
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    setCurrent(readTheme());
    const sync = (event: Event) => setCurrent((event as CustomEvent<ThemeId>).detail);
    window.addEventListener(THEME_CHANGE_EVENT, sync);
    return () => window.removeEventListener(THEME_CHANGE_EVENT, sync);
  }, []);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); root.current?.querySelector<HTMLButtonElement>("button")?.focus(); } };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    root.current?.querySelector<HTMLButtonElement>('[role="menuitemradio"][aria-checked="true"]')?.focus();
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);
  const Icon = ICONS[current] ?? Palette;
  return <div ref={root} className="mt-theme-switch">
    <button type="button" aria-label="页面风格" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(value => !value)} className="mt-icon-button h-9 w-9"><Icon className="h-4 w-4" aria-hidden="true" /></button>
    {open ? <div role="menu" aria-label="页面风格" className={`mt-theme-menu ${compact ? "mt-theme-menu-side" : ""}`}>
      <p className="px-2.5 pb-1.5 pt-1 text-[11px] font-semibold tracking-wider text-[var(--muted-foreground)]">页面风格</p>
      {THEME_OPTIONS.map(option => {
        const ItemIcon = ICONS[option.id];
        const selected = option.id === current;
        return <button key={option.id} type="button" role="menuitemradio" aria-checked={selected} onClick={() => { setTheme(option.id); setCurrent(option.id); setOpen(false); }} className="mt-theme-menu-item">
          <ItemIcon className="h-4 w-4 shrink-0" aria-hidden="true" />
          <span className="flex-1">{option.label}</span>
          {selected ? <Check className="h-3.5 w-3.5 text-[var(--primary-text)]" aria-hidden="true" /> : null}
        </button>;
      })}
    </div> : null}
  </div>;
}
