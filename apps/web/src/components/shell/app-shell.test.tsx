import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MeResponse } from "@freelancer-os/contracts";
import { Providers } from "@/components/providers";
import { SessionProvider } from "@/components/session-provider";
import { AppShell } from "./app-shell";
import { resetLocalStoreForTests } from "./local-store";

const push = vi.fn();
const hardNavigate = vi.fn();
vi.mock("@/lib/navigation", () => ({ hardNavigate: (p: string) => hardNavigate(p) }));
let pathname = "/leads";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push }),
}));

const ME: MeResponse = {
  user: { id: "u1", email: "ada@example.com", display_name: "Ada Lovelace", email_verified: false },
  workspaces: [
    {
      id: "w1",
      name: "Ada's workspace",
      kind: "personal",
      role: "owner",
      timezone: "UTC",
      demo_mode: false,
      onboarding_status: "completed",
    },
  ],
};

function renderShell(me: MeResponse = ME) {
  return render(
    <Providers>
      <SessionProvider me={me}>
        <AppShell>
          <h1>Page</h1>
        </AppShell>
      </SessionProvider>
    </Providers>,
  );
}

/** The shell polls the unread count on mount, so every test gets a stubbed API. */
function stubShellApi(unread = 0) {
  const fetchMock = vi.fn(async (req: Request) => {
    const path = new URL(req.url).pathname;
    if (path.endsWith("/notifications/unread-count")) return Response.json({ unread });
    return new Response(null, { status: 204 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => {
  stubShellApi();
  push.mockClear();
  hardNavigate.mockClear();
  pathname = "/leads";
  resetLocalStoreForTests();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AppShell", () => {
  it("renders landmarks, a skip link and marks the current page", () => {
    renderShell();
    expect(screen.getByRole("link", { name: "Skip to main content" })).toHaveAttribute(
      "href",
      "#main",
    );
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: /^Leads/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: /^Home/ })).not.toHaveAttribute("aria-current");
    expect(screen.getByRole("navigation", { name: "Breadcrumb" })).toBeInTheDocument();
  });

  it("marks planned destinations as Soon (not just by colour)", () => {
    renderShell();
    const nav = screen.getByRole("navigation", { name: "Primary" });
    expect(within(nav).getByRole("link", { name: /^Campaigns/ })).toHaveTextContent("Soon");
    expect(within(nav).getByRole("link", { name: /^Home/ })).not.toHaveTextContent("Soon");
    expect(within(nav).getByRole("link", { name: /^Leads/ })).not.toHaveTextContent("Soon");
  });

  it("collapses the sidebar, relabels links, and persists the choice", async () => {
    const user = userEvent.setup();
    const { unmount } = renderShell();
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("link", { name: "Campaigns (coming soon)" })).toBeInTheDocument();
    expect(window.localStorage.getItem("fos-sidebar-collapsed")).toBe("1");
    unmount();
    resetLocalStoreForTests();
    renderShell();
    expect(await screen.findByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
  });

  it("opens the command palette with Ctrl+K and navigates", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByRole("dialog", { name: "Command palette" })).toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: /Pipeline/ }));
    expect(push).toHaveBeenCalledWith("/pipeline");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("switches theme from the palette, applies data-theme and persists", async () => {
    const user = userEvent.setup();
    renderShell();
    await user.keyboard("{Control>}k{/Control}");
    await user.click(screen.getByRole("option", { name: /Use light theme/ }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("fos-theme")).toBe("light");
  });

  it("keeps working when localStorage is blocked", async () => {
    const user = userEvent.setup();
    const spy = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderShell();
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toBeInTheDocument();
    spy.mockRestore();
  });

  it("shows the real workspace and nudges unfinished onboarding (but not once completed)", () => {
    const { unmount } = renderShell();
    expect(screen.getByRole("button", { name: "Workspace: Ada's workspace" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Profile setup" })).toBeNull();
    unmount();
    const first = ME.workspaces[0];
    if (!first) throw new Error("fixture");
    renderShell({ ...ME, workspaces: [{ ...first, onboarding_status: "skipped" }] });
    const banner = screen.getByRole("region", { name: "Profile setup" });
    expect(within(banner).getByRole("link", { name: "Continue setup" })).toHaveAttribute(
      "href",
      "/onboarding",
    );
  });

  it("shows the signed-in user and signs out via the API", async () => {
    const user = userEvent.setup();
    const fetchMock = stubShellApi();
    renderShell();
    await user.click(screen.getByRole("button", { name: "Account menu" }));
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    const signOuts = (fetchMock.mock.calls as unknown as [Request][])
      .map(([req]) => req)
      .filter((req) => new URL(req.url).pathname === "/api/v1/auth/sign-out");
    expect(signOuts).toHaveLength(1);
    expect(signOuts[0]?.method).toBe("POST");
    expect(signOuts[0]?.headers.get("x-requested-with")).toBe("freelancer-os");
    expect(hardNavigate).toHaveBeenCalledWith("/sign-in");
  });

  it("shows the unread notification count on the bell in the top bar", async () => {
    stubShellApi(3);
    renderShell();
    expect(
      await screen.findByRole("button", { name: "Notifications, 3 unread" }),
    ).toBeInTheDocument();
  });

  it("has no structural accessibility violations", async () => {
    stubShellApi(2);
    const { container } = renderShell();
    await screen.findByRole("button", { name: "Notifications, 2 unread" });
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
    });
    expect(
      results.violations.map(
        (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
      ),
    ).toEqual([]);
  });
});
