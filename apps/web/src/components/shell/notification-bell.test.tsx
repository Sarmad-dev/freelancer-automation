import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MeResponse } from "@freelancer-os/contracts";
import { SessionProvider } from "@/components/session-provider";
import { NotificationBell, safeLink } from "./notification-bell";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const WS_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const WS_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

function me(workspaceId: string): MeResponse {
  return {
    user: { id: "u1", email: "ada@example.com", display_name: "Ada", email_verified: true },
    workspaces: [
      {
        id: workspaceId,
        name: "Workspace",
        kind: "personal",
        role: "owner",
        timezone: "UTC",
        demo_mode: false,
        onboarding_status: "completed",
      },
    ],
  };
}

interface N {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  link: string | null;
  read_at: string | null;
  created_at: string;
}

function note(over: Partial<N> = {}): N {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    kind: "task_due",
    title: "Send the invoice is due",
    body: "Due today at 17:00",
    link: "/tasks",
    read_at: null,
    created_at: "2026-10-01T09:30:00Z",
    ...over,
  };
}

const N1 = note();
const N2 = note({
  id: "22222222-2222-4222-8222-222222222222",
  kind: "task_reminder",
  title: "Reminder: call Grace",
  body: null,
  link: "/leads",
  created_at: "2026-09-30T08:00:00Z",
});
const N3 = note({
  id: "33333333-3333-4333-8333-333333333333",
  title: "Already handled",
  body: null,
  link: null,
  read_at: "2026-09-30T10:00:00Z",
  created_at: "2026-09-29T08:00:00Z",
});

type Handler = (req: Request) => Response | Promise<Response>;
interface Call {
  method: string;
  path: string;
  search: string;
}

/** A tiny fake API keyed by "METHOD /suffix-after-workspace". */
function stubApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const url = new URL(req.url);
      const path = url.pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      calls.push({ method: req.method, path: url.pathname, search: url.search });
      const key = `${req.method} ${path.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/, ":id")}`;
      const handler = routes[key];
      if (!handler) return new Response("{}", { status: 404 });
      return handler(req);
    }),
  );
  return {
    calls,
    count: (suffix: string) => calls.filter((c) => c.path.endsWith(suffix)).length,
  };
}

const unreadRoute =
  (n: number): Handler =>
  () =>
    Response.json({ unread: n });
const listRoute =
  (items: N[]): Handler =>
  () =>
    Response.json({ items, total: items.length, limit: 10, offset: 0 });
const serverError: Handler = () =>
  Response.json({ error: { code: "boom", message: "Boom" } }, { status: 500 });

const FAST = 25;

function ui(workspaceId = WS_A, pollIntervalMs = 60_000) {
  return (
    <SessionProvider me={me(workspaceId)}>
      <NotificationBell pollIntervalMs={pollIntervalMs} />
    </SessionProvider>
  );
}

let visibility: DocumentVisibilityState = "visible";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

beforeEach(() => {
  push.mockClear();
  visibility = "visible";
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => visibility,
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(document, "visibilityState");
});

async function openMenu() {
  const user = userEvent.setup();
  const trigger = await screen.findByRole("button", { name: /^Notifications/ });
  await user.click(trigger);
  return user;
}

describe("NotificationBell badge", () => {
  it("has no badge and a plain name with nothing unread", async () => {
    const api = stubApi({ "GET /notifications/unread-count": unreadRoute(0) });
    render(ui());
    await waitFor(() => expect(api.count("/unread-count")).toBe(1));
    const bell = screen.getByRole("button", { name: "Notifications" });
    expect(bell).toHaveTextContent("");
  });

  it("shows the exact number for a small count and names the state", async () => {
    stubApi({ "GET /notifications/unread-count": unreadRoute(3) });
    render(ui());
    const bell = await screen.findByRole("button", { name: "Notifications, 3 unread" });
    expect(bell).toHaveTextContent("3");
  });

  it("caps the visible badge at 9+ but keeps the exact number in the name", async () => {
    stubApi({ "GET /notifications/unread-count": unreadRoute(12) });
    render(ui());
    const bell = await screen.findByRole("button", { name: "Notifications, 12 unread" });
    expect(bell).toHaveTextContent("9+");
    expect(bell).not.toHaveTextContent("12");
  });
});

