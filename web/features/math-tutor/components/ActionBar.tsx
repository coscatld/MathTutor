"use client";

import {
  BookOpen,
  CheckCircle2,
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
import type { MathTutorCommand } from "../types";

const COMMAND_ICONS: Partial<Record<MathTutorCommand, LucideIcon>> = {
  request_hint: Lightbulb,
  request_explanation: BookOpen,
  request_example: Shapes,
  solution_shown_permitted: Eye,
  request_solution: Eye,
  accept_practice_offer: CheckCircle2,
  decline_practice_offer: XCircle,
  cancel_turn: SquareX,
};

const VARIANT_CLASSES: Record<ActionVariant, string> = {
  primary:
    "bg-[#1D4ED8] text-white hover:bg-[#1E40AF] border-transparent shadow-sm",
  secondary:
    "border-[var(--border)] bg-[var(--secondary)] text-[var(--foreground)] hover:bg-[var(--muted)]",
  solution:
    "bg-[#BE123C] text-white hover:bg-[#9F1239] border-transparent shadow-sm",
  quiet:
    "border-[var(--border)] bg-[var(--card)] text-[var(--muted-foreground)] hover:bg-[var(--muted)]",
  offer:
    "bg-[#1D4ED8] text-white hover:bg-[#1E40AF] border-transparent shadow-sm",
};

interface ActionBarProps {
  allowed: string[];
  busy: boolean;
  disabled: boolean;
  onCommand: (command: MathTutorCommand) => void;
}

/**
 * The action area. EVERY button here comes from the server's
 * allowed_next_inputs — a command the server never sent has no button.
 * "查看完整答案" therefore only renders when the server grants it.
 */
export default function ActionBar({ allowed, busy, disabled, onCommand }: ActionBarProps) {
  const buttons = allowedInputsToButtons(allowed);

  if (buttons.length === 0) {
    return (
      <section
        className="rounded-2xl border border-dashed border-[var(--border)] bg-[var(--card)] p-4"
        aria-label="可用操作"
      >
        <h2 className="mb-1 text-sm font-semibold text-[var(--foreground)]">可用操作</h2>
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          当前没有可用的操作。提交题目或答案后，这里会出现可以选择的帮助。
        </p>
      </section>
    );
  }

  return (
    <section
      className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm"
      aria-label="可用操作"
    >
      <h2 className="mb-2.5 text-sm font-semibold text-[var(--foreground)]">可用操作</h2>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-1 lg:grid-cols-2">
        {buttons.map((spec: ActionButtonSpec) => {
          const Icon = COMMAND_ICONS[spec.command] ?? Lightbulb;
          const blocked = disabled || busy;
          return (
            <button
              key={spec.command}
              type="button"
              onClick={() => onCommand(spec.command)}
              disabled={blocked}
              className={`inline-flex min-h-[44px] cursor-pointer items-center justify-center gap-2 rounded-xl border px-3 py-2 text-sm font-medium transition-all duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50 ${VARIANT_CLASSES[spec.variant]}`}
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <Icon className="h-4 w-4" aria-hidden="true" />
              )}
              {spec.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}
