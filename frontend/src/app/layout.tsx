import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "InfoHub",
  description: "本地多领域信息聚合系统",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-[var(--bg-base)] text-[var(--text-primary)] font-sans">
        {children}
      </body>
    </html>
  );
}
