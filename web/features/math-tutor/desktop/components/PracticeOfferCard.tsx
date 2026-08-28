"use client";

import { BookOpen, Clock3, Loader2, Medal } from "lucide-react";
import { difficultyLabel, offerExpiryLabel, offerStatusLabel } from "../lib/labels";
import type { PracticeOffer } from "../types";

const STATUS_STYLES: Record<string, string> = {
  ACTIVE: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-400",
  ACCEPTED: "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]",
  EXPIRED: "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]",
  REVOKED: "border-[var(--border)] bg-[var(--background)] text-[var(--muted-foreground)]",
};

/**
 * Public practice-offer card: only public labels (skills/concepts/difficulty/
 * expiry). Deliberately NO mastery, answer, verified-solution or attestation
 * material — those stay on the server.
 */
export default function PracticeOfferCard({
  offer,
  accepting,
  onStart,
}: {
  offer: PracticeOffer;
  accepting: boolean;
  onStart: () => void;
}) {
  const active = offer.status === "ACTIVE";
  const disabled = !active || accepting;
  const expiryText = active ? offerExpiryLabel(offer.expires_at) : "";

  return (
    <li
      className={`flex flex-col gap-3 rounded-2xl border bg-[var(--card)] p-4 shadow-sm transition-colors duration-200 ${
        active ? "border-[var(--border)]" : "border-[var(--border)] opacity-75"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${
              STATUS_STYLES[offer.status] ?? STATUS_STYLES.EXPIRED
            }`}
          >
            {offerStatusLabel(offer.status)}
          </span>
          {active && expiryText && (
            <span className="inline-flex items-center gap-1 text-xs text-[var(--muted-foreground)]">
              <Clock3 className="h-3.5 w-3.5" aria-hidden="true" />
              {expiryText}
            </span>
          )}
        </div>
        <span className="inline-flex items-center gap-1.5 text-sm font-medium text-[#1D4ED8] dark:text-blue-400">
          <Medal className="h-4 w-4" aria-hidden="true" />
          {difficultyLabel(offer.difficulty)}
        </span>
      </div>

      {(offer.skill_labels.length > 0 || offer.concept_labels.length > 0) && (
        <div className="flex flex-wrap gap-1.5">
          {offer.skill_labels.map((label) => (
            <span
              key={`s-${label}`}
              className="rounded-full bg-[#2563EB]/10 px-2.5 py-1 text-xs font-medium text-[#1D4ED8] dark:text-blue-400"
            >
              {label}
            </span>
          ))}
          {offer.concept_labels.map((label) => (
            <span
              key={`c-${label}`}
              className="rounded-full border border-[var(--border)] bg-[var(--background)] px-2.5 py-1 text-xs text-[var(--muted-foreground)]"
            >
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-3 border-t border-[var(--border)] pt-3">
        <p className="text-xs text-[var(--muted-foreground)]">
          {active ? "接受后即可进入针对性练习。" : "该邀请已失效。"}
        </p>
        <button
          type="button"
          onClick={onStart}
          disabled={disabled}
          className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl bg-[#2563EB] px-5 py-2 text-sm font-medium text-white transition-colors duration-200 hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {accepting ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <BookOpen className="h-4 w-4" aria-hidden="true" />
          )}
          {accepting ? "正在接受…" : "开始练习"}
        </button>
      </div>
    </li>
  );
}
