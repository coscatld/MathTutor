"use client";

import { RefreshCw, TriangleAlert } from "lucide-react";
import BrandMark from "@/components/common/BrandMark";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { fetchAuthStatus } from "@/lib/auth";
import { ApiError } from "@/lib/api-error";
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
      const auth = await fetchAuthStatus({ throwHttpErrors: true });
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
    } catch (error) {
      if (error instanceof ApiError && error.status && error.status >= 400 && error.status < 500) {
        setDecision("blocked");
        setReason(error.status === 403
          ? "访问被来源校验拒绝（403）。浏览器开发请在 web 目录运行 npm run dev，并使用 README 中的本机地址；桌面或服务器部署请检查来源与认证配置。"
          : `启动请求被拒绝（${error.status}），请检查服务配置后重新检查。`);
      } else setReason("本地 MathTutor 服务还没有准备好。");
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
    } else if (decision === "assessment") {
      router.replace("/onboarding/assessment");
    } else if (decision === "workspace" && entry) {
      router.replace("/math-tutor");
    }
  }, [decision, entry, pathname, router]);

  if (decision === "workspace" && !entry) return children;

  const blocked = decision === "blocked";
  return (
    <main className="mt-standalone">
      <div className="mt-standalone-field mt-paper" aria-hidden="true" />
      <section className="mt-rise relative w-full max-w-sm text-center" aria-live="polite">
        <div className={`mx-auto flex h-14 w-14 items-center justify-center rounded-2xl ${blocked ? "bg-[var(--warning-soft)] text-[var(--warning)]" : "mt-empty-mark"}`}>
          {blocked ? (
            <TriangleAlert className="h-6 w-6" aria-hidden="true" />
          ) : (
            <BrandMark className="h-7 w-7" animated loop />
          )}
        </div>
        <h1 className="mt-6 text-2xl font-bold tracking-tight text-[var(--foreground)]">
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
            className="mt-btn mt-btn-primary mt-6 min-h-[44px] px-5"
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            重新检查
          </button>
        )}
      </section>
    </main>
  );
}
