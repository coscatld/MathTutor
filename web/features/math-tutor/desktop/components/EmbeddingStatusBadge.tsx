import { CircleOff, Cloud, DatabaseZap, Search } from "lucide-react";
import type { EmbeddingSettings } from "../types";

const STYLES = {
  disabled: "border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]",
  local_ready: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-300",
  cloud_configured: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300",
  incomplete: "border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300",
} as const;

const ICONS = {
  disabled: CircleOff,
  local_ready: DatabaseZap,
  cloud_configured: Cloud,
  incomplete: Search,
} as const;

export default function EmbeddingStatusBadge({ settings }: { settings: EmbeddingSettings }) {
  const Icon = ICONS[settings.status];
  return (
    <span className={`inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${STYLES[settings.status]}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {settings.status_label}
    </span>
  );
}
