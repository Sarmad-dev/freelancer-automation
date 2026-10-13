import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InboxView } from "./inbox-view";
import type { ConversationDetail, InboxQuery } from "./inbox-model";

vi.mock("./thread-view", () => ({
  ThreadView: ({ thread, backHref }: { thread: { subject: string }; backHref: string }) => (
    <div data-testid="thread">
      {thread.subject}
      <a href={backHref}>Back</a>
    </div>
  ),
}));

const ID = "00000000-0000-4000-8000-0000000000c1";
const base: InboxQuery = { q: "", filter: "", account: "", page: 1, selected: "" };
const counts = { open: 0, unread: 0, needs_review: 0 };

const renderView = (query: InboxQuery, thread: ConversationDetail | null, missing = false) =>
  render(
    <InboxView
      workspaceId="w"
      items={[]}
      total={0}
      counts={counts}
      query={query}
      thread={thread}
      threadMissing={missing}
      hasMailbox
      canEdit
    />,
  );

describe("InboxView", () => {
  it("invites you to pick a conversation when none is open", () => {
    renderView(base, null);
    expect(screen.getByText("Choose a conversation to read it.")).toBeInTheDocument();
  });

  it("shows the open thread with a link back that keeps the filters", () => {
    renderView({ ...base, selected: ID, filter: "unread" }, {
      subject: "Hello",
    } as ConversationDetail);
    expect(screen.getByTestId("thread")).toHaveTextContent("Hello");
    const back = screen.getByRole("link", { name: "Back" }).getAttribute("href") ?? "";
    expect(back).toContain("filter=unread");
    expect(back).not.toContain("c=");
  });

  it("says so when the requested conversation is not available", () => {
    renderView({ ...base, selected: ID }, null, true);
    expect(screen.getByRole("alert")).toHaveTextContent("isn't available");
    expect(screen.getByRole("link", { name: "Back to the list" })).toBeInTheDocument();
  });
});
