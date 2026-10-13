import { StrictMode } from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type { ConversationDetail, ThreadMessage } from "./inbox-model";
import { ThreadView } from "./thread-view";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});
vi.mock("./reply-editor", () => ({
  ReplyEditor: ({ canEdit }: { canEdit: boolean }) => (
    <div data-testid="reply-editor">{canEdit ? "editor (owner)" : "editor (member)"}</div>
  ),
}));

const WS = "22222222-2222-4222-8222-222222222222";
const CONV = "00000000-0000-4000-8000-0000000000c1";
const LEAD = "00000000-0000-4000-8000-0000000000f1";

const message = (over: Partial<ThreadMessage> = {}): ThreadMessage => ({
  id: "00000000-0000-4000-8000-000000000001",
  direction: "inbound",
  from_address: "sam@acme.example",
  to_addresses: ["me@gmail.example"],
  subject: "Re: Hello",
  sent_at: "2026-10-12T14:05:00Z",
  is_bounce: false,
  delivery_state: "unknown",
  delivery_label: "",
  delivery_error_code: null,
  attachments: [],
  body: {
    available: true,
    text: "Sounds good.",
    html: null,
    images_blocked: false,
    text_truncated: false,
  },
  ...over,
});

const thread = (over: Partial<ConversationDetail> = {}): ConversationDetail => ({
  id: CONV,
  account_id: "00000000-0000-4000-8000-0000000000a1",
  account_email: "me@gmail.example",
  is_demo: false,
  subject: "Hello there",
  counterpart: { address: "sam@acme.example", name: "Sam Lee" },
  lead: { id: LEAD, title: "Acme website redesign" },
  company: { id: "00000000-0000-4000-8000-0000000000b1", name: "Acme Inc" },
  classification: {
    status: "classified",
    category: "interested",
    confidence: 0.9,
    source: "model",
    explanation: "They want to talk.",
    evidence: [],
    needs_review: false,
    review_reason: null,
    review_text: null,
    classified_at: "2026-10-12T14:06:00Z",
  },
  draft: null,
  has_draft: false,
  last_direction: "inbound",
  last_message_at: "2026-10-12T14:05:00Z",
  last_preview: "Sounds good.",
  message_count: 2,
  messages: [
    message({
      id: "00000000-0000-4000-8000-000000000002",
      direction: "outbound",
      from_address: "me@gmail.example",
      to_addresses: ["sam@acme.example"],
      sent_at: "2026-10-12T10:00:00Z",
      delivery_state: "sent",
      delivery_label: "Sent",
      body: {
        available: true,
        text: "Hi Sam, are you free to chat?",
        html: null,
        images_blocked: false,
        text_truncated: false,
      },
    }),
    message(),
  ],
  stop: null,
  unread: false,
  ...over,
});

