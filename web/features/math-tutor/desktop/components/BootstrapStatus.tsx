"use client";

import { CheckCircle2, ChevronDown, ChevronUp, Loader2, RefreshCw, ShieldAlert, TriangleAlert, XCircle } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchBootstrap } from "../lib/desktop-api";
import { BOOTSTRAP_STEP_STATUS_LABELS, READINESS_LABELS, bootstrapStepLabel } from "../lib/labels";
import type { BootstrapPayload, BootstrapStepStatus, ReadinessStatus } from "../types";

const BOOT_POLL_MS = 2000; // startup: poll every 2s until the boot sequence finishes
const STEADY_POLL_MS = 30000; // after boot: refresh slowly so the badge recovers

const STATUS_STYLES: Record<ReadinessStatus, { dot: string; text: string; badge: string }> = {
  READY: {
    dot: "bg-emerald-500",
    text: "text-emerald-700 dark:text-emerald-400",
    badge: "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40",
  },
  DEGRADED: {
    dot: "bg-amber-500",
    text: "text-amber-700 dark:text-amber-400",
    badge: "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
  },
  BLOCKED: {
    dot: "bg-red-500",
    text: "text-red-700 dark:text-red-400",
    badge: "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40",
  },
};

const STEP_ICONS: Record<BootstrapStepStatus, { icon: typeof CheckCircle2; className: string }> = {
  ok: { icon: CheckCircle2, className: "text-emerald-600 dark:text-emerald-400" },
  degraded: { icon: TriangleAlert, className: "text-amber-600 dark:text-amber-400" },
  blocked: { icon: XCircle, className: "text-red-600 dark:text-red-400" },
};

function StatusIcon({ status }: { status: ReadinessStatus }) {
  if (status === "READY") {
    return <CheckCircle2 className="h-4 w-4 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />;
  }
  if (status === "DEGRADED") {
    return <TriangleAlert className="h-4 w-4 text-amber-600 dark:text-amber-400" aria-hidden="true" />;
  }
  return <ShieldAlert className="h-4 w-4 text-red-600 dark:text-red-400" aria-hidden="true" />;
}

/** True once the boot sequence reached a final state. */
export function isFinal(payload: BootstrapPayload | null): boolean {
  if (!payload) return false;
  return payload.phase === "READY" || payload.readiness === "BLOCKED";
}

interface Props {
  /** Injectable fetcher — tests pass a fake. */
  fetchBootstrapFn?: typeof fetchBootstrap;
  /** Bootstrap poll interval (tests shorten it); defaults to 2s while booting. */
  bootPollMs?: number;
  /** Steady-state poll interval after boot; defaults to 30s. */
  steadyPollMs?: number;
}

interface ControlProps {
  payload: BootstrapPayload | null;
  open: boolean;
  refreshing: boolean;
  onToggle: () => void;
  onRefresh: () => void;
}

/**
 * Presentational control (exported for node tests): boot pill while booting,
 * final tri-state badge (READY / DEGRADED / BLOCKED) once the sequence
 * finishes, with an expandable step list. Steps show friendly labels and
 * friendly details only — the backend contract forbids internals (paths,
 * stacks, keys), and the UI additionally renders every detail as plain text
 * (never markup).
 */
