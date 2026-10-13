"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { CircleHelp, Menu, Monitor, Moon, Search, Sun, User } from "lucide-react";
import {
  Breadcrumbs,
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  isThemePreference,
} from "@freelancer-os/ui";
import { LogOut } from "lucide-react";
import { resolveBreadcrumbs } from "@/config/navigation";
import { useSession } from "@/components/session-provider";
import { browserApi } from "@/lib/api-client";
import { hardNavigate } from "@/lib/navigation";
import { NotificationBell } from "./notification-bell";
import { useTheme } from "./theme-provider";

const iconBtn = "text-muted hover:text-fg";

export function ThemeMenu() {
  const { preference, resolved, setPreference } = useTheme();
  const Icon = resolved === "dark" ? Moon : Sun;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label={`Theme: ${preference}`} className={iconBtn}>
          <Icon className="size-4" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={preference}
          onValueChange={(v) => {
            if (isThemePreference(v)) setPreference(v);
          }}
        >
          <DropdownMenuRadioItem value="dark">
            <Moon className="size-4" aria-hidden /> Dark
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="light">
            <Sun className="size-4" aria-hidden /> Light
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">
            <Monitor className="size-4" aria-hidden /> System
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function HelpMenu() {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Help" className={iconBtn}>
          <CircleHelp className="size-4" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>Help</DropdownMenuLabel>
        <DropdownMenuItem asChild>
          <Link href="/design-system">Design system reference</Link>
        </DropdownMenuItem>
        <DropdownMenuItem disabled>Documentation (coming later)</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ProfileMenu() {
  const { user } = useSession();

  async function signOut() {
    try {
      await browserApi().POST("/api/v1/auth/sign-out");
    } finally {
      // Even if the request failed, leave the app: the server session expires on its own.
      hardNavigate("/sign-in");
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Account menu" className={iconBtn}>
          <User className="size-4" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent className="w-64">
        <DropdownMenuLabel>
          <span className="block truncate text-sm font-medium text-fg">{user.display_name}</span>
          <span className="block truncate text-xs font-normal text-muted">{user.email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings">Settings</Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void signOut()}>
          <LogOut className="size-4" aria-hidden /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar({
  onOpenNav,
  onOpenPalette,
}: {
  onOpenNav: () => void;
  onOpenPalette: () => void;
}) {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-line bg-canvas/90 px-4 backdrop-blur md:px-6">
      <Button
        variant="ghost"
        size="icon"
        className="lg:hidden"
        aria-label="Open navigation"
        onClick={onOpenNav}
      >
        <Menu className="size-5" aria-hidden />
      </Button>

      <div className="hidden min-w-0 flex-1 sm:block">
        <Breadcrumbs
          items={resolveBreadcrumbs(pathname)}
          renderLink={(href, label) => (
            <Link href={href} className="hover:text-fg hover:underline">
              {label}
            </Link>
          )}
        />
      </div>
      <div className="flex-1 sm:hidden" />

      <button
        type="button"
        onClick={onOpenPalette}
        aria-label="Search or jump to"
        aria-keyshortcuts="Control+K Meta+K"
        className="flex h-9 w-full max-w-64 items-center gap-2 rounded-md border border-line bg-surface px-3 text-sm text-muted hover:border-muted sm:w-64"
      >
        <Search className="size-4" aria-hidden />
        <span className="flex-1 truncate text-left" aria-hidden>
          Search<span className="hidden sm:inline"> or jump to…</span>
        </span>
        <kbd className="hidden rounded-sm border border-line px-1.5 py-0.5 text-[11px] sm:inline">
          Ctrl K
        </kbd>
      </button>

      <div className="flex items-center">
        <NotificationBell />
        <HelpMenu />
        <ThemeMenu />
        <ProfileMenu />
      </div>
    </header>
  );
}
