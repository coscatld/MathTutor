"use client";

import { useState } from "react";
import { Eye, Loader2, Send } from "lucide-react";
import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { wrapLatexForDisplay } from "../lib/protocol";

interface ProblemComposerProps {
  disabled: boolean;
  /** True while the server is processing a command. */
  busy: boolean;
  onSubmit: (text: string) => void;
}

/**
 * Where the student types a problem (plain text or LaTeX) and sends
 * submit_problem. Includes a live KaTeX preview toggle.
 */
export default function ProblemComposer({
  disabled,
  busy,
  onSubmit,
}: ProblemComposerProps) {
  const [text, setText] = useState("");
  const [showPreview, setShowPreview] = useState(false);

  const canSubmit = text.trim().length > 0 && !disabled && !busy;

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || !canSubmit) return;
    onSubmit(trimmed);
    setText("");
    setShowPreview(false);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing) {
      event.preventDefault();
      submit();
    }
  };

  return (
    <section
      className="rounded-2xl border border-[var(--border)] bg-[var(--card)] p-4 shadow-sm sm:p-5"
      aria-label="输入题目"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-[var(--foreground)]">
          输入你的题目
        </h2>
        <button
          type="button"
          onClick={() => setShowPreview((value) => !value)}
          aria-pressed={showPreview}
          className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg border border-[var(--border)] bg-[var(--card)] px-3 py-1.5 text-sm font-medium text-[var(--foreground)] transition-colors duration-200 hover:bg-[var(--muted)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
        >
          <Eye className="h-4 w-4" aria-hidden="true" />
          {showPreview ? "收起预览" : "预览"}
        </button>
      </div>

      <label htmlFor="math-tutor-problem-input" className="sr-only">
        题目内容
      </label>
      <textarea
        id="math-tutor-problem-input"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onKeyDown={handleKeyDown}
        rows={3}
        disabled={disabled || busy}
        placeholder="输入一道数学题，例如：2x + 3 = 7（支持 LaTeX，如 \\frac{1}{2}）"
        className="w-full resize-y rounded-xl border border-[var(--border)] bg-[var(--background)] px-3.5 py-2.5 text-[15px] leading-relaxed text-[var(--foreground)] outline-none transition-colors duration-200 placeholder:text-[var(--muted-foreground)] focus:border-[var(--primary)]/50 focus:ring-2 focus:ring-[var(--ring)]/30 disabled:opacity-60"
      />

      {showPreview && text.trim() && (
        <div className="mt-3 rounded-xl border border-dashed border-[var(--border)] bg-[var(--muted)]/40 px-3.5 py-2.5">
          <div className="mb-1 text-xs font-medium text-[var(--muted-foreground)]">
            预览
          </div>
          <div className="overflow-x-auto font-serif text-base text-[var(--foreground)]">
            <MarkdownRenderer content={wrapLatexForDisplay(text)} enableMath />
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs leading-relaxed text-[var(--muted-foreground)]">
          提交后，辅导老师会先检查题目，再引导你自己解出答案。
        </p>
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="inline-flex min-h-[44px] cursor-pointer items-center gap-2 rounded-xl bg-[var(--primary)] px-5 py-2 text-[15px] font-semibold text-white shadow-sm transition-all duration-200 hover:bg-[var(--primary-hover)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          ) : (
            <Send className="h-4 w-4" aria-hidden="true" />
          )}
          {busy ? "正在检查题目…" : "提交题目"}
        </button>
      </div>
    </section>
  );
}
