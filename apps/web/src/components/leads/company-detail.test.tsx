import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { CompanyDetail } from "./company-detail";
import type { CompanyOut, ContactOut, LeadOut } from "./lead-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const CID = "11111111-1111-4111-8111-111111111111";
const LID = "44444444-4444-4444-8444-444444444444";
const PID = "55555555-5555-4555-8555-555555555555";

function company(over: Partial<CompanyOut> = {}): CompanyOut {
  return {
    id: CID,
    name: "Acme Freight",
    website: "https://acme.test",
    domain: "acme.test",
    industry: "Logistics",
    size_label: "11-50",
    location: "Leeds, UK",
    notes: "Line one\nLine two",
    source: "csv-import",
    source_retrieved_at: "2026-09-30T08:15:00Z",
    is_sample: false,
    archived_at: null,
    lead_count: 1,
    contact_count: 2,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    ...over,
  };
}

function lead(over: Partial<LeadOut> = {}): LeadOut {
  return {
    id: LID,
    title: "Warehouse redesign",
    status: "qualified",
    fit_band: "strong",
    fit_score: 75,
    fit_scored_at: null,
    next_action: "Send proposal",
    next_action_at: "2026-10-20T09:00:00Z",
    archived_at: null,
    budget_signal: null,
    company: { id: CID, name: "Acme Freight" },
    contact: null,
    created_at: "2026-10-01T00:00:00Z",
    do_not_contact: false,
    industry: null,
    is_sample: false,
    last_activity_at: null,
    location: null,
    notes: null,
    source: null,
    source_retrieved_at: null,
    stage: null,
    tags: [],
    updated_at: "2026-10-02T00:00:00Z",
    ...over,
  } as LeadOut;
}

function contact(over: Partial<ContactOut> = {}): ContactOut {
  return {
    id: PID,
    full_name: "Ada Lovelace",
    role_title: "COO",
    email: "ada@acme.test",
    phone: null,
    company_id: CID,
    company_name: "Acme Freight",
    do_not_contact: false,
    lead_count: 1,
    is_sample: false,
    archived_at: null,
    notes: null,
    source: null,
    source_retrieved_at: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    ...over,
  } as ContactOut;
}

function renderDetail(
  over: Partial<{
    company: CompanyOut;
    leads: LeadOut[] | null;
    contacts: ContactOut[] | null;
    canEdit: boolean;
  }> = {},
) {
  const leads = over.leads === undefined ? [lead()] : over.leads;
  const contacts =
    over.contacts === undefined
      ? [
          contact(),
          contact({
            id: "66666666-6666-4666-8666-666666666666",
            full_name: "Do Not",
            email: "dnc@acme.test",
            do_not_contact: true,
          }),
        ]
      : over.contacts;
  return render(
    <ToastProvider>
      <CompanyDetail
        workspaceId={WS}
        company={over.company ?? company()}
        leads={leads}
        leadsTotal={leads?.length ?? 0}
        contacts={contacts}
        contactsTotal={contacts?.length ?? 0}
        canEdit={over.canEdit ?? true}
      />
    </ToastProvider>,
  );
}

