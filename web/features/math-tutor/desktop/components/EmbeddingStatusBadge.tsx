"use client";

import {useI18n} from "@/lib/i18n";
import { CircleOff, Cloud, DatabaseZap, Search } from "lucide-react";
import type { EmbeddingSettings } from "../types";

const STYLES = {
  disabled: "border-[var(--border)] bg-[var(--muted)] text-[var(--muted-foreground)]",
  local_ready: "border-emerald-200 bg-emerald-50 text-[var(--success)] dark:border-emerald-900 dark:bg-emerald-950/40",
  cloud_configured: "border-sky-200 bg-sky-50 text-sky-700 dark:border-sky-900 dark:bg-sky-950/40 dark:text-sky-300",
  incomplete: "border-amber-200 bg-amber-50 text-[var(--warning)] dark:border-amber-900 dark:bg-amber-950/40",
} as const;

const ICONS = {
  disabled: CircleOff,
  local_ready: DatabaseZap,
  cloud_configured: Cloud,
  incomplete: Search,
} as const;

export default function EmbeddingStatusBadge({ settings }: { settings: EmbeddingSettings }) {
  const {t} = useI18n();
  const Icon = ICONS[settings.status];
  const label = {disabled: "未启用 Embedding", local_ready: "本地模型就绪", cloud_configured: "云端已配置", incomplete: "配置不完整（回退关键词）"}[settings.status];
  return (
    <span className={`inline-flex w-fit items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${STYLES[settings.status]}`}>
      <Icon className="h-3.5 w-3.5" aria-hidden="true" />
      {label ? t(label) : settings.status_label}
    </span>
  );
}
