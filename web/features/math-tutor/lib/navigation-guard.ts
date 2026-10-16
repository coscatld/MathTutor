export const BEFORE_TUTOR_NAVIGATION = "mathtutor-before-navigation";

/** Programmatic navigation shares the same unsaved-draft guard as links. */
export function requestTutorNavigation(): boolean {
  return window.dispatchEvent(new Event(BEFORE_TUTOR_NAVIGATION, {cancelable: true}));
}
