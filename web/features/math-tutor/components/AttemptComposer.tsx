"use client";

import { useState } from "react";
import { Loader2, Send } from "lucide-react";

interface AttemptComposerProps {
  disabled: boolean;
  busy: boolean;
  onSubmit: (answer: string) => void;
  /** Custom copy for the clarification mode (clarify_problem / clarify_attempt). */
  heading?: string;
  placeholder?: string;
  submitLabel?: string;
  helperText?: string;
}

/**
 * The answer area — enabled only while the server's allowed_next_inputs
 * contains submit_attempt (or a clarify_* input). INVARIANT 5: the page
 * renders this composer only in those server-granted situations.
 */
export default function AttemptComposer({
  disabled,
  busy,
  onSubmit,
  heading = "你的答案",
  placeholder = "写下你的答案，例如 x = 2（支持 LaTeX）",
  submitLabel = "提交答案",
  helperText = "卡住了也没关系——你可以先请求一个提示，或听听讲解、看看示例。",
}: AttemptComposerProps) {
  const [answer, setAnswer] = useState("");
  const canSubmit = answer.trim().length > 0 && !disabled && !busy;

  const submit = () => {
    const trimmed = answer.trim();
    if (!trimmed || !canSubmit) return;
    onSubmit(trimmed);
    setAnswer("");
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <section
      className="mt-card p-4"
      aria-label="作答区"
    >
      <label
        htmlFor="math-tutor-attempt-input"
        className="mb-1.5 block text-sm font-semibold text-[var(--foreground)]"
      >
        {heading}
      </label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <input
          id="math-tutor-attempt-input"
          type="text"
          value={answer}
          onChange={(event) => setAnswer(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled || busy}
          placeholder={placeholder}
          autoComplete="off"
          className="min-h-[44px] min-w-0 flex-1 rounded-xl border border-[var(--border)] bg-[var(--background)] px-3.5 py-2 text-[15px] text-[var(--foreground)] outline-none transition-colors duration-200 placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--ring)]/30 disabled:opacity-60"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="mt-btn mt-btn-primary shrink-0"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          {submitLabel}
        </button>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-[var(--muted-foreground)]">
        {helperText}
      </p>
    </section>
  );
}
