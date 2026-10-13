import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type { ConversationDetail, DraftOut, StopOut, ThreadMessage } from "./inbox-model";
import { ReplyEditor } from "./reply-editor";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
const redirectToSignIn = vi.fn();
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: (...args: unknown[]) => redirectToSignIn(...args) };
});

const WS = "22222222-2222-4222-8222-222222222222";
const CONV = "33333333-3333-4333-8333-333333333333";
const DRAFT_ID = "44444444-4444-4444-8444-444444444444";
const ACCOUNT = "55555555-5555-4555-8555-555555555555";
const LEAD = "66666666-6666-4666-8666-666666666666";

const message = (over: Partial<ThreadMessage> = {}): ThreadMessage => ({
  attachments: [],
  body: {
    available: true,
    html: null,
    images_blocked: false,
    text: "Can you send a quote?",
    text_truncated: false,
  },
  delivery_error_code: null,
  delivery_label: "Received",
  delivery_state: "sent",
  direction: "inbound",
  from_address: "sam@acme.example",
  id: "77777777-7777-4777-8777-777777777777",
  is_bounce: false,
  sent_at: "2026-10-12T09:00:00Z",
  subject: "Quote",
  to_addresses: ["alex@alex-rivera.example"],
  ...over,
});

const draft = (over: Partial<DraftOut> = {}): DraftOut => ({
  approval_is_current: false,
  approved_at: null,
  author: "ai",
  body_text: "Hi Sam, happy to help with a quote.",
  conversation_id: CONV,
  created_at: "2026-10-12T10:00:00Z",
  email_account_id: ACCOUNT,
  facts: [],
  facts_used: [],
  id: DRAFT_ID,
  lead_id: LEAD,
  message: null,
  send_locked: false,
  sent_at: null,
  status: "draft",
  subject: "Re: Quote",
  to_address: "sam@acme.example",
  updated_at: "2026-10-12T10:00:00Z",
  version: 1,
  ...over,
});

const APPROVED = (over: Partial<DraftOut> = {}) =>
  draft({
    status: "approved",
    approval_is_current: true,
    approved_at: "2026-10-12T10:05:00Z",
    version: 2,
    ...over,
  });

const STOP: StopOut = {
  address: "sam@acme.example",
  id: "88888888-8888-4888-8888-888888888888",
  reason: "unsubscribe",
  since: "2026-10-11T08:00:00Z",
  text: "Sam asked not to be contacted. Nothing can be sent to this address.",
};

const thread = (over: Partial<ConversationDetail> = {}): ConversationDetail => ({
  account_email: "alex@alex-rivera.example",
  account_id: ACCOUNT,
  classification: {
    category: "question",
    classified_at: "2026-10-12T09:01:00Z",
    confidence: 0.9,
    evidence: [],
    explanation: null,
    needs_review: false,
    review_reason: null,
    review_text: null,
    source: "model",
    status: "classified",
  },
  company: null,
  counterpart: { address: "sam@acme.example", name: "Sam" },
  draft: null,
  has_draft: false,
  id: CONV,
  is_demo: false,
  last_direction: "inbound",
  last_message_at: "2026-10-12T09:00:00Z",
  last_preview: "Can you send a quote?",
  lead: { id: LEAD, title: "Acme website" },
  message_count: 1,
  messages: [message()],
  stop: null,
  subject: "Quote",
  unread: false,
  ...over,
});

type Call = { method: string; path: string; body: unknown };
type Responder = (call: Call) => Response | Promise<Response>;
function stubApi(respond: Responder) {
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

const failWith = (
  status: number,
  code: string,
  text: string,
  headers: Record<string, string> = {},
) =>
  new Response(JSON.stringify({ error: { code, message: text } }), {
    status,
    headers: { "content-type": "application/json", ...headers },
  });

const suggestOut = (
  over: Partial<{ draft: DraftOut; warnings: string[]; regenerated: boolean }>,
) => ({
  draft: draft(),
  regenerated: false,
  warnings: [],
  ai_label: "Written by AI from your approved facts",
  is_demo_ai: false,
  ...over,
});

function setup(
  props: Partial<{ thread: ConversationDetail; canEdit: boolean }> = {},
  render_ = render,
) {
  const ui = (t: ConversationDetail, canEdit: boolean) => (
    <ToastProvider>
      <ReplyEditor workspaceId={WS} thread={t} canEdit={canEdit} />
    </ToastProvider>
  );
  const view = render_(ui(props.thread ?? thread(), props.canEdit ?? true));
  return {
    ...view,
    update: (t: ConversationDetail, canEdit = true) => view.rerender(ui(t, canEdit)),
  };
}

const status = () => screen.getByTestId("reply-status");
const rules = { rules: { "color-contrast": { enabled: false } } };
const OWN = thread({ draft: draft({ author: "user" }) });
const APPROVED_THREAD = thread({ draft: APPROVED({ author: "user" }) });

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
  redirectToSignIn.mockClear();
});

