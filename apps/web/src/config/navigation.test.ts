import { describe, expect, it } from "vitest";
import { NAV_ITEMS, findNavItem, isActivePath, resolveBreadcrumbs } from "./navigation";

describe("navigation config", () => {
  it("covers the playbook's top-level areas with unique ids and hrefs", () => {
    const labels = NAV_ITEMS.map((i) => i.label);
    expect(labels).toEqual([
      "Home",
      "Leads",
      "Inbox",
      "Campaigns",
      "Pipeline",
      "Automations",
      "Tasks & Calendar",
      "AI Workspace",
      "Integrations",
      "Analytics",
      "Settings",
    ]);
    expect(new Set(NAV_ITEMS.map((i) => i.id)).size).toBe(NAV_ITEMS.length);
    expect(new Set(NAV_ITEMS.map((i) => i.href)).size).toBe(NAV_ITEMS.length);
  });

  it("only built destinations are marked available; everything else is honestly planned with a phase", () => {
    for (const item of NAV_ITEMS) {
      if (["home", "ai", "leads", "pipeline", "tasks", "integrations"].includes(item.id))
        expect(item.status).toBe("available");
      else {
        expect(item.status).toBe("planned");
        expect(item.phase).toBeTruthy();
      }
    }
  });

  it("matches active paths without false positives", () => {
    expect(isActivePath("/", "/")).toBe(true);
    expect(isActivePath("/leads", "/")).toBe(false);
    expect(isActivePath("/leads/123", "/leads")).toBe(true);
    expect(isActivePath("/leadsx", "/leads")).toBe(false);
  });

  it("builds breadcrumbs", () => {
    expect(resolveBreadcrumbs("/")).toEqual([{ label: "Home" }]);
    expect(resolveBreadcrumbs("/leads")).toEqual([
      { label: "Home", href: "/" },
      { label: "Leads" },
    ]);
    expect(resolveBreadcrumbs("/leads/42")).toEqual([
      { label: "Home", href: "/" },
      { label: "Leads", href: "/leads" },
    ]);
  });

  it("adds a third crumb for known sub-pages and not for unknown ones", () => {
    expect(resolveBreadcrumbs("/ai-workspace/profile")).toEqual([
      { label: "Home", href: "/" },
      { label: "AI Workspace", href: "/ai-workspace" },
      { label: "Profile" },
    ]);
    expect(resolveBreadcrumbs("/ai-workspace/nope")).toHaveLength(2);
  });

  it("labels the lead pages, including detail pages", () => {
    const id = "11111111-1111-4111-8111-111111111111";
    expect(resolveBreadcrumbs("/leads/companies")).toEqual([
      { label: "Home", href: "/" },
      { label: "Leads", href: "/leads" },
      { label: "Companies" },
    ]);
    expect(resolveBreadcrumbs(`/leads/${id}`)).toEqual([
      { label: "Home", href: "/" },
      { label: "Leads", href: "/leads" },
      { label: "Lead" },
    ]);
    expect(resolveBreadcrumbs(`/leads/contacts/${id}`)).toEqual([
      { label: "Home", href: "/" },
      { label: "Leads", href: "/leads" },
      { label: "Contacts", href: "/leads/contacts" },
      { label: "Contact" },
    ]);
    expect(resolveBreadcrumbs("/leads/import").at(-1)).toEqual({ label: "Import" });
  });

  it("labels deal pages", () => {
    const id = "11111111-1111-4111-8111-111111111111";
    expect(resolveBreadcrumbs(`/pipeline/${id}`)).toEqual([
      { label: "Home", href: "/" },
      { label: "Pipeline", href: "/pipeline" },
      { label: "Deal" },
    ]);
    expect(resolveBreadcrumbs("/tasks")).toEqual([
      { label: "Home", href: "/" },
      { label: "Tasks & Calendar" },
    ]);
  });

  it("labels non-navigation routes", () => {
    expect(resolveBreadcrumbs("/design-system")).toEqual([
      { label: "Home", href: "/" },
      { label: "Design system" },
    ]);
  });

  it("findNavItem throws for unknown ids", () => {
    expect(() => findNavItem("nope")).toThrow(/Unknown/);
  });
});
