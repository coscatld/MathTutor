/**
 * MathTutor student WS session hook.
 *
 * Owns the `/api/v2/math-tutor/ws` connection lifecycle:
 *  - auth rides the same-origin dt_token cookie (same flow as the rest of
 *    the app; the backend WS auth also accepts a `?token=` query param).
 *  - auto-reconnect with capped exponential backoff;
 *  - after every (re)connect the client resyncs from the backend's
 *    owner-scoped GET /api/v2/math-tutor/sessions/{session_id} (cycle state,
 *    version, allowed inputs) — the server stays the only authority on what
 *    the UI may do. Unacknowledged requests retain their identity across a
 *    reconnect; the backend replays their durable result without new effects.
 *  - a 401 on recovery means the credentials are gone: status flips to
 *    "error" with a human hint (no auto-redirect loop).
 *
 * This hook is scoped exclusively to the MathTutor product WebSocket.
 */

import { useCallback, useEffect, useReducer, useRef } from "react";
import { apiFetch, apiUrl, wsUrl } from "@/lib/api";
import type { ConnectionStatus, MathTutorCommand, SessionSummary } from "../types";
import { buildEnvelope, makeSessionId, projectStudentFrame } from "../lib/protocol";
import {
  initialMathTutorState,
  mathTutorReducer,
} from "../lib/reducer";
import { presentationAcknowledgement, presentationFromFrame, type PendingPresentation } from "../lib/delivery";
import { ImageUploadRepository, type ChatAttachment, type MessageAttachment } from "../lib/attachments";

const WS_PATH = "/api/v2/math-tutor/ws";
const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 8000;
/** After this many consecutive failures the status settles on "disconnected". */
const RECONNECT_ATTEMPTS_BEFORE_GIVING_UP = 5;

const STATUS_NOTES: Record<ConnectionStatus, string> = {
  connecting: "正在连接辅导服务…",
  connected: "已连接",
  reconnecting: "连接中断，正在重连…",
  disconnected: "连接已断开",
  error: "无法连接辅导服务",
};