describe("members", () => {
  it("see the draft read-only with a plain note and no buttons", () => {
    setup({ thread: thread({ draft: draft() }), canEdit: false });
    expect(screen.getByRole("region", { name: "Reply" })).toBeInTheDocument();
    expect(
      screen.getByText("Only the workspace owner can write or send replies."),
    ).toBeInTheDocument();
    expect(screen.getByText("Hi Sam, happy to help with a quote.")).toBeInTheDocument();
    expect(screen.getByText("sam@acme.example")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("see 'No draft' when there is none", () => {
    setup({ canEdit: false });
    expect(screen.getByText("No draft")).toBeInTheDocument();
    expect(screen.getByText(/Only the workspace owner/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("see an unknown outcome but cannot resolve it", () => {
    setup({
      thread: thread({
        draft: APPROVED({
          message: {
            conversation_id: CONV,
            delivery_error_code: null,
            delivery_label: "Unknown",
            delivery_state: "unknown",
            id: "m1",
            is_demo: false,
            sent_at: "2026-10-12T10:10:00Z",
          },
        }),
      }),
      canEdit: false,
    });
    expect(screen.getByText(/couldn't confirm this message was sent/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("a stopped contact", () => {
  it("turns replies off with the server's words and offers nothing to write", () => {
    setup({ thread: thread({ stop: STOP }) });
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Replies are turned off for this contact");
    expect(alert).toHaveTextContent(STOP.text);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByText("No draft")).toBeNull();
  });

  it("shows an existing draft read-only, with no Send", () => {
    setup({ thread: thread({ stop: STOP, draft: APPROVED() }) });
    expect(screen.getByText("Hi Sam, happy to help with a quote.")).toBeInTheDocument();
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});

describe("nothing to reply to", () => {
  it("says so when there is no inbound message", () => {
    setup({ thread: thread({ messages: [message({ direction: "outbound" })] }) });
    expect(screen.getByText("There's nothing to reply to yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("with no draft", () => {
  it("explains what suggestions use and offers two ways to start", () => {
    setup();
    expect(
      screen.getByText(
        "Suggestions use only facts you have approved. Nothing is sent without your approval.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suggest a reply" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Write my own" })).toBeEnabled();
  });

  it("suggests a reply and shows the draft, the AI label and the warnings in words", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json(
        suggestOut({
          draft: draft({
            facts: [
              { id: "f1", kind: "service", still_approved: true, title: "Website builds" },
              { id: "f2", kind: "pricing", still_approved: false, title: "Old rate card" },
            ],
          }),
          warnings: [
            "injection_suspected",
            "placeholder_in_draft",
            "no_facts_cited",
            "review:Check the delivery date.",
            "something_unknown",
          ],
        }),
        { status: 201 },
      ),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    expect(await screen.findByRole("textbox", { name: "Message" })).toHaveValue(
      "Hi Sam, happy to help with a quote.",
    );
    expect(calls).toEqual([
      { method: "POST", path: `/inbox/conversations/${CONV}/suggest-reply`, body: undefined },
    ]);
    expect(screen.getByText("Written by AI from your approved facts")).toBeInTheDocument();
    expect(screen.getByText("AI draft: check every line")).toBeInTheDocument();
    expect(screen.getByText("Draft")).toBeInTheDocument();
    for (const text of [
      /tries to instruct the AI/,
      /placeholder to fill in/,
      /doesn't cite any approved fact/,
      "Check the delivery date.",
    ]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.queryByText(/something_unknown/)).toBeNull();
    expect(screen.getByText("Website builds")).toBeInTheDocument();
    expect(screen.getByText("service")).toBeInTheDocument();
    expect(screen.getByText("No longer approved")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /approved facts in the AI Workspace/ }),
    ).toHaveAttribute("href", "/ai-workspace/knowledge");
    expect(status()).toHaveTextContent("A draft is ready below. Read it before you approve it.");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Draft ready").length).toBeGreaterThan(0);
  });

  it("says the draft was written from the profile only when no fact is cited", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(suggestOut({}), { status: 201 }));
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    expect(
      await screen.findByText(
        "No approved fact was cited; this was written from your profile only.",
      ),
    ).toBeInTheDocument();
  });

  it("announces a replaced draft when the server regenerated it", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(suggestOut({ regenerated: true }), { status: 200 }));
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    await waitFor(() => expect(status()).toHaveTextContent(/A new draft replaced the earlier one/));
  });

  it("shows 'Writing a draft…' and blocks a second click while it works", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => undefined;
    const calls = stubApi(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    const busy = screen.getByRole("button", { name: "Writing a draft…" });
    expect(busy).toBeDisabled();
    expect(screen.getByRole("button", { name: "Write my own" })).toBeDisabled();
    expect(status()).toHaveTextContent("Writing a draft…");
    await user.click(busy);
    expect(calls).toHaveLength(1);
    release(Response.json(suggestOut({}), { status: 201 }));
    await screen.findByRole("textbox", { name: "Message" });
  });

  it("explains missing context and links to the AI Workspace", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      failWith(422, "insufficient_context", "Add a service to your AI Workspace first."),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Add a service to your AI Workspace first.");
    expect(
      within(alert).getByRole("link", { name: "Add approved facts in the AI Workspace" }),
    ).toHaveAttribute("href", "/ai-workspace/knowledge");
    expect(screen.getByRole("button", { name: "Suggest a reply" })).toBeEnabled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("refreshes when the contact was stopped meanwhile", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "contact_stopped", "This contact asked not to be contacted."));
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    expect(await screen.findByText("This contact asked not to be contacted.")).toBeInTheDocument();
    expect(refresh).toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: /AI Workspace/ })).toBeNull();
  });

  it.each([
    [409, "ai_unavailable", "The AI provider isn't set up."],
    [429, "rate_limited", "Too many requests. Wait a moment."],
    [503, "provider_unavailable", "The AI service is temporarily unavailable."],
    [502, "policy_violation", "The draft broke a safety rule and was discarded."],
  ])("shows the server's message for %s %s", async (statusCode, code, text) => {
    const user = userEvent.setup();
    stubApi(() =>
      failWith(statusCode, code, text, statusCode === 429 ? { "retry-after": "30" } : {}),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(status()).toHaveTextContent("Couldn't write a draft.");
    expect(screen.queryByRole("textbox")).toBeNull();
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
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Suggest a reply" })).toBeEnabled();
  });

  it("sends the person to sign in when the session has expired", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(401, "session_expired", "Your session expired."));
    setup();
    await user.click(screen.getByRole("button", { name: "Suggest a reply" }));
    await waitFor(() => expect(redirectToSignIn).toHaveBeenCalled());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("starts a blank draft addressed to the sender, and focuses the message", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json(draft({ author: "user", body_text: "" }), { status: 201 }),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Write my own" }));
    const box = await screen.findByRole("textbox", { name: "Message" });
    expect(calls).toEqual([
      {
        method: "POST",
        path: "/drafts",
        body: {
          conversation_id: CONV,
          lead_id: LEAD,
          email_account_id: ACCOUNT,
          to_address: "sam@acme.example",
          subject: "Re: Quote",
          body_text: "",
        },
      },
    ]);
    expect(box).toHaveValue("");
    await waitFor(() => expect(box).toHaveFocus());
    expect(screen.getByText("Written by you")).toBeInTheDocument();
    expect(screen.queryByText("Written using")).toBeNull();
    expect(refresh).toHaveBeenCalled();
  });

  it("does not double a Re: and sends a null lead when there is none", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(draft({ author: "user" }), { status: 201 }));
    setup({ thread: thread({ subject: "re: Quote", lead: null }) });
    await user.click(screen.getByRole("button", { name: "Write my own" }));
    await screen.findByRole("textbox", { name: "Message" });
    expect(calls[0]!.body).toMatchObject({ subject: "re: Quote", lead_id: null });
  });

  it("explains a failure to start a draft", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "contact_stopped", "Replies are off for this contact."));
    setup();
    await user.click(screen.getByRole("button", { name: "Write my own" }));
    expect(await screen.findByText("Replies are off for this contact.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Write my own" })).toBeEnabled();
  });
});

