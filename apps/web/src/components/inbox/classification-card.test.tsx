import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { ClassificationCard } from "./classification-card";
import type { ClassificationOut, ConversationDetail, ThreadMessage } from "./inbox-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const CONV = "00000000-0000-4000-8000-0000000000c1";

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

const classification = (over: Partial<ClassificationOut> = {}): ClassificationOut => ({
  status: "classified",
  category: "interested",
  confidence: 0.86,
  source: "model",
  explanation: "They suggested a time to talk.",
  evidence: ["Sounds good.", "Let's talk Tuesday."],
  needs_review: false,
  review_reason: null,
  review_text: null,
  classified_at: "2026-10-12T14:06:00Z",
  ...over,
});

const thread = (
  c: Partial<ClassificationOut> = {},
  over: Partial<ConversationDetail> = {},
): ConversationDetail => ({
  id: CONV,
  account_id: "00000000-0000-4000-8000-0000000000a1",
  account_email: "me@gmail.example",
  is_demo: false,
  subject: "Hello",
  counterpart: { address: "sam@acme.example", name: "Sam Lee" },
  lead: null,
  company: null,
  classification: classification(c),
  draft: null,
  has_draft: false,
  last_direction: "inbound",
  last_message_at: "2026-10-12T14:05:00Z",
  last_preview: "Sounds good.",
  message_count: 1,
  messages: [message()],
  stop: null,
  unread: false,
  ...over,
});

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

const setup = (t: ConversationDetail, canEdit = true) =>
  render(
    <ToastProvider>
      <ClassificationCard workspaceId={WS} thread={t} canEdit={canEdit} />
    </ToastProvider>,
  );

