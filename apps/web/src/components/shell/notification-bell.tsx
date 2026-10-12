"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import type { components } from "@freelancer-os/contracts";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  cn,
} from "@freelancer-os/ui";
import { formatDateTime } from "@/components/leads/lead-model";
import { useSession } from "@/components/session-provider";
import { browserApi } from "@/lib/api-client";

type NotificationOut = components["schemas"]["NotificationOut"];

export const DEFAULT_POLL_INTERVAL_MS = 60_000;
const LIST_LIMIT = 10;

/**
 * Only same-origin, path-only links are followed. The server validates links too, but a
 * notification is data from a store, so the browser checks again: a single leading slash, no
 * `//host`, no scheme, no backslash or control-character tricks.
 */
export function safeLink(link: string | null | undefined): string | null {
  if (!link || !link.startsWith("/") || link.startsWith("//")) return null;
  for (const ch of link) {
    const code = ch.charCodeAt(0);
    if (ch === "\\" || code <= 0x1f || code === 0x7f) return null;
  }
  try {
    const base = "http://notification-link.invalid";
    if (new URL(link, base).origin !== base) return null;
  } catch {
    return null;
  }
  return link;
}

type ListState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error" }
  | { status: "ready"; items: NotificationOut[] };

function describeCount(n: number): string {
  return n === 0 ? "No unread notifications" : `${n} unread notification${n === 1 ? "" : "s"}`;
}

export interface NotificationBellProps {
  /** Poll period while the tab is visible. Injectable so tests need not wait a minute. */
  pollIntervalMs?: number;
}

/** The signed-in workspace id scopes everything; remounting on change drops all cached state. */
export function NotificationBell({
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
}: NotificationBellProps) {
  const { workspace } = useSession();
  return (
    <BellInner key={workspace.id} workspaceId={workspace.id} pollIntervalMs={pollIntervalMs} />
  );
}

