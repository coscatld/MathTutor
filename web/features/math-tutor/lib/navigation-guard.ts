export const BEFORE_TUTOR_NAVIGATION = "mathtutor-before-navigation";

type Guard = { message: () => string; discard?: () => void; version?: () => unknown };
const guards = new Set<Guard>();
let releaseListeners: (() => void) | undefined;
let approved = false;
let previousFocus: HTMLElement | null = null;
export type TutorNavigationPermission = { readonly operation: object };
type Snapshot = { guard: Guard; message: string; version: unknown; discard?: () => void };
const permissions = new WeakMap<TutorNavigationPermission, { href: string; snapshots: Snapshot[] }>();

/** Ask once for all edits, retaining every draft until the caller succeeds. */
export function requestTutorNavigationPermission(operation: object): TutorNavigationPermission | null {
  if (!window.dispatchEvent(new Event(BEFORE_TUTOR_NAVIGATION, { cancelable: true }))) return null;
  const snapshots = [...guards].map(guard => ({ guard, message: guard.message(), version: guard.version?.(), discard: guard.discard }));
  const message = [...new Set(snapshots.map(snapshot => snapshot.message).filter(Boolean))].join("\n");
  if (message && !window.confirm(`${message}\n确认离开？`)) { previousFocus?.focus({ preventScroll: true }); return null; }
  const permission = Object.freeze({ operation });
  permissions.set(permission, { href: window.location.href, snapshots });
  return permission;
}

/** Single-use approval cannot discard edits made after confirmation or on another page. */
export function commitTutorNavigation(permission: TutorNavigationPermission, operation: object): boolean {
  const saved = permissions.get(permission);
  permissions.delete(permission);
  if (!saved || permission.operation !== operation || saved.href !== window.location.href
    || saved.snapshots.length !== guards.size
    || saved.snapshots.some(({ guard, message, version }) => !guards.has(guard) || guard.message() !== message || !Object.is(guard.version?.(), version))) return false;
  // Prevent a second browser beforeunload dialog for the same approved link.
  approved = true;
  for (const snapshot of saved.snapshots) if (snapshot.message) snapshot.discard?.();
  window.setTimeout(() => { approved = false; }, 0);
  return true;
}

/** Immediate links/new conversations keep the same one-confirmation behavior. */
export function requestTutorNavigation(): boolean {
  const operation = {};
  const permission = requestTutorNavigationPermission(operation);
  return permission !== null && commitTutorNavigation(permission, operation);
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
