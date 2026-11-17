"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ArrowRight, Plus, Search, Trash2 } from "lucide-react";
import { useI18n } from "@/lib/i18n";
import { productClass } from "@/styles/product-classes";
import { useUnsavedNavigation } from "../hooks/useUnsavedNavigation";
import { ExplorationApiError, explorationApi, type ExplorationConfiguration, type ExplorationView, type InquiryGoal, type InquiryLanguage, type InquiryList } from "./api";
import { ExplorationRequests } from "./requests";
import { SourceCard, SourceComparison } from "./SourceReading";
import LearningPanel from "./LearningPanel";

const goals: Array<[InquiryGoal, string]> = [["understand", "理解概念"], ["apply", "学会应用"], ["compare", "对照解法"]];
const samples = ["为什么 0.999… 等于 1？", "方程两边同时除以 x，什么时候会丢解？", "为什么函数连续不一定可导？"];
type Operation = "load" | "search" | "open" | "organize" | "reflect" | "respond" | "explain" | "delete";
const operationLabels: Record<Operation, string> = {
  load: "正在同步探索记录…", search: "正在检索知乎来源…", open: "正在打开探索…", organize: "正在整理阅读问题…",
  reflect: "正在保存理解记录…", respond: "正在检查回答…", explain: "正在打开解释…", delete: "正在删除探索…",
};

function summaryOf(view: ExplorationView): InquiryList["items"][number] {
  return { inquiry_id: view.inquiry_id, question: view.question, goal: view.goal, revision: view.revision, updated_at: view.updated_at };
}

