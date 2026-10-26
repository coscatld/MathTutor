export const BEFORE_TUTOR_NAVIGATION = "mathtutor-before-navigation";

type Guard = { message: () => string; discard?: () => void };
const guards = new Set<Guard>();
let releaseListeners: (() => void) | undefined;
let approved = false;
let previousFocus: HTMLElement | null = null;

/** One confirmation for all pending edits; callers retain focus on cancellation. */
export function requestTutorNavigation(): boolean {
  if (!window.dispatchEvent(new Event(BEFORE_TUTOR_NAVIGATION, { cancelable: true }))) return false;
  const pending = [...guards].filter(guard => guard.message());
  if (!pending.length) return true;
  const message = [...new Set(pending.map(guard => guard.message()))].join("\n");
  if (!window.confirm(`${message}\n确认离开？`)) { previousFocus?.focus({ preventScroll: true }); return false; }
  // Prevent a second browser beforeunload dialog for the same approved link.
  approved = true;
  for (const guard of pending) guard.discard?.();
  window.setTimeout(() => { approved = false; }, 0);
  return true;
}

export function registerNavigationGuard(guard: Guard): () => void {
  guards.add(guard);
  if (!releaseListeners) {
    const rememberFocus = () => { previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null; };
    const unload = (event: BeforeUnloadEvent) => {
      if (!approved && [...guards].some(item => item.message())) { event.preventDefault(); event.returnValue = ""; }
    };
    const navigate = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!target || target.hasAttribute("download") || (target.target && target.target !== "_self")) return;
      const next = new URL(target.href, window.location.href);
      if (next.origin === window.location.origin && next.pathname === window.location.pathname && next.search === window.location.search) return;
      if (!requestTutorNavigation()) { event.preventDefault(); event.stopPropagation(); }
    };
    document.addEventListener("pointerdown", rememberFocus, true);
    window.addEventListener("beforeunload", unload);
    document.addEventListener("click", navigate, true);
    releaseListeners = () => { previousFocus = null; document.removeEventListener("pointerdown", rememberFocus, true); window.removeEventListener("beforeunload", unload); document.removeEventListener("click", navigate, true); };
  }
  return () => {
    guards.delete(guard);
    if (!guards.size) { releaseListeners?.(); releaseListeners = undefined; }
  };
}