describe("NotificationBell polling", () => {
  it("polls once on mount and uses the workspace-scoped endpoint", async () => {
    const api = stubApi({ "GET /notifications/unread-count": unreadRoute(1) });
    render(ui());
    await screen.findByRole("button", { name: "Notifications, 1 unread" });
    expect(api.count("/unread-count")).toBe(1);
    expect(api.calls[0]?.path).toBe(`/api/v1/workspaces/${WS_A}/notifications/unread-count`);
  });

  it("polls again on every interval while the tab is visible", async () => {
    const api = stubApi({ "GET /notifications/unread-count": unreadRoute(1) });
    render(ui(WS_A, FAST));
    await waitFor(() => expect(api.count("/unread-count")).toBeGreaterThanOrEqual(3));
  });

  it("picks up a new count from a later poll", async () => {
    let n = 0;
    stubApi({ "GET /notifications/unread-count": () => Response.json({ unread: n }) });
    render(ui(WS_A, FAST));
    await screen.findByRole("button", { name: "Notifications" });
    n = 2;
    await screen.findByRole("button", { name: "Notifications, 2 unread" });
  });

  it("polls when the window regains focus", async () => {
    const api = stubApi({ "GET /notifications/unread-count": unreadRoute(0) });
    render(ui());
    await waitFor(() => expect(api.count("/unread-count")).toBe(1));
    fireEvent.focus(window);
    await waitFor(() => expect(api.count("/unread-count")).toBe(2));
  });

  it("polls when the tab becomes visible again", async () => {
    const api = stubApi({ "GET /notifications/unread-count": unreadRoute(0) });
    render(ui());
    await waitFor(() => expect(api.count("/unread-count")).toBe(1));
    visibility = "hidden";
    fireEvent(document, new Event("visibilitychange"));
    visibility = "visible";
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(api.count("/unread-count")).toBe(2));
  });

  it("does not poll while the tab is hidden, then resumes", async () => {
    const api = stubApi({ "GET /notifications/unread-count": unreadRoute(0) });
    render(ui(WS_A, FAST));
    await waitFor(() => expect(api.count("/unread-count")).toBeGreaterThanOrEqual(2));
    visibility = "hidden";
    fireEvent(document, new Event("visibilitychange"));
    await sleep(FAST * 2);
    const before = api.count("/unread-count");
    fireEvent.focus(window);
    await sleep(FAST * 6);
    expect(api.count("/unread-count")).toBe(before);
    visibility = "visible";
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(api.count("/unread-count")).toBeGreaterThan(before));
  });

  it("stops polling and removes listeners on unmount", async () => {
    const api = stubApi({ "GET /notifications/unread-count": unreadRoute(0) });
    const removeDoc = vi.spyOn(document, "removeEventListener");
    const removeWin = vi.spyOn(window, "removeEventListener");
    const { unmount } = render(ui(WS_A, FAST));
    await waitFor(() => expect(api.count("/unread-count")).toBeGreaterThanOrEqual(2));
    unmount();
    expect(removeDoc).toHaveBeenCalledWith("visibilitychange", expect.any(Function));
    expect(removeWin).toHaveBeenCalledWith("focus", expect.any(Function));
    await sleep(FAST);
    const after = api.count("/unread-count");
    await sleep(FAST * 5);
    expect(api.count("/unread-count")).toBe(after);
    removeDoc.mockRestore();
    removeWin.mockRestore();
  });

  it("keeps the last known count, silently, when a poll fails", async () => {
    let fail = false;
    const api = stubApi({
      "GET /notifications/unread-count": () =>
        fail ? serverError(new Request("http://x")) : Response.json({ unread: 3 }),
    });
    render(ui(WS_A, FAST));
    await screen.findByRole("button", { name: "Notifications, 3 unread" });
    fail = true;
    const before = api.count("/unread-count");
    await waitFor(() => expect(api.count("/unread-count")).toBeGreaterThanOrEqual(before + 2));
    expect(screen.getByRole("button", { name: "Notifications, 3 unread" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("survives a network error on the first poll", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    render(ui());
    await sleep(20);
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("NotificationBell menu", () => {
  it("loads the 10 newest notifications when opened", async () => {
    const api = stubApi({
      "GET /notifications/unread-count": unreadRoute(2),
      "GET /notifications": listRoute([N1, N2, N3]),
    });
    render(ui());
    await openMenu();
    const items = await screen.findAllByRole("menuitem", {
      name: /Send the invoice|Reminder|Already/,
    });
    expect(items).toHaveLength(3);
    const list = api.calls.find((c) => c.path.endsWith("/notifications"));
    expect(list?.search).toBe("?limit=10");
    const first = screen.getByRole("menuitem", { name: /Send the invoice is due/ });
    expect(within(first).getByText("Due today at 17:00")).toBeInTheDocument();
    expect(within(first).getByText("2026-10-01 09:30 UTC")).toBeInTheDocument();
  });

  it("shows a loading state before the list arrives", async () => {
    let release: (r: Response) => void = () => {};
    stubApi({
      "GET /notifications/unread-count": unreadRoute(0),
      "GET /notifications": () => new Promise<Response>((r) => (release = r)),
    });
    render(ui());
    await openMenu();
    expect(await screen.findByText("Loading notifications…")).toBeInTheDocument();
    release(Response.json({ items: [], total: 0, limit: 10, offset: 0 }));
    expect(await screen.findByText("You're all caught up")).toBeInTheDocument();
  });

  it("shows an empty state and disables Mark all as read", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(0),
      "GET /notifications": listRoute([]),
    });
    render(ui());
    await openMenu();
    expect(await screen.findByText("You're all caught up")).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Mark all as read" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  it("shows an inline error with a working retry when the list fails", async () => {
    let fail = true;
    const api = stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": (req) => (fail ? serverError(req) : listRoute([N1])(req)),
    });
    render(ui());
    const user = await openMenu();
    expect(await screen.findByText("Couldn't load notifications.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    fail = false;
    await user.click(screen.getByRole("menuitem", { name: "Try again" }));
    expect(await screen.findByRole("menuitem", { name: /Send the invoice/ })).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load notifications.")).toBeNull();
    expect(api.calls.filter((c) => c.path.endsWith("/notifications"))).toHaveLength(2);
  });

  it("shows a network failure of the list as the same inline error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (req: Request) => {
        if (req.url.endsWith("unread-count")) return Response.json({ unread: 0 });
        throw new TypeError("offline");
      }),
    );
    render(ui());
    await openMenu();
    expect(await screen.findByText("Couldn't load notifications.")).toBeInTheDocument();
  });

  it("marks unread items with text, not only a dot or colour", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(2),
      "GET /notifications": listRoute([N1, N2, N3]),
    });
    render(ui());
    await openMenu();
    expect(await screen.findByRole("menuitem", { name: /Unread: Send the invoice/ })).toBeVisible();
    expect(screen.getByRole("menuitem", { name: /Unread: Reminder: call Grace/ })).toBeVisible();
    const read = screen.getByRole("menuitem", { name: /Already handled/ });
    expect(read).not.toHaveTextContent("Unread:");
  });

  it("closes on Escape and returns focus to the bell", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": listRoute([N1]),
    });
    render(ui());
    const user = await openMenu();
    await screen.findByRole("menuitem", { name: /Send the invoice/ });
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).toBeNull();
    expect(screen.getByRole("button", { name: "Notifications, 1 unread" })).toHaveFocus();
  });

  it("can be operated with the keyboard alone", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": listRoute([N1]),
      "POST /notifications/:id/read": () =>
        Response.json({ ...N1, read_at: "2026-10-02T00:00:00Z" }),
    });
    render(ui());
    const user = userEvent.setup();
    const bell = await screen.findByRole("button", { name: "Notifications, 1 unread" });
    bell.focus();
    await user.keyboard("{Enter}");
    await screen.findByRole("menuitem", { name: /Send the invoice/ });
    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    await waitFor(() => expect(push).toHaveBeenCalledWith("/tasks"));
  });
});

