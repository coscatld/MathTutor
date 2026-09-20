import { Suspense } from "react";
import KnowledgeWorkbench from "@/features/math-tutor/knowledge/KnowledgeWorkbench";

export default function KnowledgePage() {
  return <Suspense fallback={<p className="p-6" role="status">正在打开知识库…</p>}><KnowledgeWorkbench /></Suspense>;
}
