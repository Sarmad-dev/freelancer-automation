import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { ContactDetail } from "./contact-detail";
import type { ContactOut, LeadOut } from "./lead-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const ID = "11111111-1111-4111-8111-111111111111";
const COMPANY = "33333333-3333-4333-8333-333333333333";
const COMPANIES = [
  { id: COMPANY, name: "Analytical Ltd" },
  { id: "44444444-4444-4444-8444-444444444444", name: "Babbage & Co" },
];

function contact(over: Partial<ContactOut> = {}): ContactOut {
  return {
    id: ID,
    full_name: "Ada Lovelace",
    email: "ada@example.com",
    role_title: "CTO",
    phone: "+1 (555) 010-0100",
    company_id: COMPANY,
    company_name: "Analytical Ltd",
    notes: "Met at a meetup.\nLikes short emails.",
    source: "manual",
    source_retrieved_at: null,
    do_not_contact: false,
    is_sample: false,
    lead_count: 1,
    archived_at: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    ...over,
  };
}

function lead(over: Partial<LeadOut> = {}): LeadOut {
  return {
    id: "77777777-7777-4777-8777-777777777777",
    title: "Website rebuild",
    status: "qualified",
    fit_band: "strong",
    fit_score: 75,
    next_action: "Send proposal",
    next_action_at: "2026-10-20T09:00:00Z",
    company: null,
    contact: null,
    tags: [],
    stage: null,
    archived_at: null,
    ...over,
  } as LeadOut;
}