export default function ExplorationWorkbench() {
  const { t, locale } = useI18n();
  const language: InquiryLanguage = locale === "en" ? "en" : "zh";
  const [configuration, setConfiguration] = useState<ExplorationConfiguration | null>(null);
  const [history, setHistory] = useState<InquiryList | null>(null);
  const [view, setView] = useState<ExplorationView | null>(null);
  const [question, setQuestion] = useState("");
  const [goal, setGoal] = useState<InquiryGoal>("understand");
  const [reflection, setReflection] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState<Operation | null>("load");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [reload, setReload] = useState(0);
  const requests = useRef(new ExplorationRequests());
  const viewRef = useRef<ExplorationView | null>(null);
  const reflectionRef = useRef("");
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const dirty = Boolean(view && reflection !== view.reflection);
  useUnsavedNavigation(dirty ? t("你的理解记录尚未保存。") : !view && question.trim() ? t("探索问题尚未提交。") : "", undefined, `${view?.inquiry_id}:${reflection}:${question}`);

  const acceptView = useCallback((value: ExplorationView, replaceDraft = false) => {
    const changedInquiry = viewRef.current?.inquiry_id !== value.inquiry_id;
    const draftUnchanged = reflectionRef.current === viewRef.current?.reflection;
    viewRef.current = value; setView(value);
    if (changedInquiry || replaceDraft || draftUnchanged) { reflectionRef.current = value.reflection; setReflection(value.reflection); }
    setSelected(previous => changedInquiry ? [] : previous.filter(id => value.evidence.cards.some(card => card.span_id === id)));
    setHistory(previous => previous ? { ...previous, items: [summaryOf(value), ...previous.items.filter(item => item.inquiry_id !== value.inquiry_id)] } : previous);
    setNeedsRefresh(false);
  }, []);

  useEffect(() => {
    const owner = requests.current, request = owner.begin();
    setBusy("load"); setError("");
    const currentId = viewRef.current?.inquiry_id;
    void (async () => {
      const [configResult, listResult, viewResult] = await Promise.allSettled([
        explorationApi.configuration(request.signal), explorationApi.list(request.signal),
        currentId ? explorationApi.read(currentId, language, request.signal) : Promise.resolve(null),
      ]);
      if (!owner.accepts(request)) return;
      if (configResult.status === "fulfilled") setConfiguration(configResult.value);
      if (listResult.status === "fulfilled") setHistory(listResult.value);
      if (viewResult.status === "fulfilled" && viewResult.value) acceptView(viewResult.value);
      const failure = [configResult, listResult, viewResult].find(result => result.status === "rejected");
      if (failure?.status === "rejected") {
        setError(t(failure.reason instanceof ExplorationApiError ? failure.reason.message : "探索记录暂不可用，请重试。"));
        setNeedsRefresh(true);
      } else setNeedsRefresh(false);
      owner.finish(request); setBusy(null);
    })();
    return () => owner.cancel();
  }, [language, reload, acceptView, t]);

  useEffect(() => { if (view?.inquiry_id) titleRef.current?.focus({ preventScroll: true }); }, [view?.inquiry_id]);

  async function run<T>(kind: Operation, action: (signal: AbortSignal) => Promise<T>, apply: (value: T) => void) {
    if (requests.current.busy) return;
    const request = requests.current.begin();
    setBusy(kind); setError(""); setNotice("");
    try {
      const value = await action(request.signal);
      if (requests.current.accepts(request)) apply(value);
    } catch (error) {
      if (!requests.current.accepts(request)) return;
      setError(t(error instanceof ExplorationApiError ? error.message : "请求未完成，请同步记录后重试。"));
      if (["search", "organize", "reflect", "respond", "explain", "delete"].includes(kind)) setNeedsRefresh(true);
    } finally {
      if (requests.current.accepts(request)) { requests.current.finish(request); setBusy(null); }
    }
  }

  const confirmDiscard = () => !dirty || window.confirm(t("你的理解记录尚未保存。要放弃修改吗？"));
  const refresh = () => { requests.current.cancel(); setReload(value => value + 1); };
  const reset = () => {
    if (requests.current.busy || !confirmDiscard()) return;
    viewRef.current = null; reflectionRef.current = "";
    setView(null); setReflection(""); setQuestion(""); setSelected([]); setError(""); setNotice(""); setNeedsRefresh(false);
    requestAnimationFrame(() => questionRef.current?.focus());
  };
  const create = () => {
    if (!history || !configuration?.configured || question.trim().length < 2 || needsRefresh) return;
    const inquiryId = crypto.randomUUID();
    void run("search", signal => explorationApi.create({ inquiry_id: inquiryId, generation: history.generation, question: question.trim(), goal, language }, signal), value => {
      acceptView(value, true); setQuestion("");
    });
  };
  const open = (id: string) => {
    if (id === view?.inquiry_id || !confirmDiscard()) return;
    if (!view && question.trim() && !window.confirm(t("探索问题尚未提交。要放弃这个问题吗？"))) return;
    void run("open", signal => explorationApi.read(id, language, signal), value => { acceptView(value, true); setQuestion(""); });
  };
  const remove = (id: string) => {
    if (!window.confirm(t("删除这条探索及其理解记录？"))) return;
    if (id === view?.inquiry_id && !confirmDiscard()) return;
    void run("delete", signal => explorationApi.remove(id, signal), value => {
      setHistory(value);
      if (viewRef.current?.inquiry_id === id) {
        viewRef.current = null; reflectionRef.current = ""; setView(null); setReflection(""); setSelected([]);
      }
      setNeedsRefresh(false); setNotice(t("探索记录已删除。"));
    });
  };
  const mutationDisabled = Boolean(busy) || needsRefresh;
  const reflectionLocked = ["load", "open", "search", "delete"].includes(busy || "");

  return <div className="mx-auto max-w-[1280px] px-5 py-7 sm:px-8 sm:py-10 lg:px-10">
    <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--border)] pb-6">
      <div><p className="text-sm font-semibold tracking-wide text-[var(--primary-text)]">{t("知识探索")}</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{t("让一个问题，通向更清楚的理解。")}</h1>
        <p className="mt-3 max-w-2xl text-base leading-7 text-[var(--muted-foreground)]">{t("读知乎原文，对照解法的条件，再用一道题检验自己。")}</p>
      </div>
      {view ? <button type="button" onClick={reset} disabled={Boolean(busy)} className={productClass("mt-btn min-h-11")}><Plus className="h-4 w-4" aria-hidden="true" />{t("新问题")}</button> : null}
    </header>

    {busy || notice ? <div className="mt-4 flex flex-wrap items-center gap-3" role="status" aria-live="polite">
      <p className="text-sm leading-6 text-[var(--muted-foreground)]">{busy ? t(operationLabels[busy]) : notice}</p>
      {busy && ["search", "organize", "open"].includes(busy) ? <button type="button" className={productClass("mt-btn mt-btn-ghost min-h-11")} onClick={() => {
        requests.current.cancel(); setBusy(null); setNotice(t("请求已取消。")); setNeedsRefresh(true); setReload(value => value + 1);
      }}>{t("取消请求")}</button> : null}
    </div> : null}
    {error ? <div className="mt-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--border)] p-4">
      <p role="alert" className="min-w-0 flex-1 text-sm leading-7 text-[var(--destructive)]">{error}</p>
      <button type="button" onClick={refresh} disabled={Boolean(busy)} className={productClass("mt-btn min-h-11")}>{t("同步记录")}</button>
    </div> : null}

    {!view ? <div className="grid gap-10 py-8 lg:grid-cols-[minmax(0,1fr)_280px]">
      <section aria-labelledby="question-label">
        <form onSubmit={event => { event.preventDefault(); create(); }}>
          <label id="question-label" htmlFor="exploration-question" className="block text-lg font-semibold">{t("你想弄清什么？")}</label>
          <textarea ref={questionRef} id="exploration-question" value={question} onChange={event => setQuestion(event.target.value)}
            minLength={2} maxLength={200} rows={3} required disabled={Boolean(busy)} placeholder={t("写一个具体的数学问题")}
            className={productClass("mt-input mt-4 h-auto min-h-[120px] resize-y py-3 text-base leading-7")} />
          <fieldset className="mt-5" disabled={Boolean(busy)}><legend className="mb-2 text-sm font-medium">{t("这次的目标")}</legend>
            <div className="flex flex-wrap gap-2">{goals.map(([value, label]) => <label key={value} className={`flex min-h-11 cursor-pointer items-center gap-2 rounded-lg border px-3 text-sm ${goal === value ? "border-[var(--primary)] bg-[var(--primary-soft)] text-[var(--primary-text)]" : "border-[var(--border)]"}`}>
              <input type="radio" name="exploration-goal" value={value} checked={goal === value} onChange={() => setGoal(value)} className="h-4 w-4 accent-[var(--primary)]" />{t(label)}
            </label>)}</div>
          </fieldset>
          <button type="submit" disabled={Boolean(busy) || !history || !configuration?.configured || question.trim().length < 2 || needsRefresh}
            className={productClass("mt-btn mt-btn-primary mt-5 min-h-11")}><Search className="h-4 w-4" aria-hidden="true" />{t("开始探索")}</button>
        </form>
        {configuration && !configuration.configured ? <div className="mt-5 rounded-lg bg-[var(--muted)] p-4 text-sm leading-7">
          <p>{t("先连接知乎，即可检索真实问答。已保存的探索仍可继续阅读。")}</p>
          <Link href="/math-tutor/settings?section=sources" className="inline-flex min-h-11 items-center gap-2 font-medium text-[var(--primary-text)]">{t("连接知乎")}<ArrowRight className="h-4 w-4" aria-hidden="true" /></Link>
        </div> : null}
        <div className="mt-8"><p className="text-sm font-medium text-[var(--muted-foreground)]">{t("从这些问题开始")}</p>
          <ul className="mt-2 divide-y divide-[var(--border)]">{samples.map(sample => <li key={sample}><button type="button" disabled={Boolean(busy)}
            onClick={() => { setQuestion(t(sample)); questionRef.current?.focus(); }} className="flex min-h-11 w-full items-center justify-between gap-3 py-3 text-left text-sm leading-6 hover:text-[var(--primary-text)]">
            <span>{t(sample)}</span><ArrowRight className="h-4 w-4 shrink-0" aria-hidden="true" />
          </button></li>)}</ul>
        </div>
      </section>
      <InquiryHistory history={history} activeId={null} busy={Boolean(busy)} onOpen={open} onRemove={remove} />
    </div> : <>
      <details className="mt-4 border-b border-[var(--border)] pb-2">
        <summary className="min-h-11 cursor-pointer py-3 text-sm font-medium text-[var(--muted-foreground)]">{t("已保存的探索（{count}）", { count: history?.items.length ?? 0 })}</summary>
        <InquiryHistory history={history} activeId={view.inquiry_id} busy={Boolean(busy)} onOpen={open} onRemove={remove} compact />
      </details>
      <div className="py-7"><p className="text-sm font-medium text-[var(--primary-text)]">{t(goals.find(([id]) => id === view.goal)?.[1] || "理解概念")}</p>
        <h2 ref={titleRef} tabIndex={-1} className="mt-2 max-w-4xl break-words text-2xl font-semibold leading-relaxed tracking-tight outline-none">{view.question}</h2>
      </div>
      <div className="grid items-start gap-9 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          <section aria-labelledby="sources-title">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] pb-4">
              <div><h2 id="sources-title" className="text-xl font-semibold">{t("先看来源")}</h2>
                <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">{t("检索到 {count} 段不同摘录", { count: view.evidence.distinct_excerpt_count })}</p></div>
              <button type="button" disabled={mutationDisabled || !view.evidence.cards.length || view.organization_attempts >= 2}
                onClick={() => void run("organize", signal => explorationApi.organize(view, language, signal), acceptView)}
                className={productClass("mt-btn min-h-11")}>{t(view.organization_attempts >= 2 ? "已用完本次整理次数" : view.ai_status === "not_requested" ? "AI 整理阅读问题" : "重新整理")}</button>
            </div>
            <p className="mt-4 text-sm leading-7 text-[var(--muted-foreground)]">{t("这里展示检索摘录；公式和上下文请回到原文核对。选两条摘录，比较适用条件。")}</p>
            <p className="mt-1 text-sm leading-7 text-[var(--muted-foreground)]">{t("来源中的数学结论仍需核对。")}</p>
            {view.ai_status === "unavailable" ? <p role="status" className="mt-3 text-sm leading-7 text-[var(--warning)]">{t("AI 整理未能完整完成，现有来源仍可阅读和对照。")}</p> : null}
            <SourceComparison cards={view.evidence.cards.filter(card => selected.includes(card.span_id))} comparisons={view.evidence.comparisons} onClear={() => setSelected([])} />
            {view.evidence.cards.length ? view.evidence.cards.map((card, index) => {
              const source = view.evidence.sources.find(item => item.source_id === card.source_id);
              return <SourceCard key={card.span_id} card={card} index={index} selected={selected.includes(card.span_id)} selectionFull={selected.length >= 2}
                sourceText={source?.text} warnings={source?.content_warnings}
                onSelect={() => setSelected(previous => previous.includes(card.span_id) ? previous.filter(id => id !== card.span_id) : previous.length < 2 ? [...previous, card.span_id] : previous)} />;
            }) : <div className="py-10"><h3 className="font-semibold">{t("还没有可用的来源摘录")}</h3><p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t("试着在新问题中补充概念、条件或具体例子。你仍可以完成右侧的理解检查。")}</p></div>}
          </section>
          <section className="mt-8" aria-labelledby="reflection-label">
            <form onSubmit={event => {
              event.preventDefault(); if (mutationDisabled) return;
              const submitted = reflectionRef.current;
              void run("reflect", signal => explorationApi.reflect(view, submitted, language, signal), value => {
                acceptView(value, reflectionRef.current === submitted); setNotice(t("理解记录已保存。"));
              });
            }}>
              <label id="reflection-label" htmlFor="exploration-reflection" className="text-lg font-semibold">{t("用自己的话，留下理解")}</label>
              <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{t("写下结论、适用条件，以及你还想追问的地方。")}</p>
              <textarea id="exploration-reflection" value={reflection} onChange={event => { reflectionRef.current = event.target.value; setReflection(event.target.value); }}
                maxLength={3000} rows={5} disabled={reflectionLocked} className={productClass("mt-input mt-3 h-auto min-h-[140px] resize-y py-3 text-base leading-7")} />
              <div className="mt-3 flex items-center gap-3"><button type="submit" disabled={mutationDisabled || !dirty} className={productClass("mt-btn min-h-11")}>{t("保存理解记录")}</button>
                <p className="text-sm text-[var(--muted-foreground)]" aria-live="polite">{t(dirty ? "尚未保存" : "已保存")}</p></div>
            </form>
          </section>
        </div>
        <LearningPanel view={view} busy={mutationDisabled} onRespond={answer => {
          if (view.learning.check) void run("respond", signal => explorationApi.respond(view, view.learning.check!.check_id, answer, language, signal), acceptView);
        }} onExplain={() => {
          if (view.learning.check) void run("explain", signal => explorationApi.explain(view, view.learning.check!.check_id, language, signal), acceptView);
        }} />
      </div>
    </>}
  </div>;
}