describe("a draft", () => {
  it("shows its status, author, fields and facts", () => {
    setup({
      thread: thread({
        draft: draft({
          facts: [{ id: "f1", kind: "service", still_approved: true, title: "Website builds" }],
        }),
      }),
    });
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(screen.getByText("AI draft: check every line")).toBeInTheDocument();
    expect(screen.getByText("sam@acme.example")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Subject" })).toHaveValue("Re: Quote");
    const box = screen.getByRole("textbox", { name: "Message" });
    expect(box).toHaveValue("Hi Sam, happy to help with a quote.");
    expect(box).toHaveAttribute("maxlength", "20000");
    const facts = screen.getByRole("region", { name: "Written using" });
    expect(within(facts).getByText("Website builds")).toBeInTheDocument();
    expect(within(facts).queryByText("No longer approved")).toBeNull();
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(screen.queryByText(/Editing an approved draft/)).toBeNull();
  });

  it("names a withdrawn approval", () => {
    setup({
      thread: thread({ draft: draft({ status: "approved", approval_is_current: false }) }),
    });
    expect(screen.getByText("Approval withdrawn")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("warns to check the classification first", () => {
    setup({
      thread: thread({
        draft: draft(),
        classification: {
          ...thread().classification,
          needs_review: true,
          review_text: "The AI wasn't sure this is a question.",
        },
      }),
    });
    const notice = screen.getByText("Check the classification first").closest("[role=alert]");
    expect(notice).toHaveTextContent("The AI wasn't sure this is a question.");
  });

  it("shows no AI notes for a draft you wrote", () => {
    setup({ thread: OWN });
    expect(screen.getByText("Written by you")).toBeInTheDocument();
    expect(screen.queryByText(/No approved fact was cited/)).toBeNull();
  });

  it("keeps what is typed when the page refreshes the same version, and follows a new one", async () => {
    const user = userEvent.setup();
    const view = setup({ thread: OWN });
    const box = screen.getByRole("textbox", { name: "Message" });
    await user.clear(box);
    await user.type(box, "My own words");
    view.update(thread({ draft: draft({ author: "user", updated_at: "2026-10-12T10:30:00Z" }) }));
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("My own words");
    view.update(
      thread({ draft: draft({ author: "user", version: 3, body_text: "Changed elsewhere" }) }),
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Changed elsewhere");
    view.update(thread({ draft: null }));
    expect(screen.getByRole("button", { name: "Suggest a reply" })).toBeInTheDocument();
  });
});

describe("saving", () => {
  it("enables Save only when the text changed, and says so", async () => {
    const user = userEvent.setup();
    setup({ thread: OWN });
    const save = screen.getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Message" }), " Thanks.");
    expect(save).toBeEnabled();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "{Backspace>8/}");
    expect(save).toBeDisabled();
    expect(screen.queryByText("Unsaved changes")).toBeNull();
  });

  it("saves both fields and adopts the server's draft", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json(
        draft({ author: "user", version: 2, body_text: "New text", subject: "New subject" }),
      ),
    );
    setup({ thread: OWN });
    const subject = screen.getByRole("textbox", { name: "Subject" });
    await user.clear(subject);
    await user.type(subject, "New subject");
    const box = screen.getByRole("textbox", { name: "Message" });
    await user.clear(box);
    await user.type(box, "New text");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(status()).toHaveTextContent("Draft saved."));
    expect(calls).toEqual([
      {
        method: "PATCH",
        path: `/drafts/${DRAFT_ID}`,
        body: { subject: "New subject", body_text: "New text" },
      },
    ]);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reports a draft that is locked by a send and refreshes", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "draft_locked", "A send has started, so this draft can't change."));
    setup({ thread: OWN });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(
      await screen.findByText("A send has started, so this draft can't change."),
    ).toBeInTheDocument();
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "Hi Sam, happy to help with a quote.!",
    );
  });

  it("keeps the typed text after a network failure", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup({ thread: OWN });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("makes the fields read-only and every button inert while a request runs", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => undefined;
    const calls = stubApi(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    setup({ thread: OWN });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Saving…" })).toBeDisabled();
    for (const name of ["Regenerate", "Save and approve", "Discard"]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveAttribute("readonly");
    await user.click(screen.getByRole("button", { name: "Saving…" }));
    expect(calls).toHaveLength(1);
    release(
      Response.json(draft({ author: "user", body_text: "Hi Sam, happy to help with a quote.!" })),
    );
    await waitFor(() => expect(screen.getByRole("button", { name: "Discard" })).toBeEnabled());
  });
});

describe("approving", () => {
  it("approves a clean draft and then offers Send", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(APPROVED({ author: "user" })));
    setup({ thread: OWN });
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByRole("button", { name: "Send" })).toBeEnabled();
    expect(calls).toEqual([
      { method: "POST", path: `/drafts/${DRAFT_ID}/approve`, body: undefined },
    ]);
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(
      screen.getByText("Editing an approved draft withdraws your approval."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(status()).toHaveTextContent("Draft approved. You can send it now.");
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("will not approve an empty subject or message", async () => {
    const user = userEvent.setup();
    setup({ thread: OWN });
    const box = screen.getByRole("textbox", { name: "Message" });
    await user.clear(box);
    expect(screen.getByRole("button", { name: "Save and approve" })).toBeDisabled();
    await user.type(box, "   ");
    expect(screen.getByRole("button", { name: "Save and approve" })).toBeDisabled();
    await user.type(box, "Words");
    expect(screen.getByRole("button", { name: "Save and approve" })).toBeEnabled();
    const subject = screen.getByRole("textbox", { name: "Subject" });
    await user.clear(subject);
    expect(screen.getByRole("button", { name: "Save and approve" })).toBeDisabled();
  });

  it("saves, then approves, when the text has changed", async () => {
    const user = userEvent.setup();
    const calls = stubApi((c) =>
      c.method === "PATCH"
        ? Response.json(draft({ author: "user", version: 2, body_text: "Final words" }))
        : Response.json(APPROVED({ author: "user", version: 3, body_text: "Final words" })),
    );
    setup({ thread: OWN });
    const box = screen.getByRole("textbox", { name: "Message" });
    await user.clear(box);
    await user.type(box, "Final words");
    await user.click(screen.getByRole("button", { name: "Save and approve" }));
    expect(await screen.findByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      `PATCH /drafts/${DRAFT_ID}`,
      `POST /drafts/${DRAFT_ID}/approve`,
    ]);
    expect(calls[0]!.body).toEqual({ subject: "Re: Quote", body_text: "Final words" });
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue("Final words");
  });

  it("does not approve when saving first failed", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => failWith(409, "draft_locked", "A send has started."));
    setup({ thread: OWN });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    await user.click(screen.getByRole("button", { name: "Save and approve" }));
    expect(await screen.findByText("A send has started.")).toBeInTheDocument();
    expect(calls).toHaveLength(1);
  });

  it("keeps the saved text when approving fails after saving", async () => {
    const user = userEvent.setup();
    stubApi((c) =>
      c.method === "PATCH"
        ? Response.json(
            draft({
              author: "user",
              version: 2,
              body_text: "Hi Sam, happy to help with a quote.!",
            }),
          )
        : failWith(422, "validation_error", "Nope."),
    );
    setup({ thread: OWN });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    await user.click(screen.getByRole("button", { name: "Save and approve" }));
    expect(await screen.findByText("The draft wasn't approved")).toBeInTheDocument();
    expect(status()).toHaveTextContent("Saved, but couldn't approve the draft.");
    expect(screen.queryByText("Unsaved changes")).toBeNull();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("shows field errors from the server next to the fields", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "Check the highlighted fields.",
            fields: {
              subject: "Add a subject.",
              body_text: "Write a message.",
              to_address: "Add a recipient.",
            },
          },
        },
        { status: 422 },
      ),
    );
    setup({ thread: OWN });
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(
      await screen.findByText("Fix the highlighted fields and try again."),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Subject" })).toHaveAccessibleDescription(
      "Add a subject.",
    );
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveAccessibleDescription(
      "Write a message.",
    );
    expect(screen.getByText("Add a recipient.")).toBeInTheDocument();
  });

  it("lists field errors it does not know where to put", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "Bad.",
            fields: { other: "Something else is wrong." },
          },
        },
        { status: 422 },
      ),
    );
    setup({ thread: OWN });
    await user.click(screen.getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("Something else is wrong.")).toBeInTheDocument();
  });

  it("withdraws the Send button as soon as an approved draft is edited", async () => {
    const user = userEvent.setup();
    setup({ thread: APPROVED_THREAD });
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    expect(screen.getByRole("button", { name: "Save and approve" })).toBeEnabled();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });
});