export function useMathTutorSession(explicitSessionId?: string) {
  // Child-cycle navigation support: an explicit ?session= query param opens
  // that server session instead of a fresh one (used by practice-offer
  // accepts to jump straight into the child cycle view).
  const initialSessionId =
    typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("session")
      : null;
  const sessionIdRef = useRef<string>(
    explicitSessionId?.trim() || (initialSessionId && initialSessionId.trim() ? initialSessionId.trim() : makeSessionId()),
  );
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const manuallyClosedRef = useRef(false);
  const resyncInFlightRef = useRef(false);
  const sendInFlightRef = useRef(false);
  const requestGenerationRef = useRef(0);
  const unacknowledgedRef = useRef<{ id: string; envelope: string } | null>(null);
  const presentationsRef = useRef(new Map<string, PendingPresentation>());
  const completionRef = useRef<{ id: string; resolve: (success: boolean) => void } | null>(null);
  const imageUploads = useRef(new ImageUploadRepository());
  const imageRetry = useRef<{ fingerprint: string; id: string } | null>(null);

  const [state, dispatch] = useReducer(
    mathTutorReducer,
    sessionIdRef.current,
    initialMathTutorState,
  );

  const stateRef = useRef(state);
  stateRef.current = state;

  // This effect runs after React has committed the result. It records screen
  // presentation only, never reading, understanding, or independent learning.
  const acknowledgePresentations = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    for (const [id, pending] of presentationsRef.current) {
      const wire = presentationAcknowledgement(pending, stateRef.current.messages, document.visibilityState === "visible");
      if (!wire) continue;
      try { ws.send(wire); presentationsRef.current.delete(id); } catch { break; }
    }
  }, []);
  useEffect(() => { acknowledgePresentations(); }, [state.messages, acknowledgePresentations]);
  useEffect(() => {
    document.addEventListener("visibilitychange", acknowledgePresentations);
    return () => document.removeEventListener("visibilitychange", acknowledgePresentations);
  }, [acknowledgePresentations]);

  // Late-bound refs so connect() and scheduleReconnect() can call each other
  // without a useCallback dependency cycle.
  const connectRef = useRef<() => void>(() => {});
  const scheduleReconnectRef = useRef<() => void>(() => {});

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  /** Fetch the server's authoritative cycle state for the current session. */
  const resync = useCallback(async (): Promise<boolean> => {
    if (resyncInFlightRef.current) return false;
    resyncInFlightRef.current = true;
    const requestedSession = sessionIdRef.current;
    const requestedGeneration = requestGenerationRef.current;
    try {
      const res = await apiFetch(
        apiUrl(`/api/v2/math-tutor/sessions/${encodeURIComponent(requestedSession)}`),
        { skipAuthRedirect: true },
      );
      if (requestedSession !== sessionIdRef.current || requestedGeneration !== requestGenerationRef.current || sendInFlightRef.current) return false;
      if (res.status === 401) {
        dispatch({
          type: "connection",
          status: "error",
          note: "登录已失效，请重新登录后再试。",
        });
        return false;
      }
      if (res.status === 404) {
        // Never created on the server — this session id is fresh.
        dispatch({
          type: "restore",
          summary: { state: "", state_version: 0, allowed_next_inputs: [] },
        });
        return true;
      }
      if (!res.ok) {
        dispatch({
          type: "connection",
          status: "error",
          note: "无法读取辅导进度。",
        });
        return false;
      }
      const summary = (await res.json()) as SessionSummary;
      if (requestedSession !== sessionIdRef.current || requestedGeneration !== requestGenerationRef.current || sendInFlightRef.current) return false;
      dispatch({ type: "restore", summary });
      return true;
    } catch {
      dispatch({
        type: "connection",
        status: "error",
        note: "无法连接辅导服务，请检查网络。",
      });
      return false;
    } finally {
      resyncInFlightRef.current = false;
    }
  }, []);

  const scheduleReconnect = useCallback(() => {
    clearReconnectTimer();
    if (manuallyClosedRef.current) return;
    if (attemptRef.current >= RECONNECT_ATTEMPTS_BEFORE_GIVING_UP) {
      dispatch({
        type: "connection",
        status: "disconnected",
        note: "连接已断开，点击按钮重新连接。",
      });
      return;
    }
    dispatch({ type: "connection", status: "reconnecting", note: STATUS_NOTES.reconnecting });
    const delay = Math.min(
      RECONNECT_MAX_DELAY_MS,
      RECONNECT_BASE_DELAY_MS * Math.pow(2, attemptRef.current),
    );
    attemptRef.current += 1;
    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      connectRef.current();
    }, delay);
  }, [clearReconnectTimer]);
  scheduleReconnectRef.current = scheduleReconnect;

  const connect = useCallback(() => {
    clearReconnectTimer();
    if (wsRef.current && wsRef.current.readyState <= WebSocket.OPEN) {
      return;
    }
    dispatch({ type: "connection", status: "connecting", note: STATUS_NOTES.connecting });

    let ws: WebSocket;
    try {
      ws = new WebSocket(wsUrl(WS_PATH));
    } catch {
      scheduleReconnectRef.current();
      return;
    }
    wsRef.current = ws;

    ws.onopen = async () => {
      attemptRef.current = 0;
      dispatch({ type: "connection", status: "connected", note: STATUS_NOTES.connected });
      const pending = unacknowledgedRef.current;
      const restored = await resync();
      if (restored && pending && pending === unacknowledgedRef.current && !sendInFlightRef.current && wsRef.current === ws && ws.readyState === WebSocket.OPEN) {
        sendInFlightRef.current = true;
        ws.send(pending.envelope);
      }
    };

    ws.onmessage = (event: MessageEvent<string>) => {
      let raw: unknown;
      try {
        raw = JSON.parse(String(event.data));
      } catch {
        return; // ignore malformed frames — the server contract is JSON
      }
      const frame = projectStudentFrame(raw as never);
      if (!frame || (frame.payload.conversation_id && frame.payload.conversation_id !== sessionIdRef.current)) return;
      const presentation = presentationFromFrame(frame);
      if (presentation) presentationsRef.current.set(presentation.deliveryId, presentation);
      dispatch({ type: "frame", frame });
      const completion = completionRef.current;
      if (completion && ["assistant_complete", "assistant_partial", "assistant_error"].includes(frame.event_type) && frame.payload.turn_id === completion.id) {
        completion.resolve(frame.event_type === "assistant_complete");
        if (frame.event_type === "assistant_complete") imageRetry.current = null;
        completionRef.current = null;
      }
      if (["assistant_complete", "assistant_partial", "assistant_error"].includes(frame.event_type)
        && frame.payload.turn_id === unacknowledgedRef.current?.id) {
        unacknowledgedRef.current = null;
      }
      if (frame.event_type === "turn_end") {
        sendInFlightRef.current = false;
        window.dispatchEvent(new Event("mathtutor-conversations-changed"));
        void resync();
      }
    };

    ws.onclose = () => {
      completionRef.current?.resolve(false); completionRef.current = null;
      sendInFlightRef.current = false;
      if (wsRef.current === ws) wsRef.current = null;
      scheduleReconnectRef.current();
    };

    ws.onerror = () => {
      // onclose follows; the reconnect path owns the status transition.
    };
  }, [clearReconnectTimer, resync]);
  connectRef.current = connect;

  /** Send a command envelope over the WS (only when connected). */
  const send = useCallback(
    (command: MathTutorCommand, payload: Record<string, string | string[]> = {}, onComplete?: (success: boolean) => void, attachments: MessageAttachment[] = []): boolean => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        dispatch({
          type: "connection",
          status: "disconnected",
          note: "连接已断开，请先重新连接。",
        });
        return false;
      }
      if (sendInFlightRef.current && command !== "cancel_turn") {
        return false;
      }
      sendInFlightRef.current = true;
      requestGenerationRef.current += 1;
      const fingerprint = JSON.stringify(payload);
      const requestId = attachments.length && imageRetry.current?.fingerprint === fingerprint ? imageRetry.current.id : makeSessionId();
      if (attachments.length) imageRetry.current = { fingerprint, id: requestId };
      const envelope = buildEnvelope(command, payload, sessionIdRef.current, {
        requestId,
        idempotencyKey: requestId,
        // Optimistic concurrency: the server rejects commands that race ahead
        // of the version the client has seen.
        expectedCycleVersion: stateRef.current.seenVersion,
        cycleId: stateRef.current.cycleId || undefined,
        problemRevision: stateRef.current.cycleId ? stateRef.current.problemRevision : undefined,
      });
      try {
        if (onComplete) completionRef.current = { id: requestId, resolve: onComplete };
        ws.send(envelope);
        if (command !== "cancel_turn") unacknowledgedRef.current = { id: requestId, envelope };
      } catch {
        completionRef.current = null;
        sendInFlightRef.current = false;
        return false;
      }
      const visibleText = payload.text || payload.answer || ({ request_hint: "给我一点提示", request_explanation: "讲解这个知识点", request_example: "给我一个类似例子", request_solution: "查看完整答案", request_practice: "我想独立练一道", resume_problem: "回到刚才那道题", end_problem: "结束本题", start_diagnostic: "先了解一下我的基础", skip_diagnostic: "跳过诊断，继续辅导", accept_practice_offer: "接受这道练习", decline_practice_offer: "暂不练习，保留当前题目" } as Record<string, string>)[command];
      dispatch({ type: "command_sent", command, text: typeof visibleText === "string" ? visibleText : typeof payload.choice_id === "string" ? `选择 ${payload.choice_id}` : "", attachments });
      return true;
    },
    [],
  );

  const sendMessage = useCallback(async (text: string, attachments: ChatAttachment[]) => {
    const saved = await imageUploads.current.upload(attachments);
    return new Promise<boolean>(resolve => {
      if (!send("send_message", { text, ...(saved.length ? { attachment_ids: saved.map(a => a.id) } : {}) }, resolve, saved)) resolve(false);
    });
  }, [send]);

  /** Start a brand-new tutoring problem (fresh client session id). */
  const newProblem = useCallback(() => {
    sessionIdRef.current = makeSessionId();
    requestGenerationRef.current += 1;
    sendInFlightRef.current = false;
    unacknowledgedRef.current = null;
    presentationsRef.current.clear();
    dispatch({ type: "new_session", sessionId: sessionIdRef.current });
    void resync();
  }, [resync]);

  /** Manual reconnect (used by the ConnectionStatus retry button). */
  const reconnect = useCallback(() => {
    attemptRef.current = 0;
    connectRef.current();
  }, []);

  const recover = useCallback(() => {
    if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) reconnect();
    else void resync();
  }, [reconnect, resync]);

  useEffect(() => {
    manuallyClosedRef.current = false;
    connectRef.current();
    return () => {
      completionRef.current?.resolve(false); completionRef.current = null;
      manuallyClosedRef.current = true;
      clearReconnectTimer();
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [clearReconnectTimer]);

  return {
    state,
    sessionId: sessionIdRef.current,
    send,
    sendMessage,
    newProblem,
    reconnect,
    recover,
  };
}
