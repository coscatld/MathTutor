"use client";

import {useI18n} from "@/lib/i18n";

import { BadgeCheck, BrainCircuit, Check, Loader2, Pencil, Trash2, X } from "lucide-react";
import { useRef, useState } from "react";
import { formatDateTime, MemoryConflictError, updateMemory } from "../lib/desktop-api";
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
  MODEL_INFERRED: "border-[var(--border)] bg-[var(--warning-soft)] text-[var(--warning)]",
  USER_CONFIRMED: "border-[var(--border)] bg-[var(--success-soft)] text-[var(--success)]",
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
  const {t} = useI18n();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(memoryObjectText(memory) || memory.predicate);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [editBaseline, setEditBaseline] = useState({updated_at: memory.updated_at, predicate: memory.predicate});
  const [conflictLatest, setConflictLatest] = useState<DesktopMemory | null>(null);
  const editGeneration = useRef(0);
  const savingRef = useRef(false);

  const inferred = memory.source_type === "MODEL_INFERRED";

  const handleSave = async () => {
    if (savingRef.current || conflictLatest || !value.trim()) return;
    savingRef.current = true;
    const generation = editGeneration.current;
    setSaving(true);
    setError("");
    try {
      const updated = await updateMemory(memory.memory_id, {
        expected_updated_at: editBaseline.updated_at,
        predicate: editBaseline.predicate,
        object_json: { value: value.trim() },
      });
      onUpdated(updated);
      setEditBaseline({updated_at: updated.updated_at, predicate: updated.predicate});
      if (generation === editGeneration.current) setEditing(false);
      else setError("上次提交已保存，当前仍有未保存修改。");
    } catch (reason) {
      if (reason instanceof MemoryConflictError) {
        setConflictLatest(reason.latest);
        onUpdated(reason.latest);
        setError("这条记忆已在其他位置更新。你的草稿已保留，请对照最新内容后选择如何继续。");
      } else {
        setError("保存未完成，修改内容已保留，请重试。");
      }
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  };

  return (
    <li data-memory-id={memory.memory_id} className="mt-card flex flex-col gap-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-[var(--foreground)]">{t(memoryTypeLabel(memory.memory_type))}</span>
            <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs ${SOURCE_STYLES[memory.source_type] ?? SOURCE_STYLES.USER_EXPLICIT}`}>
              {inferred && <BrainCircuit className="h-3 w-3" aria-hidden="true" />}
              {t(memorySourceLabel(memory.source_type))}
            </span>
            {inferred && (
              <span className="text-xs text-[var(--muted-foreground)]">
                {t("可信度 {value0}%", { value0: Math.round((memory.confidence ?? 0) * 100) })}</span>
            )}
          </div>

          {editing ? (
            <div className="mt-2 flex flex-col gap-2">
              <textarea
                aria-label={t("记忆内容")}
                value={value}
                onChange={(e) => {editGeneration.current++; setValue(e.target.value);}}
                className="mt-input min-h-24 py-3 leading-6"
              />
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving || busy || Boolean(conflictLatest) || !value.trim()}
                  className="mt-btn mt-btn-primary"
                >
                  {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" /> : <Check className="h-3.5 w-3.5" aria-hidden="true" />}
                  {t("保存")}</button>
                <button
                  type="button"
                  onClick={() => setEditing(false)}
                  disabled={saving}
                  className="mt-btn"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                  {t("取消")}</button>
              </div>
            </div>
          ) : (
            <>
              <p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-[var(--foreground)]">
                {memoryObjectText(memory) ? (["内容", "偏好"].includes(memory.predicate) ? memoryObjectText(memory) : `${memory.predicate}：${memoryObjectText(memory)}`) : memory.predicate}
              </p>
              <p className="text-xs text-[var(--muted-foreground)]">{t("记录于 {value0}", { value0: formatDateTime(memory.created_at) })}</p>
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
              disabled={busy || confirming || saving}
              className="mt-btn mt-btn-primary"
            >
              {confirming ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <BadgeCheck className="h-4 w-4" aria-hidden="true" />}
              {t("确认")}</button>
          )}
          <button
            type="button"
              onClick={() => { setValue(memoryObjectText(memory) || memory.predicate); setEditBaseline({updated_at: memory.updated_at, predicate: memoryObjectText(memory) ? memory.predicate : "内容"}); setConflictLatest(null); setError(""); editGeneration.current++; setEditing(true); }}
            disabled={busy || saving || editing}
            className="mt-btn"
            aria-label={t("编辑这条记忆")}
          >
            <Pencil className="h-4 w-4" aria-hidden="true" />
            {t("编辑")}</button>
          <button
            type="button"
            onClick={onDelete}
            disabled={busy || saving}
            className="mt-btn mt-btn-danger"
            aria-label={t("删除这条记忆")}
          >
            <Trash2 className="h-4 w-4" aria-hidden="true" />
            {t("删除")}</button>
        </div>
      </div>

      {error ? <p role="alert" className="text-sm text-[var(--destructive)]">{t(error)}</p> : null}
      {editing && conflictLatest ? <div role="group" aria-label={t("记忆版本冲突")} className="rounded-xl border border-[var(--border)] bg-[var(--background)] p-3">
        <p className="text-sm font-medium">{t("最新内容")}</p>
        <p className="mt-2 whitespace-pre-wrap break-words text-sm leading-6">{memoryObjectText(conflictLatest) || conflictLatest.predicate}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" className="mt-btn" onClick={() => {
            setEditBaseline({updated_at: conflictLatest.updated_at, predicate: memoryObjectText(conflictLatest) ? conflictLatest.predicate : "内容"});
            setConflictLatest(null); setError("已保留你的草稿，请检查后保存。");
          }}>{t("保留草稿，按最新版本继续编辑")}</button>
          <button type="button" className="mt-btn" onClick={() => {
            setValue(memoryObjectText(conflictLatest) || conflictLatest.predicate); editGeneration.current++;
            setEditBaseline({updated_at: conflictLatest.updated_at, predicate: memoryObjectText(conflictLatest) ? conflictLatest.predicate : "内容"});
            setConflictLatest(null); setError("");
          }}>{t("放弃草稿，载入最新内容")}</button>
        </div>
      </div> : null}
      {!editing && (
        <label className="flex min-h-[44px] cursor-pointer items-center gap-2.5 text-sm text-[var(--foreground)]">
          <input
            type="checkbox"
            checked={memory.retrieval_enabled}
            onChange={(e) => onToggleRetrieval(e.target.checked)}
            disabled={busy || inferred || saving}
            className="h-4 w-4 cursor-pointer accent-[var(--primary)] disabled:cursor-not-allowed"
          />
          {inferred ? t("确认后可允许用于辅导") : t("允许用于辅导")}
        </label>
      )}
    </li>
  );
}