describe("regenerating", () => {
  it("asks first when the text has changed, and Cancel makes no request", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(suggestOut({})));
    setup({ thread: thread({ draft: draft() }) });
    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/This replaces the text you have written/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "Hi Sam, happy to help with a quote.!",
    );
  });

  it("asks first when the draft has been through an earlier version", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(suggestOut({ regenerated: true }), { status: 200 }));
    setup({ thread: thread({ draft: draft({ version: 2 }) }) });
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    const dialog = await screen.findByRole("dialog");
    expect(calls).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Replace draft" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.path).toBe(`/inbox/conversations/${CONV}/suggest-reply`);
    await waitFor(() => expect(status()).toHaveTextContent(/A new draft replaced/));
  });

  it("does not ask when the first version is untouched", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(suggestOut({}), { status: 200 }));
    setup({ thread: thread({ draft: draft() }) });
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() => expect(calls).toHaveLength(1));
  });

  it("keeps the current draft when regenerating fails", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(422, "insufficient_context", "Add a service first."));
    setup({ thread: thread({ draft: draft() }) });
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    expect(await screen.findByText("Add a service first.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveValue(
      "Hi Sam, happy to help with a quote.",
    );
    expect(
      screen.getByRole("link", { name: "Add approved facts in the AI Workspace" }),
    ).toBeInTheDocument();
  });
});

