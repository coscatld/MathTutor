"use client";

import { useCallback, useRef, useState } from "react";
import { apiFetch, wsUrl } from "@/lib/api";
import { buildEnvelope, makeSessionId } from "../../lib/protocol";
import {
  buildChildNavigationPath,
  extractChildCycleId,
  resolveChildSessionId,
} from "../lib/offer-navigation";
import type { OfferAcceptState, PracticeOffer } from "../types";

const WS_PATH = "/api/v2/math-tutor/ws";
const ACCEPT_TIMEOUT_MS = 20000;

export interface OfferAcceptResult {
  state: OfferAcceptState;
  error: string | null;
  /** Call with an ACTIVE offer to accept it and jump to the child cycle. */
  accept: (offer: PracticeOffer) => Promise<void>;
}

/**
 * Accept a practice offer from the 练习邀请 list.
 *
 * Flow (rides the SAME session machinery as the tutoring page — no second
 * state machine): resolve the parent session via GET /cycles/{id}, resync the
 * server-authoritative state (allowed_next_inputs + version), send
 * `accept_practice_offer` over the parent session's WS, read ONLY the public
 * `extra.child_cycle_id` from the resulting frame, resolve the child session,
 * and navigate to it.
 *
 * The command is only ever sent when the server's allowed_next_inputs grants
 * it; REVOKED/EXPIRED offers surface a friendly message instead.
 */
export function useOfferAccept(): OfferAcceptResult {
  const [state, setState] = useState<OfferAcceptState>("idle");
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const navigatedRef = useRef(false);

  const cleanup = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onmessage = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const accept = useCallback(
    async (offer: PracticeOffer) => {
      setError(null);
      setState("connecting");
      navigatedRef.current = false;

      if (offer.status === "REVOKED" || offer.status === "EXPIRED") {
        setState("error");
        setError("该邀请已失效，无法开始练习。");
        return;
      }

      // 1. Resolve the parent session id.
      let sessionId: string;
      try {
        const res = await apiFetch(
          `/api/v2/math-tutor/cycles/${encodeURIComponent(offer.parent_cycle_id)}`,
        );
        if (!res.ok) throw new Error("not_found");
        const body = (await res.json()) as { session_id?: unknown };
        if (typeof body.session_id !== "string" || !body.session_id) {
          throw new Error("not_found");
        }
        sessionId = body.session_id;
      } catch {
        setState("error");
        setError("该练习邀请对应的辅导会话已不存在，请刷新列表后再试。");
        return;
      }

      // 2. Resync the server-authoritative state for the parent session.
      let stateVersion = 0;
      let allowed: string[] = [];
      try {
        const res = await apiFetch(
          `/api/v2/math-tutor/sessions/${encodeURIComponent(sessionId)}`,
          { skipAuthRedirect: true },
        );
        if (res.ok) {
          const summary = (await res.json()) as {
            state_version?: unknown;
            allowed_next_inputs?: unknown;
          };
          stateVersion =
            typeof summary.state_version === "number" ? summary.state_version : 0;
          allowed = Array.isArray(summary.allowed_next_inputs)
            ? summary.allowed_next_inputs.filter((v): v is string => typeof v === "string")
            : [];
        }
      } catch {
        // A resync failure is not fatal — the accept itself is still
        // attempted below; the server rejects it if the state moved on.
      }

      // 3. Open the parent session's WS and send the accept command — only
      // when the server still grants it.
      let ws: WebSocket;
      try {
        ws = new WebSocket(wsUrl(WS_PATH));
      } catch {
        setState("error");
        setError("无法连接辅导服务，请稍后再试。");
        return;
      }
      wsRef.current = ws;

      let phase: "connecting" | "accepting" = "connecting";
      timerRef.current = setTimeout(() => {
        cleanup();
        if (!navigatedRef.current) {
          setState("error");
          setError("接受练习超时，请检查网络后重试。");
        }
      }, ACCEPT_TIMEOUT_MS);

      ws.onopen = () => {
        if (!allowed.includes("accept_practice_offer")) {
          cleanup();
          setState("error");
          setError("当前辅导状态已不允许接受此邀请（邀请可能已失效）。");
          return;
        }
        phase = "accepting";
        setState("accepting");
        const envelope = buildEnvelope(
          "accept_practice_offer",
          { offer_id: offer.offer_id },
          sessionId,
          {
            idempotencyKey: makeSessionId(),
            expectedCycleVersion: stateVersion,
          },
        );
        ws.send(envelope);
      };

      ws.onmessage = (event: MessageEvent<string>) => {
        let raw: unknown;
        try {
          raw = JSON.parse(String(event.data));
        } catch {
          return;
        }
        const childCycleId = extractChildCycleId(raw);
        if (!childCycleId || navigatedRef.current) return;

        // 4. Resolve the child session and navigate.
        void (async () => {
          const childSessionId = await resolveChildSessionId(childCycleId);
          if (!childSessionId) {
            cleanup();
            setState("error");
            setError("练习已接受，但跳转失败，请手动刷新练习列表。");
            return;
          }
          navigatedRef.current = true;
          cleanup();
          setState("accepted");
          if (typeof window !== "undefined") {
            window.location.href = buildChildNavigationPath(childSessionId);
          }
        })();
      };

      ws.onclose = () => {
        if (!navigatedRef.current && phase === "accepting") {
          setState("error");
          setError("连接已断开，请重试。");
        }
      };
    },
    [cleanup],
  );

  return { state, error, accept };
}
