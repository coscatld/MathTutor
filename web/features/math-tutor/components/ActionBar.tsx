"use client";

import {
  BookOpen,
  BookOpenCheck,
  CheckCircle2,
  CornerUpLeft,
  Eye,
  Lightbulb,
  Loader2,
  Shapes,
  SquareX,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import {
  allowedInputsToButtons,
  type ActionButtonSpec,
  type ActionVariant,
} from "../lib/protocol";
import type { ActiveOffer, AllowedAction, MathTutorCommand } from "../types";
import { isAcceptableOffer, offerPurposeLabel } from "../lib/teaching-contract";

const COMMAND_ICONS: Partial<Record<MathTutorCommand, LucideIcon>> = {
  request_hint: Lightbulb,
  request_explanation: BookOpen,
  request_example: Shapes,
  request_solution: Eye,
  request_practice: BookOpenCheck,
  request_foundation: BookOpen,
  request_review: BookOpenCheck,
  resume_problem: CornerUpLeft,
  end_problem: SquareX,
  accept_practice_offer: CheckCircle2,
  decline_practice_offer: XCircle,
  cancel_turn: SquareX,
};

const VARIANT_CLASSES: Record<ActionVariant, string> = {
  primary:
    "bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] border-transparent shadow-sm",
  secondary:
    "border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] hover:bg-[var(--muted)]",
  solution:
    "bg-[#BE123C] text-white hover:bg-[#9F1239] border-transparent shadow-sm",
  quiet:
    "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]",
  offer:
    "bg-[var(--primary)] text-white hover:bg-[var(--primary-hover)] border-transparent shadow-sm",
};

interface ActionBarProps {
  actions?: AllowedAction[];
  offer?: ActiveOffer | null;
  allowed: string[];
  busy: boolean;
  disabled: boolean;
  onCommand: (command: MathTutorCommand, payload?: Record<string, string>) => void;
}

/**
 * Server capabilities own availability and disabled reasons. Legacy servers
 * can still supply allowed_next_inputs; the UI never grants missing actions.
 */
export default function ActionBar({ allowed, actions, offer, busy, disabled, onCommand }: ActionBarProps) {
  const buttons = allowedInputsToButtons(actions ? actions.map(a => a.command) : allowed);
  const reasons = new Map(actions?.filter(a => !a.enabled && a.description).map(a => [a.reason_code, a.description]));
  const validOffer = isAcceptableOffer(offer);
  if (!validOffer && buttons.some(spec => ["accept_practice_offer", "decline_practice_offer"].includes(spec.command))) reasons.set("NO_ACTIVE_OFFER", "当前没有可接受的有效练习，可以重新请求一道。");

  if (buttons.length === 0) {
    return null;
  }

  return (
    <section
      className="mt-card p-4"
      aria-label="可用操作"
    >
      <h2 className="mb-2.5 text-sm font-semibold text-[var(--foreground)]">可用操作</h2>
      {validOffer ? <div className="mb-3 rounded-xl bg-[var(--primary-soft)] p-3"><p className="text-xs font-medium text-[var(--primary-text)]">{offerPurposeLabel(offer.purpose)}</p>{offer.title ? <p className="mt-1 text-xs leading-5 text-[var(--muted-foreground)]">{offer.title}</p> : null}</div> : null}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-1 lg:grid-cols-2">
        {buttons.map((spec: ActionButtonSpec) => {
          const Icon = COMMAND_ICONS[spec.command] ?? Lightbulb;
          const capability = actions?.find(a => a.command === spec.command);
          const needsOffer = ["accept_practice_offer", "decline_practice_offer"].includes(spec.command);
          const blocked = disabled || busy || (actions !== undefined && capability?.enabled !== true) || (needsOffer && !validOffer);
          const reason = needsOffer && !validOffer ? "NO_ACTIVE_OFFER" : capability && !capability.enabled ? capability.reason_code : undefined;
          return (
            <button
              key={spec.command}
              type="button"
              onClick={() => onCommand(spec.command, needsOffer && validOffer ? { offer_id: offer.offer_id } : undefined)}
              disabled={blocked}
              aria-describedby={reason ? `action-reason-${reason}` : undefined}
              className={`inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition-all duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_CLASSES[spec.variant]}`}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Icon className="h-4 w-4" aria-hidden="true" />
              )}
              {capability?.label || spec.label}
            </button>
          );
        })}
      </div>
      {[...reasons].map(([code, description]) => <p key={code} id={`action-reason-${code}`} className="mt-3 text-xs leading-5 text-[var(--muted-foreground)]">{description}</p>)}
    </section>
  );
}
