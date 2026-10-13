import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type { StopOut } from "./inbox-model";
import { StopBanner } from "./stop-banner";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const STOP: StopOut = {
  id: "00000000-0000-4000-8000-0000000000e1",
  address: "sam@acme.example",
  reason: "unsubscribe",
  since: "2026-10-11T09:30:00Z",
  text: "They asked not to be contacted, so nothing will be sent to them.",
};

type Call = { method: string; path: string };
function stubApi(respond: (call: Call) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const call: Call = {
        method: req.method,
        path: new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, ""),
      };
      calls.push(call);
      return respond(call);
    }),
  );
  return calls;
}

function setup(canEdit = true) {
  return render(
    <ToastProvider>
      <StopBanner workspaceId={WS} stop={STOP} canEdit={canEdit} />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("StopBanner", () => {
  it("explains the stop, the address and the date", () => {
    setup();
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("Contact stopped")).toBeInTheDocument();
    expect(within(alert).getByText(STOP.text)).toBeInTheDocument();
    expect(alert).toHaveTextContent("sam@acme.example, added 2026-10-11 09:30 UTC");
  });

  it("gives members no way to remove it", () => {
    setup(false);
    expect(screen.getByText("Contact stopped")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("asks first, with Cancel focused, and cancelling changes nothing", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => new Response(null, { status: 204 }));
    setup();
    await user.click(screen.getByRole("button", { name: "Remove from do-not-contact list" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Remove sam@acme.example from your/)).toBeInTheDocument();
    expect(within(dialog).getByText(/become possible again/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("removes the entry, says so, and refreshes", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => new Response(null, { status: 204 }));
    setup();
    await user.click(screen.getByRole("button", { name: "Remove from do-not-contact list" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove from list" }),
    );
    expect(await screen.findByText("Removed from the do-not-contact list")).toBeInTheDocument();
    expect(calls).toEqual([{ method: "DELETE", path: `/suppressions/${STOP.id}` }]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("shows the server's reason when it refuses, and does not refresh", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "forbidden", message: "Only the owner can do that." } },
        { status: 403 },
      ),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Remove from do-not-contact list" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove from list" }),
    );
    expect(await screen.findByText("Only the owner can do that.")).toBeInTheDocument();
    expect(screen.getByText("Couldn't remove it")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Remove from do-not-contact list" })).toBeEnabled();
  });

  it("survives a network failure", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Remove from do-not-contact list" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove from list" }),
    );
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("disables the button while the request is pending", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => undefined;
    const calls = stubApi(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }) as unknown as Response,
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Remove from do-not-contact list" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Remove from list" }),
    );
    const button = await screen.findByRole("button", { name: "Removing…" });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(calls).toHaveLength(1);
    release(new Response(null, { status: 204 }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
  });

  it("has no accessibility violations, also with the dialog open", async () => {
    const user = userEvent.setup();
    const rules = { rules: { "color-contrast": { enabled: false } } };
    const { container } = setup();
    expect((await axe.run(container, rules)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Remove from do-not-contact list" }));
    expect((await axe.run(await screen.findByRole("dialog"), rules)).violations).toEqual([]);
  });
});
