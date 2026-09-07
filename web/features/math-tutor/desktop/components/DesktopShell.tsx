"use client";

import { BookOpen, BrainCircuit, FileText, GraduationCap, Settings, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import BootstrapStatus from "./BootstrapStatus";
import PrivacyPanel from "./PrivacyPanel";

const NAV_ITEMS = [
  { href: "/math-tutor", label: "练习", icon: GraduationCap },
  { href: "/math-tutor/offers", label: "练习邀请", icon: BookOpen },
  { href: "/math-tutor/documents", label: "我的资料", icon: FileText },
  { href: "/math-tutor/memory", label: "我的记忆", icon: BrainCircuit },
  { href: "/math-tutor/settings", label: "设置", icon: Settings },
];

/**
 * Desktop product shell for the MathTutor workspace: top bar with the
 * bootstrap status (boot progress → final tri-state badge + expandable
 * steps) and section navigation. Pure shell — all business logic lives in
 * the backend bridge and the math-tutor session reducer.
 *
 * Additional surfaces hosted here (no page routes needed):
 *  - 我的数据 → PrivacyPanel dialog (profile/memory/documents/summary);
 * First-run routing is owned by StartupBoundary and the dedicated provider
 * onboarding page, not by a workspace modal.
 */
export default function DesktopShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "";
  const [privacyOpen, setPrivacyOpen] = useState(false);

  const current = pathname.startsWith("/math-tutor/settings")
    ? "/math-tutor/settings"
    : pathname.startsWith("/math-tutor/memory")
      ? "/math-tutor/memory"
      : pathname.startsWith("/math-tutor/documents")
        ? "/math-tutor/documents"
        : pathname.startsWith("/math-tutor/offers")
          ? "/math-tutor/offers"
          : "/math-tutor";

  return (
    <div className="flex h-full min-h-0 w-full flex-col">
      {/* Top bar: nav + bootstrap status */}
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] bg-[var(--card)]/60 px-4 py-2.5 md:px-6">
        <nav aria-label="桌面功能" className="flex flex-wrap items-center gap-1">
          {NAV_ITEMS.map((item) => {
            const active = current === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)] ${
                  active
                    ? "bg-[#2563EB]/10 text-[#1D4ED8] dark:text-blue-400"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
                }`}
              >
                <item.icon className="h-4 w-4" aria-hidden="true" />
                {item.label}
              </Link>
            );
          })}
          <button
            type="button"
            onClick={() => setPrivacyOpen(true)}
            className="inline-flex min-h-[40px] cursor-pointer items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-[var(--muted-foreground)] transition-colors duration-200 hover:bg-[var(--muted)] hover:text-[var(--foreground)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--ring)]"
          >
            <ShieldCheck className="h-4 w-4" aria-hidden="true" />
            我的数据
          </button>
        </nav>
        <div className="flex items-center gap-2">
          <BootstrapStatus />
        </div>
      </header>

      {/* Page content */}
      <main className="min-h-0 flex-1 overflow-y-auto">{children}</main>

      {/* Privacy dialog (profile / memory / documents / read-only summary). */}
      {privacyOpen ? <PrivacyPanel onClose={() => setPrivacyOpen(false)} /> : null}
    </div>
  );
}
