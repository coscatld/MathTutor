"use client";

import { BadgeCheck, BrainCircuit, Check, Loader2, Pencil, Trash2, X } from "lucide-react";
import { useState } from "react";
import { formatDateTime, updateMemory } from "../lib/desktop-api";
import { memorySourceLabel, memoryTypeLabel } from "../lib/labels";
import type { DesktopMemory } from "../types";

export function memoryObjectText(memory: DesktopMemory): string {
  const raw = memory.object_json?.value;
  if (typeof raw === "string" && raw.trim()) return raw;
  if (typeof raw === "string") return "";
  const entries = Object.entries(memory.object_json ?? {});
  if (entries.length === 0) return "";
  return entries
    .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join("，");
}

const SOURCE_STYLES: Record<string, string> = {
  USER_EXPLICIT: "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]",
  MODEL_INFERRED: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-400",
  USER_CONFIRMED: "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-400",
};

export default function MemoryRow({
  memory,
  busy,
  onToggleRetrieval,
  onDelete,
  onConfirm,
  onUpdated,
}: {
  memory: DesktopMemory;
  busy: boolean;
  onToggleRetrieval: (enabled: boolean) => Promise<void>;
  onDelete: () => Promise<void>;
  onConfirm: () => Promise<void>;
  onUpdated: (memory: DesktopMemory) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [predicate, setPredicate] = useState(memory.predicate);
  const [value, setValue] = useState(memoryObjectText(memory));
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const inferred = memory.source_type === "MODEL_INFERRED";

  const handleSave = async () => {
    setSaving(true);
    try {
      const updated = await updateMemory(memory.memory_id, {
        predicate: predicate.trim() || undefined,
        object_json: { value: value.trim() },
      });
      onUpdated(updated);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <li className="flex flex-col gap-3 rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[var(--foreground)]">{memoryTypeLabel(memory.memory_type)}</span>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${SOURCE_STYLES[memory.source_type] ?? SOURCE_STYLES.USER_EXPLICIT}`}>
              {inferred && <BrainCircuit className="h-3 w-3" aria-hidden="true" />}
              {memorySourceLabel(memory.source_type)}
            </span>
            {inferred && (
              <span className="text-xs text-[var(--muted-foreground)]">
                可信度 {Math.round((memory.confidence ?? 0) * 100)}%
              </span>
            )}
          </div>

          {editing ? (
            <div className="mt-2 flex flex-col gap-2">
              <input
                aria-label="记忆内容（谓词）"
                value={predicate}
                onChange={(e) => setPredicate(e.target.value)}
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
              />
              <input
                aria-label="记忆内容（值）"
                value={value}
                onChange={(e) => setValue(e.target.value)}
                className="h-11 w-full rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-[var(--ring)]"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving}
                  className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg bg-[#2563EB] px-3 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                  保存
                </button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] px-3 text-sm text-[var(--muted-foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                  取消
                </button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-sm leading-relaxed text-[var(--foreground)]">
                {memory.predicate}
                {memoryObjectText(memory) ? `：${memoryObjectText(memory)}` : ""}
              </p>
              <p className="text-xs text-[var(--muted-foreground)]">记录于 {formatDateTime(memory.created_at)}</p>
            </>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          {inferred && (
            <button
              type="button"
              onClick={async () => {
                setConfirming(true);
                try {
                  await onConfirm();
                } finally {
                  setConfirming(false);
                }
              }}
              disabled={busy || confirming}
              className="inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl bg-[#2563EB] px-3 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {confirming ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <BadgeCheck className="h-4 w-4" aria-hidden="true" />}
              确认
            </button>
          )}
          <button
            type="button"
            onClick={() => setEditing(true)}
            disabled={busy}
            className="inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="编辑这条记忆"
          >
            <Pencil className="h-4 w-4" aria-hidden="true" />
            编辑
          </button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy}
            className="inline-flex min-h-[44px] cursor-pointer items-center gap-1.5 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3 text-sm font-medium text-red-600 transition-colors duration-200 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
            aria-label="删除这条记忆"
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            删除
          </button>
        </div>
      </div>

      {!editing && (
        <label className="flex min-h-[44px] cursor-pointer items-center gap-2.5 text-sm text-[var(--foreground)]">
          <input
            type="checkbox"
            checked={memory.retrieval_enabled}
            onChange={(e) => onToggleRetrieval(e.target.checked)}
            disabled={busy}
            className="h-4 w-4 cursor-pointer accent-[#2563EB] disabled:cursor-not-allowed"
          />
          参与个性化回忆
        </label>
      )}
    </li>
  );
}
