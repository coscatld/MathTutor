"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { ArrowUpRight, BookOpen, Loader2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { components } from "../desktop/generated/api";

type View = components["schemas"]["RecommendationView"];
type Resource = components["schemas"]["RecommendationResource"];
type Context = { view: View | null; error: string; busy: boolean; refresh: () => void; configure: (enabled: boolean, goal: string) => Promise<void> };
const RecommendationsContext = createContext<Context | null>(null);
const root = "/api/v2/math-tutor/desktop/recommendations";

export function RecommendationsProvider({ children }: { children: ReactNode }) {
  const { locale, t } = useI18n();
  const language = locale === "en" ? "en" : "zh";
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const current = useRef<AbortController | null>(null);
  const identityPending = useRef(false);
  const paused = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clear = useCallback(() => {
    current.current?.abort();
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }, []);
  const request = useCallback(async (controller: AbortController, path: string, method = "GET", body?: unknown) => {
    const response = await apiFetch(`${root}${path}`, { method, signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)]), cache: "no-store",
      headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
    if (response.status === 429) throw new Error(t("请求过于频繁，请稍后重试。"));
    if (!response.ok) throw new Error(t("学习推荐暂时无法更新。"));
    const result = await response.json() as View;
    if (current.current === controller && !controller.signal.aborted) setView(result);
    return result;
  }, [t]);
  useEffect(() => {
    clear();
    if (identityPending.current || paused.current || document.hidden) return;
    const controller = new AbortController();
    current.current = controller;
    setBusy(false);
    setError("");
    const started = Date.now();
    const poll = async (first: boolean) => {
      try {
        const result = await request(controller, `${first ? "/start" : ""}?language=${language}`, first ? "POST" : "GET");
        if (!controller.signal.aborted && current.current === controller && result.status === "running" && Date.now() - started < 45000)
          timer.current = setTimeout(() => void poll(false), 1500);
      } catch (cause) {
        if (!controller.signal.aborted && current.current === controller) {
          const limited = cause instanceof Error && cause.message === t("请求过于频繁，请稍后重试。");
          setError(limited ? cause.message : t("学习推荐暂时无法更新。"));
        }
      }
    };
    void poll(true);
    return clear;
  }, [language, revision, request, clear, t]);
  useEffect(() => {
    const hide = () => { clear(); setView(null); };
    const refresh = () => { hide(); setRevision(value => value + 1); };
    const identityChanging = () => { identityPending.current = true; hide(); };
    const identityChanged = () => { identityPending.current = false; refresh(); };
    const blur = () => { paused.current = true; hide(); };
    const focus = () => { paused.current = false; refresh(); };
    const visibility = () => { if (document.hidden) hide(); else refresh(); };
    window.addEventListener("mathtutor-learning-evidence-changed", refresh);
    window.addEventListener("mathtutor-identity-changing", identityChanging);
    window.addEventListener("mathtutor-identity-changed", identityChanged);
    window.addEventListener("blur", blur);
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      window.removeEventListener("mathtutor-learning-evidence-changed", refresh);
      window.removeEventListener("mathtutor-identity-changing", identityChanging);
      window.removeEventListener("mathtutor-identity-changed", identityChanged);
      window.removeEventListener("blur", blur);
      window.removeEventListener("focus", focus);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [clear]);
  const configure = async (enabled: boolean, goal: string) => {
    clear();
    const controller = new AbortController(); current.current = controller;
    setBusy(true); setError("");
    try {
      await request(controller, "/configuration", "PUT", { enabled, goal, language });
      if (!controller.signal.aborted) setRevision(value => value + 1);
    } catch {
      if (!controller.signal.aborted) setError(t("学习推荐暂时无法更新。"));
    } finally { if (current.current === controller) setBusy(false); }
  };
  return <RecommendationsContext.Provider value={{ view, error, busy, configure, refresh: () => setRevision(value => value + 1) }}>{children}</RecommendationsContext.Provider>;
}

export function RecommendationSettings() {
  const context = useContext(RecommendationsContext);
  const { t } = useI18n();
  if (!context) return null;
  const { view, error, busy, configure, refresh } = context;
  return <section className="mt-8 max-w-2xl border-t border-[var(--border)] pt-6" aria-labelledby="discovery-settings-title">
    <h3 id="discovery-settings-title" className="text-lg font-semibold">{t("为下一步学习找资料")}</h3>
    <p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{t("根据已有作答选择学习起点。后台探索只发送公开知识主题，阅读资料不会改变掌握记录。")}</p>
    {view ? <div className="mt-4 space-y-4">
      <label className="block text-sm font-medium">{t("当前学习方向")}<select value={view.goal} disabled={busy} onChange={event => void configure(view.enabled, event.target.value)} className="mt-input mt-2 min-h-11 w-full">{view.goals.map(goal => <option key={goal.id} value={goal.id}>{goal.label}</option>)}</select></label>
      <label className="flex min-h-11 cursor-pointer items-center gap-3 text-sm leading-6"><input type="checkbox" checked={view.enabled} disabled={busy} onChange={event => void configure(event.target.checked, view.goal)} className="h-4 w-4 shrink-0 accent-[var(--primary)]" />{t("启动时在后台探索知乎资料")}</label>
      <p className="text-sm leading-6 text-[var(--muted-foreground)]">{t("已有推荐会复用缓存；关闭后停止新的检索。")}</p>
    </div> : <button type="button" onClick={refresh} className="mt-btn mt-4 min-h-11">{t("重新加载学习推荐")}</button>}
    {error ? <p role="status" className="mt-3 text-sm">{error}</p> : null}
  </section>;
}

