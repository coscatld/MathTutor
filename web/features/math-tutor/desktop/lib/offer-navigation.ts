/**
 * Practice-offer accept → child-cycle navigation helpers (pure, unit-tested).
 *
 * The accept command rides the parent session's WS; the public event frame
 * carries ``extra.child_cycle_id``. This module extracts ONLY that whitelisted
 * public key, resolves the child SESSION id from the read API, and builds the
 * navigation target. No internal cycle data is ever read.
 */

/**
 * Extract the child cycle id from a raw WS frame.
 *
 * Only the whitelisted public key ``extra.child_cycle_id`` is read; any
 * other field is structurally ignored.
 */
export function extractChildCycleId(rawFrame: unknown): string | null {
  if (typeof rawFrame !== "object" || rawFrame === null) return null;
  const frame = rawFrame as Record<string, unknown>;
  const eventType = String(frame.event_type ?? "");
  // Accept flows surface on the state-committed / turn-end frames.
  if (eventType !== "cycle_state_committed" && eventType !== "turn_end") {
    return null;
  }
  const extra = frame.extra;
  if (typeof extra !== "object" || extra === null) return null;
  const childCycleId = (extra as Record<string, unknown>).child_cycle_id;
  if (typeof childCycleId !== "string" || !childCycleId) return null;
  return childCycleId;
}

/**
 * Resolve the child cycle's session id via
 * GET /api/v2/math-tutor/cycles/{cycle_id} (read endpoint, owner-scoped).
 *
 * ``fetcher`` is injectable for tests; the default uses apiFetch.
 */
export async function resolveChildSessionId(
  childCycleId: string,
  fetcher: (path: string) => Promise<Response> = defaultFetcher,
): Promise<string | null> {
  if (!childCycleId) return null;
  try {
    const res = await fetcher(
      `/api/v2/math-tutor/cycles/${encodeURIComponent(childCycleId)}`,
    );
    if (!res.ok) return null;
    const body = (await res.json()) as { session_id?: unknown };
    if (typeof body.session_id !== "string" || !body.session_id) return null;
    return body.session_id;
  } catch {
    return null;
  }
}

async function defaultFetcher(path: string): Promise<Response> {
  const { apiFetch } = await import("@/lib/api");
  return apiFetch(path);
}

/** Build the workspace URL that opens a specific session. */
export function buildChildNavigationPath(sessionId: string): string {
  return `/math-tutor?session=${encodeURIComponent(sessionId)}`;
}
