import type { MathTutorUIState } from "../types";

export interface AttemptBinding { cycleId: string; problemRevision: string }
type AttemptState = Pick<MathTutorUIState, "cycleId" | "problemRevision" | "allowedActions" | "allowedNextInputs">;

/** Writing mode binds the student's draft to a server-authorized current task. */
export function currentAttemptBinding(state: AttemptState): AttemptBinding | null {
  const allowed = state.allowedActions === undefined ? state.allowedNextInputs.includes("submit_attempt")
    : state.allowedActions.some(action => action.command === "submit_attempt" && action.enabled);
  return allowed && state.cycleId && state.problemRevision ? { cycleId: state.cycleId, problemRevision: state.problemRevision } : null;
}

export function attemptBindingIsCurrent(binding: AttemptBinding | null, state: AttemptState): binding is AttemptBinding {
  const current = currentAttemptBinding(state);
  return Boolean(binding && current && binding.cycleId === current.cycleId && binding.problemRevision === current.problemRevision);
}

/** Check the latest snapshot at send time; completion controls draft clearing. */
export function deliverBoundAttempt(answer: string, binding: AttemptBinding, readState: () => AttemptState,
  send: (command: "submit_attempt", payload: { answer: string }, onComplete: (success: boolean) => void) => boolean): Promise<boolean> {
  if (!answer.trim() || !attemptBindingIsCurrent(binding, readState())) return Promise.resolve(false);
  return new Promise(resolve => { if (!send("submit_attempt", { answer: answer.trim() }, resolve)) resolve(false); });
}
