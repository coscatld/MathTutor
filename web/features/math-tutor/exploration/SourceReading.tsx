"use client";

import { ExternalLink } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import type { EvidenceCard, ExplorationView } from "./api";

export function sourceHref(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && ["zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"].includes(url.hostname)
      && !url.username && !url.password ? value : undefined;
  } catch { return undefined; }
}

export function SourceCard({ card, index, selected, selectionFull, onSelect, sourceText, warnings = [] }: {
  card: EvidenceCard; index: number; selected: boolean; selectionFull: boolean; onSelect: () => void;
  sourceText?: string; warnings?: string[];
}) {
  const { t } = useI18n();
  const href = sourceHref(card.original_url);
  return <article className="min-w-0 border-b border-[var(--border)] py-6" aria-labelledby={`source-${card.span_id}`}>
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm text-[var(--muted-foreground)]">
      <p>{String(index + 1).padStart(2, "0")} <span className="ml-2">{t("知乎搜索摘录")}</span></p>
      <label className={`flex min-h-11 cursor-pointer items-center gap-2 ${selectionFull && !selected ? "opacity-50" : ""}`}>
        <input type="checkbox" checked={selected} disabled={selectionFull && !selected} onChange={onSelect}
          aria-label={t("对照摘录：{title}", { title: card.title })} className="h-4 w-4 accent-[var(--primary)]" />
        {t("加入对照")}
      </label>
    </div>
    <h3 id={`source-${card.span_id}`} className="mt-1 break-words text-lg font-semibold leading-7">{card.title}</h3>
    <div className="flex flex-wrap items-center gap-x-4 text-sm text-[var(--muted-foreground)]">
      <span>{card.author || t("作者未提供")}</span>
      {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1 text-[var(--primary-text)] underline-offset-4 hover:underline">
        {t("打开知乎原文")}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
      </a> : null}
    </div>
    <blockquote className="mt-2 whitespace-pre-wrap break-words border-l-2 border-[var(--primary)] pl-4 text-base leading-8">{card.quote}</blockquote>
    {warnings.includes("possible_missing_formula") ? <p className="mt-3 text-sm leading-6 text-[var(--warning)]">{t("摘录可能缺少公式，请到原文核对。")}</p> : null}
    {warnings.includes("excerpt_truncated") ? <p className="mt-3 text-sm leading-6 text-[var(--muted-foreground)]">{t("这条检索摘录较长，仅保留了开头部分。")}</p> : null}
    {card.reading_question ? <div className="mt-4 rounded-lg bg-[var(--muted)] px-4 py-3">
      <p className="text-sm font-medium text-[var(--muted-foreground)]">{t("AI 建议的阅读重点")}</p>
      <p className="mt-1 whitespace-pre-wrap break-words leading-7">{card.reading_question}</p>
    </div> : null}
    <details className="mt-3 text-sm">
      <summary className="min-h-11 cursor-pointer py-3 font-medium text-[var(--muted-foreground)]">{t("展开摘录上下文")}</summary>
      <p className="whitespace-pre-wrap break-words rounded-lg bg-[var(--muted)] p-4 leading-7">{card.context}</p>
      {sourceText && sourceText !== card.context ? <details className="mt-2">
        <summary className="min-h-11 cursor-pointer py-3 font-medium text-[var(--muted-foreground)]">{t("查看本次检索收到的摘录")}</summary>
        <p className="whitespace-pre-wrap break-words leading-7">{sourceText}</p>
      </details> : null}
    </details>
  </article>;
}

export function SourceComparison({ cards, comparisons, onClear }: {
  cards: EvidenceCard[]; comparisons: ExplorationView["evidence"]["comparisons"]; onClear: () => void;
}) {
  const { t } = useI18n();
  if (cards.length !== 2) return null;
  const questions = comparisons.filter(item => cards.every(card => item.span_ids.includes(card.span_id)));
  return <section className="my-5 border-l-2 border-[var(--primary)] bg-[var(--primary-soft)] p-5" aria-labelledby="comparison-title">
    <div className="flex items-center justify-between gap-3">
      <h3 id="comparison-title" className="text-lg font-semibold">{t("把条件放在一起看")}</h3>
      <button type="button" onClick={onClear} className="min-h-11 shrink-0 px-2 text-sm text-[var(--primary-text)]">{t("清除选择")}</button>
    </div>
    <div className="mt-3 grid gap-5 sm:grid-cols-2">{cards.map(card => {
      const href = sourceHref(card.original_url);
      return <article key={card.span_id} className="min-w-0">
        <h4 className="break-words font-medium leading-6">{card.title}</h4>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">{card.author || t("作者未提供")} · {t("知乎搜索摘录")}</p>
        <blockquote className="my-3 whitespace-pre-wrap break-words border-l-2 border-[var(--border)] pl-3 leading-7">{card.quote}</blockquote>
        <p className="text-sm leading-6">{card.reading_question || t("这段话使用了哪些定义、范围或前提？")}</p>
        {href && <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1 text-sm text-[var(--primary-text)] hover:underline">
          {t("打开知乎原文")}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
        </a>}
      </article>;
    })}</div>
    <p className="mt-4 leading-7">{t("两段话讨论的是同一个条件下的问题吗？回到原文，找出各自的适用范围。")}</p>
    {questions.map((item, index) => <div key={index} className="mt-3 border-t border-[var(--border)] pt-3">
      <p className="text-sm text-[var(--muted-foreground)]">{t("AI 对照问题 · 待你核对")}</p>
      <p className="mt-1 whitespace-pre-wrap break-words leading-7">{item.reading_question}</p>
    </div>)}
  </section>;
}
