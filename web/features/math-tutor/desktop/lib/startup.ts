import type { AuthStatus } from "@/lib/auth";
import type { BootstrapPayload, DesktopSettings } from "../types";

export type StartupDecision =
  | "waiting"
  | "workspace"
  | "onboarding"
  | "login"
  | "blocked";

/** Pure startup routing policy shared by root entry and workspace refreshes. */
export function decideStartupRoute(
  auth: AuthStatus | null,
  bootstrap: BootstrapPayload | null,
  settings: DesktopSettings | null,
): StartupDecision {
  if (!auth) return "waiting";
  if (auth.enabled && !auth.authenticated) return "login";
  if (!bootstrap) return "waiting";
  if (bootstrap.readiness === "BLOCKED") return "blocked";
  if (bootstrap.phase !== "READY") return "waiting";
  if (!settings) return "waiting";
  return settings.is_configured || settings.onboarding_completed
    ? "workspace"
    : "onboarding";
}
