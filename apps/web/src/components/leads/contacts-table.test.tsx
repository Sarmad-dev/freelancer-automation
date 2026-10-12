import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { ContactsTable } from "./contacts-table";
import { parseContactQuery } from "./contact-model";
import type { ContactOut } from "./lead-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const COMPANY = "33333333-3333-4333-8333-333333333333";
const COMPANIES = [
  { id: COMPANY, name: "Analytical Ltd" },
  { id: "44444444-4444-4444-8444-444444444444", name: "Babbage & Co" },
];

function contact(over: Partial<ContactOut> = {}): ContactOut {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    full_name: "Ada Lovelace",
    email: "ada@example.com",
    role_title: "CTO",
    phone: null,
    company_id: COMPANY,
    company_name: "Analytical Ltd",
    notes: null,
    source: "manual",
    source_retrieved_at: null,
    do_not_contact: false,
    is_sample: false,
    lead_count: 2,
    archived_at: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    ...over,
  };
}

function renderTable(
  contacts: ContactOut[],
  over: {
    canEdit?: boolean;
    total?: number;
    params?: Record<string, string>;
  } = {},
) {
  return render(
    <ToastProvider>
      <ContactsTable
        workspaceId={WS}
        contacts={contacts}
        total={over.total ?? contacts.length}
        query={parseContactQuery(over.params ?? {})}
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
      const key = `${req.method} ${path}`;
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

describe("ContactsTable", () => {
  it("lists contacts with links, badges and counts", () => {
    renderTable([
      contact(),
      contact({
        id: "55555555-5555-4555-8555-555555555555",
        full_name: "Sample Sam",
        email: null,
        role_title: null,
        company_id: null,
        company_name: null,
        lead_count: 0,
        is_sample: true,
        do_not_contact: true,
        archived_at: "2026-10-03T00:00:00Z",
        source: "CSV import",
      }),
    ]);
    const rows = screen.getAllByRole("row").slice(1);
    const first = within(rows[0]!);
    expect(first.getByRole("link", { name: "Ada Lovelace" })).toHaveAttribute(
      "href",
      "/leads/contacts/11111111-1111-4111-8111-111111111111",
    );
    expect(first.getByRole("link", { name: "ada@example.com" })).toHaveAttribute(
      "href",
      "mailto:ada@example.com",
    );
    expect(first.getByRole("link", { name: "Analytical Ltd" })).toHaveAttribute(
      "href",
      `/leads/companies/${COMPANY}`,
    );
    expect(first.getByRole("link", { name: /2 leads for Ada Lovelace/ })).toHaveAttribute(
      "href",
      "/leads?contact_id=11111111-1111-4111-8111-111111111111",
    );
    expect(first.getByText("Manual")).toBeInTheDocument();
    expect(first.getByText("2026-10-02")).toBeInTheDocument();

    const second = within(rows[1]!);
    expect(second.getByText("Sample")).toBeInTheDocument();
    expect(second.getByText("Archived")).toBeInTheDocument();
    expect(second.getByText("Do not contact")).toBeInTheDocument();
    expect(second.getByText("CSV import")).toBeInTheDocument();
    expect(second.getByText("No email")).toBeInTheDocument();
    expect(second.queryAllByRole("link", { name: /@/ })).toHaveLength(0);
  });

  it("never links the email of a do-not-contact contact", () => {
    renderTable([contact({ do_not_contact: true })]);
    expect(screen.getByText("ada@example.com").closest("a")).toBeNull();
  });

  it("renders stored markup as inert text", () => {
    renderTable([
      contact({ full_name: '<img src=x onerror="alert(1)">', role_title: "<b>boss</b>" }),
    ]);
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(screen.getByText("<b>boss</b>")).toBeInTheDocument();
  });

  it("links sortable headers, flips the active one and marks it with aria-sort", () => {
    renderTable([contact()], { params: { q: "ada" } });
    const name = screen.getByRole("columnheader", { name: /Name/ });
    expect(name).toHaveAttribute("aria-sort", "ascending");
    expect(within(name).getByRole("link")).toHaveAttribute(
      "href",
      "/leads/contacts?q=ada&sort=-full_name",
    );
    const email = screen.getByRole("columnheader", { name: /Email/ });
    expect(email).toHaveAttribute("aria-sort", "none");
    expect(within(email).getByRole("link")).toHaveAttribute(
      "href",
      "/leads/contacts?q=ada&sort=email",
    );
    const updated = screen.getByRole("columnheader", { name: /Updated/ });
    expect(within(updated).getByRole("link")).toHaveAttribute(
      "href",
      "/leads/contacts?q=ada&sort=-updated_at",
    );
    expect(screen.getByRole("columnheader", { name: "Role" })).not.toHaveAttribute("aria-sort");
  });

  it("keeps the current filters and sort in the pagination links", () => {
    renderTable([contact()], {
      total: 60,
      params: { page: "2", archived: "all", sort: "-updated_at", company_id: COMPANY },
    });
    expect(screen.getByText("Page 2 of 3 · 60 contacts")).toBeInTheDocument();
    const prev = screen.getByRole("link", { name: "Previous" });
    const next = screen.getByRole("link", { name: "Next" });
    expect(prev.getAttribute("href")).toBe(
      `/leads/contacts?company_id=${COMPANY}&archived=all&sort=-updated_at`,
    );
    expect(next.getAttribute("href")).toBe(
      `/leads/contacts?company_id=${COMPANY}&archived=all&sort=-updated_at&page=3`,
    );
  });

  it("has no Previous on the first page and no Next on the last", () => {
    renderTable([contact()], { total: 30 });
    expect(screen.queryByRole("link", { name: "Previous" })).toBeNull();
    expect(screen.getByRole("link", { name: "Next" })).toBeInTheDocument();
  });

  it("offers a search form that works without JavaScript", () => {
    renderTable([contact()], { params: { q: "ada", archived: "archived", sort: "email" } });
    const form = screen.getByRole("search", { name: "Filter contacts" });
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/leads/contacts");
    expect(within(form).getByLabelText("Search")).toHaveValue("ada");
    expect(within(form).getByLabelText("Company")).toHaveValue("");
    expect(within(form).getByLabelText("Show")).toHaveValue("archived");
    expect(form.querySelector('input[type="hidden"][name="sort"]')).toHaveValue("email");
    expect(within(form).getByRole("link", { name: "Clear filters" })).toHaveAttribute(
      "href",
      "/leads/contacts",
    );
  });

  it("shows the empty states", () => {
    const { unmount } = renderTable([], { total: 0 });
    expect(screen.getByText("No contacts yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add your first contact" })).toBeInTheDocument();
    unmount();
    renderTable([], { total: 0, params: { q: "zzz" } });
    expect(screen.getByText("No contacts match those filters")).toBeInTheDocument();
  });

  it("is read-only for members", () => {
    renderTable([contact()], { canEdit: false });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New contact" })).toBeNull();
  });

  it("creates a contact sending only the filled fields", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable([contact()]);
    await user.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog", { name: "New contact" });
    await user.type(within(dialog).getByLabelText(/Full name/), "Grace Hopper");
    await user.type(within(dialog).getByLabelText("Role"), "Rear Admiral");
    await user.selectOptions(within(dialog).getByLabelText("Company"), COMPANY);
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/contacts");
    expect(post?.body).toEqual({
      full_name: "Grace Hopper",
      role_title: "Rear Admiral",
      company_id: COMPANY,
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("needs a name before it sends anything", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable([contact()]);
    await user.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));
    expect(await within(dialog).findByText("Enter a name.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("shows a duplicate email under Email and keeps the drawer open", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /contacts": () =>
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
    renderTable([contact()]);
    await user.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Full name/), "Ada Two");
    await user.type(within(dialog).getByLabelText("Email"), "ada@example.com");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));
    const email = within(dialog).getByLabelText("Email");
    await waitFor(() => expect(email).toHaveAttribute("aria-invalid", "true"));
    expect(
      within(dialog).getByText("A contact with this email already exists."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Some fields need attention")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("shows a bad phone number under Phone", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /contacts": () =>
        Response.json(
          {
            error: {
              code: "validation_error",
              message: "Check the highlighted fields.",
              fields: { phone: "Use digits, spaces and + ( ) - . only." },
            },
          },
          { status: 422 },
        ),
    });
    renderTable([contact()]);
    await user.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Full name/), "Ada Two");
    await user.type(within(dialog).getByLabelText("Phone"), "call me");
    await user.click(within(dialog).getByRole("button", { name: "Add contact" }));
    await waitFor(() =>
      expect(within(dialog).getByLabelText("Phone")).toHaveAttribute("aria-invalid", "true"),
    );
    expect(within(dialog).getByText("Use digits, spaces and + ( ) - . only.")).toBeInTheDocument();
  });

  it("has no accessibility violations (list and open drawer)", async () => {
    const user = userEvent.setup();
    const { container } = renderTable([
      contact(),
      contact({
        id: "66666666-6666-4666-8666-666666666666",
        full_name: "Sam",
        do_not_contact: true,
      }),
    ]);
    const rules = { rules: { "color-contrast": { enabled: false } } };
    expect((await axe.run(container, rules)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog");
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
  });
});
