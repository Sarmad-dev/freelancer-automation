import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { parseLeadQuery, type LeadListQuery } from "./lead-list-model";
import type { LeadOut, TagOut } from "./lead-model";
import { LeadsTable } from "./leads-table";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh, push: vi.fn() }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const NOW = "2026-10-12T12:00:00.000Z";
const TAG_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const TAG_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const L1 = "11111111-1111-4111-8111-111111111111";
const L2 = "33333333-3333-4333-8333-333333333333";

const TAGS: TagOut[] = [
  { id: TAG_A, name: "Warm", color: null, created_at: NOW, updated_at: NOW },
  { id: TAG_B, name: "Referral", color: null, created_at: NOW, updated_at: NOW },
];

function lead(over: Partial<LeadOut> = {}): LeadOut {
  return {
    id: L1,
    title: "Redesign the booking flow",
    status: "new",
    company: { id: "c1", name: "Acme Studio" },
    contact: { id: "p1", full_name: "Rosa Diaz", email: "rosa@example.com" },
    fit_band: "strong",
    fit_score: 75,
    fit_scored_at: NOW,
    next_action: "Send intro email",
    next_action_at: "2026-10-01T09:00:00Z",
    last_activity_at: null,
    updated_at: "2026-10-10T10:00:00Z",
    created_at: "2026-10-01T00:00:00Z",
    archived_at: null,
    is_sample: false,
    do_not_contact: false,
    tags: [{ id: TAG_A, name: "Warm", color: null }],
    budget_signal: null,
    industry: null,
    location: null,
    notes: null,
    source: "manual",
    source_retrieved_at: null,
    stage: null,
    ...over,
  } as LeadOut;
}

const two = [
  lead(),
  lead({
    id: L2,
    title: "Newsletter audit",
    status: "won",
    is_sample: true,
    do_not_contact: true,
    archived_at: "2026-10-05T00:00:00Z",
    fit_band: null,
    fit_score: null,
    next_action: null,
    next_action_at: null,
    tags: [],
    company: null,
    contact: null,
  }),
];

function renderTable(
  over: {
    items?: LeadOut[];
    total?: number;
    canEdit?: boolean;
    query?: LeadListQuery;
    tags?: TagOut[];
  } = {},
) {
  const items = over.items ?? two;
  return render(
    <ToastProvider>
      <LeadsTable
        workspaceId={WS}
        items={items}
        total={over.total ?? items.length}
        query={over.query ?? parseLeadQuery({})}
        tags={over.tags ?? TAGS}
        canEdit={over.canEdit ?? true}
        nowIso={NOW}
      />
    </ToastProvider>,
  );
}

