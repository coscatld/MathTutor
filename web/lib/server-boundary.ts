// Server-only transport validation. Never import this module into a renderer.
import { timingSafeEqual } from "node:crypto";

export type BoundaryEnvironment = Record<string, string | undefined>;

export function inspectProxyRequest(
  headers: Headers,
  method: string,
  env: BoundaryEnvironment,
): { allowed: boolean; origin?: string } {
  const origins = (env.MATHTUTOR_ALLOWED_ORIGINS ?? "http://127.0.0.1:3000,http://localhost:3000")
    .split(",").map(value => value.trim()).filter(Boolean);
  const origin = headers.get("origin");
  const host = headers.get("host");
  // The frontend authority is derived from configured origins, never from
  // X-Forwarded-Host or req.nextUrl (both can reflect untrusted input).
  const matching = origins.find(value => {
    try { return new URL(value).host === host; } catch { return false; }
  });
  if (!matching || (origin !== null && !origins.includes(origin)) ||
      ["cross-site", "same-site"].includes(headers.get("sec-fetch-site") ?? "")) return { allowed: false };
  const secret = env.MATHTUTOR_BRIDGE_SECRET ?? "";
  const supplied = headers.get("x-mathtutor-bridge") ?? "";
  const credential = Boolean(secret && supplied && Buffer.byteLength(secret) === Buffer.byteLength(supplied) &&
    timingSafeEqual(Buffer.from(secret), Buffer.from(supplied)));
  const csrf = headers.get("x-mathtutor-csrf") === "1";
  const safe = ["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
  if (!safe && !credential && !csrf) return { allowed: false };
  if (origin !== null) return { allowed: true, origin };
  if (credential) return { allowed: true };
  // Same-origin browser GETs usually omit Origin. The explicit browser dev
  // profile (or account-auth web deployment) recognizes browser-controlled
  // Fetch Metadata plus our non-simple CSRF marker. Native clients instead
  // present the bridge header. These headers cannot be forged by a webpage.
  const accountWeb = /^(1|true|yes|on)$/i.test((env.MATHTUTOR_AUTH_ENABLED ?? env.AUTH_ENABLED ?? env.DEEPTUTOR_AUTH_ENABLED ?? "").trim());
  const devBrowser = env.NODE_ENV !== "production" && env.MATHTUTOR_BROWSER_DEV === "1" &&
    ["development", "test"].includes(env.MATHTUTOR_ENVIRONMENT ?? "development");
  const mode = headers.get("sec-fetch-mode");
  const destination = headers.get("sec-fetch-dest");
  let referrerMatches = false;
  try { referrerMatches = new URL(headers.get("referer") ?? "").origin === matching; } catch {}
  const browserRead = (csrf && ["cors", "same-origin"].includes(mode ?? "")) ||
    (mode === "no-cors" && destination === "image") ||
    (mode === "navigate" && destination === "document" && headers.get("sec-fetch-user") === "?1");
  const browser = safe && referrerMatches && headers.get("sec-fetch-site") === "same-origin" && browserRead;
  return (accountWeb || devBrowser) && browser ? { allowed: true, origin: matching } : { allowed: false };
}
