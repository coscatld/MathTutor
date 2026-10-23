/** Open the existing reference selector without changing the saved scope. */
export function referenceSelectionHref(conversationId?: string): string {
  const query = new URLSearchParams();
  if (conversationId) query.set("session", conversationId);
  query.set("panel", "documents");
  return `/math-tutor?${query}`;
}

/** Assign a draft conversation while retaining its requested panel or question. */
export function withTutorSession(search: {toString(): string}, sessionId: string): string {
  const query = new URLSearchParams(search.toString());
  query.set("session", sessionId);
  return `/math-tutor?${query}`;
}
