"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@freelancer-os/ui";

const TABS = [
  { href: "/ai-workspace", label: "Overview" },
  { href: "/ai-workspace/profile", label: "Profile" },
  { href: "/ai-workspace/knowledge", label: "Knowledge" },
] as const;

/** Route-based tabs: real links, so they work with the keyboard, back button and deep links. */
export function AiWorkspaceTabs() {
  const pathname = usePathname();
  return (
    <nav aria-label="AI Workspace sections" className="border-b border-line">
      <ul className="-mb-px flex gap-1">
        {TABS.map((tab) => {
          const active = pathname === tab.href;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                {...(active ? { "aria-current": "page" as const } : {})}
                className={cn(
                  "block border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  active ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg",
                )}
              >
                {tab.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
