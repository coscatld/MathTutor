"use client";
import { useLayoutEffect, useRef } from "react";
import { registerNavigationGuard } from "../lib/navigation-guard";

/** Ref-backed reads also cover edits before a passive effect could run. */
export function useUnsavedNavigation(message: string, discard?: () => void, draftVersion?: unknown) {
  const latest = useRef({ message, discard, draftVersion, revision: 0 });
  useLayoutEffect(() => {
    const previous = latest.current;
    const changed = previous.message !== message || !Object.is(previous.draftVersion, draftVersion);
    latest.current = { message, discard, draftVersion, revision: previous.revision + Number(changed) };
  });
  useLayoutEffect(() => registerNavigationGuard({
    message: () => latest.current.message,
    discard: () => latest.current.discard?.(),
    version: () => latest.current.revision,
  }), []);
}
