import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Providers } from "@/components/providers";
import { AppShell } from "./app-shell";
import { resetLocalStoreForTests } from "./local-store";

const push = vi.fn();
let pathname = "/leads";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push }),
}));

function renderShell() {
  return render(
    <Providers>
      <AppShell>
        <h1>Page</h1>
      </AppShell>
    </Providers>,
  );
}

beforeEach(() => {
  push.mockClear();
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
    expect(within(nav).getByRole("link", { name: /^Leads/ })).toHaveTextContent("Soon");
    expect(within(nav).getByRole("link", { name: /^Home/ })).not.toHaveTextContent("Soon");
  });

  it("collapses the sidebar, relabels links, and persists the choice", async () => {
    const user = userEvent.setup();
    const { unmount } = renderShell();
    await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
    expect(screen.getByRole("button", { name: "Expand sidebar" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("link", { name: "Leads (coming soon)" })).toBeInTheDocument();
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