function renderDetail(
  c: ContactOut,
  over: { canEdit?: boolean; leads?: LeadOut[]; leadTotal?: number } = {},
) {
  const leads = over.leads ?? [lead()];
  return render(
    <ToastProvider>
      <ContactDetail
        workspaceId={WS}
        contact={c}
        leads={leads}
        leadTotal={over.leadTotal ?? leads.length}
        companies={COMPANIES}
        canEdit={over.canEdit ?? true}
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
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const key = `${req.method} ${path.replace(ID, ":id")}`;
      if (extra[key]) return extra[key]();
      return Response.json(contact());
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("ContactDetail", () => {
  it("shows the summary, links and provenance", () => {
    renderDetail(contact({ source: "CSV import", source_retrieved_at: "2026-09-30T08:15:00Z" }));
    expect(screen.getByRole("heading", { level: 1, name: "Ada Lovelace" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ada@example.com" })).toHaveAttribute(
      "href",
      "mailto:ada@example.com",
    );
    expect(screen.getByRole("link", { name: "+1 (555) 010-0100" })).toHaveAttribute(
      "href",
      "tel:+15550100100",
    );
    expect(screen.getByRole("link", { name: "Analytical Ltd" })).toHaveAttribute(
      "href",
      `/leads/companies/${COMPANY}`,
    );
    expect(screen.getByText("CTO")).toBeInTheDocument();
    const notes = screen.getByText(/Met at a meetup\./);
    expect(notes.className).toContain("whitespace-pre-wrap");
    expect(
      screen.getByText("Source: CSV import · Retrieved 2026-09-30 08:15 UTC"),
    ).toBeInTheDocument();
  });

  it("says when a contact was added by hand", () => {
    renderDetail(contact({ source: "manual" }));
    expect(screen.getByText("Added manually")).toBeInTheDocument();
  });

  it("lists linked leads with status, fit and next action, or says there are none", () => {
    const { unmount } = renderDetail(contact());
    const item = screen.getByRole("listitem");
    expect(within(item).getByRole("link", { name: "Website rebuild" })).toHaveAttribute(
      "href",
      "/leads/77777777-7777-4777-8777-777777777777",
    );
    expect(within(item).getByText("Qualified")).toBeInTheDocument();
    expect(within(item).getByText("Strong fit · 75")).toBeInTheDocument();
    expect(within(item).getByText(/Send proposal/)).toBeInTheDocument();
    unmount();
    renderDetail(contact(), { leads: [] });
    expect(screen.getByText("No active leads are linked to this contact yet.")).toBeInTheDocument();
  });

  it("warns prominently about a do-not-contact email and does not link it", () => {
    renderDetail(contact({ do_not_contact: true }));
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "This email is on your do-not-contact list. Nothing will be sent to it, by you or by any automation.",
    );
    expect(screen.getAllByText("Do not contact").length).toBeGreaterThan(0);
    expect(screen.getByText("ada@example.com").closest("a")).toBeNull();
  });

  it("renders stored markup as inert text", () => {
    renderDetail(
      contact({
        full_name: '<img src=x onerror="alert(1)">',
        notes: "<script>alert(1)</script>",
        role_title: "<b>boss</b>",
      }),
      { leads: [lead({ title: "<i>Lead</i>" })] },
    );
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(document.querySelector("i")).toBeNull();
    expect(screen.getByText("<script>alert(1)</script>")).toBeInTheDocument();
  });

  it("does not turn a bad phone value into a tel link", () => {
    renderDetail(contact({ phone: "javascript:alert(1)" }));
    const phone = screen.getByText("javascript:alert(1)");
    expect(phone.closest("a")).toBeNull();
    expect(document.querySelector('a[href^="tel:"]')).toBeNull();
    expect(document.querySelector('a[href^="javascript:"]')).toBeNull();
  });

  it("is read-only for members", () => {
    renderDetail(contact(), { canEdit: false });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
  });

  it("edits sending only what changed, with a blank company clearing it", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail(contact());
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit contact" });
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(within(dialog).getByLabelText(/Full name/)).toHaveValue("Ada Lovelace");
    await user.selectOptions(within(dialog).getByLabelText("Company"), "");
    await user.clear(within(dialog).getByLabelText("Phone"));
    await user.clear(within(dialog).getByLabelText("Role"));
    await user.type(within(dialog).getByLabelText("Role"), "CEO");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.path).toBe(`/contacts/${ID}`);
    expect(patch?.body).toEqual({ company_id: null, phone: null, role_title: "CEO" });
  });

  it("shows a duplicate email under Email when editing", async () => {
    const user = userEvent.setup();
    stubApi({
      "PATCH /contacts/:id": () =>
        Response.json(
          {
            error: {
              code: "contact_exists",
              message: "A contact with this email already exists.",
              fields: { email: "A contact with this email already exists." },
            },
          },
          { status: 409 },
        ),
    });
    renderDetail(contact());
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    await user.clear(within(dialog).getByLabelText("Email"));
    await user.type(within(dialog).getByLabelText("Email"), "taken@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() =>
      expect(within(dialog).getByLabelText("Email")).toHaveAttribute("aria-invalid", "true"),
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("archives after confirmation", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail(contact());
    await user.click(screen.getByRole("button", { name: "Archive" }));
    const confirm = await screen.findByRole("dialog", { name: "Archive this contact?" });
    expect(
      within(confirm).getByText("Hidden from lists. Their leads keep the link."),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await user.click(within(confirm).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([`POST /contacts/${ID}/archive`]);
  });

  it("does not archive when the confirmation is cancelled", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail(contact());
    await user.click(screen.getByRole("button", { name: "Archive" }));
    const confirm = await screen.findByRole("dialog");
    await user.click(within(confirm).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
  });

  it("restores an archived contact and disables editing", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail(contact({ archived_at: "2026-10-03T00:00:00Z" }));
    expect(screen.getByText("This contact is archived")).toBeInTheDocument();
    expect(screen.getAllByText("Archived").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([`POST /contacts/${ID}/restore`]);
  });

  it("shows a failed archive instead of failing silently", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /contacts/:id/archive": () =>
        Response.json(
          { error: { code: "forbidden", message: "Only the owner can do that.", fields: {} } },
          { status: 403 },
        ),
    });
    renderDetail(contact());
    await user.click(screen.getByRole("button", { name: "Archive" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Archive" }),
    );
    expect(await screen.findByText("Only the owner can do that.")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("has no accessibility violations (page, edit drawer and archived)", async () => {
    const user = userEvent.setup();
    const rules = { rules: { "color-contrast": { enabled: false } } };
    const { container, unmount } = renderDetail(contact({ do_not_contact: true, is_sample: true }));
    expect((await axe.run(container, rules)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
    unmount();
    const second = renderDetail(contact({ archived_at: "2026-10-03T00:00:00Z" }), { leads: [] });
    expect((await axe.run(second.container, rules)).violations).toEqual([]);
  });
});
