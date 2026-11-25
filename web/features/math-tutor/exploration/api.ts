import { apiFetch } from "@/lib/api";
import type { components } from "../desktop/generated/api";

export type ExplorationView = components["schemas"]["ExplorationView"];
export type InquiryList = components["schemas"]["InquiryList"];
export type ExplorationConfiguration = components["schemas"]["ExplorationConfiguration"];
export type InquiryGoal = ExplorationView["goal"];
export type InquiryLanguage = "zh" | "en";
export type EvidenceCard = ExplorationView["evidence"]["cards"][number];
export type LibraryExcerpt = components["schemas"]["LibraryExcerpt"];
export type CheckPrompt = NonNullable<ExplorationView["learning"]["check"]>;

const root = "/api/v2/math-tutor/desktop/exploration";

export class ExplorationApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ExplorationApiError";
  }
}

async function request<T>(path: string, signal: AbortSignal, method = "GET", body?: unknown): Promise<T> {
  const response = await apiFetch(root + path, {
    method, signal, cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new ExplorationApiError(response.status,
      typeof data?.detail === "string" ? data.detail : "操作未完成，请刷新后重试。");
  }
  return response.json() as Promise<T>;
}

const inquiryPath = (id: string) => `/inquiries/${encodeURIComponent(id)}`;

export const explorationApi = {
  configuration: (signal: AbortSignal) => request<ExplorationConfiguration>("/configuration", signal),
  configure: (apiKey: string, signal: AbortSignal) => request<ExplorationConfiguration>("/configuration", signal, "PUT", { api_key: apiKey }),
  disconnect: (signal: AbortSignal) => request<ExplorationConfiguration>("/configuration", signal, "DELETE"),
  list: (signal: AbortSignal) => request<InquiryList>("/inquiries", signal),
  library: (question: string, signal: AbortSignal) => request<LibraryExcerpt[]>("/library", signal, "POST", { question }),
  create: (body: components["schemas"]["InquiryCreate"], signal: AbortSignal) => request<ExplorationView>("/inquiries", signal, "POST", body),
  read: (id: string, language: InquiryLanguage, signal: AbortSignal) => request<ExplorationView>(`${inquiryPath(id)}?language=${language}`, signal),
  organize: (view: ExplorationView, language: InquiryLanguage, signal: AbortSignal) =>
    request<ExplorationView>(`${inquiryPath(view.inquiry_id)}/organize`, signal, "POST", { revision: view.revision, language }),
  reflect: (view: ExplorationView, reflection: string, language: InquiryLanguage, signal: AbortSignal) =>
    request<ExplorationView>(`${inquiryPath(view.inquiry_id)}/reflection`, signal, "PUT", { revision: view.revision, language, reflection }),
  respond: (view: ExplorationView, checkId: string, answer: string, language: InquiryLanguage, signal: AbortSignal) =>
    request<ExplorationView>(`${inquiryPath(view.inquiry_id)}/response`, signal, "POST", { revision: view.revision, language, check_id: checkId, answer }),
  explain: (view: ExplorationView, checkId: string, language: InquiryLanguage, signal: AbortSignal) =>
    request<ExplorationView>(`${inquiryPath(view.inquiry_id)}/explanation`, signal, "POST", { revision: view.revision, language, check_id: checkId }),
  remove: (id: string, signal: AbortSignal) => request<InquiryList>(inquiryPath(id), signal, "DELETE"),
};
