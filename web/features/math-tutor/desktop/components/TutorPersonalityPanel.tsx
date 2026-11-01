"use client";

import { useI18n } from "@/lib/i18n";

import { Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchTutorSettings, saveTutorSettings } from "../lib/desktop-api";
import type { TutorSettings } from "../types";
import { useToast } from "./ToastProvider";

export default function TutorPersonalityPanel() {
  const { t } = useI18n();
  const [settings, setSettings] = useState<TutorSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  const styleLabels: Record<string, string> = { patient: "耐心引导", socratic: "苏格拉底式", concise: "简洁直接", detailed: "细致讲解", custom: "自定义" };
  useEffect(() => { void fetchTutorSettings().then(setSettings).catch(() => toast({ title: t("Tutor 设置读取失败"), tone: "error" })); }, [toast]);
  if (!settings) return <div className="flex items-center gap-2 py-12 text-sm text-[var(--muted-foreground)]"><Loader2 className="h-4 w-4 animate-spin" />{t("正在读取 Tutor 设置…")}</div>;
  const save = async () => {
    setSaving(true);
    try { setSettings(await saveTutorSettings({ personality: settings.personality, custom_instruction: settings.custom_instruction })); toast({ title: t("Tutor 风格已保存"), description: t("下一轮模型回复会采用新的表达风格。") }); }
    catch { toast({ title: t("Tutor 风格没有保存"), description: t("请稍后重试。"), tone: "error" }); }
    finally { setSaving(false); }
  };
  return <section className="max-w-2xl space-y-5">
    <div><h2 className="text-xl font-bold tracking-tight">{t("Tutor 风格")}</h2><p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">{t("只影响讲解的语气与组织方式，不会改变文档内容、学习记忆或答案披露规则。")}</p></div>
    <div className="mt-card p-5"><p className="mb-3 text-sm font-semibold">{t("教学表达")}</p><div className="grid gap-2 sm:grid-cols-2">{settings.presets.map((preset) => <button type="button" key={preset.id} onClick={() => setSettings({ ...settings, personality: preset.id })} className={`mt-choice min-h-11 text-left text-sm ${settings.personality === preset.id ? "mt-choice-selected font-semibold text-[var(--primary-text)]" : ""}`}>{styleLabels[preset.id] ? t(styleLabels[preset.id]) : preset.label}</button>)}</div>
      {settings.personality === "custom" ? <div className="mt-4"><label htmlFor="tutor-custom-style" className="mb-2 block text-sm font-medium">{t("自定义说明")}</label><textarea id="tutor-custom-style" value={settings.custom_instruction} onChange={(event) => setSettings({ ...settings, custom_instruction: event.target.value })} rows={5} maxLength={1000} placeholder={t("例如：语气亲切；每次只问一个问题；多用生活中的例子。")} className="mt-input h-auto p-3 leading-6" /></div> : null}
      <button type="button" onClick={save} disabled={saving} className="mt-btn mt-btn-primary mt-5 min-h-11 px-5">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}{t("保存 Tutor 风格")}</button>
    </div>
  </section>;
}
