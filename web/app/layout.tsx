import type { Metadata } from "next";
import "../styles/tokens.css";
import "../styles/motion.css";
import "./globals.css";
import "katex/dist/katex.min.css";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";
import {LOCALE_BOOT_SCRIPT} from "@/lib/i18n/messages";
import {I18nProvider} from "@/lib/i18n";

export const metadata: Metadata = {
  title: "MathTutor",
  description: "面向学习者的桌面 AI 数学学习软件，提供分级辅导、可验证练习，以及百科、教材和本机文档的来源探究。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // The boot script sets theme classes before hydration.
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
        <script dangerouslySetInnerHTML={{ __html: LOCALE_BOOT_SCRIPT }} />
      </head>
      <body className="bg-[var(--background)] text-[var(--foreground)]"><I18nProvider>{children}</I18nProvider></body>
    </html>
  );
}
