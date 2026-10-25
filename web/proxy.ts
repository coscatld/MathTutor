import { NextRequest, NextResponse } from "next/server";
import { inspectProxyRequest } from "./lib/server-boundary";

// Runtime-only backend location injected by the standalone desktop shell.
// The deprecated DeepTutor name is accepted for one upgrade cycle only and
// is intentionally not exposed to the browser bundle.
const API_BASE_URL =
  process.env.MATHTUTOR_API_BASE_URL ??
  process.env.DEEPTUTOR_API_BASE_URL ??
  "http://127.0.0.1:8001";

export function proxy(req: NextRequest): NextResponse {
  const { pathname, search } = req.nextUrl;
  if (pathname.startsWith("/api/")) {
    const decision = inspectProxyRequest(req.headers, req.method, process.env);
    if (!decision.allowed) {
      if (req.headers.get("upgrade")?.toLowerCase() === "websocket") {
        // Next's upgrade handler cannot write a Proxy JSON body reliably.
        // Send a deliberately untrusted upgrade to the backend ASGI gate so
        // uvicorn returns an explicit 403 before accept. No credential is
        // attached and no caller-controlled Host can turn this into access.
        const rejected = new Headers(req.headers);
        rejected.delete("x-mathtutor-bridge");
        rejected.set("origin", "null");
        rejected.set("host", new URL(API_BASE_URL).host);
        return NextResponse.rewrite(new URL(pathname + search, API_BASE_URL), { request: { headers: rejected } });
      }
      return NextResponse.json({ detail: "Untrusted request source" }, { status: 403 });
    }
    const headers = new Headers(req.headers);
    // An incoming header is never forwarded unchecked or sent to a response.
    headers.delete("x-mathtutor-bridge");
    if (process.env.MATHTUTOR_BRIDGE_SECRET) {
      headers.set("x-mathtutor-bridge", process.env.MATHTUTOR_BRIDGE_SECRET);
    }
    if (decision.origin) headers.set("origin", decision.origin);
    headers.set("host", new URL(API_BASE_URL).host);
    return NextResponse.rewrite(new URL(pathname + search, API_BASE_URL), { request: { headers } });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*"],
};
