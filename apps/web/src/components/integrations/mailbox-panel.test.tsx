import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { MailboxPanel } from "./mailbox-panel";
import type { EmailAccountOut, Flash, ProviderOut } from "./mailbox-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";

const account = (over: Partial<EmailAccountOut> = {}): EmailAccountOut => ({
  id: "00000000-0000-4000-8000-0000000000a1",
  provider: "gmail",
  email_address: "me@gmail.example",
  display_name: null,
  status: "connected",
  status_label: "Connected",
  is_demo: false,
  needs_reconnect: false,
  granted_scopes: [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
  ],
  last_synced_at: "2026-10-12T14:05:00Z",
  last_health_check_at: "2026-10-12T14:06:00Z",
  rate_limited_until: null,
  last_error_code: null,
  last_error: null,
  created_at: "2026-10-12T10:00:00Z",
  ...over,
});

const DEMO_ACCOUNT = account({
  id: "00000000-0000-4000-8000-0000000000d1",
  provider: "demo",
  email_address: "alex@alex-rivera.example",
  status: "demo",
  status_label: "Demo mailbox: no real email is sent or received",
  is_demo: true,
  granted_scopes: [],
  last_synced_at: null,
  last_health_check_at: null,
});

const GMAIL: ProviderOut = {
  key: "gmail",
  label: "Gmail",
  is_demo: false,
  configured: true,
  capabilities: ["oauth", "sync", "send"],
  scopes: [
    {
      scope: "https://www.googleapis.com/auth/gmail.readonly",
      why: "Read your conversations so replies appear in the inbox.",
    },
    {
      scope: "https://www.googleapis.com/auth/gmail.send",
      why: "Send only the messages you have approved.",
    },
  ],
  setup_doc: "docs/EMAIL.md#configure-gmail",
  notes: ["Not verified against a live Google account."],
  verified_live: false,
};
const DEMO: ProviderOut = {
  key: "demo",
  label: "Demo mailbox",
  is_demo: true,
  configured: true,
  capabilities: ["sync"],
  scopes: [],
  setup_doc: null,
  notes: ["Sending is simulated: nothing is delivered to anyone."],
  verified_live: false,
};

type Call = { method: string; path: string; body: unknown };
function stubApi(respond: (call: Call) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const text = await req.clone().text();
      const call: Call = {
        method: req.method,
        path: new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, ""),
        body: text ? JSON.parse(text) : undefined,
      };
      calls.push(call);
      return respond(call);
    }),
  );
  return calls;
}

