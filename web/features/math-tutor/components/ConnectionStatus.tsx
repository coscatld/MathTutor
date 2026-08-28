"use client";

import { RefreshCw } from "lucide-react";
import type { ConnectionStatus as Status } from "../types";

const STATUS_STYLES: Record<Status, { dot: string; text: string }> = {
  connected: { dot: "bg-emerald-500", text: "text-emerald-700 dark:text-emerald-400" },
  connecting: { dot: "bg-amber-500", text: "text-amber-700 dark:text-amber-400" },
  reconnecting: { dot: "bg-amber-500", text: "text-amber-700 dark:text-amber-400" },
  disconnected: { dot: "bg-red-500", text: "text-red-700 dark:text-red-400" },
  error: { dot: "bg-red-500", text: "text-red-700 dark:text-red-400" },
};

interface ConnectionStatusProps {
  status: Status;
  note: string;
  onReconnect: () => void;
}

/**
 * Connection indicator for the tutoring service. Shows a human note only —
 * no raw close codes or internal status values.
 */
export default function ConnectionStatus({
  status,
  note,
  onReconnect,
}: ConnectionStatusProps) {
  const style = STATUS_STYLES[status];
  const showRetry = status === "disconnected" || status === "error";

  return (
    <div
      className="flex items-center gap-2"
      role="status"
      aria-live="polite"
      aria-label={note}
    >
      <span
        className={`inline-block h-2.5 w-2.5 shrink-0 rounded-full ${style.dot} ${
          status === "connecting" || status === "reconnecting"
            ? "animate-pulse"
            : ""
        }`}
        aria-hidden="true"
      />
      <span className={`text-sm font-medium ${style.text}`}>{note}</span>
      {showRetry && (
        <button
          type="button"
          onClick={onReconnect}
          className="inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          重新连接
        </button>
      )}
    </div>
  );
}