type Call = { method: string; path: string; body: unknown };
function stubApi(extra: Record<string, () => Response> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const url = new URL(req.url);
      const path = url.pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const key = `${req.method} ${path}`;
      if (extra[key]) return extra[key]();
      if (key === "GET /companies") {
        return Response.json({
          items: [{ id: "c1", name: "Acme Studio" }],
          total: 1,
          limit: 100,
          offset: 0,
        });
      }
      if (key === "POST /leads/bulk-tags") {
        return Response.json({ leads: 2, tags_added: 2, tags_removed: 0 });
      }
      return Response.json(lead(), { status: 201 });
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("LeadsTable rows", () => {
  it("shows the lead with words, not colour, for status and fit", () => {
    renderTable();
    const rows = screen.getAllByRole("row").slice(1);
    const first = within(rows[0]!);
    expect(first.getByRole("link", { name: "Redesign the booking flow" })).toHaveAttribute(
      "href",
      `/leads/${L1}`,
    );
    expect(first.getByText("Acme Studio")).toBeInTheDocument();
    expect(first.getByText("Rosa Diaz")).toBeInTheDocument();
    expect(first.getByText("New")).toBeInTheDocument();
    expect(first.getByText("Strong fit · 75")).toBeInTheDocument();
    expect(first.getByText("Send intro email")).toBeInTheDocument();
    expect(first.getByText("2026-10-01")).toBeInTheDocument();
    expect(first.getByText("Overdue")).toBeInTheDocument();
    expect(first.getByText("Warm")).toBeInTheDocument();
    expect(first.getByText("2026-10-10")).toBeInTheDocument();

    const second = within(rows[1]!);
    expect(second.getByText("Sample")).toBeInTheDocument();
    expect(second.getByText("Do not contact")).toBeInTheDocument();
    expect(second.getByText("Archived")).toBeInTheDocument();
    expect(second.getByText("Not scored")).toBeInTheDocument();
    expect(second.queryByText("Overdue")).toBeNull();
  });

  it("renders stored markup as inert text", () => {
    renderTable({ items: [lead({ title: '<img src=x onerror="alert(1)">' })] });
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
  });

  it("has a table caption and sortable headers that are plain links", () => {
    renderTable({ query: parseLeadQuery({ sort: "title", fit: "strong" }) });
    expect(document.querySelector("caption")).toHaveClass("sr-only");
    const title = screen.getByRole("columnheader", { name: /Title/ });
    expect(title).toHaveAttribute("aria-sort", "ascending");
    expect(within(title).getByRole("link")).toHaveAttribute(
      "href",
      "/leads?fit=strong&sort=-title",
    );
    const updated = screen.getByRole("columnheader", { name: /Updated/ });
    expect(updated).toHaveAttribute("aria-sort", "none");
    expect(within(updated).getByRole("link")).toHaveAttribute("href", "/leads?fit=strong");
    expect(
      within(screen.getByRole("columnheader", { name: /Fit/ })).getByRole("link"),
    ).toHaveAttribute("href", "/leads?fit=strong&sort=-fit_score");
  });

  it("paginates with plain links and keeps the filters", () => {
    renderTable({
      items: [lead()],
      total: 60,
      query: parseLeadQuery({ page: "2", status: ["new", "replied"] }),
    });
    expect(screen.getByText("Page 2 of 3 · 60 leads")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/leads?status=new&status=replied",
    );
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/leads?page=3&status=new&status=replied",
    );
  });

  it("shows removable filter chips as links, and a way to clear them", () => {
    renderTable({
      query: parseLeadQuery({ status: ["new", "lost"], tag_id: TAG_A, overdue: "1" }),
    });
    const chips = screen.getByRole("list", { name: "Active filters" });
    expect(within(chips).getByText("Tag: Warm")).toBeInTheDocument();
    const remove = within(chips).getByRole("link", { name: "Remove filter: Status: Lost" });
    expect(remove.getAttribute("href")).toContain("status=new");
    expect(remove.getAttribute("href")).not.toContain("lost");
    expect(within(chips).getByRole("link", { name: "Clear filters" })).toHaveAttribute(
      "href",
      "/leads",
    );
  });

  it("builds the search form so it works without JavaScript", () => {
    renderTable({ query: parseLeadQuery({ status: ["won"], q: "acme", company_id: L1 }) });
    const form = screen.getByRole("search", { name: "Filter leads" });
    expect(form).toHaveAttribute("method", "get");
    expect(within(form).getByRole("searchbox", { name: "Search" })).toHaveValue("acme");
    expect(within(form).getByRole("checkbox", { name: "Won" })).toBeChecked();
    expect(within(form).getByRole("checkbox", { name: "New" })).not.toBeChecked();
    expect(form.querySelector('input[name="company_id"]')).toHaveValue(L1);
    expect(screen.getByRole("link", { name: "How is fit calculated?" })).toHaveAttribute(
      "href",
      "/leads/scoring",
    );
  });
});

describe("read-only members", () => {
  it("get no checkboxes, New lead, Import or Export", () => {
    renderTable({ canEdit: false });
    expect(screen.queryAllByRole("checkbox", { name: /Select/ })).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "New lead" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Export CSV" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Import CSV" })).toBeNull();
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Redesign the booking flow" })).toBeInTheDocument();
  });

  it("owners get an export link with the same filters but no page", () => {
    renderTable({ query: parseLeadQuery({ fit: "weak", page: "2", status: ["new"] }), total: 60 });
    const link = screen.getByRole("link", { name: "Export CSV" });
    expect(link).toHaveAttribute("download");
    const href = link.getAttribute("href")!;
    expect(href.startsWith(`/api/v1/workspaces/${WS}/leads/export?`)).toBe(true);
    expect(href).toContain("fit=weak");
    expect(href).toContain("status=new");
    expect(href).not.toContain("page");
    expect(screen.getByRole("link", { name: "Import CSV" })).toHaveAttribute(
      "href",
      "/leads/import",
    );
  });
});