type Call = { method: string; path: string };
function stubApi(respond: (call: Call) => Response = () => Response.json({})) {
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

const setup = (t: ConversationDetail, canEdit = true, strict = false) => {
  const tree = (
    <ToastProvider>
      <ThreadView workspaceId={WS} thread={t} canEdit={canEdit} backHref="/inbox?filter=unread" />
    </ToastProvider>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
};

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("what is shown", () => {
  it("shows the header, with the lead, the company and the mailbox", () => {
    stubApi();
    setup(thread());
    const section = screen.getByRole("region", { name: "Conversation: Hello there" });
    expect(
      within(section).getByRole("heading", { level: 2, name: "Hello there" }),
    ).toBeInTheDocument();
    expect(within(section).getByText("With").nextSibling).toHaveTextContent(
      "Sam Lee sam@acme.example",
    );
    expect(within(section).getByText("Mailbox").nextSibling).toHaveTextContent("me@gmail.example");
    expect(within(section).queryByText("Demo")).toBeNull();
    expect(within(section).getByRole("link", { name: "Acme website redesign" })).toHaveAttribute(
      "href",
      `/leads/${LEAD}`,
    );
    expect(within(section).getByText("Acme Inc")).toBeInTheDocument();
    expect(within(section).getByText("Messages").nextSibling).toHaveTextContent("2");
  });

  it("falls back for a missing subject, name, lead and company, and labels a demo mailbox", () => {
    stubApi();
    setup(
      thread({
        subject: null,
        counterpart: { address: "sam@acme.example", name: null },
        lead: null,
        company: null,
        is_demo: true,
      }),
    );
    expect(screen.getByRole("heading", { level: 2, name: "(no subject)" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Conversation: (no subject)" })).toBeInTheDocument();
    expect(screen.getByText("Demo")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /leads|Acme/ })).toBeNull();
    expect(screen.queryByText("Company")).toBeNull();
    expect(screen.getByText("With").nextSibling).toHaveTextContent(/^sam@acme\.example$/);
  });

  it("offers the way back to the list on small screens only", () => {
    stubApi();
    setup(thread());
    const back = screen.getByRole("link", { name: /Back to the list/ });
    expect(back).toHaveAttribute("href", "/inbox?filter=unread");
    expect(back.className).toContain("lg:hidden");
  });

  it("lists the messages in the order given, then the reply editor", () => {
    stubApi();
    setup(thread());
    const list = screen.getByRole("list", { name: "Messages" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent("Hi Sam, are you free to chat?");
    expect(items[1]).toHaveTextContent("Sounds good.");
    const editor = screen.getByTestId("reply-editor");
    expect(editor).toHaveTextContent("editor (owner)");
    expect(list.compareDocumentPosition(editor) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("passes read-only access on to the editor", () => {
    stubApi();
    setup(thread(), false);
    expect(screen.getByTestId("reply-editor")).toHaveTextContent("editor (member)");
  });

  it("shows the classification card, and the stop banner only when contact is stopped", () => {
    stubApi();
    const { unmount } = setup(thread());
    expect(screen.getByRole("region", { name: "Classification" })).toBeInTheDocument();
    expect(screen.queryByText("Contact stopped")).toBeNull();
    unmount();
    setup(
      thread({
        stop: {
          id: "00000000-0000-4000-8000-0000000000e1",
          address: "sam@acme.example",
          reason: "unsubscribe",
          since: "2026-10-11T09:30:00Z",
          text: "They asked not to be contacted.",
        },
      }),
    );
    expect(screen.getByText("Contact stopped")).toBeInTheDocument();
    expect(screen.getByText("They asked not to be contacted.")).toBeInTheDocument();
  });
});

describe("read state", () => {
  it("marks an unread conversation read once, even in strict mode, then refreshes", async () => {
    const calls = stubApi();
    setup(thread({ unread: true }), true, true);
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toEqual([{ method: "POST", path: `/inbox/conversations/${CONV}/read` }]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not mark anything when it is already read", async () => {
    const calls = stubApi();
    setup(thread({ unread: false }));
    await Promise.resolve();
    expect(calls).toHaveLength(0);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("never marks read for members", async () => {
    const calls = stubApi();
    setup(thread({ unread: true }), false);
    await Promise.resolve();
    expect(calls).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "Mark unread" })).toBeNull();
  });

  it("ignores a failure to mark read, without refreshing or a message", async () => {
    const calls = stubApi(() =>
      Response.json({ error: { code: "server_error", message: "Boom." } }, { status: 500 }),
    );
    setup(thread({ unread: true }));
    await waitFor(() => expect(calls).toHaveLength(1));
    await Promise.resolve();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.queryByText("Boom.")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ignores a network failure when marking read", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("offline");
    });
    vi.stubGlobal("fetch", fetchMock);
    setup(thread({ unread: true }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    await Promise.resolve();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.queryByText(/Can't reach the server/)).toBeNull();
  });

  it("marks unread for the owner, with a toast and a refresh", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    setup(thread());
    await user.click(screen.getByRole("button", { name: "Mark unread" }));
    expect(await screen.findByText("Marked unread")).toBeInTheDocument();
    expect(calls).toEqual([{ method: "POST", path: `/inbox/conversations/${CONV}/unread` }]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not offer Mark unread while it is unread", () => {
    stubApi();
    setup(thread({ unread: true }));
    expect(screen.queryByRole("button", { name: "Mark unread" })).toBeNull();
  });

  it("shows the server's reason when marking unread is refused", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "forbidden", message: "Only the owner can do that." } },
        { status: 403 },
      ),
    );
    setup(thread());
    await user.click(screen.getByRole("button", { name: "Mark unread" }));
    expect(await screen.findByText("Only the owner can do that.")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Mark unread" })).toBeEnabled();
  });

  it("survives a network failure when marking unread", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup(thread());
    await user.click(screen.getByRole("button", { name: "Mark unread" }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("sends one request when Mark unread is pressed twice", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => undefined;
    const calls = stubApi(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }) as unknown as Response,
    );
    setup(thread());
    const button = screen.getByRole("button", { name: "Mark unread" });
    await user.click(button);
    expect(button).toBeDisabled();
    await user.click(button);
    expect(calls).toHaveLength(1);
    release(Response.json({}));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(button).toBeEnabled();
  });
});

describe("accessibility", () => {
  it("has no violations", async () => {
    stubApi();
    const rules = { iframes: false, rules: { "color-contrast": { enabled: false } } };
    const { container } = setup(
      thread({
        is_demo: true,
        stop: {
          id: "00000000-0000-4000-8000-0000000000e1",
          address: "sam@acme.example",
          reason: "unsubscribe",
          since: "2026-10-11T09:30:00Z",
          text: "They asked not to be contacted.",
        },
      }),
    );
    expect((await axe.run(container, rules)).violations).toEqual([]);
  });
});
