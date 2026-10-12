import Link from "next/link";
import { EmptyState } from "@freelancer-os/ui";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen max-w-lg items-center p-6">
      <EmptyState
        titleAs="h1"
        title="Page not found"
        description="The page you're looking for doesn't exist or has moved."
      >
        <Link
          href="/"
          className="inline-flex h-9 items-center rounded-md bg-accent px-4 text-sm font-medium text-on-accent hover:brightness-110"
        >
          Go to Home
        </Link>
      </EmptyState>
    </main>
  );
}
