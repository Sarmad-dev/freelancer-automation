import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "./cn";

export interface Crumb {
  label: string;
  href?: string;
}

export function Breadcrumbs({
  items,
  renderLink,
}: {
  items: Crumb[];
  /** Framework link renderer (e.g. next/link). Defaults to a plain anchor. */
  renderLink?: (href: string, children: ReactNode) => ReactNode;
}) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex items-center gap-1 text-[13px] text-muted">
        {items.map((c, i) => {
          const last = i === items.length - 1;
          return (
            <li key={`${c.label}-${i}`} className="flex items-center gap-1">
              {c.href && !last ? (
                (renderLink?.(c.href, c.label) ?? (
                  <a href={c.href} className="hover:text-fg hover:underline">
                    {c.label}
                  </a>
                ))
              ) : (
                <span
                  {...(last ? { "aria-current": "page" as const } : {})}
                  className={cn(last && "text-fg")}
                >
                  {c.label}
                </span>
              )}
              {last ? null : <ChevronRight className="size-3.5" aria-hidden />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Standard page header: title, optional status badge/description, and page-level actions. */
export function PageHeader({
  title,
  description,
  badge,
  actions,
  className,
}: {
  title: string;
  description?: ReactNode;
  badge?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-4", className)}>
      <div className="min-w-0">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
          {badge}
        </div>
        {description ? <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