describe("empty states", () => {
  it("offers to add or import when there are no leads at all", async () => {
    stubApi();
    const user = userEvent.setup();
    renderTable({ items: [], total: 0 });
    expect(screen.getByRole("heading", { name: "No leads yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import CSV" })).toHaveAttribute(
      "href",
      "/leads/import",
    );
    await user.click(screen.getByRole("button", { name: "New lead" }));
    expect(await screen.findByRole("dialog", { name: "New lead" })).toBeInTheDocument();
  });

  it("does not offer actions to members", () => {
    renderTable({ items: [], total: 0, canEdit: false });
    expect(screen.getByRole("heading", { name: "No leads yet" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New lead" })).toBeNull();
  });

  it("says when filters match nothing and offers to clear them", () => {
    renderTable({ items: [], total: 0, query: parseLeadQuery({ q: "zzz", sort: "title" }) });
    expect(
      screen.getByRole("heading", { name: "No leads match these filters" }),
    ).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Clear filters" });
    for (const l of links) expect(l).toHaveAttribute("href", "/leads?sort=title");
  });

  it("handles a page past the end", () => {
    renderTable({ items: [], total: 30, query: parseLeadQuery({ page: "9" }) });
    expect(screen.getByRole("link", { name: "Go to the first page" })).toHaveAttribute(
      "href",
      "/leads",
    );
  });
});

describe("bulk tagging", () => {
  it("selects rows and sends the ids with the chosen tag", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable();
    expect(screen.queryByText(/selected$/)).toBeNull();

    await user.click(screen.getByRole("checkbox", { name: "Select all leads on this page" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Select Newsletter audit" }));
    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(
      screen.getByRole("checkbox", { name: "Select all leads on this page" }),
    ).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Select Newsletter audit" }));

    const add = screen.getByRole("button", { name: "Add tag" });
    expect(add).toBeDisabled();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tag for selected leads" }),
      "Referral",
    );
    await user.click(add);

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const call = calls.find((c) => c.path === "/leads/bulk-tags")!;
    expect(call.method).toBe("POST");
    expect(call.body).toEqual({ lead_ids: [L1, L2], add_tag_ids: [TAG_B] });
    expect(await screen.findByText(/2 leads checked · 2 tags added/)).toBeInTheDocument();
    expect(screen.queryByText(/selected$/)).toBeNull();
  });

  it("removes a tag from one lead", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      "POST /leads/bulk-tags": () => Response.json({ leads: 1, tags_added: 0, tags_removed: 1 }),
    });
    renderTable();
    await user.click(screen.getByRole("checkbox", { name: "Select Redesign the booking flow" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tag for selected leads" }),
      "Warm",
    );
    await user.click(screen.getByRole("button", { name: "Remove tag" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls.find((c) => c.path === "/leads/bulk-tags")!.body).toEqual({
      lead_ids: [L1],
      remove_tag_ids: [TAG_A],
    });
    expect(await screen.findByText(/1 lead checked · 1 tag removed/)).toBeInTheDocument();
  });

  it("shows the failure and keeps the selection", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /leads/bulk-tags": () =>
        Response.json(
          { error: { code: "forbidden", message: "Only the owner can do that.", fields: {} } },
          { status: 403 },
        ),
    });
    renderTable();
    await user.click(screen.getByRole("checkbox", { name: "Select all leads on this page" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Tag for selected leads" }),
      "Warm",
    );
    await user.click(screen.getByRole("button", { name: "Add tag" }));
    expect(await screen.findByText("Only the owner can do that.")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });
});

describe("New lead drawer", () => {
  it("sends only the fields that were filled in", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable();
    await user.click(screen.getByRole("button", { name: "New lead" }));
    const dialog = await screen.findByRole("dialog", { name: "New lead" });
    await waitFor(() => expect(calls.some((c) => c.path === "/companies")).toBe(true));

    await user.type(within(dialog).getByRole("textbox", { name: /^Title/ }), "  Brand refresh ");
    await user.type(within(dialog).getByRole("combobox", { name: "Company name" }), "Acme Studio");
    await user.selectOptions(
      within(dialog).getByRole("combobox", { name: "Budget signal" }),
      "High",
    );
    await user.click(within(dialog).getByRole("checkbox", { name: "Referral" }));
    await user.click(within(dialog).getByRole("button", { name: "Add lead" }));

    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const post = calls.find((c) => c.method === "POST" && c.path === "/leads")!;
    expect(post.body).toEqual({
      title: "Brand refresh",
      status: "new",
      company_name: "Acme Studio",
      budget_signal: "high",
      tag_ids: [TAG_B],
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("converts the next action date to an ISO string", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable();
    await user.click(screen.getByRole("button", { name: "New lead" }));
    const dialog = await screen.findByRole("dialog", { name: "New lead" });
    await user.type(within(dialog).getByRole("textbox", { name: /^Title/ }), "Call back");
    await user.type(within(dialog).getByRole("textbox", { name: "Next action" }), "Phone them");
    await user.type(within(dialog).getByLabelText("Next action date (UTC)"), "2026-11-02T09:30");
    await user.click(within(dialog).getByRole("button", { name: "Add lead" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "POST" && c.path === "/leads")!.body).toEqual({
      title: "Call back",
      status: "new",
      next_action: "Phone them",
      next_action_at: "2026-11-02T09:30:00.000Z",
    });
  });

  it("asks for a title before sending anything", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable();
    await user.click(screen.getByRole("button", { name: "New lead" }));
    const dialog = await screen.findByRole("dialog", { name: "New lead" });
    await user.click(within(dialog).getByRole("button", { name: "Add lead" }));
    expect(await within(dialog).findByText("Enter a title for this lead.")).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("maps API field errors onto the fields and stays open", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /leads": () =>
        Response.json(
          {
            error: {
              code: "validation_error",
              message: "Check the highlighted fields.",
              fields: {
                contact_email: "Enter a valid email address.",
                company_website: "Use a full web address.",
              },
            },
          },
          { status: 422 },
        ),
    });
    renderTable();
    await user.click(screen.getByRole("button", { name: "New lead" }));
    const dialog = await screen.findByRole("dialog", { name: "New lead" });
    await user.type(within(dialog).getByRole("textbox", { name: /^Title/ }), "X");
    await user.type(within(dialog).getByRole("textbox", { name: "Contact email" }), "nope");
    await user.click(within(dialog).getByRole("button", { name: "Add lead" }));

    expect(await within(dialog).findByText("Some fields need attention")).toBeInTheDocument();
    const email = within(dialog).getByRole("textbox", { name: "Contact email" });
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveAccessibleDescription("Enter a valid email address.");
    expect(within(dialog).getByText("Use a full web address.")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("accessibility", () => {
  it("has no axe violations (owner, with rows and bulk bar)", async () => {
    const user = userEvent.setup();
    const { container } = renderTable({
      query: parseLeadQuery({ status: ["new"], fit: "strong" }),
      total: 60,
    });
    await user.click(screen.getByRole("checkbox", { name: "Select all leads on this page" }));
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });

  it("has no axe violations (member, and empty states)", async () => {
    const a = renderTable({ canEdit: false });
    expect(
      (await axe.run(a.container, { rules: { "color-contrast": { enabled: false } } })).violations,
    ).toEqual([]);
    a.unmount();
    const b = renderTable({ items: [], total: 0, query: parseLeadQuery({ q: "x" }) });
    expect(
      (await axe.run(b.container, { rules: { "color-contrast": { enabled: false } } })).violations,
    ).toEqual([]);
  });

  it("has no axe violations with the New lead drawer open", async () => {
    const user = userEvent.setup();
    stubApi();
    renderTable();
    await user.click(screen.getByRole("button", { name: "New lead" }));
    const dialog = await screen.findByRole("dialog", { name: "New lead" });
    const results = await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