function setup(
  props: Partial<{
    accounts: EmailAccountOut[];
    providers: ProviderOut[];
    canEdit: boolean;
    flash: Flash | null;
  }> = {},
) {
  const navigate = vi.fn();
  const view = render(
    <ToastProvider>
      <MailboxPanel
        workspaceId={WS}
        accounts={props.accounts ?? []}
        providers={props.providers ?? [DEMO, GMAIL]}
        canEdit={props.canEdit ?? true}
        flash={props.flash ?? null}
        navigate={navigate}
      />
    </ToastProvider>,
  );
  return { navigate, ...view };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("what is shown", () => {
  it("starts with an honest empty state and the connectors that exist", () => {
    setup();
    expect(screen.getByText("No mailbox yet")).toBeInTheDocument();
    const gmail = screen.getByRole("article", { name: "Gmail" });
    expect(within(gmail).getByText("Not verified live")).toBeInTheDocument();
    expect(
      within(gmail).getByText(/Not verified against a live Google account/),
    ).toBeInTheDocument();
    expect(within(gmail).getByText(/gmail\.readonly/)).toBeInTheDocument();
    expect(within(gmail).getByText(/Read your conversations/)).toBeInTheDocument();
    const demo = screen.getByRole("article", { name: "Demo mailbox" });
    expect(within(demo).getByText("Demo")).toBeInTheDocument();
    expect(screen.queryByText(/calendar|Outlook|Slack/i)).toBeNull(); // nothing that does not exist is listed
  });

  it("says plainly when the server has no credentials, and does not offer a dead button", () => {
    setup({ providers: [DEMO, { ...GMAIL, configured: false }] });
    const gmail = screen.getByRole("article", { name: "Gmail" });
    expect(within(gmail).getByText("Not set up")).toBeInTheDocument();
    expect(within(gmail).getByText(/no Gmail credentials yet/)).toBeInTheDocument();
    expect(within(gmail).getByRole("button", { name: "Connect Gmail" })).toBeDisabled();
  });

  it("describes a connected mailbox, with times in UTC and its permissions", () => {
    setup({ accounts: [account()] });
    const card = screen.getByRole("article", { name: "me@gmail.example" });
    expect(within(card).getByText("Connected", { selector: "span" })).toBeInTheDocument();
    expect(within(card).getByText("2026-10-12 14:05 UTC")).toBeInTheDocument();
    expect(within(card).getByText("2026-10-12 14:06 UTC")).toBeInTheDocument();
    expect(within(card).getByText("gmail.readonly, gmail.send")).toBeInTheDocument();
    for (const name of [
      /Sync me@gmail.example now/,
      /Test the connection/,
      /Disconnect me@gmail.example/,
    ]) {
      expect(within(card).getByRole("button", { name })).toBeEnabled();
    }
    expect(within(card).queryByRole("button", { name: /Reconnect/ })).toBeNull();
  });

  it("labels the demo mailbox and never offers a disconnect or a connection test for it", () => {
    setup({ accounts: [DEMO_ACCOUNT] });
    const card = screen.getByRole("article", { name: "alex@alex-rivera.example" });
    expect(within(card).getByText(/no real email is sent or received/)).toBeInTheDocument();
    expect(within(card).getByText("Sample")).toBeInTheDocument();
    expect(within(card).getAllByText("Never", { selector: "dd" })).toHaveLength(2);
    expect(within(card).getByRole("button", { name: /Sync/ })).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /Disconnect|Test/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Demo mailbox added" })).toBeDisabled();
  });

  it("makes a revoked connection impossible to miss and offers only reconnect and disconnect", () => {
    setup({
      accounts: [
        account({
          status: "needs_reauth",
          status_label: "Reconnect needed",
          needs_reconnect: true,
          last_error_code: "access_revoked",
          last_error: "Access to this mailbox was removed or expired. Reconnect it to continue.",
        }),
      ],
    });
    const card = screen.getByRole("article", { name: "me@gmail.example" });
    expect(within(card).getAllByText("Reconnect needed").length).toBeGreaterThan(0);
    expect(within(card).getByRole("alert")).toHaveTextContent(/removed or expired/);
    expect(
      within(card).getByRole("button", { name: "Reconnect me@gmail.example" }),
    ).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /Sync|Test/ })).toBeNull();
    expect(within(card).getByRole("button", { name: /Disconnect/ })).toBeInTheDocument();
  });

  it("shows a provider pause and a disconnected mailbox", () => {
    setup({
      accounts: [
        account({ rate_limited_until: "2026-10-12T15:00:00Z" }),
        account({
          id: "00000000-0000-4000-8000-0000000000a2",
          email_address: "old@gmail.example",
          status: "disconnected",
          status_label: "Disconnected",
          granted_scopes: [],
        }),
      ],
    });
    expect(screen.getByText(/resume after 2026-10-12 15:00 UTC/)).toBeInTheDocument();
    const old = screen.getByRole("article", { name: "old@gmail.example" });
    expect(
      within(old).getByRole("button", { name: "Connect old@gmail.example" }),
    ).toHaveTextContent("Connect again");
  });

  it("shows the result banner from the provider redirect", () => {
    setup({
      flash: {
        tone: "danger",
        title: "The mailbox was not connected",
        text: "You declined access.",
      },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("You declined access.");
  });

  it("is read-only for members", () => {
    setup({ accounts: [account()], canEdit: false });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("actions", () => {
  it("adds the demo mailbox and refreshes", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(DEMO_ACCOUNT, { status: 201 }));
    setup();
    await user.click(screen.getByRole("button", { name: "Add demo mailbox" }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(calls).toEqual([{ method: "POST", path: "/email/accounts/demo", body: undefined }]);
    expect(
      await screen.findByText(/fictional data and never sends real email/),
    ).toBeInTheDocument();
  });

  it("starts a connection and leaves for the provider's consent screen", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json({ authorization_url: "https://accounts.example/consent?state=abc" }),
    );
    const { navigate } = setup();
    await user.click(screen.getByRole("button", { name: "Connect Gmail" }));
    await waitFor(() =>
      expect(navigate).toHaveBeenCalledWith("https://accounts.example/consent?state=abc"),
    );
    expect(calls[0]).toEqual({
      method: "POST",
      path: "/email/accounts/connect",
      body: { provider: "gmail" },
    });
  });

  it("reconnects through the same flow", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json({ authorization_url: "https://accounts.example/again" }));
    const { navigate } = setup({
      accounts: [account({ status: "needs_reauth", needs_reconnect: true })],
    });
    await user.click(screen.getByRole("button", { name: "Reconnect me@gmail.example" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("https://accounts.example/again"));
  });

  it("explains a refusal to start a connection and does not navigate", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "provider_not_configured",
            message: "Gmail is not set up on this server.",
          },
        },
        { status: 409 },
      ),
    );
    const { navigate } = setup();
    await user.click(screen.getByRole("button", { name: "Connect Gmail" }));
    expect(await screen.findByText("Gmail is not set up on this server.")).toBeInTheDocument();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("syncs and reports what arrived", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json({
        account: account(),
        conversations_created: 3,
        messages_created: 6,
        messages_updated: 0,
        skipped: 0,
        pages: 1,
        complete: true,
        rate_limited_until: null,
        error_code: null,
      }),
    );
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Sync me@gmail.example now/ }));
    expect(await screen.findByText("6 new messages in 3 new conversations.")).toBeInTheDocument();
    expect(calls[0]!.path).toMatch(/^\/email\/accounts\/[^/]+\/sync$/);
    expect(refresh).toHaveBeenCalled();
  });

  it("tells people when the provider asked to slow down, with the server's words", async () => {
    const user = userEvent.setup();
    stubApi(
      () =>
        new Response(
          JSON.stringify({
            error: {
              code: "rate_limited",
              message: "The email provider asked us to slow down. Try again later.",
            },
          }),
          { status: 429, headers: { "content-type": "application/json", "retry-after": "60" } },
        ),
    );
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Sync me@gmail.example now/ }));
    expect(await screen.findByText(/asked us to slow down/)).toBeInTheDocument();
    expect(screen.getByText("Couldn't sync")).toBeInTheDocument();
  });

  it("tests a connection and says whether it really worked", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ ok: true, account: account() }));
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Test the connection/ }));
    expect(await screen.findByText("Connection works")).toBeInTheDocument();
    expect(calls[0]!.path).toMatch(/\/test$/);
  });

  it("reports a failed test as a failure", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json({
        ok: false,
        account: account({
          last_error:
            "The email provider is not responding. The last sync did not finish; try again shortly.",
        }),
      }),
    );
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Test the connection/ }));
    expect(await screen.findByText("The connection test failed")).toBeInTheDocument();
    expect(screen.getAllByText(/not responding/).length).toBeGreaterThan(0);
  });

  it("asks before disconnecting, with Cancel as the safe default, then reports the revocation", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json({ account: account({ status: "disconnected" }), revoked: true }),
    );
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Disconnect me@gmail.example/ }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText(/revoke access and delete our stored credentials/),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(calls).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    expect(
      await screen.findByText(/Access was revoked and the stored credentials were deleted/),
    ).toBeInTheDocument();
    expect(calls[0]!.path).toMatch(/\/disconnect$/);
  });

  it("does not claim access was revoked when the provider could not confirm it", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json({ account: account({ status: "disconnected" }), revoked: false }));
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Disconnect me@gmail.example/ }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Disconnect" }),
    );
    expect(
      await screen.findByText(/couldn't confirm the provider revoked access/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Access was revoked/)).toBeNull();
  });

  it("cancelling the disconnect changes nothing", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Disconnect me@gmail.example/ }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );
    expect(calls).toHaveLength(0);
  });

  it("survives a network failure with a clear message", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Sync me@gmail.example now/ }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
  });

  it("allows one action at a time", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => undefined;
    stubApi(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }) as unknown as Response,
    );
    setup({ accounts: [account()] });
    await user.click(screen.getByRole("button", { name: /Sync me@gmail.example now/ }));
    expect(screen.getByRole("button", { name: /Test the connection/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Sync me@gmail.example now/ })).toHaveTextContent(
      "Syncing…",
    );
    release(
      Response.json({
        account: account(),
        conversations_created: 0,
        messages_created: 0,
        messages_updated: 0,
        skipped: 0,
        pages: 1,
        complete: true,
        rate_limited_until: null,
        error_code: null,
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Test the connection/ })).toBeEnabled(),
    );
  });
});

describe("accessibility", () => {
  it("has no violations in any state", async () => {
    const rules = { rules: { "color-contrast": { enabled: false } } };
    const user = userEvent.setup();
    const { container } = setup({
      accounts: [
        account(),
        DEMO_ACCOUNT,
        account({
          id: "00000000-0000-4000-8000-0000000000a3",
          email_address: "x@gmail.example",
          status: "needs_reauth",
          needs_reconnect: true,
          last_error: "Reconnect it.",
          rate_limited_until: "2026-10-12T15:00:00Z",
        }),
      ],
      flash: {
        tone: "success",
        title: "Mailbox connected",
        text: "The connection test succeeded.",
      },
    });
    expect((await axe.run(container, rules)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: /Disconnect me@gmail.example/ }));
    expect((await axe.run(await screen.findByRole("dialog"), rules)).violations).toEqual([]);
  });
});
