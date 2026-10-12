import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import {
  LiveStatus,
  MoveDialogs,
  MoveStageSelect,
  applyMove,
  applyOps,
  overlayDeal,
  requestMove,
  requestReopen,
  stageStatus,
  useMoveDeal,
  type MoveOp,
} from "./deal-move";
import type { BoardColumn, OpportunityOut, PipelineStage } from "./pipeline-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const KEYS = ["new", "qualified", "proposal", "won", "lost"] as const;
const stage = (key: (typeof KEYS)[number]): PipelineStage => ({
  id: `00000000-0000-4000-8000-00000000020${KEYS.indexOf(key)}`,
  key,
  name: key[0]!.toUpperCase() + key.slice(1),
  position: KEYS.indexOf(key),
  is_won: key === "won",
  is_lost: key === "lost",
});
const STAGES = KEYS.map(stage);

function deal(key: (typeof KEYS)[number], over: Partial<OpportunityOut> = {}): OpportunityOut {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    lead: { id: "9", title: "Lead", company_name: null },
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

function columns(
  placed: Partial<Record<(typeof KEYS)[number], OpportunityOut[]>>,
  per: Partial<Record<(typeof KEYS)[number], Partial<BoardColumn>>> = {},
): BoardColumn[] {
  return KEYS.map((k) => ({
    stage: stage(k),
    count: (placed[k] ?? []).length,
    unvalued: 0,
    totals: [],
    items: placed[k] ?? [],
    ...per[k],
  }));
}

const col = (cols: BoardColumn[], key: (typeof KEYS)[number]) =>
  cols.find((c) => c.stage.key === key)!;

describe("applyMove", () => {
  it("moves the card to the top of the new column and updates counts", () => {
    const d = deal("new");
    const other = deal("qualified", { id: "22", title: "Other" });
    const before = columns({ new: [d], qualified: [other] }, { qualified: { count: 9 } });
    const after = applyMove(before, d.id, stage("qualified"));
    expect(col(after, "new").items).toEqual([]);
    expect(col(after, "new").count).toBe(0);
    expect(col(after, "qualified").items.map((x) => x.id)).toEqual([d.id, "22"]);
    expect(col(after, "qualified").count).toBe(10);
    expect(col(after, "qualified").items[0]).toMatchObject({ status: "open" });
    expect(col(after, "qualified").items[0]!.stage.id).toBe(stage("qualified").id);
    // The input is never touched.
    expect(col(before, "new").items).toHaveLength(1);
  });

  it("keeps money per currency, exact, and never mixes currencies", () => {
    const d = deal("new", { value_amount: "100.10", probability: 50, weighted_value: "50.05" });
    const e = deal("new", { id: "3", value_amount: "20.00", currency: "EUR" });
    const before = columns(
      { new: [d, e], qualified: [] },
      {
        new: {
          totals: [
            { currency: "USD", amount: "100.10", weighted: "50.05" },
            { currency: "EUR", amount: "20.00", weighted: "0.00" },
          ],
        },
        qualified: { totals: [{ currency: "USD", amount: "0.20", weighted: "0.10" }] },
      },
    );
    let after = applyMove(before, d.id, stage("qualified"));
    expect(col(after, "new").totals).toEqual([
      { currency: "EUR", amount: "20.00", weighted: "0.00" },
    ]);
    expect(col(after, "qualified").totals).toEqual([
      { currency: "USD", amount: "100.30", weighted: "50.15" },
    ]);
    after = applyMove(after, e.id, stage("qualified"));
    expect(col(after, "qualified").totals).toEqual([
      { currency: "USD", amount: "100.30", weighted: "50.15" },
      { currency: "EUR", amount: "20.00", weighted: "0.00" },
    ]);
    expect(col(after, "new").totals).toEqual([]);
  });

  it("leaves weighted out of won and lost columns and counts deals without a value", () => {
    const d = deal("proposal", { value_amount: "10.00", probability: 50, weighted_value: "5.00" });
    const u = deal("proposal", { id: "4", title: "No value" });
    const before = columns(
      { proposal: [d, u] },
      {
        proposal: {
          unvalued: 1,
          totals: [{ currency: "USD", amount: "10.00", weighted: "5.00" }],
        },
        won: { totals: [] },
      },
    );
    let after = applyMove(before, d.id, stage("won"));
    expect(col(after, "won").totals).toEqual([
      { currency: "USD", amount: "10.00", weighted: null },
    ]);
    expect(col(after, "won").items[0]).toMatchObject({ status: "won", weighted_value: null });
    expect(col(after, "proposal").totals).toEqual([]);
    after = applyMove(after, u.id, stage("won"));
    expect(col(after, "proposal").unvalued).toBe(0);
    expect(col(after, "won").unvalued).toBe(1);
  });

  it("works out a reopened deal's weighted value only from its own value and chance", () => {
    const d = deal("won", { value_amount: "200.00", probability: 25 });
    const noChance = deal("lost", { id: "5", value_amount: "300.00" });
    const before = columns({ won: [d], lost: [noChance], new: [] });
    const after = applyMove(applyMove(before, d.id, stage("new")), noChance.id, stage("new"));
    expect(col(after, "new").totals).toEqual([
      { currency: "USD", amount: "500.00", weighted: "50.00" },
    ]);
    expect(col(after, "new").items.map((x) => x.weighted_value)).toEqual([null, "50.00"]);
  });

  it("records the reason on a lost deal and clears it again when reopened", () => {
    const d = deal("proposal");
    const lost = applyMove(columns({ proposal: [d] }), d.id, stage("lost"), {
      lossReason: "Too pricey",
    });
    expect(col(lost, "lost").items[0]).toMatchObject({ status: "lost", loss_reason: "Too pricey" });
    const back = applyMove(lost, d.id, stage("new"));
    expect(col(back, "new").items[0]).toMatchObject({ status: "open", loss_reason: null });
  });

  it("uses the server's version of the deal when it has one", () => {
    const d = deal("new");
    const server = deal("qualified", { title: "Renamed by server" });
    const after = applyMove(columns({ new: [d] }), d.id, stage("qualified"), { result: server });
    expect(col(after, "qualified").items[0]).toBe(server);
  });

  it("is a no-op for unknown deals and stages", () => {
    const d = deal("new");
    const before = columns({ new: [d] });
    expect(applyMove(before, "nope", stage("qualified"))).toEqual(before);
    expect(applyMove(before, d.id, { ...stage("qualified"), id: "elsewhere" })).toEqual(before);
    expect(col(applyMove(before, d.id, stage("new")), "new").items).toEqual([d]);
  });

  it("replays several moves in order and drops a refused one exactly", () => {
    const a = deal("new", { title: "A" });
    const b = deal("new", { id: "6", title: "B" });
    const before = columns({ new: [a, b] });
    const op = (key: number, dealId: string, target: PipelineStage): MoveOp => ({
      key,
      dealId,
      kind: "move",
      target,
      lossReason: null,
      state: "pending",
    });
    const both = applyOps(before, [
      op(1, a.id, stage("qualified")),
      op(2, b.id, stage("proposal")),
    ]);
    expect(col(both, "qualified").items.map((x) => x.title)).toEqual(["A"]);
    expect(col(both, "proposal").items.map((x) => x.title)).toEqual(["B"]);
    const onlyB = applyOps(before, [op(2, b.id, stage("proposal"))]);
    expect(col(onlyB, "new").items.map((x) => x.title)).toEqual(["A"]);
    expect(applyOps(before, [])).toEqual(before);
  });

  it("overlays an in-flight move on a single deal for the table", () => {
    const d = deal("new");
    const op: MoveOp = {
      key: 1,
      dealId: d.id,
      kind: "move",
      target: stage("won"),
      lossReason: null,
      state: "pending",
    };
    expect(overlayDeal(d, [])).toBe(d);
    expect(overlayDeal(d, [op])).toMatchObject({ status: "won", stage: { key: "won" } });
    const server = deal("won", { title: "Server" });
    expect(overlayDeal(d, [{ ...op, state: "settled", result: server }])).toBe(server);
    expect(overlayDeal(deal("new", { id: "other" }), [op]).stage.key).toBe("new");
  });

  it("reads a stage's status from its flags", () => {
    expect(stageStatus(stage("won"))).toBe("won");
    expect(stageStatus(stage("lost"))).toBe("lost");
    expect(stageStatus(stage("new"))).toBe("open");
  });
});

type Call = { method: string; path: string; body: Record<string, unknown> };
function stubApi(respond: () => Response | Promise<Response>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const text = await req.clone().text();
      calls.push({
        method: req.method,
        path: new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, ""),
        body: text ? JSON.parse(text) : undefined,
      });
      return respond();
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("requests", () => {
  it("always sends the stage it expects, and a trimmed reason only when there is one", async () => {
    const d = deal("proposal");
    const calls = stubApi(() => Response.json(deal("lost")));
    expect(await requestMove(WS, d, stage("lost"), "  too pricey ")).toMatchObject({ ok: true });
    await requestMove(WS, d, stage("lost"), "   ");
    await requestMove(WS, d, stage("lost"));
    expect(calls.map((c) => c.body)).toEqual([
      {
        stage_id: stage("lost").id,
        expected_stage_id: stage("proposal").id,
        loss_reason: "too pricey",
      },
      { stage_id: stage("lost").id, expected_stage_id: stage("proposal").id },
      { stage_id: stage("lost").id, expected_stage_id: stage("proposal").id },
    ]);
    expect(calls[0]!.path).toBe(`/opportunities/${d.id}/move`);
  });

  it("reopens with just the stage", async () => {
    const d = deal("won");
    const calls = stubApi(() => Response.json(deal("new")));
    expect(await requestReopen(WS, d, stage("new"))).toMatchObject({ ok: true });
    expect(calls[0]).toMatchObject({
      path: `/opportunities/${d.id}/reopen`,
      body: { stage_id: stage("new").id },
    });
  });

  it("turns each failure into words and says whether the board is stale", async () => {
    const d = deal("new");
    const fail = (status: number, code: string, message: string, fields = {}) =>
      Response.json({ error: { code, message, fields } }, { status });
    stubApi(() => fail(409, "stale_stage", "Moved by someone else."));
    expect(await requestMove(WS, d, stage("qualified"))).toEqual({
      ok: false,
      code: "stale_stage",
      message: "Moved by someone else.",
      stale: true,
      silent: false,
    });
    stubApi(() => fail(409, "opportunity_closed", "Closed deals can't be moved."));
    expect(await requestMove(WS, d, stage("qualified"))).toMatchObject({ stale: true });
    stubApi(() => fail(422, "validation_error", "Check.", { loss_reason: "Too long." }));
    expect(await requestMove(WS, d, stage("lost"))).toMatchObject({
      message: "Too long.",
      stale: false,
    });
    stubApi(() => fail(500, "internal_error", "Down."));
    expect(await requestMove(WS, d, stage("qualified"))).toMatchObject({
      message: "Down.",
      stale: false,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    expect(await requestReopen(WS, d, stage("new"))).toMatchObject({
      ok: false,
      code: "network_error",
    });
  });

  it("stays silent when the session has expired", async () => {
    stubApi(() =>
      Response.json({ error: { code: "session_expired", message: "Sign in." } }, { status: 401 }),
    );
    expect(await requestMove(WS, deal("new"), stage("qualified"))).toMatchObject({
      ok: false,
      silent: true,
    });
  });
});

describe("MoveStageSelect", () => {
  it("is labelled with the deal, and choosing a stage reports it once", async () => {
    const user = userEvent.setup();
    const onChoose = vi.fn();
    render(<MoveStageSelect deal={deal("new")} stages={STAGES} onChoose={onChoose} />);
    const select = screen.getByRole("combobox", { name: "Move Big project to…" });
    await user.selectOptions(select, "Proposal");
    expect(onChoose).toHaveBeenCalledTimes(1);
    expect(onChoose).toHaveBeenCalledWith(stage("proposal"));
    expect(select).toHaveValue("");
  });

  it("cannot pick the stage the deal is already in", () => {
    render(<MoveStageSelect deal={deal("new")} stages={STAGES} onChoose={() => {}} />);
    expect(screen.getByRole("option", { name: "New (current)" })).toBeDisabled();
  });

  it("is disabled while busy and in reopen mode lists open stages only", () => {
    const { rerender } = render(
      <MoveStageSelect deal={deal("won")} stages={STAGES} onChoose={() => {}} disabled />,
    );
    expect(screen.getByRole("combobox")).toBeDisabled();
    rerender(
      <MoveStageSelect deal={deal("won")} stages={STAGES} mode="reopen" onChoose={() => {}} />,
    );
    expect(
      within(screen.getByRole("combobox", { name: "Reopen Big project…" }))
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Reopen…", "New", "Qualified", "Proposal"]);
  });
});

function Harness({ target = "qualified" }: { target?: (typeof KEYS)[number] }) {
  const controller = useMoveDeal({ workspaceId: WS });
  const d = deal("new");
  return (
    <>
      <button onClick={() => controller.move(d, stage(target))}>go</button>
      <button onClick={() => controller.reopen(deal("won"), stage("new"))}>reopen</button>
      <span data-testid="ops">{controller.ops.map((o) => `${o.kind}:${o.state}`).join(",")}</span>
      <span data-testid="busy">{String(controller.isBusy(d.id))}</span>
      <LiveStatus message={controller.message} />
      <MoveDialogs controller={controller} />
    </>
  );
}

const renderHarness = (target?: (typeof KEYS)[number]) =>
  render(
    <ToastProvider>
      <Harness {...(target ? { target } : {})} />
    </ToastProvider>,
  );

describe("useMoveDeal", () => {
  it("tracks a move through pending and settled, and refreshes once", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json(deal("qualified")));
    renderHarness();
    await user.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() => expect(screen.getByTestId("ops")).toHaveTextContent("move:settled"));
    expect(screen.getByTestId("busy")).toHaveTextContent("false");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("status")).toHaveTextContent("Moved Big project to Qualified");
  });

  it("forgets a refused move completely", async () => {
    const user = userEvent.setup();
    stubApi(() => Response.json({ error: { code: "x", message: "Nope." } }, { status: 400 }));
    renderHarness();
    await user.click(screen.getByRole("button", { name: "go" }));
    await waitFor(() =>
      expect(screen.getByRole("status")).toHaveTextContent("Couldn't move Big project: Nope."),
    );
    expect(screen.getByTestId("ops")).toHaveTextContent("");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("does not send a move to the stage the deal is already in", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(deal("new")));
    renderHarness("new");
    await user.click(screen.getByRole("button", { name: "go" }));
    expect(calls).toHaveLength(0);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("reopens without a question", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(deal("new")));
    renderHarness();
    await user.click(screen.getByRole("button", { name: "reopen" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.path).toMatch(/\/reopen$/);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("asks about Won and Lost, and Escape counts as cancel", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(deal("won")));
    const first = renderHarness("won");
    await user.click(screen.getByRole("button", { name: "go" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    first.unmount();
    renderHarness("lost");
    await user.click(screen.getByRole("button", { name: "go" }));
    expect(await screen.findByRole("dialog", { name: "Mark as lost?" })).toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls).toHaveLength(0);
  });

  it("limits the reason to 300 characters and passes it through", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(deal("lost")));
    renderHarness("lost");
    await user.click(screen.getByRole("button", { name: "go" }));
    const reason = await screen.findByLabelText("Why was it lost?");
    fireEvent.change(reason, { target: { value: "x".repeat(300) } });
    expect(reason).toHaveValue("x".repeat(300));
    await user.click(screen.getByRole("button", { name: "Mark as lost" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body.loss_reason).toHaveLength(300);
  });

  it("has no accessibility violations in its dialogs", async () => {
    const user = userEvent.setup();
    const { container } = renderHarness("lost");
    const rules = { rules: { "color-contrast": { enabled: false } } };
    expect((await axe.run(container, rules)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "go" }));
    expect((await axe.run(await screen.findByRole("dialog"), rules)).violations).toEqual([]);
  });
});
