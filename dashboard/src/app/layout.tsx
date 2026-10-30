import type { Metadata, Viewport } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Codify Pipeline", template: "%s · Codify Pipeline" },
  description: "Lead review for Codify Labs",
  applicationName: "Codify Pipeline",
  appleWebApp: { capable: true, title: "Pipeline", statusBarStyle: "default" },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a0a0a" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
