"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, wsUrl } from "@/lib/api";
import { buildEnvelope, makeSessionId, projectAllowedActions } from "../../lib/protocol";
import { buildChildNavigationPath, extractChildCycleId, resolveChildSessionId } from "../lib/offer-navigation";
import type { OfferAcceptState, PracticeOffer } from "../types";

const ACCEPT_TIMEOUT_MS = 20000;
interface Operation {
  controller: AbortController;
  socket: WebSocket | null;
  timer: ReturnType<typeof setTimeout> | null;
  promise: Promise<void>;
  finish: (state: OfferAcceptState, message?: string) => void;
}

export interface OfferAcceptResult {
  state: OfferAcceptState;
  error: string | null;
  /** Settles only after navigation, failure, timeout or unmount cancellation. */
  accept: (offer: PracticeOffer) => Promise<void>;
}

export function useOfferAccept(): OfferAcceptResult {
  const [state, setState] = useState<OfferAcceptState>("idle");
  const [error, setError] = useState<string | null>(null);
  const current = useRef<Operation | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; current.current?.finish("idle"); };
  }, []);

  const accept = useCallback((offer: PracticeOffer): Promise<void> => {
    // A ref locks synchronously, including two clicks before React renders.
    if (current.current) return current.current.promise;
    if (!mounted.current) return Promise.resolve();
    let resolve!: () => void;
    const operation: Operation = {
      controller: new AbortController(), socket: null, timer: null,
      promise: new Promise<void>(done => { resolve = done; }),
      finish: () => {},
    };
    const active = () => current.current === operation;
    operation.finish = (next, message) => {
      if (!active()) return;
      current.current = null;
      operation.controller.abort();
      if (operation.timer !== null) clearTimeout(operation.timer);
      if (operation.socket) {
        const socket = operation.socket;
        socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
        socket.close();
      }
      if (mounted.current) { setState(next); setError(message ?? null); }
      resolve();
    };
    current.current = operation;
    setState("connecting"); setError(null);
    operation.timer = setTimeout(() => operation.finish("error", "接受练习超时，请刷新列表确认是否已接受，再重试。"), ACCEPT_TIMEOUT_MS);
    const signal = operation.controller.signal;
    void (async () => {
      if (offer.status !== "ACTIVE" || !offer.offer_id?.trim() || !offer.parent_cycle_id?.trim()) {
        operation.finish("error", "该邀请已失效，无法开始练习。"); return;
      }
      try {
        const parent = await apiFetch(`/api/v2/math-tutor/cycles/${encodeURIComponent(offer.parent_cycle_id)}`, { signal });
        if (!active()) return;
        if (!parent.ok) throw new Error(parent.status === 404
          ? "该练习邀请对应的辅导会话已不存在，请刷新列表后再试。"
          : "无法读取辅导会话，请检查网络后重试。");
        const body = await parent.json() as { session_id?: string };
        if (!active()) return;
        if (typeof body.session_id !== "string" || !body.session_id.trim()) throw new Error("无法读取辅导会话，请刷新列表后再试。");
        const sessionId = body.session_id;
        const resync = await apiFetch(`/api/v2/math-tutor/sessions/${encodeURIComponent(sessionId)}`, { signal, skipAuthRedirect: true });
        if (!active()) return;
        if (!resync.ok) throw new Error("辅导状态同步失败，请检查网络后重试。");
        const summary = await resync.json();
        if (!active()) return;
        const allowed = summary.allowed_actions !== undefined
          ? projectAllowedActions(summary.allowed_actions).filter(action => action.enabled).map(action => action.command)
          : Array.isArray(summary.allowed_next_inputs) ? summary.allowed_next_inputs : [];
        if (!allowed.includes("accept_practice_offer")) throw new Error("当前辅导状态已不允许接受此邀请，请刷新列表。");
        const socket = new WebSocket(wsUrl("/api/v2/math-tutor/ws"));
        operation.socket = socket;
        let resolvingChild = false;
        socket.onopen = () => {
          if (!active()) return;
          setState("accepting");
          try {
            socket.send(buildEnvelope("accept_practice_offer", { offer_id: offer.offer_id }, sessionId, {
              idempotencyKey: makeSessionId(),
              expectedCycleVersion: typeof summary.state_version === "number" ? summary.state_version : 0,
              cycleId: typeof summary.cycle_id === "string" ? summary.cycle_id : undefined,
              problemRevision: typeof summary.problem_revision === "string" ? summary.problem_revision : undefined,
            }));
          } catch { operation.finish("error", "发送练习请求失败，请刷新列表后重试。"); }
        };
        socket.onmessage = event => {
          if (!active() || resolvingChild) return;
          let frame: unknown;
          try { frame = JSON.parse(String(event.data)); } catch { return; }
          if (frame && typeof frame === "object" && "event_type" in frame &&
              ["turn_error", "assistant_error", "error"].includes(String(frame.event_type))) {
            operation.finish("error", "辅导服务未能接受此邀请，请刷新列表后重试。"); return;
          }
          const childCycleId = extractChildCycleId(frame);
          if (!childCycleId) return;
          resolvingChild = true;
          // The server has accepted; later WS closure must not cancel the GET.
          void resolveChildSessionId(childCycleId, path => apiFetch(path, { signal })).then(childSessionId => {
            if (!active()) return;
            if (!childSessionId) {
              operation.finish("error", "练习已接受，但跳转失败，请刷新列表后点击“继续练习”。"); return;
            }
            try {
              window.location.href = buildChildNavigationPath(childSessionId);
              operation.finish("accepted");
            } catch { operation.finish("error", "练习已接受，请刷新列表后点击“继续练习”。"); }
          });
        };
        socket.onerror = socket.onclose = () => {
          if (!resolvingChild) operation.finish("error", "连接已断开，请刷新列表后重试。");
        };
      } catch (cause) {
        if (active()) operation.finish("error", cause instanceof Error && cause.name !== "TypeError"
          ? cause.message : "无法连接辅导服务，请检查网络后重试。");
      }
    })();
    return operation.promise;
  }, []);
  return { state, error, accept };
}
