import type { Metadata, Viewport } from "next";
import { GeistSans } from "geist/font/sans";
import { THEME_INIT_SCRIPT } from "@freelancer-os/ui";
import { Providers } from "@/components/providers";
import "./globals.css";

const appName = process.env.NEXT_PUBLIC_APP_NAME || "Freelancer OS";

export const metadata: Metadata = {
  title: { default: appName, template: `%s · ${appName}` },
  description: "AI-assisted CRM and workflow automation for independent freelancers.",
};

export const viewport: Viewport = {
  colorScheme: "dark light",
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#101114" },
    { media: "(prefers-color-scheme: light)", color: "#f6f7f9" },
  ],
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // suppressHydrationWarning: the pre-paint script sets data-theme before React hydrates.
    <html lang="en" data-theme="dark" className={GeistSans.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