export function BootstrapStatusControl({ payload, open, refreshing, onToggle, onRefresh }: ControlProps) {
  const final = isFinal(payload);
  const steps = payload?.steps ?? [];
  const doneCount = steps.filter((s) => s.status === "ok").length;
  const style = payload ? STATUS_STYLES[payload.readiness] : null;
  const label = payload ? READINESS_LABELS[payload.readiness] : "";

  return (
    <div className="relative">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        aria-label={payload ? `系统状态：${label}` : "系统正在启动"}
        className={`inline-flex min-h-[40px] cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] ${
          payload !== null && final && style !== null
            ? `${style.badge} ${style.text}`
            : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)]"
        }`}
      >
        <span aria-live="polite" className="sr-only">
          {payload ? `系统状态：${label}` : "系统正在启动"}
        </span>
        {payload !== null && final ? (
          <>
            <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${STATUS_STYLES[payload.readiness].dot} ${payload.readiness === "DEGRADED" ? "animate-pulse" : ""}`} aria-hidden="true" />
            <StatusIcon status={payload.readiness} />
            {label}
          </>
        ) : (
          <>
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            {steps.length > 0 ? `正在启动… ${doneCount}/${steps.length}` : "正在启动本地服务…"}
          </>
        )}
        {open ? (
          <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
        )}
      </button>

      {open && (
        <div
          role="region"
          aria-label="启动步骤"
          className="absolute right-0 z-20 mt-2 w-96 max-w-[calc(100vw-2rem)] rounded-2xl border border-[var(--border)] bg-[var(--card)] p-3 text-sm shadow-lg"
        >
          {steps.length === 0 ? (
            <p className="flex items-center gap-2 px-1 py-2 text-[var(--muted-foreground)]">
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              正在启动本地服务，请稍候…
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {steps.map((step) => {
                const stepIcon = STEP_ICONS[step.status] ?? STEP_ICONS.ok;
                const StepIconComponent = stepIcon.icon;
                return (
                  <li key={step.key} className="flex items-start gap-2 text-[var(--foreground)]">
                    <StepIconComponent className={`mt-0.5 h-3.5 w-3.5 shrink-0 ${stepIcon.className}`} aria-hidden="true" />
                    <span className="flex min-w-0 flex-col gap-0.5">
                      <span className="flex flex-wrap items-baseline gap-x-2">
                        <span className="font-medium">{bootstrapStepLabel(step.key, step.label)}</span>
                        <span className="text-xs text-[var(--muted-foreground)]">
                          {BOOTSTRAP_STEP_STATUS_LABELS[step.status] ?? step.status}
                        </span>
                      </span>
                      {step.detail ? (
                        // Plain text only — defensive: details are never rendered as markup.
                        <span className="text-xs leading-relaxed text-[var(--muted-foreground)]">{step.detail}</span>
                      ) : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}

          {payload?.reason ? (
            <p className="mt-2 border-t border-[var(--border)] pt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
              {payload.reason}
            </p>
          ) : null}
          {payload && payload.readiness !== "READY" ? (
            <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
              核心练习与模板辅导仍可使用；配置 AI 模型后即可解锁全部功能。
            </p>
          ) : null}

          <div className="mt-2 flex justify-end border-t border-[var(--border)] pt-2">
            <button
              type="button"
              onClick={onRefresh}
              disabled={refreshing}
              className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg px-2.5 text-xs font-medium text-[var(--primary-text)] transition-colors duration-200 hover:bg-[var(--primary-soft)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {refreshing ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />}
              重新检测
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Bootstrap status control: polls GET /bootstrap every 2s while the boot
 * sequence runs, then settles into the final tri-state badge with an
 * expandable step list. The presentational work lives in
 * ``BootstrapStatusControl`` so node tests can assert all three final
 * states without running effects.
 */
export default function BootstrapStatus({
  fetchBootstrapFn = fetchBootstrap,
  bootPollMs = BOOT_POLL_MS,
  steadyPollMs = STEADY_POLL_MS,
}: Props) {
  const [payload, setPayload] = useState<BootstrapPayload | null>(null);
  const [open, setOpen] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const payloadRef = useRef<BootstrapPayload | null>(null);
  payloadRef.current = payload;

  const poll = useCallback(async () => {
    try {
      const next = await fetchBootstrapFn();
      setPayload(next);
    } catch {
      // Backend still starting: keep the boot pill, keep polling.
    }
  }, [fetchBootstrapFn]);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;
    const tick = async () => {
      await poll();
      if (cancelled) return;
      const interval = isFinal(payloadRef.current) ? steadyPollMs : bootPollMs;
      timer = window.setTimeout(tick, interval);
    };
    tick();
    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [poll, bootPollMs, steadyPollMs]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await poll();
    setRefreshing(false);
  };

  return (
    <BootstrapStatusControl
      payload={payload}
      open={open}
      refreshing={refreshing}
      onToggle={() => setOpen((v) => !v)}
      onRefresh={handleRefresh}
    />
  );
}
