import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import "./globals.css";

const appName = process.env.NEXT_PUBLIC_APP_NAME || "Freelancer OS";

export const metadata: Metadata = {
  title: { default: appName, template: `%s · ${appName}` },
  description: "AI-assisted CRM and workflow automation for independent freelancers.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" className={GeistSans.variable}>
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
