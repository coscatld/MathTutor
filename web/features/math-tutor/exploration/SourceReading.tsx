"use client";

import { ExternalLink } from "lucide-react";
import Link from "next/link";
import { useI18n } from "@/lib/i18n";
import type { EvidenceCard, ExplorationView, LibraryExcerpt } from "./api";

const providerNames = {
  zhihu: "知乎搜索摘录", wikipedia: "维基百科", wikibooks: "维基教科书",
  active_calculus: "Active Calculus", open_math_books: "Open Math Books",
};
const textbookPages = {
  active_calculus: "https://activecalculus.org/single/sec-1-7-lim-cont-diff.html",
  open_math_books: "https://discrete.openmathbooks.org/dmoi3/sec_logic-proofs.html",
};

export function sourceHref(value: string, provider: EvidenceCard["provider"] = "zhihu"): string | undefined {
  if (typeof value !== "string" || value.length > 2048 || /[\x00-\x20\x7f\\]/.test(value)) return undefined;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port) return undefined;
    if (provider === "zhihu") return ["zhihu.com", "www.zhihu.com", "zhuanlan.zhihu.com"].includes(url.hostname)
      && /^\/(?:question\/\d+(?:\/answer\/\d+)?|(?:en\/)?answer\/\d+|p\/\d+)\/?$/.test(url.pathname) ? value : undefined;
    if (provider === "wikipedia" || provider === "wikibooks") return ["zh", "en"].some(lang => url.hostname === `${lang}.${provider}.org`)
      && url.pathname === "/w/index.php" && /^\?oldid=[1-9]\d*$/.test(url.search) && !url.hash ? value : undefined;
    return textbookPages[provider] === value ? value : undefined;
  } catch { return undefined; }
}

function sourceLabel(card: EvidenceCard, t: (text: string) => string) {
  const provider = card.provider ?? "zhihu";
  if (provider === "zhihu") return t(providerNames.zhihu);
  const scope = card.source_scope === "textbook_excerpt" ? "内置教材节选" : card.source_scope === "page_excerpt" ? "原页节选" : "搜索摘要";
  return `${t(providerNames[provider])} · ${t(scope)}`;
}

export function RetrievalStatus({ attempts, onRetry }: { attempts: NonNullable<ExplorationView["retrieval_attempts"]>; onRetry?: () => void }) {
  const { t } = useI18n();
  if (!attempts.length) return null;
  const labels = { found: "找到 {count} 条", empty: "无匹配", unavailable: "连接或响应异常", rate_limited: "请求受限" };
  const online = attempts.filter(row => row.access !== "bundled");
  const projects = new Set(online.map(row => row.provider));
  const failed = [...projects].filter(provider => {
    const rows = online.filter(row => row.provider === provider);
    return rows.length && rows.every(row => row.status === "rate_limited" || row.status === "unavailable");
  }).length;
  return <div className="mt-4">{failed > 0 && <div role="status" className="flex flex-wrap items-center gap-x-4 text-sm leading-6 text-[var(--warning)]">
    <p>{t(failed === projects.size ? "在线来源暂不可用。" : "部分在线来源暂不可用。")}</p>
    {onRetry && <button type="button" className="min-h-11 text-[var(--primary-text)] underline" onClick={onRetry}>{t("用这个问题重新查询")}</button>}
  </div>}
  <ul aria-label={t("各来源检索状态")} className="flex flex-wrap gap-x-5 gap-y-1 text-sm leading-6 text-[var(--muted-foreground)]">
    {attempts.filter(item => item.access !== "bundled" || item.status !== "empty").map(item => <li key={`${item.provider}-${item.language}`}>{t(providerNames[item.provider])} · {t(item.access === "bundled" ? "内置教材节选" : item.language === "zh" ? "中文" : "英文")} · {t(labels[item.status], { count: item.count ?? 0 })}</li>)}
  </ul></div>;
}

