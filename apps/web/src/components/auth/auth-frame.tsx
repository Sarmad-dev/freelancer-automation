import Link from "next/link";
import type { ReactNode } from "react";
import { ThemeMenu } from "@/components/shell/topbar";

export function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between px-4 py-4 md:px-8">
        <Link href="/" className="flex items-center gap-2 text-sm font-semibold text-fg">
          <span
            aria-hidden
            className="flex size-7 items-center justify-center rounded-md bg-accent text-on-accent"
          >
            F
          </span>
          Freelancer OS
        </Link>
        <ThemeMenu />
      </header>
      <main
        id="main"
        className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-8"
      >
        {children}
      </main>
    </div>
  );
}

export function AuthHeading({ title, description }: { title: string; description: string }) {
  return (
    <div>
      <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
      <p className="mt-1 text-sm text-muted">{description}</p>
    </div>
  );
}
