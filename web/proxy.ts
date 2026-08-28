import { NextRequest, NextResponse } from "next/server";

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
    return NextResponse.rewrite(new URL(pathname + search, API_BASE_URL));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*"],
};
