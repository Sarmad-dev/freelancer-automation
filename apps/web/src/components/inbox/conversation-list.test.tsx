import { render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { describe, expect, it } from "vitest";
import { ConversationList } from "./conversation-list";
import type { ConversationSummary, InboxCounts, InboxQuery } from "./inbox-model";

const ID = "00000000-0000-4000-8000-0000000000c1";
const base: InboxQuery = { q: "", filter: "", account: "", page: 1, selected: "" };
const counts: InboxCounts = { open: 3, unread: 2, needs_review: 1 };

const item = (over: Partial<ConversationSummary> = {}): ConversationSummary => ({
  id: ID,
  account_id: "00000000-0000-4000-8000-0000000000a1",
  account_email: "me@gmail.example",
  is_demo: false,
  subject: "Website rebuild",
  counterpart: { address: "sam@acme.example", name: "Sam Lee" },
  lead: null,
  company: { id: "00000000-0000-4000-8000-0000000000b1", name: "Acme Inc" },
  classification: {
    status: "classified",
    category: "interested",
    confidence: 0.9,
    source: "model",
    explanation: null,
    evidence: [],
    needs_review: false,
    review_reason: null,
    review_text: null,
    classified_at: "2026-10-12T14:06:00Z",
  },
  has_draft: false,
  last_direction: "inbound",
  last_message_at: "2026-10-12T14:05:00Z",
  last_preview: "Sounds good.",
  message_count: 2,
  stop: null,
  unread: false,
  ...over,
});

const renderList = (
  items: ConversationSummary[],
  query = base,
  hasMailbox = true,
  total = items.length,
) =>
  render(
    <ConversationList
      items={items}
      total={total}
      query={query}
      counts={counts}
      hasMailbox={hasMailbox}
    />,
  );

describe("ConversationList", () => {
  it("shows sender, subject, preview, category and company, and links to the thread", () => {
    renderList([item()]);
    const link = screen.getByRole("link", { name: /Sam Lee/ });
    expect(link).toHaveAttribute("href", expect.stringContaining(`c=${ID}`));
    expect(within(link).getByText("Website rebuild")).toBeInTheDocument();
    expect(within(link).getByText("Sounds good.")).toBeInTheDocument();
    expect(within(link).getByText("Interested")).toBeInTheDocument();
    expect(within(link).getByText("Acme Inc")).toBeInTheDocument();
  });

  it("flags unread, needs review, stopped, draft and demo conversations", () => {
    renderList([
      item({
        unread: true,
        has_draft: true,
        is_demo: true,
        stop: {
          id: ID,
          reason: "unsubscribe",
          address: "sam@acme.example",
          since: "2026-10-12T14:06:00Z",
          text: "Stopped",
        },
        classification: { ...item().classification, needs_review: true },
      }),
    ]);
    const link = screen.getByRole("link", { name: /Sam Lee/ });
    expect(within(link).getByText(/Unread/)).toBeInTheDocument();
    expect(within(link).getByText("Needs review")).toBeInTheDocument();
    expect(within(link).getByText("Stopped")).toBeInTheDocument();
    expect(within(link).getByText("Draft")).toBeInTheDocument();
  });

  it("shows classifying while pending and an unknown-sender fallback", () => {
    renderList([
      item({
        counterpart: { address: "", name: null },
        subject: null,
        classification: { ...item().classification, status: "pending", category: null },
      }),
    ]);
    expect(screen.getByText("Classifying…")).toBeInTheDocument();
    expect(screen.getByText("Unknown sender")).toBeInTheDocument();
    expect(screen.getByText("(no subject)")).toBeInTheDocument();
  });

  it("marks the open conversation and shows counts on the filters", () => {
    renderList([item()], { ...base, selected: ID });
    expect(screen.getByRole("link", { name: /Sam Lee/ })).toHaveAttribute("aria-current", "true");
    expect(screen.getByRole("link", { name: /Unread/ })).toHaveTextContent("2");
    expect(screen.getByRole("link", { name: /Needs review/ })).toHaveTextContent("1");
    expect(screen.getByRole("link", { name: "Interested" })).toHaveAttribute(
      "href",
      expect.stringContaining("filter=interested"),
    );
  });

  it("explains each empty state", () => {
    const { unmount } = renderList([], base, false);
    expect(screen.getByText("No mailbox connected")).toBeInTheDocument();
    unmount();
    const second = renderList([], { ...base, q: "zzz" });
    expect(screen.getByText("Nothing matches")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Clear search and filters" })).toHaveAttribute(
      "href",
      "/inbox",
    );
    second.unmount();
    renderList([]);
    expect(screen.getByText("No conversations yet")).toBeInTheDocument();
  });

  it("pages with Newer and Older links", () => {
    renderList([item()], { ...base, page: 2 }, true, 80);
    expect(screen.getByText("Page 2 of 4")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Newer" })).toHaveAttribute(
      "href",
      expect.stringContaining("/inbox"),
    );
    expect(screen.getByRole("link", { name: "Older" })).toHaveAttribute(
      "href",
      expect.stringContaining("page=3"),
    );
  });

  it("keeps the search form usable and has no accessibility violations", async () => {
    const { container } = renderList([item({ unread: true })]);
    expect(screen.getByRole("search")).toBeInTheDocument();
    expect(screen.getByLabelText("Search conversations")).toBeInTheDocument();
    const result = await axe.run(container);
    expect(result.violations).toEqual([]);
  });
});