describe("discarding", () => {
  it("asks first, Cancel being the default, and Cancel makes no request", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup({ thread: OWN });
    await user.click(screen.getByRole("button", { name: "Discard" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
    expect(screen.getByRole("textbox", { name: "Message" })).toBeInTheDocument();
  });

  it("discards and returns to the no-draft state", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(draft({ status: "discarded" })));
    setup({ thread: OWN });
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard draft" }),
    );
    expect(await screen.findByRole("button", { name: "Suggest a reply" })).toBeInTheDocument();
    expect(calls).toEqual([
      { method: "POST", path: `/drafts/${DRAFT_ID}/discard`, body: undefined },
    ]);
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(status()).toHaveTextContent("Draft discarded.");
    expect(refresh).toHaveBeenCalled();
  });

  it("keeps the draft when discarding fails", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "draft_locked", "A send has started."));
    setup({ thread: OWN });
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Discard draft" }),
    );
    expect(await screen.findByText("A send has started.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Message" })).toBeInTheDocument();
    expect(status()).toHaveTextContent("Couldn't discard the draft.");
  });
});

const sendOut = (state: "sent" | "demo" | "queued" | "failed" | "unknown", replayed = false) => ({
  replayed,
  draft: APPROVED({
    author: "user",
    status: state === "sent" || state === "demo" ? "sent" : "approved",
    sent_at: "2026-10-12T10:10:00Z",
    message: {
      conversation_id: CONV,
      delivery_error_code: state === "failed" ? "provider_rejected" : null,
      delivery_label: state === "failed" ? "The provider rejected the message." : "Label",
      delivery_state: state,
      id: "99999999-9999-4999-8999-999999999999",
      is_demo: state === "demo",
      sent_at: "2026-10-12T10:10:00Z",
    },
  }),
});