function BellInner({
  workspaceId,
  pollIntervalMs,
}: {
  workspaceId: string;
  pollIntervalMs: number;
}) {
  const router = useRouter();
  const [count, setCount] = useState<number | null>(null);
  const [list, setList] = useState<ListState>({ status: "idle" });
  const [announcement, setAnnouncement] = useState("");

  const alive = useRef(true);
  const countRef = useRef<number | null>(null);
  // Bumped by every poll and every local change so an older response never overwrites newer state.
  const epoch = useRef(0);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  /** Set the count and announce it politely, but only when a known count actually changes. */
  const applyCount = useCallback((next: number) => {
    const prev = countRef.current;
    countRef.current = next;
    setCount(next);
    if (prev !== null && prev !== next) setAnnouncement(describeCount(next));
  }, []);

  const poll = useCallback(async () => {
    const mine = ++epoch.current;
    try {
      const { data } = await browserApi().GET(
        "/api/v1/workspaces/{workspace_id}/notifications/unread-count",
        { params: { path: { workspace_id: workspaceId } } },
      );
      if (data && alive.current && mine === epoch.current) applyCount(data.unread);
    } catch {
      // Silent on purpose: keep the last known count.
    }
  }, [workspaceId, applyCount]);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | undefined;
    const visible = () => document.visibilityState === "visible";
    const stop = () => {
      if (timer !== undefined) clearInterval(timer);
      timer = undefined;
    };
    const start = () => {
      stop();
      if (visible()) timer = setInterval(() => void poll(), pollIntervalMs);
    };
    const onVisibility = () => {
      if (visible()) {
        void poll();
        start();
      } else {
        stop();
      }
    };
    const onFocus = () => {
      if (visible()) {
        void poll();
        start();
      }
    };
    // Deferred a tick so the effect body itself never sets state synchronously.
    queueMicrotask(() => void poll());
    start();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", onFocus);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("focus", onFocus);
    };
  }, [poll, pollIntervalMs]);

  const loadList = useCallback(async () => {
    setList((cur) => (cur.status === "ready" ? cur : { status: "loading" }));
    try {
      const { data } = await browserApi().GET("/api/v1/workspaces/{workspace_id}/notifications", {
        params: { path: { workspace_id: workspaceId }, query: { limit: LIST_LIMIT } },
      });
      if (!alive.current) return;
      if (data) setList({ status: "ready", items: data.items });
      else setList((cur) => (cur.status === "ready" ? cur : { status: "error" }));
    } catch {
      if (alive.current) setList((cur) => (cur.status === "ready" ? cur : { status: "error" }));
    }
  }, [workspaceId]);

  const setItemRead = useCallback((id: string, readAt: string | null) => {
    setList((cur) =>
      cur.status === "ready"
        ? {
            status: "ready",
            items: cur.items.map((n) => (n.id === id ? { ...n, read_at: readAt } : n)),
          }
        : cur,
    );
  }, []);

  const markRead = useCallback(
    async (n: NotificationOut) => {
      epoch.current++;
      setItemRead(n.id, new Date().toISOString());
      const decremented = countRef.current !== null && countRef.current > 0;
      if (decremented) applyCount((countRef.current ?? 1) - 1);
      let ok = false;
      try {
        const { data } = await browserApi().POST(
          "/api/v1/workspaces/{workspace_id}/notifications/{notification_id}/read",
          { params: { path: { workspace_id: workspaceId, notification_id: n.id } } },
        );
        ok = Boolean(data);
      } catch {
        ok = false;
      }
      if (!ok && alive.current) {
        epoch.current++;
        setItemRead(n.id, null);
        if (decremented) applyCount((countRef.current ?? 0) + 1);
      }
    },
    [workspaceId, setItemRead, applyCount],
  );

  const items = list.status === "ready" ? list.items : [];
  const hasUnreadItem = items.some((n) => !n.read_at);
  const unread = count ?? 0;

  const markAllRead = useCallback(async () => {
    epoch.current++;
    const prevCount = countRef.current;
    const snapshot = list;
    const stamp = new Date().toISOString();
    setList((cur) =>
      cur.status === "ready"
        ? {
            status: "ready",
            items: cur.items.map((n) => (n.read_at ? n : { ...n, read_at: stamp })),
          }
        : cur,
    );
    applyCount(0);
    let ok = false;
    try {
      const { data } = await browserApi().POST(
        "/api/v1/workspaces/{workspace_id}/notifications/read-all",
        { params: { path: { workspace_id: workspaceId } } },
      );
      ok = Boolean(data);
    } catch {
      ok = false;
    }
    if (!ok && alive.current) {
      epoch.current++;
      setList(snapshot);
      if (prevCount !== null) applyCount(prevCount);
    }
  }, [list, workspaceId, applyCount]);

  function activate(n: NotificationOut) {
    const href = safeLink(n.link);
    if (!n.read_at) void markRead(n);
    if (href) router.push(href);
  }

  const label = unread > 0 ? `Notifications, ${unread} unread` : "Notifications";

  return (
    <>
      <DropdownMenu onOpenChange={(open) => open && void loadList()}>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            size="icon"
            aria-label={label}
            className="relative text-muted hover:text-fg"
          >
            <Bell className="size-4" aria-hidden />
            {unread > 0 ? (
              <span
                aria-hidden
                className="absolute top-0.5 right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] leading-none font-semibold text-on-accent"
              >
                {unread > 9 ? "9+" : unread}
              </span>
            ) : null}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent className="max-h-[min(30rem,var(--radix-dropdown-menu-content-available-height))] w-80 max-w-[calc(100vw-2rem)] overflow-y-auto">
          <DropdownMenuLabel>Notifications</DropdownMenuLabel>
          <DropdownMenuItem
            disabled={unread === 0 && !hasUnreadItem}
            onSelect={(e) => {
              e.preventDefault();
              void markAllRead();
            }}
          >
            Mark all as read
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          {list.status === "error" ? (
            <>
              <p className="px-2.5 py-2 text-sm text-fg">Couldn&apos;t load notifications.</p>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault();
                  void loadList();
                }}
              >
                Try again
              </DropdownMenuItem>
            </>
          ) : list.status === "ready" ? (
            items.length === 0 ? (
              <div className="px-2.5 py-4">
                <p className="text-sm font-medium text-fg">You&apos;re all caught up</p>
                <p className="mt-1 text-[13px] text-muted">
                  Due tasks, reminders and approvals will show up here.
                </p>
              </div>
            ) : (
              items.map((n) => <NotificationRow key={n.id} n={n} onActivate={activate} />)
            )
          ) : (
            <p className="px-2.5 py-4 text-sm text-muted">Loading notifications…</p>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      <span role="status" className="sr-only">
        {announcement}
      </span>
    </>
  );
}

function NotificationRow({
  n,
  onActivate,
}: {
  n: NotificationOut;
  onActivate: (n: NotificationOut) => void;
}) {
  const unread = !n.read_at;
  const when = formatDateTime(n.created_at);
  return (
    <DropdownMenuItem className="items-start py-2" onSelect={() => onActivate(n)}>
      <span
        aria-hidden
        className={cn(
          "mt-1.5 size-2 shrink-0 rounded-full",
          unread ? "bg-accent" : "border border-line",
        )}
      />
      <span className="min-w-0 flex-1">
        <span className={cn("block text-sm break-words", unread ? "font-semibold" : "font-normal")}>
          {unread ? <span className="sr-only">Unread:</span> : null}
          {unread ? " " : null}
          {n.title}
        </span>
        {n.body ? (
          <span className="mt-0.5 line-clamp-2 block text-[13px] break-words text-muted">
            {n.body}
          </span>
        ) : null}
        {when ? (
          <time dateTime={n.created_at} className="mt-0.5 block text-xs text-muted">
            {when}
          </time>
        ) : null}
      </span>
    </DropdownMenuItem>
  );
}
