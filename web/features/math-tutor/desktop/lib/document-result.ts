import type { DesktopDocument } from "../types";
import {translate, type MessageParams} from "@/lib/i18n/messages";

type Translator = (message: string, params?: MessageParams) => string;
const chinese: Translator = (message, params) => translate("zh-CN", message, params);

export function documentScopeLabel(doc: DesktopDocument, t: Translator = chinese): string {
  return doc.is_global ? t("共享范围：所有对话") : doc.conversation_ids?.length
    ? t("仅关联的 {count} 个对话可使用", {count: doc.conversation_ids.length}) : t("未归类，不跨对话检索");
}

/** HTTP success means persisted; parse status and retrieval permission are separate. */
export function documentResult(doc: DesktopDocument, t: Translator = chinese): { title: string; description: string; tone: "success" | "info" | "error" } {
  const ready = ["ready", "ready_with_warnings"].includes(doc.status);
  const retrievable = ready && doc.retrieval_enabled && doc.chunk_count > 0;
  let detail: string;
  if (doc.status === "needs_ocr") detail = t("未提取到文字，当前不可检索。可更换带文字层的文件或检查解析条件后重新解析。");
  else if (doc.status === "failed") detail = t("解析失败，当前不可检索。可检查文件后重新解析或删除。");
  else if (!ready) detail = t("解析尚未完成，当前不可检索。");
  else if (!retrievable) detail = doc.chunk_count > 0 ? t("检索已停用。") : t("没有可检索的文字分块。");
  else detail = doc.is_global || doc.conversation_ids?.length ? t("可在所选范围内检索。") : t("已解析；关联对话或设为总资料后可检索。");
  if (doc.status === "ready_with_warnings") detail += t(" 部分内容可能未提取：{warning}", {warning: doc.parse_warning || t("请检查缺页或空白页。")});
  return {
    title: doc.status === "failed" ? t("资料已保存，解析失败") : doc.status === "needs_ocr" ? t("资料已保存，未提取到文字") : t("资料已保存"),
    description: t("《{filename}》{detail} {scope}。", {filename: doc.filename, detail, scope: documentScopeLabel(doc, t)}),
    tone: doc.status === "failed" ? "error" : retrievable && doc.status === "ready" ? "success" : "info",
  };
}
