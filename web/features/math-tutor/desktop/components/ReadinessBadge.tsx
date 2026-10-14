"use client";

import { CheckCircle2, ChevronDown, ChevronUp, ShieldAlert, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { READINESS_LABELS } from "../lib/labels";
import type { Readiness, ReadinessStatus } from "../types";

const STATUS_STYLES: Record<ReadinessStatus, { dot: string; text: string; badge: string }> = {
  READY: {
    dot: "bg-emerald-500",
    text: "text-[var(--success)]",
    badge: "border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40",
  },
  DEGRADED: {
    dot: "bg-amber-500",
    text: "text-[var(--warning)]",
    badge: "border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40",
  },
  BLOCKED: {
    dot: "bg-red-500",
    text: "text-[var(--destructive)]",
    badge: "border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/40",
  },
};

function StatusIcon({ status }: { status: ReadinessStatus }) {
  if (status === "READY") {
    return <CheckCircle2 className="h-4 w-4 text-[var(--success)]" aria-hidden="true" />;
  }
  if (status === "DEGRADED") {
    return <TriangleAlert className="h-4 w-4 text-[var(--warning)]" aria-hidden="true" />;
  }
  return <ShieldAlert className="h-4 w-4 text-[var(--destructive)]" aria-hidden="true" />;
}

/**
 * Readiness pill — READY / DEGRADED / BLOCKED with expandable human reasons.
 * Pure presentational: the parent supplies the Readiness payload.
 */
export default function ReadinessBadge({ readiness }: { readiness: Readiness }) {
  const [open, setOpen] = useState(false);
  const style = STATUS_STYLES[readiness.status];
  const reasons = Object.entries(readiness.reasons ?? {});

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`系统状态：${READINESS_LABELS[readiness.status]}`}
        className={`inline-flex min-h-[40px] cursor-pointer items-center gap-2 rounded-full border px-3 py-1.5 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] ${style.badge} ${style.text}`}
      >
        <span className={`inline-block h-2 w-2 shrink-0 rounded-full ${style.dot} ${readiness.status === "DEGRADED" ? "animate-pulse" : ""}`} aria-hidden="true" />
        <StatusIcon status={readiness.status} />
        {READINESS_LABELS[readiness.status]}
        {reasons.length > 0 &&
          (open ? (
            <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
          ))}
      </button>

      {open && reasons.length > 0 && (
        <div
          role="region"
          aria-label="状态详情"
          className="mt-card absolute right-0 z-20 mt-2 w-80 max-w-[calc(100vw-2rem)] p-3 text-sm shadow-lg"
        >
          <ul className="flex flex-col gap-2">
            {reasons.map(([key, reason]) => (
              <li key={key} className="flex items-start gap-2 text-[var(--foreground)]">
                <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-[var(--warning)]" aria-hidden="true" />
                <span className="min-w-0">{reason}</span>
              </li>
            ))}
          </ul>
          {readiness.status !== "READY" && (
            <p className="mt-2 border-t border-[var(--border)] pt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
              核心练习仍可使用；配置模型后即可解锁全部功能。
            </p>
          )}
        </div>
      )}
    </div>
  );
}
