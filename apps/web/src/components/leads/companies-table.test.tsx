import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { CompaniesTable } from "./companies-table";
import { parseCompanyQuery, type CompanyOut, type CompanyQuery } from "./company-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const ID1 = "11111111-1111-4111-8111-111111111111";
const ID2 = "33333333-3333-4333-8333-333333333333";

function company(over: Partial<CompanyOut> = {}): CompanyOut {
  return {
    id: ID1,
    name: "Acme Freight",
    website: "https://acme.test",
    domain: "acme.test",
    industry: "Logistics",
    size_label: "11-50",
    location: "Leeds, UK",
    notes: null,
    source: "manual",
    source_retrieved_at: null,
    is_sample: false,
    archived_at: null,
    lead_count: 3,
    contact_count: 2,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    ...over,
  };
}

function renderTable(
  items: CompanyOut[],
  over: { canEdit?: boolean; total?: number; query?: CompanyQuery } = {},
) {
  return render(
    <ToastProvider>
      <CompaniesTable
        workspaceId={WS}
        items={items}
        total={over.total ?? items.length}
        query={over.query ?? parseCompanyQuery({})}
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

describe("CompaniesTable", () => {
  it("renders rows with links, counts, badges and dates", () => {
    renderTable([
      company(),
      company({
        id: ID2,
        name: "Demo Co",
        is_sample: true,
        archived_at: "2026-10-03T00:00:00Z",
        website: null,
      }),
    ]);
    const rows = screen.getAllByRole("row").slice(1);
    const first = within(rows[0]!);
    expect(first.getByRole("link", { name: "Acme Freight" })).toHaveAttribute(
      "href",
      `/leads/companies/${ID1}`,
    );
    const site = first.getByRole("link", { name: "https://acme.test" });
    expect(site).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(site).toHaveAttribute("target", "_blank");
    expect(first.getByText("Logistics")).toBeInTheDocument();
    expect(first.getByText("11–50")).toBeInTheDocument();
    expect(first.getByText("Leeds, UK")).toBeInTheDocument();
    expect(first.getByRole("link", { name: "3 leads at Acme Freight" })).toHaveAttribute(
      "href",
      `/leads?company_id=${ID1}`,
    );
    expect(first.getByRole("link", { name: "2 contacts at Acme Freight" })).toHaveAttribute(
      "href",
      `/leads/contacts?company_id=${ID1}`,
    );
    expect(first.getByText("2026-10-02")).toBeInTheDocument();
    const second = within(rows[1]!);
    expect(second.getByText("Sample")).toBeInTheDocument();
    expect(second.getByText("Archived")).toBeInTheDocument();
  });

  it("makes sortable headers plain links with aria-sort", () => {
    renderTable([company()], { query: parseCompanyQuery({ q: "ac", sort: "-updated_at" }) });
    const updated = screen.getByRole("columnheader", { name: /Updated/ });
    expect(updated).toHaveAttribute("aria-sort", "descending");
    expect(within(updated).getByRole("link")).toHaveAttribute(
      "href",
      "/leads/companies?q=ac&sort=updated_at",
    );
    const name = screen.getByRole("columnheader", { name: "Name" });
    expect(name).toHaveAttribute("aria-sort", "none");
    expect(within(name).getByRole("link")).toHaveAttribute("href", "/leads/companies?q=ac");
  });

  it("paginates with plain links", () => {
    renderTable([company()], { total: 60, query: parseCompanyQuery({ q: "ac", page: "2" }) });
    expect(screen.getByText("Page 2 of 3 · 60 companies")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/leads/companies?q=ac",
    );
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/leads/companies?q=ac&page=3",
    );
  });

  it("has a GET search form that works without JS and keeps the sort", () => {
    renderTable([company()], {
      query: parseCompanyQuery({ q: "ac", size_label: "2-10", sort: "industry" }),
    });
    const form = screen.getByRole("search", { name: "Filter companies" });
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/leads/companies");
    expect(within(form).getByLabelText("Search")).toHaveValue("ac");
    expect(within(form).getByLabelText("Size")).toHaveValue("2-10");
    expect(within(form).getByLabelText("Show")).toHaveValue("active");
    expect(form.querySelector('input[name="sort"]')).toHaveValue("industry");
    expect(form.querySelector('input[name="industry"]')).not.toBeNull();
  });

  it("shows both empty states", () => {
    const { unmount } = renderTable([]);
    expect(screen.getByText("No companies yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add your first company" })).toBeInTheDocument();
    unmount();
    renderTable([], { query: parseCompanyQuery({ q: "zzz" }) });
    expect(screen.getByText("No companies match those filters")).toBeInTheDocument();
  });

  it("is view only for members", () => {
    renderTable([company()], { canEdit: false });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New company" })).toBeNull();
  });

  it("does not link an unsafe website and renders markup as inert text", () => {
    renderTable([
      company({ name: '<img src=x onerror="alert(1)">', website: "javascript:alert(1)" }),
    ]);
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
  });

  it("creates a company sending only the filled fields", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable([company()]);
    await user.click(screen.getByRole("button", { name: "New company" }));
    const dialog = await screen.findByRole("dialog", { name: "New company" });
    await user.type(within(dialog).getByLabelText(/Name/), "Globex");
    await user.type(within(dialog).getByLabelText("Industry"), "Energy");
    await user.click(within(dialog).getByRole("button", { name: "Add company" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: "/companies",
      body: { name: "Globex", industry: "Energy" },
    });
    expect(Object.keys(calls[0]!.body as object).sort()).toEqual(["industry", "name"]);
    expect(await screen.findByText("Company added")).toBeInTheDocument();
  });

  it("requires a name before calling the API", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable([company()]);
    await user.click(screen.getByRole("button", { name: "New company" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Add company" }));
    expect(await within(dialog).findByText("Enter the company's name.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("shows a duplicate website under the Website field", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "company_exists",
            message: "A company with this website already exists.",
            fields: { website: "A company with this website already exists." },
          },
        },
        { status: 409 },
      ),
    );
    renderTable([company()]);
    await user.click(screen.getByRole("button", { name: "New company" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Name/), "Globex");
    await user.type(within(dialog).getByLabelText("Website"), "https://acme.test");
    await user.click(within(dialog).getByRole("button", { name: "Add company" }));
    const website = within(dialog).getByLabelText("Website");
    await waitFor(() => expect(website).toHaveAttribute("aria-invalid", "true"));
    expect(website).toHaveAccessibleDescription(/already exists/);
    expect(refresh).not.toHaveBeenCalled();
    expect(within(dialog).getByText("Some fields need attention")).toBeInTheDocument();
  });

  it("has no axe violations", async () => {
    const user = userEvent.setup();
    const { container } = renderTable([
      company(),
      company({ id: ID2, name: "Demo Co", is_sample: true, archived_at: "2026-10-03T00:00:00Z" }),
    ]);
    const run = () => axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect((await run()).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "New company" }));
    const dialog = await screen.findByRole("dialog");
    expect(
      (await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } })).violations,
    ).toEqual([]);
  });
});