function InquiryHistory({ history, activeId, busy, onOpen, onRemove, compact = false }: {
  history: InquiryList | null; activeId: string | null; busy: boolean; onOpen: (id: string) => void; onRemove: (id: string) => void; compact?: boolean;
}) {
  const { t, locale } = useI18n();
  return <section aria-label={t("继续之前的探索")} className={compact ? "py-2" : "border-t border-[var(--border)] pt-5 lg:border-l lg:border-t-0 lg:pl-6 lg:pt-0"}>
    {!compact ? <h2 className="text-base font-semibold">{t("继续之前的探索")}</h2> : null}
    {history?.items.length ? <ul className={`mt-3 divide-y divide-[var(--border)] ${compact ? "max-h-72 overflow-y-auto" : ""}`}>{history.items.map(item =>
      <li key={item.inquiry_id} className="flex items-start gap-1 py-2">
        <button type="button" disabled={busy} aria-current={activeId === item.inquiry_id ? "true" : undefined} onClick={() => onOpen(item.inquiry_id)}
          className={`min-h-11 min-w-0 flex-1 rounded-lg px-2 py-2 text-left ${activeId === item.inquiry_id ? "bg-[var(--primary-soft)] text-[var(--primary-text)]" : "hover:bg-[var(--muted)]"}`}>
          <span className="block break-words text-sm font-medium leading-6">{item.question}</span>
          <time dateTime={item.updated_at} className="mt-1 block text-sm text-[var(--muted-foreground)]">{new Date(item.updated_at).toLocaleDateString(locale)}</time>
        </button>
        <button type="button" onClick={() => onRemove(item.inquiry_id)} disabled={busy} aria-label={t("删除探索：{question}", { question: item.question })}
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--destructive)]"><Trash2 className="h-4 w-4" aria-hidden="true" /></button>
      </li>)}</ul> : <p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">{t(history ? "探索过的问题和理解记录会保存在这里。" : "正在读取探索记录…")}</p>}
  </section>;
}