async function openSendDialog(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Send" }));
  return screen.findByRole("dialog");
}

describe("the send dialog", () => {
  it("shows where it goes and what it sends, with Cancel as the default", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    expect(within(dialog).getByText("sam@acme.example")).toBeInTheDocument();
    expect(within(dialog).getByText("alex@alex-rivera.example")).toBeInTheDocument();
    expect(within(dialog).getByText("Re: Quote")).toBeInTheDocument();
    expect(
      within(dialog).getByText("This sends exactly the text you approved."),
    ).toBeInTheDocument();
    expect(within(dialog).queryByText(/Demo mailbox/)).toBeNull();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByRole("button", { name: "Send" })).toHaveFocus();
  });

  it("says plainly when the mailbox is a demo", async () => {
    const user = userEvent.setup();
    setup({ thread: { ...APPROVED_THREAD, is_demo: true } });
    const dialog = await openSendDialog(user);
    expect(
      within(dialog).getByText("Demo mailbox: nothing will be delivered to anyone."),
    ).toBeInTheDocument();
  });

  it("sends with an idempotency key and says the message was sent", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(sendOut("sent"), { status: 201 }));
    setup({ thread: APPROVED_THREAD });
    await user.click(
      within(await openSendDialog(user)).getByRole("button", { name: "Send message" }),
    );
    expect(await screen.findAllByText("Message sent")).not.toHaveLength(0);
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "POST", path: `/drafts/${DRAFT_ID}/send` });
    expect((calls[0]!.body as { idempotency_key: string }).idempotency_key).toMatch(
      /^[A-Za-z0-9._:-]{8,100}$/,
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(status()).toHaveTextContent("The message was sent.");
    expect(screen.getByText("Sent")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("says a demo send delivered nothing", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(sendOut("demo"), { status: 201 }));
    setup({ thread: { ...APPROVED_THREAD, is_demo: true } });
    await user.click(
      within(await openSendDialog(user)).getByRole("button", { name: "Send message" }),
    );
    expect(await screen.findAllByText("Demo only: nothing was delivered")).not.toHaveLength(0);
    expect(screen.queryByText("Message sent")).toBeNull();
  });

  it("says when the message had already been sent", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(sendOut("sent", true), { status: 200 }));
    setup({ thread: APPROVED_THREAD });
    await user.click(
      within(await openSendDialog(user)).getByRole("button", { name: "Send message" }),
    );
    expect(await screen.findAllByText("This message was already sent")).not.toHaveLength(0);
    expect(screen.queryByText("Message sent")).toBeNull();
  });

  it("reports a send that is still being delivered", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(sendOut("queued"), { status: 201 }));
    setup({ thread: APPROVED_THREAD });
    await user.click(
      within(await openSendDialog(user)).getByRole("button", { name: "Send message" }),
    );
    await waitFor(() => expect(status()).toHaveTextContent("Sending…"));
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveAttribute("readonly");
  });

  it("reports a send the provider refused after accepting it", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(sendOut("failed"), { status: 201 }));
    setup({ thread: APPROVED_THREAD });
    await user.click(
      within(await openSendDialog(user)).getByRole("button", { name: "Send message" }),
    );
    expect(await screen.findAllByText("The message wasn't sent")).not.toHaveLength(0);
    const notice = screen.getByText("The last send failed").closest("[role=alert]");
    expect(notice).toHaveTextContent("The provider rejected the message.");
    expect(notice).toHaveTextContent("You can try sending it again.");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  it("keeps a persistent warning when the outcome is unknown, and lets the owner resolve it", async () => {
    const user = userEvent.setup();
    const calls = stubApi((c) =>
      c.path.endsWith("/send")
        ? Response.json(sendOut("unknown"), { status: 202 })
        : Response.json({ ...sendOut("sent").draft }),
    );
    setup({ thread: APPROVED_THREAD });
    await user.click(
      within(await openSendDialog(user)).getByRole("button", { name: "Send message" }),
    );
    const notice = (await screen.findByText(/couldn't confirm this message was sent/)).closest(
      "[role=alert]",
    );
    expect(notice).toHaveTextContent(
      "We couldn't confirm this message was sent. Check your mailbox, then tell us what happened.",
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "It was sent" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toEqual({
      method: "POST",
      path: `/drafts/${DRAFT_ID}/resolve-send`,
      body: { outcome: "sent" },
    });
    await waitFor(() => expect(status()).toHaveTextContent("Recorded as sent."));
    expect(screen.queryByText(/couldn't confirm this message was sent/)).toBeNull();
  });

  it("treats an unknown delivery state with a 201 the same way", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(sendOut("unknown"), { status: 201 }));
    setup({ thread: APPROVED_THREAD });
    await user.click(
      within(await openSendDialog(user)).getByRole("button", { name: "Send message" }),
    );
    expect(await screen.findByRole("button", { name: "It was not sent" })).toBeInTheDocument();
  });

  it("uses the same key for every retry in one dialog and a new one after reopening", async () => {
    const user = userEvent.setup();
    let attempt = 0;
    const calls = stubApi(() => {
      attempt += 1;
      return attempt < 4
        ? failWith(503, "provider_unavailable", "The provider is down.")
        : Response.json(sendOut("sent"), { status: 201 });
    });
    setup({ thread: APPROVED_THREAD });
    let dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(await within(dialog).findByText("The provider is down.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    await within(dialog).findByText("The provider is down.");
    const key = (i: number) => (calls[i]!.body as { idempotency_key: string }).idempotency_key;
    expect(key(1)).toBe(key(0));

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    dialog = await openSendDialog(user);
    expect(within(dialog).queryByText("The provider is down.")).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(key(2)).not.toBe(key(0));
    await within(dialog).findByText("The provider is down.");
    await user.click(within(dialog).getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls).toHaveLength(4));
    expect(key(3)).toBe(key(2));
  });

  it("blocks a second click while sending", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => undefined;
    const calls = stubApi(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }),
    );
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    const busy = within(dialog).getByRole("button", { name: "Sending…" });
    expect(busy).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.click(busy);
    expect(calls).toHaveLength(1);
    release(Response.json(sendOut("sent"), { status: 201 }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("survives a network failure and says retrying is safe", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(await within(dialog).findByText(/Can't reach the server/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Trying again is safe/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Try again" })).toBeEnabled();
  });

  it("links to Integrations when the mailbox needs reconnecting", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "reconnect_required", "Reconnect your mailbox to send."));
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(await within(dialog).findByText("Reconnect your mailbox to send.")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("link", { name: /Reconnect your mailbox in Integrations/ }),
    ).toHaveAttribute("href", "/integrations");
    expect(refresh).not.toHaveBeenCalled();
  });

  it.each(["send_rate_limited", "rate_limited"])("asks the person to wait on %s", async (code) => {
    const user = userEvent.setup();
    stubApi(() => failWith(429, code, "Too many sends.", { "retry-after": "120" }));
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(
      await within(dialog).findByText(
        "Too many sends. Please wait about 2 minutes before trying again.",
      ),
    ).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Try again" })).toBeEnabled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("explains a recipient on the do-not-contact list, refreshes and blocks retrying", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "recipient_suppressed", "This address is suppressed."));
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(await within(dialog).findByText(/do-not-contact list/)).toBeInTheDocument();
    expect(within(dialog).getByText(/This address is suppressed\./)).toBeInTheDocument();
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(within(dialog).getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it.each([
    ["draft_changed", "The draft changed after you approved it."],
    ["draft_not_approved", "The draft is not approved."],
    ["already_sent", "This draft was already sent."],
  ])("refreshes and blocks on %s", async (code, text) => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, code, text));
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(await within(dialog).findByText(text)).toBeInTheDocument();
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(within(dialog).getByRole("button", { name: "Send message" })).toBeDisabled();
  });

  it.each([
    [409, "send_in_progress", "A send is already running."],
    [409, "idempotency_key_conflict", "That key was used for a different draft."],
    [409, "provider_not_configured", "No email provider is set up."],
    [502, "provider_rejected", "The provider rejected the message."],
    [503, "provider_unavailable", "The provider is unavailable."],
  ])("shows the server's message for %s %s", async (statusCode, code, text) => {
    const user = userEvent.setup();
    stubApi(() => failWith(statusCode, code, text));
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(await within(dialog).findByText(text)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Try again" })).toBeEnabled();
    expect(status()).toHaveTextContent("The message wasn't sent.");
  });

  it("explains an outcome that is already unknown and refreshes", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "send_outcome_unknown", "An earlier send may have gone out."));
    setup({ thread: APPROVED_THREAD });
    const dialog = await openSendDialog(user);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    expect(
      await within(dialog).findByText("An earlier send may have gone out."),
    ).toBeInTheDocument();
    expect(refresh).toHaveBeenCalledTimes(1);
  });
});

