"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Check, ChevronsUpDown, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import {
  Badge,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
  cn,
} from "@freelancer-os/ui";
import { NAV_ITEMS, isActivePath } from "@/config/navigation";

export const WORKSPACE_NAME = "Personal workspace";

function WorkspaceSwitcher({ collapsed }: { collapsed: boolean }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={`Workspace: ${WORKSPACE_NAME}`}
          className={cn(
            "flex w-full items-center gap-3 rounded-md border border-line bg-surface p-2 text-left hover:bg-elevated",
            collapsed && "justify-center",
          )}
        >
          <span
            aria-hidden
            className="flex size-8 shrink-0 items-center justify-center rounded-md bg-accent text-sm font-semibold text-on-accent"
          >
            F
          </span>
          {collapsed ? null : (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium text-fg">{WORKSPACE_NAME}</span>
                <span className="block truncate text-xs text-muted">Free · Owner</span>
              </span>
              <ChevronsUpDown className="size-4 shrink-0 text-muted" aria-hidden />
            </>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Workspaces</DropdownMenuLabel>
        <DropdownMenuItem>
          <Check className="size-4 text-accent" aria-hidden />
          {WORKSPACE_NAME}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>Create workspace (coming later)</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function SidebarContent({
  collapsed = false,
  onNavigate,
  onToggleCollapsed,
}: {
  collapsed?: boolean;
  onNavigate?: () => void;
  onToggleCollapsed?: () => void;
}) {
  const pathname = usePathname();
  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <WorkspaceSwitcher collapsed={collapsed} />

      <nav aria-label="Primary" className="flex-1 overflow-y-auto">
        <ul className="flex flex-col gap-0.5">
          {NAV_ITEMS.map((item) => {
            const active = isActivePath(pathname, item.href);
            const planned = item.status === "planned";
            const Icon = item.icon;
            const link = (
              <Link
                href={item.href}
                onClick={onNavigate}
                {...(active ? { "aria-current": "page" as const } : {})}
                aria-label={
                  collapsed ? `${item.label}${planned ? " (coming soon)" : ""}` : undefined
                }
                className={cn(
                  "flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium transition-colors",
                  collapsed && "justify-center px-0",
                  active
                    ? "bg-elevated text-fg shadow-[inset_2px_0_0_var(--fos-accent)]"
                    : "text-muted hover:bg-elevated hover:text-fg",
                )}
              >
                <Icon className="size-[18px] shrink-0" aria-hidden />
                {collapsed ? null : (
                  <>
                    <span className="flex-1 truncate">{item.label}</span>
                    {planned ? <Badge>Soon</Badge> : null}
                  </>
                )}
              </Link>
            );
            return (
              <li key={item.id}>
                {collapsed ? (
                  <Tooltip content={planned ? `${item.label} — coming soon` : item.label}>
                    {link}
                  </Tooltip>
                ) : (
                  link
                )}
              </li>
            );
          })}
        </ul>
      </nav>

      {collapsed ? null : (
        <section
          aria-label="Workspace status"
          className="rounded-md border border-line bg-surface p-3 text-xs"
        >
          <dl className="flex flex-col gap-1.5">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Mode</dt>
              <dd className="text-fg">Development</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Integrations</dt>
              <dd className="text-fg">None connected</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Automations</dt>
              <dd className="text-fg">Not enabled</dd>
            </div>
          </dl>
        </section>
      )}

      {onToggleCollapsed ? (
        <Button
          variant="ghost"
          size={collapsed ? "icon" : "sm"}
          onClick={onToggleCollapsed}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-pressed={collapsed}
          className={cn(!collapsed && "justify-start text-muted")}
        >
          {collapsed ? (
            <PanelLeftOpen className="size-4" aria-hidden />
          ) : (
            <>
              <PanelLeftClose className="size-4" aria-hidden />
              Collapse
            </>
          )}
        </Button>
      ) : null}
    </div>
  );
}