type Call = { method: string; path: string; body: unknown };
function stubApi(respond?: (call: Call) => Response | undefined) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      const call = { method: req.method, path, body: text ? JSON.parse(text) : undefined };
      calls.push(call);
      return respond?.(call) ?? Response.json(company());
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("CompanyDetail", () => {
  it("shows the summary with provenance and a safe website link", () => {
    renderDetail();
    expect(screen.getByRole("heading", { level: 1, name: "Acme Freight" })).toBeInTheDocument();
    const summary = within(screen.getByRole("region", { name: "Summary" }));
    const link = summary.getByRole("link", { name: "https://acme.test" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(link).toHaveAttribute("target", "_blank");
    expect(summary.getByText("acme.test")).toBeInTheDocument();
    expect(summary.getByText("11–50")).toBeInTheDocument();
    expect(summary.getByText(/Line one\s+Line two/)).toHaveClass("whitespace-pre-wrap");
    expect(summary.getByText(/csv-import/)).toHaveTextContent(
      "csv-import · retrieved 2026-09-30 08:15 UTC",
    );
  });

  it("says when a company was added manually", () => {
    renderDetail({ company: company({ source: "manual", source_retrieved_at: null }) });
    expect(screen.getByText("Added manually")).toBeInTheDocument();
  });

  it("lists leads and contacts with links and a do-not-contact badge", () => {
    renderDetail();
    const leads = within(screen.getByRole("region", { name: "Leads" }));
    expect(leads.getByRole("link", { name: "Warehouse redesign" })).toHaveAttribute(
      "href",
      `/leads/${LID}`,
    );
    expect(leads.getByText("Qualified")).toBeInTheDocument();
    expect(leads.getByText("Strong fit · 75")).toBeInTheDocument();
    expect(leads.getByText(/Send proposal/)).toBeInTheDocument();
    const contacts = within(screen.getByRole("region", { name: "Contacts" }));
    expect(contacts.getByRole("link", { name: "Ada Lovelace" })).toHaveAttribute(
      "href",
      `/leads/contacts/${PID}`,
    );
    expect(contacts.getAllByText("COO").length).toBeGreaterThan(0);
    const dncRow = contacts.getByRole("link", { name: "Do Not" }).closest("tr")!;
    expect(within(dncRow).getByText("Do not contact")).toBeInTheDocument();
    expect(contacts.getAllByText("Do not contact")).toHaveLength(1);
  });

  it("shows empty and failed related lists", () => {
    const { unmount } = renderDetail({ leads: [], contacts: [] });
    expect(screen.getByText("No leads for this company yet")).toBeInTheDocument();
    expect(screen.getByText("No contacts for this company yet")).toBeInTheDocument();
    unmount();
    renderDetail({ leads: null, contacts: null });
    expect(screen.getByText("Couldn't load leads")).toBeInTheDocument();
    expect(screen.getByText("Couldn't load contacts")).toBeInTheDocument();
  });

  it("is read-only for members", () => {
    renderDetail({ canEdit: false });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
  });

  it("renders markup and unsafe websites as inert text", () => {
    renderDetail({
      company: company({
        name: '<img src=x onerror="alert(1)">',
        website: "javascript:alert(1)",
        notes: "<script>alert(1)</script>",
      }),
    });
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      '<img src=x onerror="alert(1)">',
    );
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  });

  it("sends only the changed fields when editing, and blank clears", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit company" });
    const save = within(dialog).getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();
    await user.clear(within(dialog).getByLabelText("Industry"));
    await user.clear(within(dialog).getByLabelText("Location"));
    await user.type(within(dialog).getByLabelText("Location"), "York");
    await user.click(save);
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({
      method: "PATCH",
      path: `/companies/${CID}`,
      body: { industry: null, location: "York" },
    });
    expect(await screen.findByText("Company saved")).toBeInTheDocument();
  });

  it("shows server errors in the edit drawer without closing it", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "company_exists",
            message: "Taken.",
            fields: { website: "Already used." },
          },
        },
        { status: 409 },
      ),
    );
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    await user.clear(within(dialog).getByLabelText("Website"));
    await user.type(within(dialog).getByLabelText("Website"), "https://other.test");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByText("Already used.")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("archives after confirmation", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    const dialog = await screen.findByRole("alertdialog").catch(() => screen.findByRole("dialog"));
    expect(
      within(dialog).getByText("Hidden from lists. Its leads and contacts keep the link."),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toEqual([{ method: "POST", path: `/companies/${CID}/archive`, body: undefined }]);
    expect(await screen.findByText("Company archived")).toBeInTheDocument();
  });

  it("does not archive when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
  });

  it("restores an archived company and disables editing", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail({ company: company({ archived_at: "2026-10-05T00:00:00Z" }) });
    expect(screen.getByText("This company is archived")).toBeInTheDocument();
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toEqual([{ method: "POST", path: `/companies/${CID}/restore`, body: undefined }]);
  });

  it("shows a failed archive as an error", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "forbidden", message: "Not allowed.", fields: {} } },
        { status: 403 },
      ),
    );
    renderDetail({ company: company({ archived_at: "2026-10-05T00:00:00Z" }) });
    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(await screen.findByText("Not allowed.")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("has no axe violations", async () => {
    const user = userEvent.setup();
    const { container } = renderDetail();
    const opts = { rules: { "color-contrast": { enabled: false } } };
    expect((await axe.run(container, opts)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    expect((await axe.run(dialog, opts)).violations).toEqual([]);
  });

  it("has no axe violations when empty, archived and read-only", async () => {
    const { container } = renderDetail({
      company: company({ archived_at: "2026-10-05T00:00:00Z", is_sample: true, website: null }),
      leads: [],
      contacts: [],
      canEdit: false,
    });
    expect(
      (await axe.run(container, { rules: { "color-contrast": { enabled: false } } })).violations,
    ).toEqual([]);
  });
});