describe("what the server says about delivery", () => {
  const withMessage = (state: "failed" | "queued" | "unknown") =>
    thread({
      draft: APPROVED({
        author: "user",
        message: {
          conversation_id: CONV,
          delivery_error_code: state === "failed" ? "provider_rejected" : null,
          delivery_label: state === "failed" ? "The provider rejected the message." : "Label",
          delivery_state: state,
          id: "99999999-9999-4999-8999-999999999999",
          is_demo: false,
          sent_at: "2026-10-12T10:10:00Z",
        },
      }),
    });

  it("shows a failed send with its reason and a way to retry", () => {
    setup({ thread: withMessage("failed") });
    const notice = screen.getByText("The last send failed").closest("[role=alert]");
    expect(notice).toHaveTextContent("The provider rejected the message.");
    expect(notice).toHaveTextContent("You can try sending it again.");
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  });

  it("shows a queued send as 'Sending…' and freezes the draft", () => {
    setup({ thread: withMessage("queued") });
    expect(status()).toHaveTextContent("Sending…");
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("textbox", { name: "Message" })).toHaveAttribute("readonly");
  });

  it("shows an unknown send with both ways to resolve it", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json(draft({ status: "approved", approval_is_current: true, version: 2 })),
    );
    setup({ thread: withMessage("unknown") });
    expect(screen.getByText(/couldn't confirm this message was sent/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "It was not sent" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      method: "POST",
      path: `/drafts/${DRAFT_ID}/resolve-send`,
      body: { outcome: "not_sent" },
    });
    await waitFor(() =>
      expect(status()).toHaveTextContent("Recorded as not sent. You can send it again."),
    );
    expect(screen.queryByText(/couldn't confirm this message was sent/)).toBeNull();
    expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
    expect(refresh).toHaveBeenCalled();
  });

  it("keeps the warning when recording what happened fails", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "draft_locked", "Not now."));
    setup({ thread: withMessage("unknown") });
    await user.click(screen.getByRole("button", { name: "It was sent" }));
    expect(await screen.findByText("Not now.")).toBeInTheDocument();
    expect(screen.getByText(/couldn't confirm this message was sent/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "It was sent" })).toBeEnabled();
  });

  it("survives a network failure while resolving", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup({ thread: withMessage("unknown") });
    await user.click(screen.getByRole("button", { name: "It was sent" }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
  });
});

