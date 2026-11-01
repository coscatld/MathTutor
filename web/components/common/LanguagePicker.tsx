"use client";

import {useI18n, type Locale} from "@/lib/i18n";
import {useId, useState} from "react";

export default function LanguagePicker({compact = false}: {compact?: boolean}) {
  const {locale, setLocale, t} = useI18n();
  const id = useId();
  const [temporary, setTemporary] = useState(false);
  const choose = (value: string) => setTemporary(!setLocale(value as Locale));
  if (compact) return <label className="inline-flex flex-wrap items-center gap-2 text-sm">
    <span>语言 / Language</span>
    <select aria-label={t("界面语言")} value={locale} onChange={event => choose(event.target.value)} className="mt-input min-h-11 min-w-32 text-base">
      <option value="zh-CN" lang="zh-CN">中文</option><option value="en" lang="en">English</option>
    </select>
    {temporary && <span role="status">{t("浏览器未允许保存偏好，本次会话已切换语言。")}</span>}
  </label>;
  return <div className="mt-card space-y-3 p-5">
    <label htmlFor={id} className="block text-sm font-semibold">{t("界面语言")}</label>
    <select id={id} value={locale} onChange={event => choose(event.target.value)}
      aria-describedby={`${id}-description`} className="mt-input min-h-11 w-full max-w-sm text-base">
      <option value="zh-CN" lang="zh-CN">中文</option>
      <option value="en" lang="en">English</option>
    </select>
    <p id={`${id}-description`} className="text-sm leading-6 text-[var(--muted-foreground)]">{t("立即切换界面语言，选择保存在本机。笔记、题目和历史对话保留原文。")}</p>
    {temporary && <p role="status" className="text-sm leading-6">{t("浏览器未允许保存偏好，本次会话已切换语言。")}</p>}
  </div>;
}