export function LibraryReadings({ items }: { items: LibraryExcerpt[] | null }) {
  const { t } = useI18n();
  return <section className="mt-4" aria-label={t("我的本机资料")}>
    <Link href="/math-tutor/documents" className="inline-flex min-h-11 items-center font-medium text-[var(--primary-text)]">{t("管理或导入资料")}</Link>
    {items === null ? null : <><p role="status" className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
      {t(items.length ? "在本机找到 {count} 段摘录" : "本机资料中未找到匹配段落。可以更换关键词，或在资料库中导入并启用文档。", { count: items.length })}</p>
      <ul className="divide-y divide-[var(--border)]">{items.map(item => <li key={item.chunk_id} className="py-4">
        <Link href={`/math-tutor/documents#document-${item.document_id}`} className="inline-flex min-h-11 items-center break-words font-medium text-[var(--primary-text)]">{item.filename}</Link>
        <p className="text-sm text-[var(--muted-foreground)]">{[t("本机文档"), item.page ? t("第 {page} 页", {
          page: item.page_end && item.page_end !== item.page ? `${item.page}–${item.page_end}` : item.page,
        }) : null, item.section].filter(Boolean).join(" · ")}</p>
        <blockquote className="mt-2 whitespace-pre-wrap break-words border-l-2 border-[var(--primary)] pl-4 leading-7">{item.text}</blockquote>
        {item.truncated && <p className="mt-1 text-sm">{t("已截取段落开头。")}</p>}
      </li>)}</ul></>}
  </section>;
}

export function SourceCard({ card, selected, selectionFull, onSelect, sourceText, retrievedAt, warnings = [] }: {
  card: EvidenceCard; index: number; selected: boolean; selectionFull: boolean; onSelect: () => void;
  sourceText?: string; retrievedAt?: string; warnings?: string[];
}) {
  const { t, locale } = useI18n();
  const href = sourceHref(card.original_url, card.provider);
  const origin = card.attribution;
  return <article className="min-w-0 border-b border-[var(--border)] py-6" aria-labelledby={`source-${card.span_id}`}>
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-sm text-[var(--muted-foreground)]">
      <p>{sourceLabel(card, t)}</p>
      <label className={`flex min-h-11 cursor-pointer items-center gap-2 ${selectionFull && !selected ? "opacity-50" : ""}`}>
        <input type="checkbox" checked={selected} disabled={selectionFull && !selected} onChange={onSelect}
          aria-label={t("对照摘录：{title}", { title: card.title })} className="h-4 w-4 accent-[var(--primary)]" />
        {t("加入对照")}
      </label>
    </div>
    <h3 id={`source-${card.span_id}`} className="mt-1 break-words text-lg font-semibold leading-7">{card.title}</h3>
    <div className="flex flex-wrap items-center gap-x-4 text-sm text-[var(--muted-foreground)]">
      <span>{card.author || t("作者未提供")}</span>
      {origin && <><span>{t(origin.language === "zh" ? "中文" : "英文")} · {card.provider === "wikipedia" || card.provider === "wikibooks" ? t("修订 {id}", { id: origin.version }) : origin.version}</span>
        <a className="inline-flex min-h-11 items-center underline" href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noopener noreferrer">{origin.license}</a></>}
      {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1 text-[var(--primary-text)] underline-offset-4 hover:underline">
        {t(card.provider && card.provider !== "zhihu" ? "打开原文" : "打开知乎原文")}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
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
      {retrievedAt && <p className="mb-2 text-[var(--muted-foreground)]">{t("收录于此探索")} <time dateTime={retrievedAt}>{new Date(retrievedAt).toLocaleString(locale)}</time></p>}
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
      const href = sourceHref(card.original_url, card.provider);
      return <article key={card.span_id} className="min-w-0">
        <h4 className="break-words font-medium leading-6">{card.title}</h4>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">{card.author || t("作者未提供")} · {sourceLabel(card, t)}</p>
        <blockquote className="my-3 whitespace-pre-wrap break-words border-l-2 border-[var(--border)] pl-3 leading-7">{card.quote}</blockquote>
        <p className="text-sm leading-6">{card.reading_question || t("这段话使用了哪些定义、范围或前提？")}</p>
        {href && <a href={href} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1 text-sm text-[var(--primary-text)] hover:underline">
          {t(card.provider && card.provider !== "zhihu" ? "打开原文" : "打开知乎原文")}<ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
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
