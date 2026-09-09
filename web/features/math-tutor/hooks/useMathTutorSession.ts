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
 *    the UI may do. The WS itself is stateless per connection and does NOT
 *    replay missed events; already-received tutor messages stay in local
 *    state, so no re-subscription is needed.
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

  const [state, dispatch] = useReducer(
    mathTutorReducer,
    sessionIdRef.current,
    initialMathTutorState,
  );

  const stateRef = useRef(state);
  stateRef.current = state;

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
    try {
      const res = await apiFetch(
        apiUrl(`/api/v2/math-tutor/sessions/${encodeURIComponent(requestedSession)}`),
        { skipAuthRedirect: true },
      );
      if (requestedSession !== sessionIdRef.current || sendInFlightRef.current) return false;
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
      if (requestedSession !== sessionIdRef.current || sendInFlightRef.current) return false;
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

    ws.onopen = () => {
      attemptRef.current = 0;
      dispatch({ type: "connection", status: "connected", note: STATUS_NOTES.connected });
      void resync();
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
      dispatch({ type: "frame", frame });
      if (["turn_end", "turn_error", "assistant_complete", "assistant_partial", "assistant_error"].includes(frame.event_type)) {
        sendInFlightRef.current = false;
      }
      if (frame.event_type === "turn_end") {
        window.dispatchEvent(new Event("mathtutor-conversations-changed"));
      }
    };

    ws.onclose = () => {
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
    (command: MathTutorCommand, payload: Record<string, string> = {}): boolean => {
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
      const envelope = buildEnvelope(command, payload, sessionIdRef.current, {
        idempotencyKey: makeSessionId(),
        // Optimistic concurrency: the server rejects commands that race ahead
        // of the version the client has seen.
        expectedCycleVersion: stateRef.current.seenVersion,
      });
      try {
        ws.send(envelope);
      } catch {
        sendInFlightRef.current = false;
        return false;
      }
      const visibleText = payload.text || payload.answer || ({ request_hint: "给我一点提示", request_explanation: "讲解这个知识点", request_example: "给我一个类似例子", request_solution: "查看完整答案" } as Record<string, string>)[command];
      dispatch({ type: "command_sent", command, text: visibleText });
      return true;
    },
    [],
  );

  /** Start a brand-new tutoring problem (fresh client session id). */
  const newProblem = useCallback(() => {
    sessionIdRef.current = makeSessionId();
    sendInFlightRef.current = false;
    dispatch({ type: "new_session", sessionId: sessionIdRef.current });
    void resync();
  }, [resync]);

  /** Manual reconnect (used by the ConnectionStatus retry button). */
  const reconnect = useCallback(() => {
    attemptRef.current = 0;
    connectRef.current();
  }, []);

  useEffect(() => {
    manuallyClosedRef.current = false;
    connectRef.current();
    return () => {
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
    newProblem,
    reconnect,
  };
}
