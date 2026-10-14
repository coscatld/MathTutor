"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import BrandMark from "@/components/common/BrandMark";
import { register, checkIsFirstUser, fetchAuthStatus } from "@/lib/auth";

const ZH: Record<string, string> = {
  "Login failed": "登录失败，请检查后重试",
  "Sign in to your account": "登录后继续你的学习",
  "Account created! Sign in to continue.": "账户已创建，请登录继续。",
  "Email or username": "邮箱或用户名",
  "Password": "密码",
  "Signing in…": "正在登录…",
  "Sign in": "登录",
  "Don't have an account?": "还没有账户？",
  "Create one": "创建账户",
  "Passwords do not match": "两次输入的密码不一致",
  "Registration failed": "注册失败，请重试",
  "Create your account": "创建你的学习账户",
  "First user:": "首位用户：",
  "You will be granted admin privileges and can manage other users from the admin dashboard.": "你将获得管理员权限，可以在管理后台管理其他用户。",
  "At least 8 characters": "至少 8 个字符",
  "Confirm password": "确认密码",
  "Creating account…": "正在创建…",
  "Create account": "创建账户",
  "Already have an account?": "已有账户？",
};
const t = (message: string): string => ZH[message] ?? message;

export default function RegisterPage() {
  const router = useRouter();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [isFirst, setIsFirst] = useState(false);
  const [checkingFirst, setCheckingFirst] = useState(true);

  useEffect(() => {
    // Redirect if already logged in
    fetchAuthStatus().then((status) => {
      if (status?.authenticated) router.replace("/");
    });

    // Check if this will be the first (admin) user
    checkIsFirstUser().then((first) => {
      setIsFirst(first);
      setCheckingFirst(false);
    });
  }, [router]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError(t("Passwords do not match"));
      return;
    }

    setLoading(true);
    const result = await register(username, password);

    if (result.ok) {
      router.replace("/login?registered=1");
    } else {
      setError(result.error ?? t("Registration failed"));
      setLoading(false);
    }
  }

  return (
    <div className="mt-rise relative w-full max-w-sm">
      {/* Logo / Title */}
      <div className="mb-8 flex flex-col items-center text-center">
        <span className="mt-empty-mark mb-5"><BrandMark className="h-6 w-6" /></span>
        <h1 className="mt-wordmark mt-wordmark-lg">
          Math<span>Tutor</span>
        </h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          {t("Create your account")}
        </p>
      </div>

      {/* First-user notice */}
      {!checkingFirst && isFirst && (
        <div className="mb-4 rounded-lg border border-[var(--primary-border)] bg-[var(--primary-soft)] px-4 py-3 text-sm text-[var(--primary-text)]">
          <strong>{t("First user:")}</strong>{" "}
          {t(
            "You will be granted admin privileges and can manage other users from the admin dashboard.",
          )}
        </div>
      )}

      {/* Card */}
      <div className="rounded-[22px] border border-[var(--border)] bg-[var(--card)] px-7 py-7 shadow-[var(--shadow-xl)]">
        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Email or username */}
          <div>
            <label
              htmlFor="username"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Email or username")}
            </label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="mt-input"
              placeholder="you@example.com"
            />
          </div>

          {/* Password */}
          <div>
            <label
              htmlFor="password"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Password")}
            </label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-input"
              placeholder="••••••••"
            />
            <p className="mt-1 text-xs text-[var(--muted-foreground)]">
              {t("At least 8 characters")}
            </p>
          </div>

          {/* Confirm Password */}
          <div>
            <label
              htmlFor="confirmPassword"
              className="block text-sm font-medium text-[var(--foreground)] mb-1.5"
            >
              {t("Confirm password")}
            </label>
            <input
              id="confirmPassword"
              type="password"
              autoComplete="new-password"
              required
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              className="mt-input"
              placeholder="••••••••"
            />
          </div>

          {/* Error message */}
          {error && (
            <p role="alert" className="rounded-lg bg-red-500/10 px-3 py-2 text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}

          {/* Submit */}
          <button
            type="submit"
            disabled={loading}
            className="mt-btn mt-btn-primary min-h-[44px] w-full"
          >
            {loading ? t("Creating account…") : t("Create account")}
          </button>
        </form>
      </div>

      <p className="mt-6 text-center text-sm text-[var(--muted-foreground)]">
        {t("Already have an account?")}{" "}
        <Link
          href="/login"
          className="font-semibold text-[var(--primary-text)] underline decoration-transparent underline-offset-4 transition-colors hover:decoration-[var(--primary-text)]"
        >
          {t("Sign in")}
        </Link>
      </p>

      <p className="mt-3 text-center text-xs text-[var(--muted-foreground)]">
        MathTutor · K12 数学辅导
      </p>
    </div>
  );
}