function ResourceRow({ resource }: { resource: Resource }) {
  const { t, locale } = useI18n();
  const excerpt = typeof resource.provenance?.excerpt === "string" ? resource.provenance.excerpt : "";
  const time = resource.source_time ? new Date(resource.source_time) : null;
  return <li className="py-4 first:pt-0 last:pb-0">
    <a href={resource.url} target="_blank" rel="noopener noreferrer" className="group inline-flex min-h-11 items-center gap-2 font-medium leading-6 hover:text-[var(--primary)]"><span>{resource.title}</span><ArrowUpRight className="h-4 w-4 shrink-0" aria-hidden="true" /></a>
    <p className="mt-1 text-sm text-[var(--muted-foreground)]">{resource.author || t("作者未提供")} · {t(resource.review_status === "reviewed_excerpt" ? "已审片段" : "新发现 · 待阅读")}</p>
    <p className="mt-2 text-sm leading-7">{resource.summary}</p><p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{resource.selection_reason || resource.recommendation_reason}</p>
      <details className="mt-2 text-sm"><summary className="min-h-11 cursor-pointer py-3">{t("查看证据与审核范围")}</summary><p className="leading-6 text-[var(--muted-foreground)]">{t("以下为平台返回的可见摘要，不代表全文审核或作者逐字原文。")}</p>{time && !Number.isNaN(time.valueOf()) ? <p className="mt-2 leading-6">{t("平台记录时间（发布或更新）")}：{time.toLocaleDateString(locale)}</p> : <p className="mt-2">{t("来源时间未提供")}</p>}<p className="mt-3 whitespace-pre-wrap break-words leading-7">{excerpt}</p></details>
  </li>;
}

export function LearningRecommendations() {
  const context = useContext(RecommendationsContext);
  const { t } = useI18n();
  if (!context) return null;
  const { view, error, refresh } = context;
  const retry = error && <div role="status" className="mt-3 flex flex-wrap items-center gap-3 text-sm">
    <span>{error}</span>
    <button type="button" onClick={refresh} className="mt-btn min-h-11">{t("重新加载学习推荐")}</button>
  </div>;
  if (!view) return retry ? <section className="mt-10 border-t border-[var(--border)] pt-6" aria-label={t("下一步学习资料")}>
    <h2 className="text-base font-semibold">{t("下一步学习资料")}</h2>{retry}
  </section> : null;
  const resources = view.plan.resources.slice(0, 4);
  return <section className="mt-10 border-t border-[var(--border)] pt-6" aria-label={t("下一步学习资料")}>
    <div className="flex items-center gap-2"><BookOpen className="h-4 w-4 text-[var(--primary)]" aria-hidden="true" /><h2 className="text-base font-semibold">{t("下一步学习资料")}</h2>{view.status === "running" ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" aria-label={t("正在后台探索")} /> : null}</div>
    {retry}
    <p className="mt-3 text-base font-medium">{view.plan.title}</p><p className="mt-2 text-sm leading-7 text-[var(--muted-foreground)]">{view.plan.reason}</p>
    {resources.length ? <ul className="mt-4 divide-y divide-[var(--border)]">{resources.map(resource => <ResourceRow key={resource.resource_id} resource={resource} />)}</ul> : null}
    {view.discovery?.resources.length ? <div className="mt-6"><h3 className="text-sm font-semibold">{t("本次发现")}</h3><ul className="mt-4 divide-y divide-[var(--border)]">{view.discovery.resources.map(resource => <ResourceRow key={resource.resource_id} resource={resource} />)}</ul></div> : null}
    {view.updated_at ? <p className="mt-4 text-sm text-[var(--muted-foreground)]">{t("探索更新于")} <time dateTime={view.updated_at}>{new Date(view.updated_at).toLocaleString()}</time></p> : null}
    {["failed", "not_configured", "rate_limited"].includes(view.status) ? <p role="status" className="mt-4 text-sm leading-6">{t(view.status === "not_configured" ? "连接知乎后可发现更多资料。" : "本次探索未完成，已保留可用的学习资料。")}</p> : null}
    <div className="mt-4 flex flex-wrap gap-x-5">
      <Link href={{ pathname: "/math-tutor/explore", query: { topic: view.plan.target_label } }} className="inline-flex min-h-11 items-center gap-1 font-medium text-[var(--primary-text)]">{t("探索这个主题")}<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link>
      <Link href="/math-tutor/settings?section=sources" className="inline-flex min-h-11 items-center gap-1 text-sm text-[var(--primary-text)]">{t("调整学习方向与探索设置")}<ArrowUpRight className="h-4 w-4" aria-hidden="true" /></Link>
    </div>
  </section>;
}
