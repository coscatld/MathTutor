"use client";

import { Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchCostSettings, saveCostSettings } from "../lib/desktop-api";
import type { CostSettings, CostSettingsInput } from "../types";
import { useToast } from "./ToastProvider";

const FIELDS: { key: keyof CostSettingsInput; label: string; hint: string; integer?: boolean }[] = [
  { key: "input_price_per_mtok", label: "输入单价（每百万 token）", hint: "按服务商价目填写；不填则只统计 token，不估算费用。" },
  { key: "output_price_per_mtok", label: "输出单价（每百万 token）", hint: "需与输入单价一起填写。" },
  { key: "daily_budget", label: "每日费用预算", hint: "达到后当天改用本地模板教学，需先填写单价。" },
  { key: "daily_token_budget", label: "每日 token 预算", hint: "不填单价时也可以按 token 限额。", integer: true },
];

function toInput(settings: CostSettings): CostSettingsInput {
  const { input_price_per_mtok, output_price_per_mtok, currency, daily_budget, daily_token_budget } = settings;
  return { input_price_per_mtok, output_price_per_mtok, currency, daily_budget, daily_token_budget };
}

/** Prices and daily budget for model calls. Nothing here reaches the model. */
export default function CostSettingsPanel() {
  const [settings, setSettings] = useState<CostSettings | null>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  useEffect(() => {
    void fetchCostSettings().then(result => {
      setSettings(result);
      setDraft(Object.fromEntries(FIELDS.map(field => [field.key, result[field.key] == null ? "" : String(result[field.key])])));
    }).catch(() => toast({ title: "费用设置读取失败", tone: "error" }));
  }, [toast]);
  if (!settings) return <div className="flex items-center gap-2 py-6 text-sm text-[var(--muted-foreground)]"><Loader2 className="h-4 w-4 animate-spin" />正在读取费用设置…</div>;
  const save = async () => {
    setSaving(true);
    try {
      const input: CostSettingsInput = { ...toInput(settings) };
      for (const field of FIELDS) {
        const raw = (draft[field.key] || "").trim();
        (input as unknown as Record<string, number | null>)[field.key] = raw ? (field.integer ? Number.parseInt(raw, 10) : Number(raw)) : null;
      }
      setSettings(await saveCostSettings(input));
      toast({ title: "费用设置已保存" });
    } catch {
      toast({ title: "费用设置没有保存", description: "单价需成对填写；金额预算需要先填写单价。", tone: "error" });
    } finally {
      setSaving(false);
    }
  };
  const today = settings.today;
  return <section className="max-w-2xl space-y-4">
    <div><h2 className="text-xl font-bold tracking-tight">模型费用与预算</h2><p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">费用按你填写的单价估算，仅供参考，以服务商账单为准。超过预算后当天不再调用模型，数学核验和学习记录不受影响。</p></div>
    <div className="mt-card p-5">
      <p className="text-sm">今天已用 <strong>{today.tokens.toLocaleString()}</strong> token{settings.input_price_per_mtok != null ? <>，约 <strong>{today.cost}</strong> {today.currency}</> : null}{settings.over_budget ? <span className="ml-2 text-[var(--danger,#b42318)]">已达预算</span> : null}</p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {FIELDS.map(field => <label key={field.key} className="block text-sm">
          <span className="mb-1 block font-medium">{field.label}</span>
          <input inputMode="decimal" value={draft[field.key] || ""} onChange={event => setDraft({ ...draft, [field.key]: event.target.value })} className="mt-input" placeholder="不填" />
          <span className="mt-1 block text-xs leading-5 text-[var(--muted-foreground)]">{field.hint}</span>
        </label>)}
      </div>
      <button type="button" onClick={save} disabled={saving} className="mt-btn mt-btn-primary mt-5 min-h-11 px-5">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}保存费用设置</button>
    </div>
  </section>;
}
