"use client";

import { ErrorState } from "@freelancer-os/ui";
import "./globals.css";

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en" data-theme="dark">
      <body className="flex min-h-screen items-center justify-center p-6">
        <div className="max-w-lg">
          <ErrorState title="The application hit an unexpected error" onRetry={reset} />
        </div>
      </body>
    </html>
  );
}
