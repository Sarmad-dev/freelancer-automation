import {
  BarChart3,
  CalendarCheck,
  House,
  Inbox,
  KanbanSquare,
  Megaphone,
  Plug,
  Settings,
  Sparkles,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import type { Crumb } from "@freelancer-os/ui";

export interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  description: string;
  /** "available" = functional now. "planned" = placeholder page, clearly marked in the UI. */
  status: "available" | "planned";
  /** Playbook phase that delivers it (shown on planned pages). */
  phase?: string;
}

/**
 * Full information architecture from the playbook. The MVP only implements a few destinations, but
 * every top-level area has a stable route so the navigation does not need to change later.
 */
export const NAV_ITEMS: readonly NavItem[] = [
  {
    id: "home",
    label: "Home",
    href: "/",
    icon: House,
    status: "available",
    description: "Overview, next actions, recent activity and system status.",
  },
  {
    id: "leads",
    label: "Leads",
    href: "/leads",
    icon: Users,
    status: "planned",
    phase: "MVP Prompt 6",
    description: "Leads, companies and contacts with CSV import, filtering and fit scoring.",
  },
  {
    id: "inbox",
    label: "Inbox",
    href: "/inbox",
    icon: Inbox,
    status: "planned",
    phase: "MVP Prompt 10",
    description: "Email conversations, AI reply classification and draft review.",
  },
  {
    id: "campaigns",
    label: "Campaigns",
    href: "/campaigns",
    icon: Megaphone,
    status: "planned",
    phase: "Post-MVP",
    description: "Multi-step outreach sequences with approvals and analytics.",
  },
  {
    id: "pipeline",
    label: "Pipeline",
    href: "/pipeline",
    icon: KanbanSquare,
    status: "planned",
    phase: "MVP Prompt 7",
    description: "Opportunities by stage, with table and Kanban views.",
  },
  {
    id: "automations",
    label: "Automations",
    href: "/automations",
    icon: Workflow,
    status: "planned",
    phase: "MVP Prompts 11–13",
    description: "Visual workflows, run history and the approval center.",
  },
  {
    id: "tasks",
    label: "Tasks & Calendar",
    href: "/tasks",
    icon: CalendarCheck,
    status: "planned",
    phase: "MVP Prompt 7",
    description: "Follow-ups, reminders and deadlines.",
  },
  {
    id: "ai",
    label: "AI Workspace",
    href: "/ai-workspace",
    icon: Sparkles,
    status: "available",
    description:
      "Your profile and the approved knowledge AI is allowed to use. Generation history arrives with the AI features.",
  },
  {
    id: "integrations",
    label: "Integrations",
    href: "/integrations",
    icon: Plug,
    status: "planned",
    phase: "MVP Prompts 9 and 14",
    description: "Connected apps, permissions and connection diagnostics.",
  },
  {
    id: "analytics",
    label: "Analytics",
    href: "/analytics",
    icon: BarChart3,
    status: "planned",
    phase: "MVP Prompt 15",
    description: "Lead, outreach, pipeline and workflow reliability metrics.",
  },
  {
    id: "settings",
    label: "Settings",
    href: "/settings",
    icon: Settings,
    status: "planned",
    phase: "MVP Prompt 3",
    description: "Profile, workspace, security and data controls.",
  },
] as const;

export function findNavItem(id: string): NavItem {
  const item = NAV_ITEMS.find((i) => i.id === id);
  if (!item) throw new Error(`Unknown navigation item: ${id}`);
  return item;
}

export function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Routes outside the primary navigation that still need a readable breadcrumb. */
const EXTRA_ROUTE_LABELS: Record<string, string> = {
  "/design-system": "Design system",
  "/sign-in": "Sign in",
  "/sign-up": "Create account",
  "/onboarding": "Onboarding",
};

/** Known second-level pages inside a primary destination. */
const SUBPAGE_LABELS: Record<string, string> = {
  "/ai-workspace/profile": "Profile",
  "/ai-workspace/knowledge": "Knowledge",
};

export function resolveBreadcrumbs(pathname: string): Crumb[] {
  const current = NAV_ITEMS.find((i) => i.href !== "/" && isActivePath(pathname, i.href));
  if (!current) {
    const extra = EXTRA_ROUTE_LABELS[pathname];
    if (extra) return [{ label: "Home", href: "/" }, { label: extra }];
    return pathname === "/"
      ? [{ label: "Home" }]
      : [{ label: "Home", href: "/" }, { label: "Page" }];
  }
  const crumbs: Crumb[] = [{ label: "Home", href: "/" }];
  const sub = SUBPAGE_LABELS[pathname];
  crumbs.push(
    pathname === current.href
      ? { label: current.label }
      : { label: current.label, href: current.href },
  );
  if (sub) crumbs.push({ label: sub });
  return crumbs;
}
