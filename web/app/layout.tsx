import type { Metadata } from "next";
import "./globals.css";
import "katex/dist/katex.min.css";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "MathTutor——基于学习过程追踪与可验证解题的开源数学智能辅导系统",
  description: "面向小学至高中的开源数学智能辅导系统，结合学习过程追踪、受限数学核验、个人资料库与创作者教学插件。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // The boot script sets theme classes before hydration.
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOT_SCRIPT }} />
      </head>
      <body className="bg-[var(--background)] text-[var(--foreground)]">{children}</body>
    </html>
  );
}
