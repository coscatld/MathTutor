import { apiFetch, apiUrl } from "@/lib/api";

export type TrashedConversation = { conversation_id: string; title: string; trashed_at: string };

export async function conversationAction(id: string, action: "trash" | "restore" | "purge") {
  const encoded = encodeURIComponent(id);
  const path = action === "trash" ? `sessions/${encoded}` : `trash/${encoded}${action === "restore" ? "/restore" : ""}`;
  const response = await apiFetch(apiUrl(`/api/v2/math-tutor/${path}`), { method: action === "restore" ? "POST" : "DELETE" });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : "操作失败，请重试。");
  }
  window.dispatchEvent(new Event("mathtutor-conversations-changed"));
}

export async function fetchTrash(): Promise<TrashedConversation[]> {
  const response = await apiFetch(apiUrl("/api/v2/math-tutor/trash"));
  if (!response.ok) throw new Error("垃圾桶加载失败，请重试。");
  return response.json();
}
