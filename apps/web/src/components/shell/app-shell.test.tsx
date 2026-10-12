import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

beforeEach(() => {
  push.mockClear();
  hardNavigate.mockClear();
  pathname = "/leads";
  resetLocalStoreForTests();
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
    expect(within(nav).getByRole("link", { name: /^Inbox/ })).toHaveTextContent("Soon");
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
    expect(screen.getByRole("link", { name: "Inbox (coming soon)" })).toBeInTheDocument();
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
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    renderShell();
    await user.click(screen.getByRole("button", { name: "Account menu" }));
    expect(screen.getByText("ada@example.com")).toBeInTheDocument();
    await user.click(screen.getByRole("menuitem", { name: /Sign out/ }));
    expect(fetchMock).toHaveBeenCalledOnce();
    const req = fetchMock.mock.calls[0] as unknown as [Request];
    expect(req[0].method).toBe("POST");
    expect(new URL(req[0].url).pathname).toBe("/api/v1/auth/sign-out");
    expect(req[0].headers.get("x-requested-with")).toBe("freelancer-os");
    expect(hardNavigate).toHaveBeenCalledWith("/sign-in");
    vi.unstubAllGlobals();
  });

  it("has no structural accessibility violations", async () => {
    const { container } = renderShell();
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