describe("NotificationBell actions", () => {
  it("marks an item read optimistically and follows its safe link", async () => {
    let release: (r: Response) => void = () => {};
    const api = stubApi({
      "GET /notifications/unread-count": unreadRoute(3),
      "GET /notifications": listRoute([N1, N2]),
      "POST /notifications/:id/read": () => new Promise<Response>((r) => (release = r)),
    });
    render(ui());
    const user = await openMenu();
    await screen.findByRole("button", { name: "Notifications, 3 unread", hidden: true });
    await user.click(await screen.findByRole("menuitem", { name: /Send the invoice/ }));
    // Optimistic: the count drops before the server answers.
    expect(
      screen.getByRole("button", { name: "Notifications, 2 unread", hidden: true }),
    ).toBeInTheDocument();
    expect(push).toHaveBeenCalledWith("/tasks");
    release(Response.json({ ...N1, read_at: "2026-10-02T00:00:00Z" }));
    await waitFor(() => expect(api.count(`/${N1.id}/read`)).toBe(1));
    expect(
      screen.getByRole("button", { name: "Notifications, 2 unread", hidden: true }),
    ).toBeInTheDocument();
    expect(api.calls.find((c) => c.method === "POST")?.path).toBe(
      `/api/v1/workspaces/${WS_A}/notifications/${N1.id}/read`,
    );
  });

  it("rolls the count and the unread marker back when marking read fails", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(3),
      "GET /notifications": listRoute([N1, N2]),
      "POST /notifications/:id/read": serverError,
    });
    render(ui());
    const user = await openMenu();
    await user.click(await screen.findByRole("menuitem", { name: /Send the invoice/ }));
    await screen.findByRole("button", { name: "Notifications, 3 unread" });
    await user.click(screen.getByRole("button", { name: "Notifications, 3 unread" }));
    expect(await screen.findByRole("menuitem", { name: /Unread: Send the invoice/ })).toBeVisible();
  });

  it("rolls back when the read request cannot reach the server", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (req: Request) => {
        const path = new URL(req.url).pathname;
        if (path.endsWith("unread-count")) return Response.json({ unread: 1 });
        if (req.method === "GET") return listRoute([N1])(req);
        throw new TypeError("offline");
      }),
    );
    render(ui());
    const user = await openMenu();
    await user.click(await screen.findByRole("menuitem", { name: /Send the invoice/ }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Notifications, 1 unread" })).toBeInTheDocument(),
    );
  });

  it("marks read without navigating when there is no link", async () => {
    const unreadNoLink = note({ link: null });
    const api = stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": listRoute([unreadNoLink]),
      "POST /notifications/:id/read": () => Response.json({ ...unreadNoLink, read_at: "x" }),
    });
    render(ui());
    const user = await openMenu();
    await user.click(await screen.findByRole("menuitem", { name: /Send the invoice/ }));
    await screen.findByRole("button", { name: "Notifications" });
    expect(api.count("/read")).toBe(1);
    expect(push).not.toHaveBeenCalled();
  });

  it("does not call the API again for an item that is already read, but still navigates", async () => {
    const readWithLink = note({ id: N3.id, read_at: "2026-09-30T10:00:00Z", link: "/pipeline" });
    const api = stubApi({
      "GET /notifications/unread-count": unreadRoute(0),
      "GET /notifications": listRoute([readWithLink]),
    });
    render(ui());
    const user = await openMenu();
    await user.click(await screen.findByRole("menuitem", { name: /Send the invoice/ }));
    expect(push).toHaveBeenCalledWith("/pipeline");
    expect(api.calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it.each([
    "//evil.example",
    "https://evil.example/x",
    "javascript:alert(1)",
    "/\\evil.example",
    "tasks",
  ])("never navigates to the unsafe link %s", async (link) => {
    const api = stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": listRoute([note({ link })]),
      "POST /notifications/:id/read": () => Response.json({ ...N1, read_at: "x" }),
    });
    render(ui());
    const user = await openMenu();
    await user.click(await screen.findByRole("menuitem", { name: /Send the invoice/ }));
    await waitFor(() => expect(api.count("/read")).toBe(1));
    expect(push).not.toHaveBeenCalled();
  });

  it("marks everything read, keeps the menu open and announces it politely", async () => {
    const api = stubApi({
      "GET /notifications/unread-count": unreadRoute(2),
      "GET /notifications": listRoute([N1, N2, N3]),
      "POST /notifications/read-all": () => Response.json({ marked: 2 }),
    });
    render(ui());
    const status = screen.getByRole("status");
    expect(status).toBeEmptyDOMElement();
    const user = await openMenu();
    await screen.findByRole("menuitem", { name: /Unread: Send the invoice/ });
    // The first known count is not announced.
    expect(status).toBeEmptyDOMElement();
    await user.click(screen.getByRole("menuitem", { name: "Mark all as read" }));
    expect(
      await screen.findByRole("button", { name: "Notifications", hidden: true }),
    ).toBeInTheDocument();
    expect(api.count("/read-all")).toBe(1);
    expect(screen.getByRole("menu")).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Unread:/ })).toBeNull();
    expect(screen.getByRole("menuitem", { name: "Mark all as read" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(status).toHaveTextContent("No unread notifications");
    expect(status).toHaveAttribute("role", "status");
  });

  it("restores the count and markers when mark all fails", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(2),
      "GET /notifications": listRoute([N1, N2]),
      "POST /notifications/read-all": serverError,
    });
    render(ui());
    const user = await openMenu();
    await screen.findByRole("menuitem", { name: /Unread: Send the invoice/ });
    await user.click(screen.getByRole("menuitem", { name: "Mark all as read" }));
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Notifications, 2 unread", hidden: true }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("menuitem", { name: /Unread: Send the invoice/ })).toBeVisible();
  });
});