describe("accessibility", () => {
  it("has no violations in any state", async () => {
    const cases: [string, ConversationDetail, boolean][] = [
      ["no draft", thread(), true],
      ["nothing to reply to", thread({ messages: [] }), true],
      ["member", thread({ draft: draft() }), false],
      ["stopped", thread({ stop: STOP, draft: draft() }), true],
      [
        "ai draft",
        thread({
          draft: draft({
            facts: [{ id: "f1", kind: "service", still_approved: false, title: "Website builds" }],
          }),
          classification: {
            ...thread().classification,
            needs_review: true,
            review_text: "Check it.",
          },
        }),
        true,
      ],
      ["approved", APPROVED_THREAD, true],
      ["unknown", thread({ draft: APPROVED({ message: sendOut("unknown").draft.message }) }), true],
      ["failed", thread({ draft: APPROVED({ message: sendOut("failed").draft.message }) }), true],
    ];
    for (const [name, t, canEdit] of cases) {
      const { container, unmount } = setup({ thread: t, canEdit });
      expect((await axe.run(container, rules)).violations, name).toEqual([]);
      unmount();
    }
  });

  it("has no violations with an error or open dialogs", async () => {
    const user = userEvent.setup();
    stubApi(() => failWith(409, "reconnect_required", "Reconnect your mailbox to send."));
    const { container } = setup({ thread: APPROVED_THREAD });
    let dialog = await openSendDialog(user);
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Send message" }));
    await within(dialog).findByText("Reconnect your mailbox to send.");
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.type(screen.getByRole("textbox", { name: "Message" }), "!");
    await user.click(screen.getByRole("button", { name: "Regenerate" }));
    dialog = await screen.findByRole("dialog");
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "Discard" }));
    dialog = await screen.findByRole("dialog");
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect((await axe.run(container, rules)).violations).toEqual([]);
  });

  it("has no violations with a field error showing", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "Bad.",
            fields: { subject: "Add a subject." },
          },
        },
        { status: 422 },
      ),
    );
    const { container } = setup({ thread: OWN });
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await screen.findByText("Fix the highlighted fields and try again.");
    expect((await axe.run(container, rules)).violations).toEqual([]);
  });
});
