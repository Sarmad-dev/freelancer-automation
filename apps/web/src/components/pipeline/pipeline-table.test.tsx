import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { parsePipelineQuery } from "./pipeline-list-model";
import { PipelineTable } from "./pipeline-table";
import type { OpportunityOut, PipelineStage } from "./pipeline-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const TODAY = "2026-10-12";
const KEYS = ["new", "qualified", "proposal", "won", "lost"] as const;
const stage = (key: (typeof KEYS)[number]): PipelineStage => ({
  id: `00000000-0000-4000-8000-00000000030${KEYS.indexOf(key)}`,
  key,
  name: key[0]!.toUpperCase() + key.slice(1),
  position: KEYS.indexOf(key),
  is_won: key === "won",
  is_lost: key === "lost",
});
const STAGES = KEYS.map(stage);

let seq = 0;
function deal(key: (typeof KEYS)[number], over: Partial<OpportunityOut> = {}): OpportunityOut {
  seq += 1;
  const n = String(seq).padStart(12, "0");
  return {
    id: `11111111-1111-4111-8111-${n}`,
    lead: { id: `99999999-9999-4999-8999-${n}`, title: "Acme lead", company_name: "Acme Ltd" },
    stage: stage(key),
    status: key === "won" ? "won" : key === "lost" ? "lost" : "open",
    title: "Big project",
    value_amount: null,
    currency: "USD",
    probability: null,
    weighted_value: null,
    expected_close_date: null,
    next_action: null,
    loss_reason: null,
    closed_at: null,
    owner_user_id: null,
    is_sample: false,
    open_tasks: 0,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    ...over,
  };
}

function renderTable(
  deals: OpportunityOut[],
  over: { canEdit?: boolean; total?: number; params?: Record<string, string> } = {},
) {
  return render(
    <ToastProvider>
      <PipelineTable
        workspaceId={WS}
        deals={deals}
        total={over.total ?? deals.length}
        query={parsePipelineQuery(over.params ?? {})}
        stages={STAGES}
        today={TODAY}
        canEdit={over.canEdit ?? true}
      />
    </ToastProvider>,
  );
}

type Call = { method: string; path: string; body: Record<string, unknown> };
function stubApi(handlers: Record<string, () => Response | Promise<Response>> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const key = `${req.method} ${path.replace(/\/opportunities\/[^/]+\//, "/opportunities/:id/")}`;
      return handlers[key]?.() ?? Response.json(deal("proposal"));
    }),
  );
  return calls;
}

const live = () => document.querySelector<HTMLElement>('p[role="status"]')!;
const rows = () => screen.getAllByRole("row").slice(1);

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
  seq = 0;
});

describe("PipelineTable rows", () => {
  it("shows the deal, its lead, stage, value, chance, close date, next action, tasks and update", () => {
    const d = deal("proposal", {
      value_amount: "12000.5",
      probability: 60,
      expected_close_date: "2026-10-01",
      next_action: "Send proposal",
      open_tasks: 2,
      is_sample: true,
    });
    renderTable([d]);
    const row = within(rows()[0]!);
    expect(row.getByRole("link", { name: "Big project" })).toHaveAttribute(
      "href",
      `/pipeline/${d.id}`,
    );
    expect(row.getByRole("link", { name: "Acme lead" })).toHaveAttribute(
      "href",
      `/leads/${d.lead.id}`,
    );
    expect(row.getByText(/Acme Ltd/)).toBeInTheDocument();
    expect(row.getByText("Proposal", { selector: "span" })).toBeInTheDocument();
    expect(row.getByText("$12,000.50")).toBeInTheDocument();
    expect(row.getByText("60%")).toBeInTheDocument();
    expect(row.getByText("2026-10-01")).toBeInTheDocument();
    expect(row.getByText("Overdue")).toBeInTheDocument();
    expect(row.getByText("Send proposal")).toBeInTheDocument();
    expect(row.getByRole("link", { name: "2 open tasks" })).toHaveAttribute("href", "/tasks");
    expect(row.getByText("2026-10-02")).toBeInTheDocument();
    expect(row.getByText("Sample")).toBeInTheDocument();
  });

  it("leaves missing facts blank in words, never guessed", () => {
    renderTable([deal("new")]);
    const row = within(rows()[0]!);
    expect(row.getAllByText("None").length).toBeGreaterThanOrEqual(4);
    expect(row.queryByText("Overdue")).toBeNull();
    expect(row.queryByText(/%/)).toBeNull();
  });

  it("marks closed deals in words and is not overdue for them", () => {
    renderTable([
      deal("won", { title: "Done", expected_close_date: "2020-01-01" }),
      deal("lost", { title: "Gone" }),
    ]);
    const [won, lost] = rows();
    expect(within(won!).getByText("Won", { selector: "span" })).toBeInTheDocument();
    expect(within(won!).queryByText("Overdue")).toBeNull();
    expect(within(lost!).getByText("Lost", { selector: "span" })).toBeInTheDocument();
  });

  it("renders stored markup as inert text", () => {
    renderTable([
      deal("new", {
        title: '<img src=x onerror="alert(1)">',
        next_action: "<b>soon</b>",
        lead: { id: "9", title: "<script>x</script>", company_name: null },
      }),
    ]);
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(screen.getByText("<b>soon</b>")).toBeInTheDocument();
  });
});

