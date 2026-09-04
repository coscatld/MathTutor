"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { fetchAuthStatus } from "@/lib/auth";

type AuthCheck = "checking" | "ready" | "unavailable";

/**
 * Resolve the standalone backend's runtime auth state before mounting the
 * workspace. This prevents the workspace from issuing protected API/WS
 * requests before an unauthenticated user has reached the login flow.
 */
export default function AuthBoundary({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || "/math-tutor";
  const router = useRouter();
  const [state, setState] = useState<AuthCheck>("checking");

  const check = useCallback(async () => {
    setState("checking");
    const status = await fetchAuthStatus();
    if (!status) {
      setState("unavailable");
      return;
    }
    if (status.enabled && !status.authenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    setState("ready");
  }, [pathname, router]);

  useEffect(() => {
    void check();
  }, [check]);

  if (state === "ready") return children;

  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--background)] p-6">
      <div className="w-full max-w-sm rounded-2xl border border-[var(--border)] bg-[var(--card)] p-6 text-center shadow-sm">
        {state === "checking" ? (
          <>
            <Loader2 className="mx-auto h-6 w-6 animate-spin text-[#2563EB]" aria-hidden="true" />
            <h1 className="mt-3 text-base font-semibold text-[var(--foreground)]">正在验证登录状态</h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">请稍候，正在连接本地 MathTutor 服务…</p>
          </>
        ) : (
          <>
            <h1 className="text-base font-semibold text-[var(--foreground)]">暂时无法连接本地服务</h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">请确认 MathTutor 已完成启动，然后重试。</p>
            <button
              type="button"
              onClick={() => void check()}
              className="mt-4 inline-flex min-h-[40px] items-center gap-2 rounded-lg bg-[#2563EB] px-4 py-2 text-sm font-medium text-white"
            >
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
              重新连接
            </button>
          </>
        )}
      </div>
    </main>
  );
}
