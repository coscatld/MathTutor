"use client";

import { useI18n } from "@/lib/i18n";

import { Loader2, Save } from "lucide-react";
import { useEffect, useState } from "react";
import type { LearnerSettings, LearnerStage } from "../../lib/question-bank-types";
import { fetchLearnerSettings, saveLearnerSettings } from "../lib/desktop-api";
import { gradeLabel, STAGES } from "../lib/question-bank";
import { useToast } from "./ToastProvider";

type StageOption = { stage: LearnerStage; label: string; grades: number[] };

/** Pure form: stage radios (or 不设置) and, for the chosen stage only, its grades. */
export function LearnerStageForm({ stages = STAGES, stage, grade, saving = false, onStage, onGrade, onSave }: {
  stages?: StageOption[];
  stage: LearnerStage | null;
  grade: number | null;
  saving?: boolean;
  onStage: (stage: LearnerStage | null) => void;
  onGrade: (grade: number | null) => void;
  onSave: () => void;
}) {
  const { locale, t } = useI18n();
  const current = stages.find(item => item.stage === stage);
  const options: { value: LearnerStage | null; label: string }[] = [...stages.map(item => ({ value: item.stage, label: item.label })), { value: null, label: "不设置" }];
  return <div className="mt-card space-y-5 p-5">
    <fieldset>
      <legend className="mb-2 text-sm font-medium">{t("学段")}</legend>
      <div className="grid gap-2 sm:grid-cols-4">{options.map(option => <label key={option.value ?? "none"} className={`mt-choice ${stage === option.value ? "mt-choice-selected" : ""}`}>
        <input type="radio" name="learner-stage" className="sr-only" checked={stage === option.value} onChange={() => onStage(option.value)} />
        {t(option.label)}
      </label>)}</div>
    </fieldset>
    {current ? <label className="block text-sm">
      <span className="mb-1 block font-medium">{t("年级（可选）")}</span>
      <select aria-label={t("年级")} value={grade ?? ""} onChange={event => onGrade(event.target.value ? Number(event.target.value) : null)} className="mt-input">
        <option value="">{t("不指定年级")}</option>
        {current.grades.map(value => <option key={value} value={value}>{locale === "en" ? t("{grade} 年级", {grade: value}) : gradeLabel(value)}</option>)}
      </select>
      <span className="mt-1 block text-xs leading-5 text-[var(--muted-foreground)]">{t("指定年级后，题库会先展开这一年级的册目。")}</span>
    </label> : null}
    <button type="button" onClick={onSave} disabled={saving} className="mt-btn mt-btn-primary min-h-11 px-5">{saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Save className="h-4 w-4" aria-hidden="true" />}{t("保存学段")}</button>
  </div>;
}

/** Settings → 学段. The question bank only shows this stage's terms. */
export default function LearnerStagePanel({ fetchLearnerFn = fetchLearnerSettings, saveLearnerFn = saveLearnerSettings }: {
  fetchLearnerFn?: typeof fetchLearnerSettings;
  saveLearnerFn?: typeof saveLearnerSettings;
}) {
  const { t } = useI18n();
  const [settings, setSettings] = useState<LearnerSettings | null>(null);
  const [stage, setStage] = useState<LearnerStage | null>(null);
  const [grade, setGrade] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const toast = useToast();
  useEffect(() => {
    void fetchLearnerFn().then(result => { setSettings(result); setStage(result.stage); setGrade(result.grade); })
      .catch(() => setError("学段设置读取失败，请稍后再试。"));
  }, [fetchLearnerFn]);
  const save = async () => {
    setSaving(true);
    try {
      const result = await saveLearnerFn(stage, stage ? grade : null);
      setSettings(result); setStage(result.stage); setGrade(result.grade);
      toast({ title: t("学段已保存") });
    } catch {
      toast({ title: t("学段没有保存"), description: t("年级需要属于所选学段。"), tone: "error" });
    } finally { setSaving(false); }
  };
  return <section className="max-w-2xl space-y-4">
    <div><h2 className="text-xl font-bold tracking-tight">{t("学段")}</h2><p className="mt-1 text-sm leading-6 text-[var(--muted-foreground)]">{t("选择你所在的学段。题库只显示这一学段的册目：小学为一年级上册到六年级下册，初中为七年级上册到九年级下册，高中为高一上到高三下。不设置时，进入题库会先请你选择。")}</p></div>
    {error ? <p role="alert" className="rounded-xl bg-[var(--muted)] p-4 text-sm">{t(error)}</p>
      : !settings ? <div role="status" className="flex items-center gap-2 py-6 text-sm text-[var(--muted-foreground)]"><Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />{t("正在读取学段设置…")}</div>
      : <LearnerStageForm stages={settings.stages?.length ? settings.stages : STAGES} stage={stage} grade={grade} saving={saving}
          onStage={next => { setStage(next); if (next !== stage) setGrade(null); }} onGrade={setGrade} onSave={() => void save()} />}
  </section>;
}
