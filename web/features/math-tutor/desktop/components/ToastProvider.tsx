"use client";

import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

type ToastTone = "success" | "error" | "info";
type ToastInput = { title: string; description?: string; tone?: ToastTone; action?: { label: string; onClick: () => void } };
type ToastItem = ToastInput & { id: number };
const ToastContext = createContext<(toast: ToastInput) => void>(() => {});
export function useToast() { return useContext(ToastContext); }

export default function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toast, setToast] = useState<ToastItem | null>(null);
  const counter = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = useCallback(() => { if (timer.current) clearTimeout(timer.current); timer.current = null; }, []);
  const startTimer = useCallback(() => { clearTimer(); timer.current = setTimeout(() => setToast(null), 5000); }, [clearTimer]);
  const show = useCallback((input: ToastInput) => { counter.current += 1; setToast({ ...input, id: counter.current }); }, []);
  useEffect(() => { if (toast) startTimer(); return clearTimer; }, [toast, startTimer, clearTimer]);
  const Icon = toast?.tone === "error" ? CircleAlert : toast?.tone === "info" ? Info : CheckCircle2;
  return <ToastContext.Provider value={show}>{children}{toast ? (
    <div className="pointer-events-none fixed inset-x-0 top-5 z-[100] flex justify-center px-4" role="status" aria-live="polite">
      <div className="pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-2xl border border-[var(--border)] bg-[var(--popover)] px-4 py-3 text-[var(--popover-foreground)] shadow-[0_12px_32px_rgba(15,20,30,.12)]" onMouseEnter={clearTimer} onMouseLeave={startTimer} onFocus={clearTimer} onBlur={startTimer}>
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${toast.tone === "error" ? "text-[var(--destructive)]" : "text-[var(--primary-text)]"}`} aria-hidden="true" />
        <div className="min-w-0 flex-1"><p className="text-sm font-semibold">{toast.title}</p>{toast.description ? <p className="mt-0.5 text-xs leading-5 text-[var(--muted-foreground)]">{toast.description}</p> : null}{toast.action ? <button type="button" className="mt-btn mt-2" onClick={toast.action.onClick}>{toast.action.label}</button> : null}</div>
        <button type="button" aria-label="关闭通知" onClick={() => setToast(null)} className="rounded-md p-1 text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]"><X className="h-4 w-4" /></button>
      </div>
    </div>
  ) : null}</ToastContext.Provider>;
}