describe("NotificationBell safety and scoping", () => {
  it("renders hostile titles and bodies as inert text", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": listRoute([note({ title: hostile, body: "<b>bold</b>" })]),
    });
    render(ui());
    await openMenu();
    expect(await screen.findByText(new RegExp("onerror"))).toBeInTheDocument();
    expect(screen.getByText("<b>bold</b>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
  });

  it("drops all state and polls the new workspace when the workspace changes", async () => {
    const api = stubApi({
      "GET /notifications/unread-count": (req) =>
        Response.json({ unread: req.url.includes(WS_A) ? 5 : 0 }),
      "GET /notifications": listRoute([N1]),
    });
    const { rerender } = render(ui(WS_A));
    await screen.findByRole("button", { name: "Notifications, 5 unread" });
    rerender(ui(WS_B));
    // Immediately reset, never showing workspace A's count against workspace B.
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
    await waitFor(() =>
      expect(api.calls.some((c) => c.path.includes(`/workspaces/${WS_B}/`))).toBe(true),
    );
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
  });

  it("does not show another workspace's list after switching", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": (req) => listRoute(req.url.includes(WS_A) ? [N1] : [N2])(req),
    });
    const { rerender } = render(ui(WS_A));
    const user = await openMenu();
    await screen.findByRole("menuitem", { name: /Send the invoice/ });
    await user.keyboard("{Escape}");
    rerender(ui(WS_B));
    await user.click(await screen.findByRole("button", { name: /^Notifications/ }));
    expect(
      await screen.findByRole("menuitem", { name: /Reminder: call Grace/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /Send the invoice/ })).toBeNull();
  });
});

