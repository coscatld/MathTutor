"use client";

import MarkdownRenderer from "@/components/common/MarkdownRenderer";
import { NotebookPen } from "lucide-react";
import { wrapLatexForDisplay } from "../lib/protocol";

interface ProblemCardProps {
  /** Verified problem LaTeX (extracted from the server's verification frame). */
  latex: string | null;
}

/**
 * The problem area — the visual anchor of the workspace. Renders the
 * server-verified problem with KaTeX, large and centered for readability.
 */
export default function ProblemCard({ latex }: ProblemCardProps) {
  return (
    <section
      className="mt-card p-4 sm:p-5"
      aria-label="当前题目"
    >
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-[var(--muted-foreground)]">
        <NotebookPen className="h-4 w-4 text-[var(--primary)]" aria-hidden="true" />
        题目
      </div>
      {latex ? (
        <div className="min-h-[64px] overflow-x-auto py-2 text-center font-serif text-xl leading-relaxed text-[var(--foreground)] sm:text-2xl">
          <MarkdownRenderer content={wrapLatexForDisplay(latex)} enableMath />
        </div>
      ) : (
        <div className="flex min-h-[64px] items-center justify-center py-2 text-sm text-[var(--muted-foreground)]">
          提交题目后，这里会显示本题。
        </div>
      )}
    </section>
  );
}
