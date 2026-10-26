"use client";
import { useLayoutEffect, useRef } from "react";
import { registerNavigationGuard } from "../lib/navigation-guard";

/** Ref-backed reads also cover edits before a passive effect could run. */
export function useUnsavedNavigation(message: string, discard?: () => void) {
  const latest = useRef({ message, discard });
  useLayoutEffect(() => { latest.current = { message, discard }; });
  useLayoutEffect(() => registerNavigationGuard({
    message: () => latest.current.message,
    discard: () => latest.current.discard?.(),
  }), []);
}
