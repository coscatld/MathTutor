"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { TutorMessage } from "../types";

/** Follow new replies only while the reader is at the end, never steal a reading position. */
export function useConversationScroll(messages: TutorMessage[], pending: unknown) {
  const viewport = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const studentId = useRef<string | undefined>(undefined);
  const [away, setAway] = useState(false);
  const onScroll = useCallback(() => {
    const node = viewport.current;
    if (!node) return;
    follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 64;
    setAway(!follow.current);
  }, []);
  const toLatest = useCallback(() => {
    follow.current = true;
    setAway(false);
    const node = viewport.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, []);
  useLayoutEffect(() => {
    const latestStudent = [...messages].reverse().find(message => message.kind === "student")?.id;
    if (latestStudent !== studentId.current) {
      studentId.current = latestStudent;
      follow.current = true;
    }
    if (follow.current) toLatest();
  }, [messages, pending, toLatest]);
  useLayoutEffect(() => {
    const observer = new ResizeObserver(() => { if (follow.current) toLatest(); });
    if (content.current) observer.observe(content.current);
    if (viewport.current) observer.observe(viewport.current);
    return () => observer.disconnect();
  }, [toLatest]);
  return { viewport, content, away, onScroll, toLatest };
}