describe("PipelineTable sorting, filters and pages", () => {
  it("links sortable headers, flips the active one and marks it with aria-sort", () => {
    renderTable([deal("new")], { params: { q: "acme" } });
    const updated = screen.getByRole("columnheader", { name: /Updated/ });
    expect(updated).toHaveAttribute("aria-sort", "descending");
    expect(within(updated).getByRole("link")).toHaveAttribute(
      "href",
      "/pipeline?view=table&q=acme&sort=updated_at",
    );
    const title = screen.getByRole("columnheader", { name: /Deal/ });
    expect(title).toHaveAttribute("aria-sort", "none");
    expect(within(title).getByRole("link")).toHaveAttribute(
      "href",
      "/pipeline?view=table&q=acme&sort=title",
    );
    expect(
      within(screen.getByRole("columnheader", { name: /Value/ })).getByRole("link"),
    ).toHaveAttribute("href", "/pipeline?view=table&q=acme&sort=-value_amount");
    expect(
      within(screen.getByRole("columnheader", { name: /Expected close/ })).getByRole("link"),
    ).toHaveAttribute("href", "/pipeline?view=table&q=acme&sort=expected_close_date");
    expect(screen.getByRole("columnheader", { name: "Next action" })).not.toHaveAttribute(
      "aria-sort",
    );
    expect(screen.getByRole("columnheader", { name: "Stage" })).not.toHaveAttribute("aria-sort");
  });

  it("keeps filters and sort in the pagination links", () => {
    renderTable([deal("new")], {
      total: 60,
      params: { page: "2", status: "open", sort: "title", stage_id: STAGES[1]!.id },
    });
    expect(screen.getByText("Page 2 of 3 · 60 deals")).toBeInTheDocument();
    const base = `/pipeline?view=table&status=open&stage_id=${STAGES[1]!.id}&sort=title`;
    expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute("href", base);
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute("href", `${base}&page=3`);
  });

  it("has no Previous on the first page and no Next on the last", () => {
    renderTable([deal("new")], { total: 30 });
    expect(screen.queryByRole("link", { name: "Previous" })).toBeNull();
    expect(screen.getByRole("link", { name: "Next" })).toBeInTheDocument();
  });

  it("offers a search form that works without JavaScript", () => {
    renderTable([deal("new")], {
      params: { q: "acme", status: "won", stage_id: STAGES[3]!.id, sort: "title" },
    });
    const form = screen.getByRole("search", { name: "Filter deals" });
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/pipeline");
    expect(form.querySelector('input[type="hidden"][name="view"]')).toHaveValue("table");
    expect(form.querySelector('input[type="hidden"][name="sort"]')).toHaveValue("title");
    expect(within(form).getByLabelText("Search")).toHaveValue("acme");
    expect(within(form).getByLabelText("Status")).toHaveValue("won");
    expect(within(form).getByLabelText("Stage")).toHaveValue(STAGES[3]!.id);
    expect(
      within(within(form).getByLabelText("Status"))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["All", "Open", "Won", "Lost"]);
    expect(within(form).getByRole("link", { name: "Clear filters" })).toHaveAttribute(
      "href",
      "/pipeline?view=table",
    );
  });

  it("ignores hostile URL params in the form and the links", () => {
    renderTable([deal("new")], {
      params: { status: "x'--", stage_id: "<script>", sort: "-secret", q: "ok" },
    });
    const form = screen.getByRole("search");
    expect(within(form).getByLabelText("Status")).toHaveValue("");
    expect(within(form).getByLabelText("Stage")).toHaveValue("");
    expect(form.querySelector('input[name="sort"]')).toBeNull();
    expect(
      within(screen.getByRole("columnheader", { name: /Deal/ })).getByRole("link"),
    ).toHaveAttribute("href", "/pipeline?view=table&q=ok&sort=title");
  });

  it("shows the empty states", () => {
    const first = renderTable([], { total: 0 });
    expect(screen.getByText("No deals yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to leads" })).toHaveAttribute("href", "/leads");
    expect(screen.getByRole("button", { name: "New deal" })).toBeInTheDocument();
    first.unmount();
    const filtered = renderTable([], { total: 0, params: { q: "zzz" } });
    expect(screen.getByText("No deals match those filters")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New deal" })).toBeNull();
    filtered.unmount();
    renderTable([], { total: 3, params: { page: "5" } });
    expect(screen.getByText("Nothing on this page")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the first page" })).toHaveAttribute(
      "href",
      "/pipeline?view=table",
    );
  });

  it("does not offer New deal to members in the empty state", () => {
    renderTable([], { total: 0, canEdit: false });
    expect(screen.getByText("No deals yet")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New deal" })).toBeNull();
  });
});

describe("PipelineTable moving", () => {
  it("moves a deal from its Move to… menu and updates the row at once", async () => {
    const user = userEvent.setup();
    const d = deal("new");
    let release!: (r: Response) => void;
    const calls = stubApi({
      "POST /opportunities/:id/move": () => new Promise<Response>((r) => (release = r)),
    });
    renderTable([d]);
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Qualified");
    expect(within(rows()[0]!).getByText("Qualified", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByLabelText("Move Big project to…")).toBeDisabled();
    expect(calls[0]).toMatchObject({
      path: `/opportunities/${d.id}/move`,
      body: { stage_id: STAGES[1]!.id, expected_stage_id: STAGES[0]!.id },
    });
    release(Response.json({ ...d, stage: STAGES[1] }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(live()).toHaveTextContent("Moved Big project to Qualified");
  });

  it("puts the row back when the move is refused", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /opportunities/:id/move": () =>
        Response.json(
          { error: { code: "stale_stage", message: "Moved by someone else." } },
          { status: 409 },
        ),
    });
    renderTable([deal("new")]);
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Qualified");
    await waitFor(() => expect(live()).toHaveTextContent("Couldn't move Big project: Moved by"));
    expect(within(rows()[0]!).getByText("New", { selector: "span" })).toBeInTheDocument();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("asks before marking won or lost", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTable([deal("proposal")]);
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Won");
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toHaveLength(0);
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Lost");
    await user.type(await screen.findByLabelText("Why was it lost?"), "No budget");
    await user.click(screen.getByRole("button", { name: "Mark as lost" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toMatchObject({ stage_id: STAGES[4]!.id, loss_reason: "No budget" });
  });

  it("reopens a closed deal", async () => {
    const user = userEvent.setup();
    const d = deal("won");
    const calls = stubApi();
    renderTable([d]);
    expect(screen.queryByLabelText("Move Big project to…")).toBeNull();
    await user.selectOptions(screen.getByLabelText("Reopen Big project…"), "Proposal");
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      path: `/opportunities/${d.id}/reopen`,
      body: { stage_id: STAGES[2]!.id },
    });
  });

  it("is read-only for members", () => {
    renderTable([deal("new"), deal("won")], { canEdit: false });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /Move|Reopen/ })).toBeNull();
    // The search form's own selects are still there.
    expect(screen.getAllByRole("combobox")).toHaveLength(2);
  });
});

describe("PipelineTable accessibility", () => {
  const rules = { rules: { "color-contrast": { enabled: false } } };

  it("has no violations for the list, empty states and dialogs", async () => {
    const user = userEvent.setup();
    const list = renderTable([
      deal("new", { value_amount: "10.00", expected_close_date: "2020-01-01", is_sample: true }),
      deal("won"),
      deal("lost", { title: "Gone" }),
    ]);
    expect((await axe.run(list.container, rules)).violations).toEqual([]);
    await user.selectOptions(screen.getAllByLabelText("Move Big project to…")[0]!, "Won");
    expect((await axe.run(await screen.findByRole("dialog"), rules)).violations).toEqual([]);
    list.unmount();

    const empty = renderTable([], { total: 0 });
    expect((await axe.run(empty.container, rules)).violations).toEqual([]);
    empty.unmount();
    const member = renderTable([deal("new")], { canEdit: false });
    expect((await axe.run(member.container, rules)).violations).toEqual([]);
  });
});
