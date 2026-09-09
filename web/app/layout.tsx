import type { Metadata } from "next";
import "./globals.css";
import "katex/dist/katex.min.css";

export const metadata: Metadata = {
  title: "MathTutor",
  description: "K12 MathTutor student product",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body className="bg-[var(--background)] text-[var(--foreground)]">{children}</body>
    </html>
  );
}

