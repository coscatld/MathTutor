"use client";

import { Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { fetchAuthStatus } from "@/lib/auth";
import { fetchBootstrap, fetchSettings } from "../lib/desktop-api";
import { decideStartupRoute, type StartupDecision } from "../lib/startup";

interface Props {
  children?: React.ReactNode;
  entry?: boolean;
}

/**
 * Local application bootstrap. Desktop users see runtime/data language only;
 * auth-on server deployments retain their explicit login route.
 */
export default function StartupBoundary({ children, entry = false }: Props) {
  const router = useRouter();
  const pathname = usePathname() || "/";
  const [decision, setDecision] = useState<StartupDecision>("waiting");
  const [reason, setReason] = useState("");

  const check = useCallback(async () => {
    setDecision("waiting");
    setReason("");
    try {
      const auth = await fetchAuthStatus();
      if (!auth) {
        setReason("本地 MathTutor 服务还没有准备好。");
        return;
      }
      if (auth?.enabled && !auth.authenticated) {
        setDecision("login");
        return;
      }
      const [bootstrap, settings] = await Promise.all([
        fetchBootstrap(),
        fetchSettings(),
      ]);
      const next = decideStartupRoute(auth, bootstrap, settings);
      setDecision(next);
      setReason(bootstrap.reason || "");
    } catch {
      setReason("本地 MathTutor 服务还没有准备好。");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => {
    if (decision !== "waiting" || !reason) return;
    const timer = window.setTimeout(() => void check(), 800);
    return () => window.clearTimeout(timer);
  }, [check, decision, reason]);

  useEffect(() => {
    if (decision === "login") {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    } else if (decision === "onboarding") {
      router.replace("/onboarding/provider");
    } else if (decision === "workspace" && entry) {
      router.replace("/math-tutor");
    }
  }, [decision, entry, pathname, router]);

  if (decision === "workspace" && !entry) return children;

  const blocked = decision === "blocked";
  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[var(--background)] p-6">
      <div className="pointer-events-none absolute inset-0 opacity-50 [background-image:radial-gradient(circle_at_20%_20%,rgba(37,99,235,0.12),transparent_34%),radial-gradient(circle_at_80%_75%,rgba(176,80,30,0.10),transparent_32%)]" />
      <section className="relative w-full max-w-md rounded-3xl border border-[var(--border)] bg-[var(--card)] p-8 text-center shadow-[0_24px_80px_rgba(28,24,22,0.10)]">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-[#2563EB]/10 text-[#2563EB]">
          {blocked ? (
            <TriangleAlert className="h-6 w-6" aria-hidden="true" />
          ) : (
            <Loader2 className="h-6 w-6 animate-spin" aria-hidden="true" />
          )}
        </div>
        <h1 className="mt-5 font-serif text-2xl font-semibold tracking-tight text-[var(--foreground)]">
          {blocked ? "MathTutor 需要你的协助" : "正在启动 MathTutor"}
        </h1>
        <p className="mt-2 text-sm leading-6 text-[var(--muted-foreground)]">
          {blocked
            ? reason || "本地学习环境未能完成初始化。"
            : reason || "正在加载本地学习数据与课程资源…"}
        </p>
        {(blocked || reason) && (
          <button
            type="button"
            onClick={() => void check()}
            className="mt-5 inline-flex min-h-[44px] items-center gap-2 rounded-xl bg-[#2563EB] px-5 py-2 text-sm font-medium text-white transition hover:bg-[#1D4ED8] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            重新检查
          </button>
        )}
      </section>
    </main>
  );
}
