import type { Metadata } from "next";
import "./globals.css";
import "katex/dist/katex.min.css";
import { THEME_BOOT_SCRIPT } from "@/lib/theme";

export const metadata: Metadata = {
  title: "MathTutor",
  description: "K12 MathTutor student product",
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
