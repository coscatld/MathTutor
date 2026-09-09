"use client";

import { Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchTutorSettings, saveTutorSettings } from "../lib/desktop-api";
import type { TutorSettings } from "../types";
import { useToast } from "./ToastProvider";

export default function TutorPersonalityPanel() {
  const [settings, setSettings] = useState<TutorSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const toast = useToast();
  useEffect(() => { void fetchTutorSettings().then(setSettings).catch(() => toast({ title: "Tutor 设置读取失败", tone: "error" })); }, [toast]);
  if (!settings) return <div className="flex items-center gap-2 py-12 text-sm text-slate-500"><Loader2 className="h-4 w-4 animate-spin" />正在读取 Tutor 设置…</div>;
  const save = async () => {
    setSaving(true);
    try { setSettings(await saveTutorSettings({ personality: settings.personality, custom_instruction: settings.custom_instruction })); toast({ title: "Tutor 风格已保存", description: "下一轮模型回复会采用新的表达风格。" }); }
    catch { toast({ title: "Tutor 风格没有保存", description: "请稍后重试。", tone: "error" }); }
    finally { setSaving(false); }
  };
  return <section className="max-w-2xl space-y-5">
    <div><h2 className="font-serif text-xl font-bold">Tutor 风格</h2><p className="mt-1 text-sm leading-6 text-slate-500">只影响讲解的语气与组织方式，不会改变文档内容、学习记忆或答案披露规则。</p></div>
    <div className="rounded-2xl border border-[#deddd7] bg-white p-5 dark:border-slate-700 dark:bg-slate-900"><p className="mb-3 text-sm font-semibold">教学表达</p><div className="grid gap-2 sm:grid-cols-2">{settings.presets.map((preset) => <button type="button" key={preset.id} onClick={() => setSettings({ ...settings, personality: preset.id })} className={`rounded-xl border px-4 py-3 text-left text-sm ${settings.personality === preset.id ? "border-[#1d5fd1] bg-blue-50 font-semibold text-[#174c9e] dark:bg-blue-950" : "border-[#deddd7] hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800"}`}>{preset.label}</button>)}</div>
      {settings.personality === "custom" ? <div className="mt-4"><label htmlFor="tutor-custom-style" className="mb-2 block text-sm font-medium">自定义说明</label><textarea id="tutor-custom-style" value={settings.custom_instruction} onChange={(event) => setSettings({ ...settings, custom_instruction: event.target.value })} rows={5} maxLength={1000} placeholder="例如：语气亲切；每次只问一个问题；多用生活中的例子。" className="w-full rounded-xl border border-[#deddd7] bg-transparent p-3 text-sm leading-6 outline-none focus:border-[#1d5fd1] dark:border-slate-700" /></div> : null}
      <button type="button" onClick={save} disabled={saving} className="mt-5 flex h-11 items-center gap-2 rounded-xl bg-[#1d5fd1] px-5 text-sm font-semibold text-white hover:bg-[#174fab] disabled:opacity-50">{saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}保存 Tutor 风格</button>
    </div>
  </section>;
}
