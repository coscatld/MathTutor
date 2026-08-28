"use client";

import { BookOpen, Inbox, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { fetchOffers } from "../lib/desktop-api";
import type { PracticeOffer } from "../types";
import { useOfferAccept } from "../hooks/useOfferAccept";
import PracticeOfferCard from "./PracticeOfferCard";

/**
 * 练习邀请 — the public offer list. Accepting rides the parent session's
 * state machine (server-driven), then jumps to the child cycle view.
 */
export default function OffersPanel({
  fetchOffersFn = fetchOffers,
}: {
  fetchOffersFn?: typeof fetchOffers;
}) {
  const [offers, setOffers] = useState<PracticeOffer[]>([]);
  const [loading, setLoading] = useState(true);
  const [acceptingOfferId, setAcceptingOfferId] = useState<string | null>(null);
  const { state: acceptState, error: acceptError, accept } = useOfferAccept();

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      setOffers(await fetchOffersFn());
    } finally {
      setLoading(false);
    }
  }, [fetchOffersFn]);

  useEffect(() => {
    refresh().catch(() => undefined);
  }, [refresh]);

  const handleStart = async (offer: PracticeOffer) => {
    setAcceptingOfferId(offer.offer_id);
    try {
      await accept(offer);
    } finally {
      setAcceptingOfferId(null);
    }
  };

  const activeOffers = offers.filter((o) => o.status === "ACTIVE");
  const inactiveOffers = offers.filter((o) => o.status !== "ACTIVE");

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-semibold text-[var(--foreground)]">
            <BookOpen className="h-5 w-5 text-[#2563EB]" aria-hidden="true" />
            练习邀请
          </h1>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            系统根据你的学习情况推荐针对性练习，邀请会在一段时间后过期。
          </p>
        </div>
        <button
          type="button"
          onClick={() => refresh().catch(() => undefined)}
          disabled={loading}
          className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl border border-[var(--border)] bg-[var(--card)] px-4 py-2 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <RefreshCw className="h-4 w-4" aria-hidden="true" />}
          刷新
        </button>
      </div>

      {acceptError && (
        <p role="status" className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-950/40 dark:text-red-400">
          {acceptError}
        </p>
      )}

      {loading ? (
        <p className="flex items-center gap-2 py-10 text-sm text-[var(--muted-foreground)]">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          正在加载邀请…
        </p>
      ) : offers.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)] px-6 py-12 text-center">
          <Inbox className="h-8 w-8 text-[var(--muted-foreground)]" aria-hidden="true" />
          <p className="text-sm font-medium text-[var(--foreground)]">暂时没有练习邀请</p>
          <p className="max-w-sm text-sm leading-relaxed text-[var(--muted-foreground)]">
            完成几道练习后，系统会根据你的学习情况生成针对性邀请。
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-5">
          {activeOffers.length > 0 && (
            <section aria-label="可接受的练习邀请">
              <ul className="flex flex-col gap-3">
                {activeOffers.map((offer) => (
                  <PracticeOfferCard
                    key={offer.offer_id}
                    offer={offer}
                    accepting={acceptingOfferId === offer.offer_id && (acceptState === "connecting" || acceptState === "accepting")}
                    onStart={() => handleStart(offer)}
                  />
                ))}
              </ul>
            </section>
          )}
          {inactiveOffers.length > 0 && (
            <section aria-label="已接受的邀请">
              <h2 className="mb-2 text-sm font-medium text-[var(--muted-foreground)]">已结束</h2>
              <ul className="flex flex-col gap-3">
                {inactiveOffers.map((offer) => (
                  <PracticeOfferCard
                    key={offer.offer_id}
                    offer={offer}
                    accepting={false}
                    onStart={() => undefined}
                  />
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
