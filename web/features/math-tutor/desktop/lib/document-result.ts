import type { DesktopDocument } from "../types";

export function documentScopeLabel(doc: DesktopDocument): string {
  return doc.is_global ? "共享范围：所有对话" : doc.conversation_ids?.length
    ? `仅关联的 ${doc.conversation_ids.length} 个对话可使用` : "未归类，不跨对话检索";
}

/** HTTP success means persisted; parse status and retrieval permission are separate. */
export function documentResult(doc: DesktopDocument): { title: string; description: string; tone: "success" | "info" | "error" } {
  const ready = ["ready", "ready_with_warnings"].includes(doc.status);
  const retrievable = ready && doc.retrieval_enabled && doc.chunk_count > 0;
  let detail: string;
  if (doc.status === "needs_ocr") detail = "未提取到文字，当前不可检索。可更换带文字层的文件或检查解析条件后重新解析。";
  else if (doc.status === "failed") detail = "解析失败，当前不可检索。可检查文件后重新解析或删除。";
  else if (!ready) detail = "解析尚未完成，当前不可检索。";
  else if (!retrievable) detail = doc.chunk_count > 0 ? "检索已停用。" : "没有可检索的文字分块。";
  else detail = doc.is_global || doc.conversation_ids?.length ? "可在所选范围内检索。" : "已解析；关联对话或设为总资料后可检索。";
  if (doc.status === "ready_with_warnings") detail += ` 部分内容可能未提取：${doc.parse_warning || "请检查缺页或空白页。"}`;
  return {
    title: doc.status === "failed" ? "资料已保存，解析失败" : doc.status === "needs_ocr" ? "资料已保存，未提取到文字" : "资料已保存",
    description: `《${doc.filename}》${detail} ${documentScopeLabel(doc)}。`,
    tone: doc.status === "failed" ? "error" : retrievable && doc.status === "ready" ? "success" : "info",
  };
}