const picker = () => screen.getByRole("combobox", { name: "Category" });
const CLASSIFICATION_PATH = `/inbox/conversations/${CONV}/classification`;

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("what is shown", () => {
  it("shows the category, confidence, source, explanation and evidence", () => {
    setup(thread());
    const section = screen.getByRole("region", { name: "Classification" });
    expect(within(section).getByText("Interested", { selector: "span" })).toBeInTheDocument();
    expect(within(section).getByText("86% confident")).toBeInTheDocument();
    expect(within(section).getByText("AI")).toBeInTheDocument();
    expect(within(section).getByText("They suggested a time to talk.")).toBeInTheDocument();
    expect(within(section).getByRole("heading", { name: "From the message" })).toBeInTheDocument();
    const quotes = section.querySelectorAll("blockquote");
    expect([...quotes].map((q) => q.textContent)).toEqual(["Sounds good.", "Let's talk Tuesday."]);
    expect(within(section).queryByText("Needs your review")).toBeNull();
  });

  it("says plainly when the source is a demo or a fallback", () => {
    setup(thread({ source: "demo_ai" }));
    expect(screen.getByText(/Demo AI: a rule-based stand-in/)).toBeInTheDocument();
  });

  it("omits confidence, explanation and evidence when there are none", () => {
    setup(thread({ confidence: null, explanation: null, evidence: [], source: "manual" }));
    expect(screen.queryByText(/confident/)).toBeNull();
    expect(screen.queryByText("From the message")).toBeNull();
    expect(screen.getByText("Set by you")).toBeInTheDocument();
  });

  it("asks for a review when needed, with the reason in plain words", () => {
    setup(
      thread({
        needs_review: true,
        review_reason: "low_confidence",
        review_text: "The AI wasn't sure. Please check it.",
      }),
    );
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText("Needs your review")).toBeInTheDocument();
    expect(within(alert).getByText("The AI wasn't sure. Please check it.")).toBeInTheDocument();
  });

  it("shows a pending classification with a way to check again", async () => {
    const user = userEvent.setup();
    setup(thread({ status: "pending", category: null, evidence: [], explanation: null }));
    expect(screen.getByRole("status")).toHaveTextContent("Classifying this reply…");
    expect(screen.queryByRole("combobox")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Check again" }));
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("lets members check a pending classification too", () => {
    setup(thread({ status: "pending", category: null }), false);
    expect(screen.getByRole("button", { name: "Check again" })).toBeEnabled();
  });

  it("shows a failed classification and still lets the owner choose", () => {
    setup(thread({ status: "failed", category: null, evidence: [], explanation: null }));
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't classify this automatically");
    expect(picker()).toHaveValue("");
    expect(screen.getByRole("button", { name: "Save category" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Classify again" })).toBeEnabled();
  });

  it("has nothing to classify before any reply has arrived", () => {
    setup(
      thread(
        { status: "none", category: null, evidence: [], explanation: null },
        { messages: [message({ direction: "outbound" })], last_direction: "outbound" },
      ),
    );
    expect(screen.getByText("Nothing to classify yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("offers a first classification when a reply is waiting", () => {
    setup(thread({ status: "none", category: null, evidence: [], explanation: null }));
    expect(screen.getByText("This reply hasn't been classified yet.")).toBeInTheDocument();
    expect(picker()).toBeInTheDocument();
  });
});

describe("members", () => {
  it("see the result but cannot change it", () => {
    setup(thread({ needs_review: true, review_text: "Check it." }), false);
    expect(screen.getByText("Interested", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Only the workspace owner can change this.")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("see the same note when classification failed", () => {
    setup(thread({ status: "failed", category: null }), false);
    expect(screen.getByText("Only the workspace owner can change this.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("changing the category", () => {
  it("lists every category and describes the selected one", async () => {
    const user = userEvent.setup();
    setup(thread());
    expect(within(picker()).getAllByRole("option")).toHaveLength(8);
    expect(picker()).toHaveValue("interested");
    expect(picker()).toHaveAccessibleDescription("They want to talk or hear more.");
    await user.selectOptions(picker(), "referral");
    expect(picker()).toHaveAccessibleDescription("They pointed to someone else.");
  });

  it("keeps Save disabled until the category differs", async () => {
    const user = userEvent.setup();
    setup(thread());
    const save = screen.getByRole("button", { name: "Save category" });
    expect(save).toBeDisabled();
    await user.selectOptions(picker(), "question");
    expect(save).toBeEnabled();
  });

  it("saves the chosen category, tells the owner and refreshes", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup(thread());
    await user.selectOptions(picker(), "objection");
    await user.click(screen.getByRole("button", { name: "Save category" }));
    expect(await screen.findByText("Marked as Objection.")).toBeInTheDocument();
    expect(calls).toEqual([
      { method: "PUT", path: CLASSIFICATION_PATH, body: { category: "objection" } },
    ]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("confirms the current category when it needs review", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup(thread({ needs_review: true, review_text: "Check it." }));
    await user.click(screen.getByRole("button", { name: "Confirm “Interested”" }));
    expect(await screen.findByText("Category confirmed")).toBeInTheDocument();
    expect(calls[0]).toEqual({
      method: "PUT",
      path: CLASSIFICATION_PATH,
      body: { category: "interested" },
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("confirms whatever is picked at that moment", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup(thread({ needs_review: true, review_text: "Check it." }));
    await user.selectOptions(picker(), "not_now");
    await user.click(screen.getByRole("button", { name: "Confirm “Not now”" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toEqual({ category: "not_now" });
  });

  it("does not offer Confirm when nothing needs review", () => {
    setup(thread());
    expect(screen.queryByRole("button", { name: /^Confirm/ })).toBeNull();
  });

  it("picks a category for a failed classification", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup(thread({ status: "failed", category: null }));
    await user.selectOptions(picker(), "question");
    await user.click(screen.getByRole("button", { name: "Save category" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toEqual({ category: "question" });
  });

  it("follows the server when a new classification arrives", async () => {
    const user = userEvent.setup();
    const { rerender } = setup(thread());
    await user.selectOptions(picker(), "question");
    rerender(
      <ToastProvider>
        <ClassificationCard workspaceId={WS} thread={thread({ category: "referral" })} canEdit />
      </ToastProvider>,
    );
    expect(picker()).toHaveValue("referral");
  });

  it("shows the server's words when saving is refused", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "forbidden", message: "Only the owner can change this." } },
        { status: 403 },
      ),
    );
    setup(thread());
    await user.selectOptions(picker(), "question");
    await user.click(screen.getByRole("button", { name: "Save category" }));
    expect(await screen.findByText("Only the owner can change this.")).toBeInTheDocument();
    expect(screen.getByText("Couldn't save the category")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(picker()).toHaveValue("question"); // the choice is kept for another try
  });

  it("survives a network failure", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup(thread());
    await user.selectOptions(picker(), "question");
    await user.click(screen.getByRole("button", { name: "Save category" }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Save category" })).toBeEnabled();
  });

  it("allows one request at a time", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => undefined;
    const calls = stubApi(
      () =>
        new Promise<Response>((resolve) => {
          release = resolve;
        }) as unknown as Response,
    );
    setup(thread({ needs_review: true, review_text: "Check it." }));
    await user.selectOptions(picker(), "question");
    await user.click(screen.getByRole("button", { name: "Save category" }));
    expect(await screen.findByRole("button", { name: "Saving…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Classify again" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Confirm/ })).toBeDisabled();
    expect(picker()).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Saving…" }));
    expect(calls).toHaveLength(1);
    release(Response.json({}));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("button", { name: "Save category" })).toBeEnabled();
  });
});

describe("unsubscribe", () => {
  it("asks before adding the address to the do-not-contact list, Cancel first", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup(thread());
    await user.selectOptions(picker(), "unsubscribe");
    expect(picker()).toHaveAccessibleDescription(/added to your do-not-contact list/);
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Save category" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByText("Add sam@acme.example to your do-not-contact list?"),
    ).toBeInTheDocument();
    expect(within(dialog).getByText(/Nothing will be sent to this address/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(calls).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("saves only after the person agrees", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup(thread());
    await user.selectOptions(picker(), "unsubscribe");
    await user.click(screen.getByRole("button", { name: "Save category" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Add to do-not-contact list",
      }),
    );
    expect(await screen.findByText(/is on your do-not-contact list/)).toBeInTheDocument();
    expect(calls).toEqual([
      { method: "PUT", path: CLASSIFICATION_PATH, body: { category: "unsubscribe" } },
    ]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("also asks when confirming an unsubscribe that needs review", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({}));
    setup(
      thread({
        category: "unsubscribe",
        needs_review: true,
        review_reason: "unsubscribe_unconfirmed",
        review_text: "Confirm before we stop contacting them.",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Confirm “Unsubscribe”" }));
    expect(calls).toHaveLength(0);
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", {
        name: "Add to do-not-contact list",
      }),
    );
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(screen.getByRole("button", { name: "Confirm “Unsubscribe”" })).toBeInTheDocument();
    expect(await screen.findByText("Category confirmed")).toBeInTheDocument();
  });
});

describe("classify again", () => {
  it("starts a new classification and refreshes", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json({ queued: true, message: "Queued." }, { status: 202 }),
    );
    setup(thread());
    await user.click(screen.getByRole("button", { name: "Classify again" }));
    expect(await screen.findByText("Classification started")).toBeInTheDocument();
    expect(calls).toEqual([
      { method: "POST", path: `/inbox/conversations/${CONV}/classify`, body: undefined },
    ]);
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("reports a refusal", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "rate_limited", message: "Too many requests. Wait a moment." } },
        { status: 429 },
      ),
    );
    setup(thread());
    await user.click(screen.getByRole("button", { name: "Classify again" }));
    expect(await screen.findByText("Too many requests. Wait a moment.")).toBeInTheDocument();
    expect(screen.getByText("Couldn't start the classification")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("survives a network failure", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    setup(thread());
    await user.click(screen.getByRole("button", { name: "Classify again" }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
  });
});

describe("accessibility", () => {
  it("has no violations in any state, also inside the dialog", async () => {
    const user = userEvent.setup();
    const rules = { rules: { "color-contrast": { enabled: false } } };
    const states: ConversationDetail[] = [
      thread({ needs_review: true, review_text: "Check it." }),
      thread({ status: "pending", category: null }),
      thread({ status: "failed", category: null }),
      thread({ status: "none", category: null }),
    ];
    for (const t of states) {
      const { container, unmount } = setup(t);
      expect((await axe.run(container, rules)).violations).toEqual([]);
      unmount();
    }
    const { container } = setup(thread(), false);
    expect((await axe.run(container, rules)).violations).toEqual([]);
    const owner = setup(thread());
    await user.selectOptions(within(owner.container).getByRole("combobox"), "unsubscribe");
    await user.click(within(owner.container).getByRole("button", { name: "Save category" }));
    expect((await axe.run(await screen.findByRole("dialog"), rules)).violations).toEqual([]);
  });
});
