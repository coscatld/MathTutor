"use client";

import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

type ToastTone = "success" | "error" | "info";
type ToastInput = { title: string; description?: string; tone?: ToastTone };
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
      <div className="pointer-events-auto flex w-full max-w-md items-start gap-3 rounded-2xl border border-black/10 bg-[#1f2933] px-4 py-3 text-white shadow-[0_18px_45px_rgba(17,24,39,.22)]" onMouseEnter={clearTimer} onMouseLeave={startTimer}>
        <Icon className={`mt-0.5 h-5 w-5 shrink-0 ${toast.tone === "error" ? "text-rose-300" : "text-sky-300"}`} aria-hidden="true" />
        <div className="min-w-0 flex-1"><p className="text-sm font-semibold">{toast.title}</p>{toast.description ? <p className="mt-0.5 text-xs leading-5 text-slate-300">{toast.description}</p> : null}</div>
        <button type="button" aria-label="关闭通知" onClick={() => setToast(null)} className="rounded-md p-1 text-slate-300 hover:bg-white/10 hover:text-white"><X className="h-4 w-4" /></button>
      </div>
    </div>
  ) : null}</ToastContext.Provider>;
}