describe("NotificationBell accessibility", () => {
  const rules = { "color-contrast": { enabled: false }, region: { enabled: false } };

  it("has no axe violations while closed", async () => {
    stubApi({ "GET /notifications/unread-count": unreadRoute(3) });
    const { container } = render(ui());
    await screen.findByRole("button", { name: "Notifications, 3 unread" });
    const results = await axe.run(container, { rules });
    expect(
      results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(", ")}`),
    ).toEqual([]);
  });

  it.each([
    ["with notifications", [N1, N2, N3]],
    ["empty", []],
  ])("has no axe violations while open (%s)", async (_name, items) => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(2),
      "GET /notifications": listRoute(items),
    });
    render(ui());
    await openMenu();
    await screen.findByRole(
      items.length ? "menuitem" : "menu",
      items.length ? { name: /Send the invoice/ } : {},
    );
    if (!items.length) await screen.findByText("You're all caught up");
    const results = await axe.run(document.body, { rules });
    expect(
      results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(", ")}`),
    ).toEqual([]);
  });

  it("has no axe violations in the loading and error states", async () => {
    stubApi({
      "GET /notifications/unread-count": unreadRoute(1),
      "GET /notifications": serverError,
    });
    render(ui());
    await openMenu();
    await screen.findByText("Couldn't load notifications.");
    const results = await axe.run(document.body, { rules });
    expect(
      results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.html).join(", ")}`),
    ).toEqual([]);
  });
});

describe("safeLink", () => {
  it.each(["/tasks", "/leads/123", "/pipeline?stage=won", "/tasks#top"])("accepts %s", (l) => {
    expect(safeLink(l)).toBe(l);
  });
  it.each([
    null,
    "",
    "//evil.example",
    "///evil.example",
    "https://evil.example",
    "http://evil.example",
    "javascript:alert(1)",
    "data:text/html,x",
    "tasks",
    "/\\evil.example",
    "/ok\nnext",
    "/\t/evil.example",
  ])("rejects %j", (l) => {
    expect(safeLink(l)).toBeNull();
  });
});
