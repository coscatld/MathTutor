"use client";

import {BookOpen, RefreshCw} from "lucide-react";
import {useCallback, useEffect, useState} from "react";
import {fetchOffers, sendOfferFeedback} from "../lib/desktop-api";
import type {PracticeOffer} from "../types";
import {useOfferAccept} from "../hooks/useOfferAccept";
import PracticeOfferCard from "./PracticeOfferCard";

export function groupOffers(offers: PracticeOffer[]) {
  const sorted = [...offers].sort((a,b) => b.offered_at.localeCompare(a.offered_at) || a.offer_id.localeCompare(b.offer_id));
  return {
    inProgress: sorted.filter(o => o.display_status === "in_progress" && o.resume_session_id),
    pending: sorted.filter(o => o.display_status === "pending" || (!o.display_status && o.status === "ACTIVE")),
    later: sorted.filter(o => o.display_status === "later"),
    completed: sorted.filter(o => o.display_status === "completed"),
    history: sorted.filter(o => o.display_status === "history" || (!o.display_status && o.status !== "ACTIVE")),
  };
}

export default function OffersPanel({fetchOffersFn = fetchOffers}: {fetchOffersFn?: typeof fetchOffers}) {
  const [offers, setOffers] = useState<PracticeOffer[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const {error: acceptError, accept} = useOfferAccept();
  const refresh = useCallback(async () => {
    setLoading(true); setError("");
    try {setOffers(await fetchOffersFn());} catch {setError("推荐暂时无法加载，请重试。");}
    finally {setLoading(false);}
  }, [fetchOffersFn]);
  useEffect(() => {void refresh();}, [refresh]);
  const start = async (offer: PracticeOffer) => {
    setBusy(offer.offer_id);
    try {await accept(offer);} finally {setBusy(null);}
  };
  const feedback = async (offer: PracticeOffer, kind: "later" | "not_relevant") => {
    setBusy(offer.offer_id); setError("");
    try {await sendOfferFeedback(offer.offer_id, kind); await refresh();}
    catch {setError("反馈暂时无法保存，请重试。");} finally {setBusy(null);}
  };
  const groups = groupOffers(offers);
  const card = (offer: PracticeOffer) => <PracticeOfferCard key={offer.offer_id} offer={offer}
    accepting={busy === offer.offer_id} disabled={busy !== null}
    onStart={() => void start(offer)} onFeedback={kind => void feedback(offer, kind)} />;
  return <div className="mt-page">
    <header className="flex items-start justify-between gap-4"><div><p className="mt-eyebrow">让每次练习都有来由</p><h1 className="mt-2">推荐练习</h1><p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">继续已经开始的题目，再决定下一步。稍后再做不会影响学习判断。</p></div><button aria-label="刷新推荐练习" disabled={loading} onClick={() => void refresh()} className="mt-btn mt-btn-icon shrink-0"><RefreshCw className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`} aria-hidden="true" /></button></header>
    {(error || acceptError) && <p role="alert" className="rounded-xl bg-[var(--muted)] p-4">{error || acceptError}</p>}
    {loading && !offers.length ? <p role="status" className="py-10">正在加载推荐…</p> : <>
      {!!groups.inProgress.length && <section aria-label="进行中的练习"><h2 className="mt-section-title mb-3">先继续这道题</h2><ul className="space-y-4">{groups.inProgress.map(card)}</ul></section>}
      {!!groups.pending.length && <section aria-label="待开始的推荐"><h2 className="mt-section-title mb-3">{groups.inProgress.length ? "接下来可选" : "建议的下一步"}</h2><ul className="space-y-4">{groups.pending.slice(0,1).map(card)}</ul>{groups.pending.length > 1 && <details className="mt-4"><summary className="cursor-pointer py-2 text-sm text-[var(--muted-foreground)]">其他选择</summary><ul className="mt-3 space-y-3">{groups.pending.slice(1,3).map(card)}</ul></details>}</section>}
      {!offers.length && !error && <section className="mt-card mt-paper border-dashed p-8"><BookOpen className="mb-3 h-6 w-6 text-[var(--primary-text)]" aria-hidden="true"/><h2 className="text-xl font-semibold tracking-tight">暂时没有推荐练习</h2><p className="mt-3 text-sm leading-7 text-[var(--muted-foreground)]">先完成当前题目。获得可核验的作答后，系统会在合适时机给出下一步建议。</p><a href="/math-tutor" className="mt-4 inline-flex min-h-11 items-center text-sm text-[var(--primary)]">回到辅导</a></section>}
      {!!groups.later.length && <section aria-label="稍后再做"><h2 className="mt-section-title mb-3">稍后再做</h2><ul className="space-y-3">{groups.later.map(card)}</ul></section>}
      {!!groups.completed.length && <section aria-label="已完成的练习"><h2 className="mt-section-title mb-3">完成后观察到了什么</h2><ul className="space-y-3">{groups.completed.map(card)}</ul></section>}
      {!!groups.history.length && <details><summary className="cursor-pointer py-2 text-sm text-[var(--muted-foreground)]">历史建议 · {groups.history.length}</summary><ul className="mt-3 space-y-3">{groups.history.map(card)}</ul></details>}
    </>}
  </div>;
}
