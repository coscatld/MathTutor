"use client";

import { RefreshCw } from "lucide-react";
import type { ConnectionStatus as Status } from "../types";

const STATUS_STYLES: Record<Status, { tone: string; live: boolean }> = {
  connected: { tone: "text-[var(--success)]", live: false },
  connecting: { tone: "text-[var(--warning)]", live: true },
  reconnecting: { tone: "text-[var(--warning)]", live: true },
  disconnected: { tone: "text-[var(--destructive)]", live: false },
  error: { tone: "text-[var(--destructive)]", live: false },
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
      <span className={`mt-status-pill ${style.tone}`}>
        <span className="mt-status-dot" data-live={style.live} aria-hidden="true" />
        <span className="text-xs font-semibold">{note}</span>
      </span>
      {showRetry && (
        <button
          type="button"
          onClick={onReconnect}
          className="mt-btn h-8 min-h-0 px-3 text-xs"
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
          重新连接
        </button>
      )}
    </div>
  );
}
