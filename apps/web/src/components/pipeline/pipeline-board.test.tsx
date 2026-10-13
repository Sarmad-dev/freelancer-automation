import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { PipelineBoard } from "./pipeline-board";
import type { BoardColumn, OpportunityOut, PipelineBoard as Board } from "./pipeline-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const TODAY = "2026-10-12";
const KEYS = [
  ["new", "New"],
  ["contacted", "Contacted"],
  ["replied", "Replied"],
  ["qualified", "Qualified"],
  ["meeting", "Meeting"],
  ["proposal", "Proposal"],
  ["won", "Won"],
  ["lost", "Lost"],
] as const;
const sid = (key: string) => {
  const n = KEYS.findIndex(([k]) => k === key);
  return `00000000-0000-4000-8000-00000000010${n}`;
};
const stage = (key: string) => {
  const i = KEYS.findIndex(([k]) => k === key);
  return {
    id: sid(key),
    key,
    name: KEYS[i]![1],
    position: i,
    is_won: key === "won",
    is_lost: key === "lost",
  };
};

let seq = 0;
function deal(stageKey: string, over: Partial<OpportunityOut> = {}): OpportunityOut {
  seq += 1;
  const n = String(seq).padStart(12, "0");
  return {
    id: `11111111-1111-4111-8111-${n}`,
    lead: { id: `99999999-9999-4999-8999-${n}`, title: "Acme lead", company_name: "Acme Ltd" },
    stage: stage(stageKey),
    status: stageKey === "won" ? "won" : stageKey === "lost" ? "lost" : "open",
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

function board(
  placed: Record<string, OpportunityOut[]> = {},
  per: Record<string, Partial<BoardColumn>> = {},
): Board {
  return {
    columns: KEYS.map(([key]) => ({
      stage: stage(key),
      count: (placed[key] ?? []).length,
      unvalued: 0,
      totals: [],
      items: placed[key] ?? [],
      ...per[key],
    })),
    per_column_limit: 50,
    generated_at: "2026-10-12T08:00:00Z",
  };
}

function renderBoard(b: Board, canEdit = true) {
  const ui = (next: Board) => (
    <ToastProvider>
      <PipelineBoard workspaceId={WS} board={next} today={TODAY} canEdit={canEdit} />
    </ToastProvider>
  );
  const result = render(ui(b));
  return { ...result, rerenderBoard: (next: Board) => result.rerender(ui(next)) };
}

type Call = { method: string; path: string; body: Record<string, unknown> };
type Handler = () => Response | Promise<Response>;
function stubApi(handlers: Record<string, Handler> = {}, fallback?: OpportunityOut) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const key = `${req.method} ${path.replace(/\/opportunities\/[^/]+\//, "/opportunities/:id/")}`;
      const handler = handlers[key];
      if (handler) return handler();
      return Response.json(fallback ?? deal("proposal"));
    }),
  );
  return calls;
}

function errorResponse(status: number, code: string, message: string, fields = {}) {
  return Response.json({ error: { code, message, fields } }, { status });
}

function deferred() {
  let release!: (r: Response) => void;
  const promise = new Promise<Response>((resolve) => (release = resolve));
  return { promise, release };
}

function fakeTransfer(data: Record<string, string> = {}) {
  const store = { ...data };
  return {
    setData: (k: string, v: string) => {
      store[k] = v;
    },
    getData: (k: string) => store[k] ?? "",
    effectAllowed: "",
    dropEffect: "",
    types: [] as string[],
  };
}

const col = (key: string) => document.querySelector<HTMLElement>(`[data-stage="${key}"]`)!;
const live = () => document.querySelector<HTMLElement>('p[role="status"]')!;
const card = (title: string) => screen.getByRole("article", { name: title });

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
  seq = 0;
});

