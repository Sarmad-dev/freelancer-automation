"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { CommandPalette, Drawer, cn, type CommandGroup } from "@freelancer-os/ui";
import { NAV_ITEMS } from "@/config/navigation";
import { SidebarContent } from "./sidebar";
import { useTheme } from "./theme-provider";
import { Topbar } from "./topbar";
import { usePersistentBoolean } from "./use-persistent-boolean";

export function AppShell({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { setPreference } = useTheme();
  const [collapsed, setCollapsed] = usePersistentBoolean("fos-sidebar-collapsed");
  const [navOpen, setNavOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const groups = useMemo<CommandGroup[]>(
    () => [
      {
        heading: "Go to",
        items: NAV_ITEMS.map((item) => ({
          id: `nav-${item.id}`,
          label: item.label,
          icon: <item.icon className="size-4" />,
          ...(item.status === "planned" ? { hint: "Coming soon" } : {}),
          onSelect: () => router.push(item.href),
        })),
      },
      {
        heading: "Theme",
        items: [
          {
            id: "theme-dark",
            label: "Use dark theme",
            icon: <Moon className="size-4" />,
            onSelect: () => setPreference("dark"),
          },
          {
            id: "theme-light",
            label: "Use light theme",
            icon: <Sun className="size-4" />,
            onSelect: () => setPreference("light"),
          },
          {
            id: "theme-system",
            label: "Match system theme",
            icon: <Monitor className="size-4" />,
            onSelect: () => setPreference("system"),
          },
        ],
      },
    ],
    [router, setPreference],
  );

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#main"
        className="sr-only z-[70] rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to main content
      </a>

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 hidden border-r border-line bg-sidebar transition-[width] duration-200 lg:block",
          collapsed ? "w-[4.5rem]" : "w-64",
        )}
      >
        <SidebarContent collapsed={collapsed} onToggleCollapsed={() => setCollapsed(!collapsed)} />
      </aside>

      <Drawer
        open={navOpen}
        onOpenChange={setNavOpen}
        side="left"
        title="Navigation"
        className="bg-sidebar"
        bodyClassName="p-0"
      >
        <SidebarContent onNavigate={() => setNavOpen(false)} />
      </Drawer>

      <div
        className={cn(
          "transition-[padding] duration-200",
          collapsed ? "lg:pl-[4.5rem]" : "lg:pl-64",
        )}
      >
        <Topbar onOpenNav={() => setNavOpen(true)} onOpenPalette={() => setPaletteOpen(true)} />
        <main
          id="main"
          tabIndex={-1}
          className="mx-auto w-full max-w-7xl px-4 py-6 outline-none md:px-8 md:py-8"
        >
          {children}
        </main>
      </div>

      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        groups={groups}
        footer="Jump to pages and switch theme. Searching leads and messages arrives with those features."
      />
    </div>
  );
}
