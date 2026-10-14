"use client";

import { BrainCircuit, Loader2, Plus, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  confirmMemory,
  createMemory,
  deleteMemory,
  DesktopApiError,
  fetchMemories,
  toggleMemoryRetrieval,
} from "../lib/desktop-api";
import { MEMORY_TYPE_LABELS } from "../lib/labels";
import type { DesktopMemory } from "../types";
import MemoryRow from "./MemoryRow";
import { useToast } from "./ToastProvider";

/** Category tabs: user-entered types + the AI-inferred category. */
const FILTER_TABS: { key: string; label: string; ai?: boolean }[] = [
  { key: "all", label: "全部" },
  { key: "learning_preference", label: "学习偏好" },
  { key: "learning_goal", label: "学习目标" },
  { key: "interest", label: "兴趣" },
  { key: "user_note", label: "个人说明" },
  { key: "ai_inference", label: "AI 推测", ai: true },
];

/**
 * 我的记忆 — personal memory knowledge graph. AI-inferred entries carry a
 * distinct badge; confirming them is the only way they become user-verified.
 */
export default function MemoryPanel({
  fetchMemoriesFn = fetchMemories,
  createMemoryFn = createMemory,
  confirmMemoryFn = confirmMemory,
}: {
  fetchMemoriesFn?: typeof fetchMemories;
  createMemoryFn?: typeof createMemory;
  confirmMemoryFn?: typeof confirmMemory;
}) {
  const toast = useToast();
  const [memories, setMemories] = useState<DesktopMemory[]>([]);
  const [filter, setFilter] = useState("all");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  // Add-form state
  const [adding, setAdding] = useState(false);
  const [addType, setAddType] = useState("learning_preference");
  const [addPredicate, setAddPredicate] = useState("");
  const [addValue, setAddValue] = useState("");
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setMemories(await fetchMemoriesFn());
    } catch (err) {
      setMessage({
        kind: "error",
        text: err instanceof DesktopApiError ? err.message : "读取记忆失败，请稍后再试。",
      });
    } finally {
      setLoading(false);
    }
  }, [fetchMemoriesFn]);

  useEffect(() => {
    refresh().catch(() => undefined);
  }, [refresh]);

  const visible = useMemo(() => {
    if (filter === "all") return memories;
    return memories.filter((m) => m.memory_type === filter);
  }, [memories, filter]);

  const inferredCount = useMemo(
    () => memories.filter((m) => m.source_type === "MODEL_INFERRED").length,
    [memories],
  );

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!addPredicate.trim() && !addValue.trim()) return;
    setSaving(true);
    try {
      const created = await createMemoryFn({
        memory_type: addType,
        subject: "我",
        predicate: addPredicate.trim() || "偏好",
        object_json: { value: addValue.trim() },
      });
      setMemories((list) => [...list, created]);
      setAddPredicate("");
      setAddValue("");
      setAdding(false);
      setFilter(created.memory_type);
      setMessage({ kind: "ok", text: "记忆已保存。" });
      toast({ title: "记忆已保存", tone: "success" });
    } catch (err) {
      const text = err instanceof DesktopApiError ? err.message : "保存失败，请稍后再试。";
      setMessage({ kind: "error", text });
      toast({ title: "保存记忆失败", description: text, tone: "error" });
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (memory: DesktopMemory, enabled: boolean) => {
    setBusyId(memory.memory_id);
    try {
      const updated = await toggleMemoryRetrieval(memory.memory_id, enabled);
      setMemories((list) => list.map((m) => (m.memory_id === updated.memory_id ? updated : m)));
    } catch (err) {
      const text = err instanceof DesktopApiError ? err.message : "更新失败，请稍后再试。";
      setMessage({ kind: "error", text });
      toast({ title: "更新记忆失败", description: text, tone: "error" });
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async (memory: DesktopMemory) => {
    setBusyId(memory.memory_id);
    try {
      await deleteMemory(memory.memory_id);
      setMemories((list) => list.filter((m) => m.memory_id !== memory.memory_id));
      setMessage({ kind: "ok", text: "已删除这条记忆。" });
      toast({ title: "记忆已删除", tone: "success" });
    } catch (err) {
      const text = err instanceof DesktopApiError ? err.message : "删除失败，请稍后再试。";
      setMessage({ kind: "error", text });
      toast({ title: "删除记忆失败", description: text, tone: "error" });
    } finally {
      setBusyId(null);
    }
  };

  const handleConfirm = async (memory: DesktopMemory) => {
    setBusyId(memory.memory_id);
    try {
      const updated = await confirmMemoryFn(memory.memory_id);
      setMemories((list) => list.map((m) => (m.memory_id === updated.memory_id ? updated : m)));
      setMessage({ kind: "ok", text: "已确认这条 AI 推测，将参与个性化回忆。" });
      toast({ title: "AI 推测已确认", description: "这条记忆将参与个性化回忆。", tone: "success" });
    } catch (err) {
      const text = err instanceof DesktopApiError ? err.message : "确认失败，请稍后再试。";
      setMessage({ kind: "error", text });
      toast({ title: "确认失败", description: text, tone: "error" });
    } finally {
      setBusyId(null);
    }
  };

  const handleUpdated = (updated: DesktopMemory) => {
    setMemories((list) => list.map((m) => (m.memory_id === updated.memory_id ? updated : m)));
  };

  return (
    <div className="mt-page">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="mt-eyebrow flex items-center gap-1.5"><BrainCircuit className="h-3.5 w-3.5" aria-hidden="true" />让辅导更懂你的节奏</p>
          <h1 className="mt-2">我的记忆</h1>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-[var(--muted-foreground)]">
            记录你的学习偏好、目标与兴趣，辅导会据此调整节奏。
            {inferredCount > 0 && ` 当前有 ${inferredCount} 条 AI 推测记忆待你确认。`}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setAdding((v) => !v)}
          className="mt-btn mt-btn-primary"
        >
          <Plus className="h-4 w-4" aria-hidden="true" />
          添加记忆
        </button>
      </header>

      {/* Category tabs */}
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="记忆类别">
        {FILTER_TABS.map((tab) => {
          const active = filter === tab.key;
          return (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setFilter(tab.key)}
              className={`inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] ${
                active
                  ? "border-[var(--primary)] bg-[var(--primary-soft)] text-[var(--primary-text)]"
                  : "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:text-[var(--foreground)]"
              }`}
            >
              {tab.ai && <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />}
              {tab.label}
            </button>
          );
        })}
      </div>

      {/* Add form */}
      {adding && (
        <form
          onSubmit={handleAdd}
          className="mt-card flex flex-col gap-3 p-4"
          aria-label="添加记忆"
        >
          <div className="flex flex-wrap gap-3">
            <label className="flex min-w-40 flex-1 flex-col gap-1.5 text-sm font-medium text-[var(--foreground)]">
              类别
              <select
                value={addType}
                onChange={(e) => setAddType(e.target.value)}
                className="mt-input h-11"
              >
                {Object.entries(MEMORY_TYPE_LABELS)
                  .filter(([key]) => key !== "ai_inference")
                  .map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
              </select>
            </label>
            <label className="flex min-w-48 flex-1 flex-col gap-1.5 text-sm font-medium text-[var(--foreground)]">
              内容
              <input
                value={addPredicate}
                onChange={(e) => setAddPredicate(e.target.value)}
                placeholder="例如：喜欢举一反三的讲解方式"
                className="mt-input h-11"
              />
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="mt-btn"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={saving}
              className="mt-btn mt-btn-primary"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Plus className="h-4 w-4" aria-hidden="true" />}
              保存记忆
            </button>
          </div>
        </form>
      )}

      {message && (
        <p
          role="status"
          className={`rounded-xl px-3 py-2 text-sm ${
            message.kind === "ok"
              ? "bg-emerald-50 text-[var(--success)] dark:bg-emerald-950/40"
              : "bg-red-50 text-[var(--destructive)] dark:bg-red-950/40"
          }`}
        >
          {message.text}
        </p>
      )}

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          正在加载记忆…
        </p>
      ) : visible.length === 0 ? (
        <div className="mt-card flex flex-col items-center gap-2 border-dashed px-6 py-12 text-center">
          <BrainCircuit className="h-8 w-8 text-[var(--muted-foreground)]" aria-hidden="true" />
          <p className="text-sm font-medium text-[var(--foreground)]">这里还没有记忆</p>
          <p className="max-w-sm text-sm leading-relaxed text-[var(--muted-foreground)]">
            点击「添加记忆」记下你的偏好与目标；AI 也会在学习中推测一些记忆，等你确认后才会使用。
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-3">
          {visible.map((memory) => (
            <MemoryRow
              key={memory.memory_id}
              memory={memory}
              busy={busyId === memory.memory_id}
              onToggleRetrieval={(enabled) => handleToggle(memory, enabled)}
              onDelete={() => handleDelete(memory)}
              onConfirm={() => handleConfirm(memory)}
              onUpdated={handleUpdated}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
