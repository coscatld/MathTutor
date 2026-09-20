"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import { normalizeMath } from "./math-normalization";

export interface MarkdownRendererProps {
  content: string;
  className?: string;
  variant?: "default" | "compact" | "prose" | "trace";
  enableMath?: boolean;
  enableCode?: boolean;
  enableMermaid?: boolean;
  allowHtml?: boolean;
  trackSourceLines?: boolean;
}

/** Narrow standalone renderer for the MathTutor student surface. */
export default function MarkdownRenderer({ content, className = "", enableMath = true }: MarkdownRendererProps) {
  return (
    <div className={`markdown-message ${className}`}>
      <ReactMarkdown skipHtml components={{img: ({alt}) => <span>[图片未自动加载：{alt || "外部图片"}]</span>}} remarkPlugins={enableMath ? [remarkGfm, remarkMath] : [remarkGfm]} rehypePlugins={enableMath ? [[rehypeKatex, { strict: false, trust: false, throwOnError: false }]] : []}>{enableMath ? normalizeMath(content) : content}</ReactMarkdown>
    </div>
  );
}