describe("PipelineBoard layout", () => {
  it("shows every stage in order, each as a labelled column with its count", () => {
    renderBoard(board({ new: [deal("new"), deal("new", { title: "Second" })] }));
    const headings = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    expect(headings).toEqual([
      "New 2 deals",
      "Contacted 0 deals",
      "Replied 0 deals",
      "Qualified 0 deals",
      "Meeting 0 deals",
      "Proposal 0 deals",
      "Won 0 deals",
      "Lost 0 deals",
    ]);
    const sections = document.querySelectorAll("section[aria-labelledby]");
    expect(sections).toHaveLength(8);
    expect(screen.getByRole("region", { name: "New 2 deals" })).toBeInTheDocument();
    expect(screen.getAllByText("No deals here")).toHaveLength(7);
    expect(screen.getByRole("region", { name: "Pipeline board" })).toHaveAttribute("tabindex", "0");
  });

  it("shows per-currency totals, weighted only for open columns, and how many have no value", () => {
    renderBoard(
      board(
        { qualified: [deal("qualified")], won: [deal("won")] },
        {
          qualified: {
            unvalued: 2,
            totals: [
              { currency: "USD", amount: "1500.00", weighted: "900.00" },
              { currency: "EUR", amount: "200.50", weighted: "100.25" },
            ],
          },
          won: { totals: [{ currency: "USD", amount: "7000.00", weighted: null }] },
        },
      ),
    );
    const q = within(col("qualified"));
    expect(q.getByText("$1,500.00")).toBeInTheDocument();
    expect(q.getByText("€200.50")).toBeInTheDocument();
    expect(q.getByText("≈ $900.00 weighted")).toBeInTheDocument();
    expect(q.getByText("≈ €100.25 weighted")).toBeInTheDocument();
    expect(q.getByText("2 without a value")).toBeInTheDocument();
    const w = within(col("won"));
    expect(w.getByText("$7,000.00")).toBeInTheDocument();
    expect(w.queryByText(/weighted/)).toBeNull();
    expect(within(col("new")).queryByText(/without a value/)).toBeNull();
  });

  it("says when only the newest deals are shown and links to the table for that stage", () => {
    renderBoard(board({ replied: [deal("replied")] }, { replied: { count: 83 } }));
    const r = within(col("replied"));
    expect(r.getByText(/Showing the newest 1 of 83/)).toBeInTheDocument();
    expect(r.getByRole("link", { name: "See all 83 in the table" })).toHaveAttribute(
      "href",
      `/pipeline?view=table&stage_id=${sid("replied")}`,
    );
    expect(within(col("new")).queryByText(/Showing the newest/)).toBeNull();
  });

  it("shows the empty state when there are no deals at all", () => {
    renderBoard(board());
    expect(screen.getByRole("heading", { name: "No deals yet" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Go to leads" })).toHaveAttribute("href", "/leads");
    expect(screen.getByRole("button", { name: "New deal" })).toBeInTheDocument();
    expect(document.querySelector("section")).toBeNull();
  });

  it("does not offer New deal to members", () => {
    renderBoard(board(), false);
    expect(screen.queryByRole("button", { name: "New deal" })).toBeNull();
  });
});

describe("PipelineBoard cards", () => {
  it("shows what matters on a deal and links out", () => {
    renderBoard(
      board({
        proposal: [
          deal("proposal", {
            title: "Big project",
            value_amount: "12000.5",
            probability: 60,
            expected_close_date: "2026-10-01",
            next_action: "Send proposal",
            open_tasks: 3,
            is_sample: true,
          }),
        ],
      }),
    );
    const c = within(card("Big project"));
    expect(c.getByRole("link", { name: "Big project" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/pipeline\/11111111-/),
    );
    expect(c.getByRole("heading", { level: 3 })).toBeInTheDocument();
    expect(c.getByRole("link", { name: "Acme lead" })).toHaveAttribute(
      "href",
      expect.stringMatching(/^\/leads\/99999999-/),
    );
    expect(c.getByText(/Acme Ltd/)).toBeInTheDocument();
    expect(c.getByText("$12,000.50")).toBeInTheDocument();
    expect(c.getByText(/60% chance/)).toBeInTheDocument();
    expect(c.getByText("2026-10-01")).toBeInTheDocument();
    expect(c.getByText("Overdue")).toBeInTheDocument();
    expect(c.getByText("Next: Send proposal")).toBeInTheDocument();
    expect(c.getByRole("link", { name: "3 open tasks" })).toHaveAttribute("href", "/tasks");
    expect(c.getByText("Sample")).toBeInTheDocument();
  });

  it("never invents a chance, a value or an overdue flag", () => {
    renderBoard(
      board({
        new: [deal("new", { title: "Plain" })],
        meeting: [deal("meeting", { title: "Future", expected_close_date: TODAY })],
      }),
    );
    const plain = within(card("Plain"));
    expect(plain.getByText("No value yet")).toBeInTheDocument();
    expect(plain.queryByText(/chance/)).toBeNull();
    expect(plain.queryByText("Overdue")).toBeNull();
    expect(plain.queryByRole("link", { name: /open task/ })).toBeNull();
    expect(within(card("Future")).queryByText("Overdue")).toBeNull();
  });

  it("marks won and lost cards in words and never calls them overdue", () => {
    renderBoard(
      board({
        won: [deal("won", { title: "Done", expected_close_date: "2020-01-01" })],
        lost: [deal("lost", { title: "Gone", loss_reason: "Budget cut" })],
      }),
    );
    expect(within(card("Done")).getByText("Won")).toBeInTheDocument();
    expect(within(card("Done")).queryByText("Overdue")).toBeNull();
    expect(within(card("Gone")).getByText("Lost")).toBeInTheDocument();
    expect(within(card("Gone")).getByText("Lost because: Budget cut")).toBeInTheDocument();
  });

  it("renders stored markup as inert text", () => {
    renderBoard(
      board({
        new: [
          deal("new", {
            title: '<img src=x onerror="alert(1)">',
            next_action: "<script>alert(2)</script>",
            lead: { id: "9", title: "<b>lead</b>", company_name: "<i>co</i>" },
          }),
        ],
      }),
    );
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(screen.getByText("Next: <script>alert(2)</script>")).toBeInTheDocument();
    expect(screen.getByText("<b>lead</b>")).toBeInTheDocument();
  });
});

describe("moving with the menu", () => {
  it("lists every stage and sends the new stage with the one it expects", async () => {
    const user = userEvent.setup();
    const d = deal("qualified", { title: "Big project" });
    const calls = stubApi();
    renderBoard(board({ qualified: [d] }));
    const select = screen.getByLabelText("Move Big project to…");
    const options = within(select)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual([
      "Move to…",
      "New",
      "Contacted",
      "Replied",
      "Qualified (current)",
      "Meeting",
      "Proposal",
      "Won",
      "Lost",
    ]);
    await user.selectOptions(select, "Proposal");
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: `/opportunities/${d.id}/move`,
      body: { stage_id: sid("proposal"), expected_stage_id: sid("qualified") },
    });
    expect(calls[0]!.body).not.toHaveProperty("loss_reason");
    expect(live()).toHaveTextContent("Moved Big project to Proposal");
  });

  it("moves the card, the counts and the totals straight away, before the server answers", async () => {
    const user = userEvent.setup();
    const d = deal("qualified", {
      title: "Big project",
      value_amount: "12000.00",
      probability: 50,
      weighted_value: "6000.00",
    });
    const gate = deferred();
    stubApi({ "POST /opportunities/:id/move": () => gate.promise });
    renderBoard(
      board(
        {
          qualified: [d],
          proposal: [deal("proposal", { title: "Other", value_amount: "1000.00" })],
        },
        {
          qualified: { totals: [{ currency: "USD", amount: "12000.00", weighted: "6000.00" }] },
          proposal: { totals: [{ currency: "USD", amount: "1000.00", weighted: "500.00" }] },
        },
      ),
    );
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Proposal");

    expect(within(col("qualified")).queryByRole("article")).toBeNull();
    expect(within(col("proposal")).getAllByRole("article")).toHaveLength(2);
    expect(screen.getByRole("region", { name: "Proposal 2 deals" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Qualified 0 deals" })).toBeInTheDocument();
    expect(within(col("proposal")).getByText("$13,000.00")).toBeInTheDocument();
    expect(within(col("proposal")).getByText("≈ $6,500.00 weighted")).toBeInTheDocument();
    expect(within(col("qualified")).queryByText("$12,000.00")).toBeNull();
    // The card is disabled while its request is in flight.
    expect(card("Big project")).toHaveAttribute("aria-busy", "true");
    expect(card("Big project")).toHaveAttribute("draggable", "false");
    expect(screen.getByLabelText("Move Big project to…")).toBeDisabled();

    gate.release(Response.json({ ...d, stage: stage("proposal") }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(screen.getByLabelText("Move Big project to…")).toBeEnabled();
  });

  it("puts everything back exactly when the server refuses (422)", async () => {
    const user = userEvent.setup();
    const d = deal("qualified", { title: "Big project", value_amount: "500.00" });
    const gate = deferred();
    stubApi({ "POST /opportunities/:id/move": () => gate.promise });
    const original = board(
      { qualified: [d] },
      { qualified: { totals: [{ currency: "USD", amount: "500.00", weighted: "0.00" }] } },
    );
    renderBoard(original);
    const before = document.querySelector("[aria-label='Pipeline board']")!.innerHTML;
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Meeting");
    expect(within(col("meeting")).getByRole("article")).toBeInTheDocument();
    gate.release(
      errorResponse(422, "validation_error", "Check the highlighted fields.", {
        stage_id: "That stage can't be used.",
      }),
    );
    await waitFor(() =>
      expect(live()).toHaveTextContent("Couldn't move Big project: That stage can't be used."),
    );
    expect(within(col("qualified")).getByRole("article")).toBeInTheDocument();
    expect(within(col("meeting")).queryByRole("article")).toBeNull();
    expect(document.querySelector("[aria-label='Pipeline board']")!.innerHTML).toBe(before);
    expect(refresh).not.toHaveBeenCalled();
    expect(await screen.findByText("Couldn't move Big project")).toBeInTheDocument();
  });

  it("rolls back on a server error and says so", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /opportunities/:id/move": () =>
        errorResponse(500, "internal_error", "The service is temporarily unavailable."),
    });
    renderBoard(board({ new: [deal("new", { title: "Big project" })] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Contacted");
    await waitFor(() =>
      expect(live()).toHaveTextContent(
        "Couldn't move Big project: The service is temporarily unavailable.",
      ),
    );
    expect(within(col("new")).getByRole("article")).toBeInTheDocument();
    expect(within(col("contacted")).queryByRole("article")).toBeNull();
    expect(screen.getByLabelText("Move Big project to…")).toBeEnabled();
  });

  it("rolls back and refreshes the board when someone else moved the deal (409 stale_stage)", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /opportunities/:id/move": () =>
        errorResponse(409, "stale_stage", "This deal was moved by someone else."),
    });
    renderBoard(board({ new: [deal("new", { title: "Big project" })] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Contacted");
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(live()).toHaveTextContent(
      "Couldn't move Big project: This deal was moved by someone else. The board has been refreshed.",
    );
    expect(within(col("new")).getByRole("article")).toBeInTheDocument();
  });

  it("explains a network failure", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    renderBoard(board({ new: [deal("new", { title: "Big project" })] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Contacted");
    await waitFor(() => expect(live()).toHaveTextContent(/Couldn't move Big project: Can't reach/));
    expect(within(col("new")).getByRole("article")).toBeInTheDocument();
  });

  it("takes the server's fresh board over the optimistic one", async () => {
    const user = userEvent.setup();
    const d = deal("new", { title: "Big project" });
    stubApi({}, { ...d, stage: stage("contacted") });
    const { rerenderBoard } = renderBoard(board({ new: [d] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Contacted");
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(within(col("contacted")).getByRole("article")).toBeInTheDocument();
    // The server now says someone moved it on again, and the board arrives with that.
    rerenderBoard(board({ replied: [{ ...d, stage: stage("replied") }] }));
    expect(within(col("replied")).getByRole("article")).toBeInTheDocument();
    expect(within(col("contacted")).queryByRole("article")).toBeNull();
  });
});

describe("won and lost", () => {
  it("asks before marking a deal won, and cancelling sends nothing", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderBoard(board({ proposal: [deal("proposal", { title: "Big project" })] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Won");
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Mark as won?")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toHaveLength(0);
    expect(within(col("proposal")).getByRole("article")).toBeInTheDocument();
    expect(within(col("won")).queryByRole("article")).toBeNull();
    expect(live()).toHaveTextContent("");
  });

  it("moves the deal to Won once confirmed", async () => {
    const user = userEvent.setup();
    const d = deal("proposal", { title: "Big project" });
    const calls = stubApi();
    renderBoard(board({ proposal: [d] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Won");
    await user.click(await screen.findByRole("button", { name: "Mark as won" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]!.body).toEqual({ stage_id: sid("won"), expected_stage_id: sid("proposal") });
    const won = within(col("won"));
    expect(within(won.getByRole("article")).getByText("Won")).toBeInTheDocument();
    expect(live()).toHaveTextContent("Moved Big project to Won");
  });

  it("asks why a deal was lost (optional, 300 characters) and sends the reason", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderBoard(board({ proposal: [deal("proposal", { title: "Big project" })] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Lost");
    const dialog = await screen.findByRole("dialog", { name: "Mark as lost?" });
    const reason = within(dialog).getByLabelText("Why was it lost?");
    expect(reason).toHaveAttribute("maxlength", "300");
    await user.type(reason, "  Went with a cheaper agency  ");
    await user.click(within(dialog).getByRole("button", { name: "Mark as lost" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls[0]!.body).toEqual({
      stage_id: sid("lost"),
      expected_stage_id: sid("proposal"),
      loss_reason: "Went with a cheaper agency",
    });
    expect(within(within(col("lost")).getByRole("article")).getByText("Lost")).toBeInTheDocument();
  });

  it("lets the reason stay blank, and cancelling the lost dialog sends nothing", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderBoard(board({ proposal: [deal("proposal", { title: "Big project" })] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Lost");
    let dialog = await screen.findByRole("dialog", { name: "Mark as lost?" });
    await user.type(within(dialog).getByLabelText("Why was it lost?"), "typed then abandoned");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toHaveLength(0);
    expect(within(col("proposal")).getByRole("article")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Lost");
    dialog = await screen.findByRole("dialog", { name: "Mark as lost?" });
    expect(within(dialog).getByLabelText("Why was it lost?")).toHaveValue("");
    await user.click(within(dialog).getByRole("button", { name: "Mark as lost" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toEqual({ stage_id: sid("lost"), expected_stage_id: sid("proposal") });
  });

  it("puts a lost deal back when the server refuses the reason", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /opportunities/:id/move": () =>
        errorResponse(422, "validation_error", "Check the fields.", {
          loss_reason: "Keep it under 300 characters.",
        }),
    });
    renderBoard(board({ proposal: [deal("proposal", { title: "Big project" })] }));
    await user.selectOptions(screen.getByLabelText("Move Big project to…"), "Lost");
    await user.click(await screen.findByRole("button", { name: "Mark as lost" }));
    await waitFor(() =>
      expect(live()).toHaveTextContent("Couldn't move Big project: Keep it under 300 characters."),
    );
    expect(within(col("proposal")).getByRole("article")).toBeInTheDocument();
    expect(within(col("lost")).queryByRole("article")).toBeNull();
  });
});

describe("reopening closed deals", () => {
  it("offers Reopen with open stages only, and sends the stage", async () => {
    const user = userEvent.setup();
    const d = deal("won", { title: "Done", value_amount: "100.00", probability: 80 });
    const calls = stubApi({}, { ...d, stage: stage("meeting"), status: "open" });
    renderBoard(board({ won: [d] }));
    const select = screen.getByLabelText("Reopen Done…");
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Reopen…", "New", "Contacted", "Replied", "Qualified", "Meeting", "Proposal"]);
    expect(screen.queryByLabelText("Move Done to…")).toBeNull();
    await user.selectOptions(select, "Meeting");
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      path: `/opportunities/${d.id}/reopen`,
      body: { stage_id: sid("meeting") },
    });
    expect(calls[0]!.body).not.toHaveProperty("expected_stage_id");
    const reopened = within(col("meeting")).getByRole("article");
    expect(within(reopened).queryByText("Won", { selector: "span" })).toBeNull();
    expect(within(reopened).getByLabelText("Move Done to…")).toBeInTheDocument();
    expect(live()).toHaveTextContent("Reopened Done in Meeting");
  });

  it("does not let closed cards be dragged", () => {
    renderBoard(
      board({ won: [deal("won", { title: "Done" })], lost: [deal("lost", { title: "Gone" })] }),
    );
    expect(card("Done")).toHaveAttribute("draggable", "false");
    expect(card("Gone")).toHaveAttribute("draggable", "false");
  });

  it("reopening that fails leaves the deal closed", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /opportunities/:id/reopen": () =>
        errorResponse(409, "opportunity_open", "This deal is already open."),
    });
    renderBoard(board({ lost: [deal("lost", { title: "Gone" })] }));
    await user.selectOptions(screen.getByLabelText("Reopen Gone…"), "New");
    await waitFor(() =>
      expect(live()).toHaveTextContent("Couldn't move Gone: This deal is already open."),
    );
    expect(within(col("lost")).getByRole("article")).toBeInTheDocument();
    expect(within(col("new")).queryByRole("article")).toBeNull();
  });
});

describe("dragging", () => {
  it("makes open cards draggable and sets the deal id", () => {
    const d = deal("new", { title: "Big project" });
    renderBoard(board({ new: [d] }));
    expect(card("Big project")).toHaveAttribute("draggable", "true");
    const dt = fakeTransfer();
    fireEvent.dragStart(card("Big project"), { dataTransfer: dt });
    expect(dt.getData("text/plain")).toBe(d.id);
    expect(dt.effectAllowed).toBe("move");
  });

  it("shows a drop indicator over another column and moves the deal on drop", async () => {
    const d = deal("new", { title: "Big project" });
    const calls = stubApi();
    renderBoard(board({ new: [d] }));
    const dt = fakeTransfer();
    fireEvent.dragStart(card("Big project"), { dataTransfer: dt });
    fireEvent.dragOver(col("replied"), { dataTransfer: dt });
    expect(col("replied")).toHaveAttribute("data-drop-target", "true");
    expect(within(col("replied")).getByText("Drop here to move to Replied")).toBeInTheDocument();
    expect(col("new")).not.toHaveAttribute("data-drop-target");
    fireEvent.drop(col("replied"), { dataTransfer: dt });
    expect(col("replied")).not.toHaveAttribute("data-drop-target");
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      path: `/opportunities/${d.id}/move`,
      body: { stage_id: sid("replied"), expected_stage_id: sid("new") },
    });
    expect(within(col("replied")).getByRole("article")).toBeInTheDocument();
  });

  it("clears the indicator when the drag leaves or ends", () => {
    renderBoard(board({ new: [deal("new", { title: "Big project" })] }));
    const dt = fakeTransfer();
    fireEvent.dragStart(card("Big project"), { dataTransfer: dt });
    fireEvent.dragOver(col("replied"), { dataTransfer: dt });
    fireEvent.dragLeave(col("replied"), { dataTransfer: dt });
    expect(col("replied")).not.toHaveAttribute("data-drop-target");
    fireEvent.dragOver(col("replied"), { dataTransfer: dt });
    fireEvent.dragEnd(card("Big project"), { dataTransfer: dt });
    expect(col("replied")).not.toHaveAttribute("data-drop-target");
  });

  it("does nothing when dropped on its own column", () => {
    const calls = stubApi();
    renderBoard(board({ new: [deal("new", { title: "Big project" })] }));
    const dt = fakeTransfer();
    fireEvent.dragStart(card("Big project"), { dataTransfer: dt });
    fireEvent.dragOver(col("new"), { dataTransfer: dt });
    expect(col("new")).not.toHaveAttribute("data-drop-target");
    fireEvent.drop(col("new"), { dataTransfer: dt });
    expect(calls).toHaveLength(0);
    expect(refresh).not.toHaveBeenCalled();
    expect(live()).toHaveTextContent("");
  });

  it("asks first when a card is dropped on Won or Lost", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderBoard(board({ proposal: [deal("proposal", { title: "Big project" })] }));
    const dt = fakeTransfer();
    fireEvent.dragStart(card("Big project"), { dataTransfer: dt });
    fireEvent.drop(col("won"), { dataTransfer: dt });
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Mark as won?")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toHaveLength(0);
  });

  it("ignores things that are not a deal on this board", () => {
    const calls = stubApi();
    renderBoard(board({ new: [deal("new", { title: "Big project" })] }));
    fireEvent.drop(col("replied"), {
      dataTransfer: fakeTransfer({ "text/plain": "some text from another page" }),
    });
    fireEvent.drop(col("replied"), { dataTransfer: fakeTransfer() });
    expect(calls).toHaveLength(0);
  });

  it("cannot drag a closed deal into a column", () => {
    const calls = stubApi();
    const d = deal("won", { title: "Done" });
    renderBoard(board({ won: [d] }));
    fireEvent.dragStart(card("Done"), { dataTransfer: fakeTransfer() });
    fireEvent.drop(col("new"), { dataTransfer: fakeTransfer({ "text/plain": d.id }) });
    expect(calls).toHaveLength(0);
  });

  it("sends one request when the same card is moved twice while the first is in flight", async () => {
    const d = deal("new", { title: "Big project" });
    const gate = deferred();
    const calls = stubApi({ "POST /opportunities/:id/move": () => gate.promise });
    renderBoard(board({ new: [d] }));
    const dt = fakeTransfer({ "text/plain": d.id });
    fireEvent.drop(col("replied"), { dataTransfer: dt });
    await waitFor(() => expect(calls).toHaveLength(1));
    fireEvent.drop(col("meeting"), { dataTransfer: dt });
    fireEvent.drop(col("contacted"), { dataTransfer: dt });
    expect(calls).toHaveLength(1);
    gate.release(Response.json({ ...d, stage: stage("replied") }));
    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(calls).toHaveLength(1);
    expect(within(col("replied")).getByRole("article")).toBeInTheDocument();
  });

  it("lets other cards move while one is in flight", async () => {
    const a = deal("new", { title: "Alpha" });
    const b = deal("new", { title: "Beta" });
    const user = userEvent.setup();
    const gate = deferred();
    let first = true;
    const calls = stubApi({
      "POST /opportunities/:id/move": () => {
        if (first) {
          first = false;
          return gate.promise;
        }
        return Promise.resolve(Response.json({ ...b, stage: stage("meeting") }));
      },
    });
    renderBoard(board({ new: [a, b] }));
    await user.selectOptions(screen.getByLabelText("Move Alpha to…"), "Replied");
    await user.selectOptions(screen.getByLabelText("Move Beta to…"), "Meeting");
    await waitFor(() => expect(calls).toHaveLength(2));
    // Alpha's request fails: only Alpha goes back; Beta's move stays.
    gate.release(errorResponse(500, "internal_error", "Down."));
    await waitFor(() => expect(live()).toHaveTextContent("Couldn't move Alpha: Down."));
    expect(within(col("new")).getByRole("article", { name: "Alpha" })).toBeInTheDocument();
    expect(within(col("meeting")).getByRole("article", { name: "Beta" })).toBeInTheDocument();
  });
});

describe("members", () => {
  it("see everything but cannot move anything", () => {
    renderBoard(
      board({
        new: [deal("new", { title: "Big project" })],
        won: [deal("won", { title: "Done" })],
      }),
      false,
    );
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(card("Big project")).toHaveAttribute("draggable", "false");
    expect(within(card("Big project")).getByText("Big project")).toBeInTheDocument();
    expect(screen.queryByText(/Drag a card/)).toBeNull();
  });

  it("ignore drops", () => {
    const calls = stubApi();
    const d = deal("new", { title: "Big project" });
    renderBoard(board({ new: [d] }), false);
    fireEvent.dragStart(card("Big project"), { dataTransfer: fakeTransfer() });
    fireEvent.drop(col("replied"), { dataTransfer: fakeTransfer({ "text/plain": d.id }) });
    expect(calls).toHaveLength(0);
  });
});

describe("accessibility", () => {
  const rules = { rules: { "color-contrast": { enabled: false } } };

  it("has no violations on a full board, with a heading order of 2 then 3", async () => {
    const { container } = renderBoard(
      board(
        {
          new: [deal("new", { title: "A", value_amount: "10.00" })],
          proposal: [deal("proposal", { title: "B", expected_close_date: "2020-01-01" })],
          won: [deal("won", { title: "C", is_sample: true })],
          lost: [deal("lost", { title: "D" })],
        },
        { new: { count: 80, unvalued: 1 } },
      ),
    );
    expect((await axe.run(container, rules)).violations).toEqual([]);
    const levels = screen.getAllByRole("heading").map((h) => h.tagName);
    expect(levels.slice(0, 2)).toEqual(["H2", "H3"]);
    expect(levels.every((l) => l === "H2" || l === "H3")).toBe(true);
  });

  it("has no violations for a member, the empty state or the dialogs", async () => {
    const user = userEvent.setup();
    const member = renderBoard(board({ new: [deal("new", { title: "A" })] }), false);
    expect((await axe.run(member.container, rules)).violations).toEqual([]);
    member.unmount();
    const empty = renderBoard(board());
    expect((await axe.run(empty.container, rules)).violations).toEqual([]);
    empty.unmount();

    renderBoard(board({ proposal: [deal("proposal", { title: "B" })] }));
    await user.selectOptions(screen.getByLabelText("Move B to…"), "Won");
    expect((await axe.run(await screen.findByRole("dialog"), rules)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.selectOptions(screen.getByLabelText("Move B to…"), "Lost");
    expect((await axe.run(await screen.findByRole("dialog"), rules)).violations).toEqual([]);
  });

  it("has a polite live region that is there before anything is said", () => {
    renderBoard(board({ new: [deal("new")] }));
    expect(live()).toHaveAttribute("aria-live", "polite");
    expect(live()).toHaveTextContent("");
  });
});
