"use client";

import { ErrorState } from "@freelancer-os/ui";

export default function AppError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // Never render error.message: server errors can contain internal details.
  return <ErrorState onRetry={reset} {...(error.digest ? { detail: error.digest } : {})} />;
}
