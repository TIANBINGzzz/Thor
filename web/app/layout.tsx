import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { BRAND } from "./lib/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: `${BRAND.displayName} — ${BRAND.tagline}`,
  description: BRAND.description,
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `(() => { try { const saved = localStorage.getItem("thor-theme") || localStorage.getItem("ccsdkscribe-theme"); const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches; document.documentElement.dataset.theme = saved === "light" || (!saved && !systemDark) ? "light" : "dark"; } catch { document.documentElement.dataset.theme = "light"; } })();`,
          }}
        />
      </head>
      <body className={`${GeistSans.variable} ${GeistMono.variable}`}>{children}</body>
    </html>
  );
}
