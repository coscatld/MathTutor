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
      className="mt-card p-4 sm:p-5"
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
          className="mt-btn"
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
          className="mt-btn mt-btn-primary"
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
