import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type { ActivityOut } from "@/components/leads/lead-model";
import type { TaskOut } from "@/components/tasks/task-model";
import { DealDetail } from "./deal-detail";
import type { OpportunityOut, PipelineStage } from "./pipeline-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const DEAL_ID = "11111111-1111-4111-8111-111111111111";
const LEAD_ID = "33333333-3333-4333-8333-333333333333";
const S_QUAL = "66666666-6666-4666-8666-666666666661";
const S_PROP = "66666666-6666-4666-8666-666666666662";
const S_WON = "66666666-6666-4666-8666-666666666663";
const S_LOST = "66666666-6666-4666-8666-666666666664";
const TODAY = "2026-10-12";

const STAGES: PipelineStage[] = [
  { id: S_QUAL, key: "qualified", name: "Qualified", position: 0, is_won: false, is_lost: false },
  { id: S_PROP, key: "proposal", name: "Proposal", position: 1, is_won: false, is_lost: false },
  { id: S_WON, key: "won", name: "Won", position: 2, is_won: true, is_lost: false },
  { id: S_LOST, key: "lost", name: "Lost", position: 3, is_won: false, is_lost: true },
];

function deal(over: Partial<OpportunityOut> = {}): OpportunityOut {
  return {
    id: DEAL_ID,
    lead: { id: LEAD_ID, title: "Website rebuild", company_name: "Acme Ltd" },
    stage: STAGES[0]!,
    status: "open",
    title: "Acme website rebuild",
    value_amount: "12000.00",
    currency: "USD",
    probability: 40,
    weighted_value: "4800.00",
    expected_close_date: "2026-11-30",
    next_action: "Send proposal",
    loss_reason: null,
    closed_at: null,
    owner_user_id: "88888888-8888-4888-8888-888888888888",
    is_sample: false,
    open_tasks: 0,
    created_at: "2026-10-01T08:00:00Z",
    updated_at: "2026-10-12T09:00:00Z",
    ...over,
  };
}

function activity(over: Partial<ActivityOut> = {}): ActivityOut {
  return {
    id: "77777777-7777-4777-8777-777777777771",
    kind: "note",
    summary: "Intro call booked",
    body: "Talked about scope.\nSecond line.",
    details: {},
    actor_user_id: "88888888-8888-4888-8888-888888888888",
    occurred_at: "2026-10-11T08:00:00Z",
    ...over,
  };
}

function task(over: Partial<TaskOut> = {}): TaskOut {
  return {
    id: "99999999-9999-4999-8999-999999999991",
    title: "Send quote",
    description: null,
    status: "open",
    priority: "normal",
    due_at: "2026-10-20T07:00:00Z",
    due_timezone: "Europe/Berlin",
    remind_at: null,
    completed_at: null,
    assignee_user_id: null,
    lead: null,
    opportunity: { id: DEAL_ID, title: "Acme website rebuild" },
    conversation_id: null,
    created_by: "user",
    is_sample: false,
    is_overdue: false,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...over,
  };
}

type Over = Partial<React.ComponentProps<typeof DealDetail>>;
function renderDetail(over: Over = {}) {
  return render(
    <ToastProvider>
      <DealDetail
        workspaceId={WS}
        deal={deal()}
        stages={STAGES}
        activities={{ items: [activity()], total: 1 }}
        openTasks={{ items: [], total: 0 }}
        doneTasks={{ items: [], total: 0 }}
        canEdit
        today={TODAY}
        {...over}
      />
    </ToastProvider>,
  );
}

type Call = { method: string; path: string; body: unknown; search: string };
function stubApi(extra: Record<string, (call: Call) => Response> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const url = new URL(req.url);
      const path = url.pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      const call = {
        method: req.method,
        path,
        body: text ? JSON.parse(text) : undefined,
        search: url.search,
      };
      calls.push(call);
      const key = `${req.method} ${path.replace(/[0-9a-f-]{36}/, ":id")}`;
      if (extra[key]) return extra[key](call);
      return Response.json(deal());
    }),
  );
  return calls;
}

function errorResponse(
  status: number,
  code: string,
  message: string,
  fields?: Record<string, string>,
) {
  return Response.json({ error: { code, message, ...(fields ? { fields } : {}) } }, { status });
}

const MOVE = "POST /opportunities/:id/move";
const REOPEN = "POST /opportunities/:id/reopen";

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("DealDetail header and summary", () => {
  it("shows the title, badges and every summary fact for an open deal", () => {
    renderDetail({ deal: deal({ is_sample: true, expected_close_date: "2026-10-01" }) });
    expect(screen.getByRole("heading", { level: 1, name: "Acme website rebuild" })).toBeVisible();
    expect(screen.getByRole("link", { name: /Back to pipeline/ })).toHaveAttribute(
      "href",
      "/pipeline",
    );
    expect(screen.getByText("Stage: Qualified")).toBeInTheDocument();
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText("Sample")).toBeInTheDocument();
    expect(screen.getByText("$12,000.00")).toBeInTheDocument();
    expect(screen.getByText("40%")).toBeInTheDocument();
    expect(screen.getByText("$4,800.00")).toBeInTheDocument();
    expect(screen.getByText("2026-10-01")).toBeInTheDocument();
    expect(screen.getByText("Overdue")).toBeInTheDocument();
    expect(screen.getByText("Send proposal")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Website rebuild" })).toHaveAttribute(
      "href",
      `/leads/${LEAD_ID}`,
    );
    expect(screen.getByText(/Acme Ltd/)).toBeInTheDocument();
    expect(screen.getByText("2026-10-01 08:00 UTC")).toBeInTheDocument();
    expect(screen.getByText("2026-10-12 09:00 UTC")).toBeInTheDocument();
  });

  it("does not flag a future close date as overdue", () => {
    renderDetail();
    expect(screen.queryByText("Overdue")).not.toBeInTheDocument();
  });

  it("says plainly when there is no value, chance or weighted value", () => {
    renderDetail({
      deal: deal({
        value_amount: null,
        probability: null,
        weighted_value: null,
        expected_close_date: null,
        next_action: null,
      }),
    });
    expect(screen.getByText("No value yet")).toBeInTheDocument();
    expect(screen.getByText("Not estimated")).toBeInTheDocument();
    expect(
      screen.getByText("Add a value and a chance of winning to see a weighted value"),
    ).toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.getAllByText("Not set")).toHaveLength(2);
  });

  it("shows a won deal as closed, without an overdue flag", () => {
    renderDetail({
      deal: deal({
        status: "won",
        stage: STAGES[2]!,
        weighted_value: null,
        closed_at: "2026-10-10T12:00:00Z",
        expected_close_date: "2026-10-01",
      }),
    });
    expect(screen.getByText("This deal is won on 2026-10-10")).toBeInTheDocument();
    expect(screen.getByText("Won", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByText("Overdue")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reopen" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Move" })).not.toBeInTheDocument();
  });

  it("shows why a lost deal was lost, and says so when no reason was recorded", () => {
    const lost = deal({
      status: "lost",
      stage: STAGES[3]!,
      weighted_value: null,
      closed_at: "2026-10-10T12:00:00Z",
      loss_reason: "Budget cut",
    });
    const { unmount } = renderDetail({ deal: lost });
    expect(screen.getByText("This deal is lost on 2026-10-10")).toBeInTheDocument();
    expect(screen.getByText("Reason: Budget cut")).toBeInTheDocument();
    unmount();
    renderDetail({ deal: { ...lost, loss_reason: null } });
    expect(screen.getByText("No reason was recorded.")).toBeInTheDocument();
  });

  it("renders stored markup as inert text", () => {
    renderDetail({
      deal: deal({
        title: '<img src=x onerror="alert(1)">',
        next_action: "<script>alert(2)</script>",
        lead: { id: LEAD_ID, title: "<b>lead</b>", company_name: "<i>Co</i>" },
      }),
      activities: {
        total: 1,
        items: [activity({ summary: "<u>hi</u>", body: "<svg onload=alert(3)>" })],
      },
      openTasks: { items: [task({ title: "<b>task</b>" })], total: 1 },
    });
    expect(document.querySelector("img, script, b, i, u, [onload], [onerror]")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
      '<img src=x onerror="alert(1)">',
    );
    expect(screen.getByText("<script>alert(2)</script>")).toBeInTheDocument();
    expect(screen.getByText("<svg onload=alert(3)>")).toBeInTheDocument();
    expect(screen.getByText("<b>task</b>")).toBeInTheDocument();
  });
});

describe("DealDetail moving", () => {
  it("moves to an open stage with the expected stage, then shows the response", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      [MOVE]: () => Response.json(deal({ stage: STAGES[1]!, updated_at: "2026-10-12T10:00:00Z" })),
    });
    renderDetail();
    expect(screen.getByRole("button", { name: "Move" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("Stage"), "Proposal");
    await user.click(screen.getByRole("button", { name: "Move" }));
    await screen.findByText("Stage: Proposal");
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: `/opportunities/${DEAL_ID}/move`,
      body: { stage_id: S_PROP, expected_stage_id: S_QUAL },
    });
    expect(refresh).toHaveBeenCalled();
  });

  it("does not change the stage until the server answers", async () => {
    const user = userEvent.setup();
    let release: (r: Response) => void = () => {};
    stubApi({
      [MOVE]: () => {
        throw new Error("replaced below");
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((resolve) => (release = resolve))),
    );
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Stage"), "Proposal");
    await user.click(screen.getByRole("button", { name: "Move" }));
    expect(await screen.findByRole("button", { name: "Moving…" })).toBeDisabled();
    expect(screen.getByText("Stage: Qualified")).toBeInTheDocument();
    release(Response.json(deal({ stage: STAGES[1]! })));
    await screen.findByText("Stage: Proposal");
  });

  it("asks before marking as won, and sends nothing on cancel", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      [MOVE]: () =>
        Response.json(
          deal({
            stage: STAGES[2]!,
            status: "won",
            weighted_value: null,
            closed_at: "2026-10-12T10:00:00Z",
          }),
        ),
    });
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Stage"), "Won");
    await user.click(screen.getByRole("button", { name: "Move" }));
    const dialog = await screen.findByRole("dialog", { name: "Mark as won?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Move" }));
    await user.click(
      within(await screen.findByRole("dialog", { name: "Mark as won?" })).getByRole("button", {
        name: "Mark as won",
      }),
    );
    await screen.findByText("This deal is won on 2026-10-12");
    expect(calls).toHaveLength(1);
    expect(calls[0]!.body).toEqual({ stage_id: S_WON, expected_stage_id: S_QUAL });
  });

  it("collects an optional loss reason, and sends nothing on cancel", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      [MOVE]: () =>
        Response.json(
          deal({
            stage: STAGES[3]!,
            status: "lost",
            weighted_value: null,
            closed_at: "2026-10-12T10:00:00Z",
            loss_reason: "Went with another agency",
          }),
        ),
    });
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Stage"), "Lost");
    await user.click(screen.getByRole("button", { name: "Move" }));
    let dialog = await screen.findByRole("dialog", { name: "Mark as lost?" });
    expect(within(dialog).getByLabelText("Why was it lost?")).toHaveAttribute("maxlength", "300");
    await user.type(within(dialog).getByLabelText("Why was it lost?"), "typed then cancelled");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Move" }));
    dialog = await screen.findByRole("dialog", { name: "Mark as lost?" });
    expect(within(dialog).getByLabelText("Why was it lost?")).toHaveValue("");
    await user.type(
      within(dialog).getByLabelText("Why was it lost?"),
      "  Went with another agency ",
    );
    await user.click(within(dialog).getByRole("button", { name: "Mark as lost" }));
    await screen.findByText("Reason: Went with another agency");
    expect(calls).toHaveLength(1);
    expect(calls[0]!.body).toEqual({
      stage_id: S_LOST,
      expected_stage_id: S_QUAL,
      loss_reason: "Went with another agency",
    });
  });

  it("leaves out the loss reason when none is given", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      [MOVE]: () => Response.json(deal({ stage: STAGES[3]!, status: "lost" })),
    });
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Stage"), "Lost");
    await user.click(screen.getByRole("button", { name: "Move" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Mark as lost" }),
    );
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toEqual({ stage_id: S_LOST, expected_stage_id: S_QUAL });
  });

  it("reopens a closed deal into the chosen open stage", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      [REOPEN]: () => Response.json(deal({ stage: STAGES[1]!, status: "open" })),
    });
    renderDetail({
      deal: deal({ status: "won", stage: STAGES[2]!, closed_at: "2026-10-10T12:00:00Z" }),
    });
    await user.click(screen.getByRole("button", { name: "Reopen" }));
    const dialog = await screen.findByRole("dialog", { name: "Reopen this deal?" });
    const select = within(dialog).getByLabelText("Open stage");
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Qualified", "Proposal"]);
    await user.selectOptions(select, "Proposal");
    await user.click(within(dialog).getByRole("button", { name: "Reopen deal" }));
    await screen.findByText("Stage: Proposal");
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: `/opportunities/${DEAL_ID}/reopen`,
      body: { stage_id: S_PROP },
    });
    expect(screen.queryByText(/This deal is won/)).not.toBeInTheDocument();
  });

  it("explains a stale stage, refreshes, and keeps the old stage", async () => {
    const user = userEvent.setup();
    stubApi({
      [MOVE]: () =>
        errorResponse(409, "stale_stage", "The deal is no longer in the expected stage."),
    });
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Stage"), "Proposal");
    await user.click(screen.getByRole("button", { name: "Move" }));
    expect(await screen.findByText("This deal was moved elsewhere")).toBeInTheDocument();
    expect(screen.getByText(/Check the stage and try again/)).toBeInTheDocument();
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByText("Stage: Qualified")).toBeInTheDocument();
    expect(screen.getByLabelText("Stage")).toHaveValue(S_QUAL);
  });

  it("shows the server's message on a failed move and keeps the old state", async () => {
    const user = userEvent.setup();
    stubApi({
      [MOVE]: () => errorResponse(422, "validation_error", "That stage is not available."),
    });
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Stage"), "Proposal");
    await user.click(screen.getByRole("button", { name: "Move" }));
    expect(await screen.findByText("That stage is not available.")).toBeInTheDocument();
    expect(screen.getByText("Stage: Qualified")).toBeInTheDocument();
    expect(screen.getByLabelText("Stage")).toHaveValue(S_QUAL);
    expect(refresh).not.toHaveBeenCalled();
  });

  it("shows the network failure message when the request cannot be sent", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("network");
      }),
    );
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Stage"), "Proposal");
    await user.click(screen.getByRole("button", { name: "Move" }));
    expect(await screen.findByText(/Can't reach the server/)).toBeInTheDocument();
    expect(screen.getByText("Stage: Qualified")).toBeInTheDocument();
  });
});

describe("DealDetail edit drawer", () => {
  it("sends only the changed fields", async () => {
    const user = userEvent.setup();
    const calls = stubApi({ [`PATCH /opportunities/:id`]: () => Response.json(deal()) });
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit deal" });
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(within(dialog).queryByLabelText("Reason lost")).not.toBeInTheDocument();
    const probability = within(dialog).getByLabelText("Chance of winning (%)");
    await user.clear(probability);
    await user.type(probability, "60");
    await user.clear(within(dialog).getByLabelText("Next action"));
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "PATCH",
      path: `/opportunities/${DEAL_ID}`,
      body: { probability: 60, next_action: null },
    });
    expect(Object.keys(calls[0]!.body as object).sort()).toEqual(["next_action", "probability"]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("clears the chance of winning with null rather than a guess", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    await user.clear(within(dialog).getByLabelText("Chance of winning (%)"));
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toEqual({ probability: null });
  });

  it("checks the form before sending", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    const value = within(dialog).getByLabelText("Value");
    await user.clear(value);
    await user.type(value, "abc");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(
      await within(dialog).findByText("Use a positive number with at most 2 decimals."),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("puts API field errors next to their fields and keeps the drawer open", async () => {
    const user = userEvent.setup();
    stubApi({
      "PATCH /opportunities/:id": () =>
        errorResponse(422, "validation_error", "Invalid", {
          expected_close_date: "Pick a valid date.",
        }),
    });
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Next action"), " today");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByText("Pick a valid date.")).toBeInTheDocument();
    expect(within(dialog).getByText("Some fields need attention")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Expected close date")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("lets the reason lost be edited on a lost deal, and only there", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail({
      deal: deal({
        status: "lost",
        stage: STAGES[3]!,
        weighted_value: null,
        closed_at: "2026-10-10T12:00:00Z",
        loss_reason: "Budget cut",
      }),
    });
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    const reason = within(dialog).getByLabelText("Reason lost");
    expect(reason).toHaveValue("Budget cut");
    await user.clear(reason);
    await user.type(reason, "Timing");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toEqual({ loss_reason: "Timing" });
  });

  it("does not offer the reason field for a won deal", async () => {
    const user = userEvent.setup();
    renderDetail({
      deal: deal({ status: "won", stage: STAGES[2]!, closed_at: "2026-10-10T12:00:00Z" }),
    });
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByLabelText("Reason lost")).not.toBeInTheDocument();
  });
});

describe("DealDetail timeline", () => {
  it("lists newest first with kind, time, actor, body and stage names", () => {
    renderDetail({
      activities: {
        total: 3,
        items: [
          activity({
            id: "77777777-7777-4777-8777-777777777772",
            kind: "stage_change",
            summary: "Moved to Proposal",
            body: null,
            details: { from: "qualified", to: "proposal" },
            actor_user_id: null,
            occurred_at: "2026-10-12T08:00:00Z",
          }),
          activity({
            id: "77777777-7777-4777-8777-777777777773",
            kind: "stage_change",
            summary: "Odd move",
            body: null,
            details: { from: "mystery", to: "proposal" },
            actor_user_id: null,
          }),
          activity(),
        ],
      },
    });
    const list = screen.getByRole("list", { name: "Activity, newest first" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("Stage change")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Qualified → Proposal")).toBeInTheDocument();
    expect(within(rows[0]!).getByText(/System/)).toBeInTheDocument();
    expect(within(rows[1]!).getByText("mystery → Proposal")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Note")).toBeInTheDocument();
    expect(within(rows[2]!).getByText(/You/)).toBeInTheDocument();
    expect(within(rows[2]!).getByText("2026-10-11 08:00 UTC")).toBeInTheDocument();
    const body = within(rows[2]!).getByText(/Talked about scope/);
    expect(body.className).toContain("whitespace-pre-wrap");
  });

  it("shows an empty state", () => {
    renderDetail({ activities: { items: [], total: 0 } });
    expect(screen.getByText("Nothing has happened on this deal yet.")).toBeInTheDocument();
  });

  it("logs a call with a summary and details, then shows it first", async () => {
    const user = userEvent.setup();
    const created = activity({
      id: "77777777-7777-4777-8777-777777777799",
      kind: "call",
      summary: "Rang Dana",
      body: "Wants a quote",
    });
    const calls = stubApi({
      "POST /opportunities/:id/activities": () => Response.json(created, { status: 201 }),
    });
    renderDetail();
    const form = screen.getByRole("form", { name: "Log activity" });
    await user.selectOptions(within(form).getByLabelText("What happened"), "Call");
    await user.type(within(form).getByLabelText(/Summary/), "  Rang Dana ");
    await user.type(within(form).getByLabelText("Details (optional)"), "Wants a quote");
    await user.click(within(form).getByRole("button", { name: "Add to timeline" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: `/opportunities/${DEAL_ID}/activities`,
      body: { kind: "call", summary: "Rang Dana", body: "Wants a quote" },
    });
    const rows = within(screen.getByRole("list", { name: "Activity, newest first" })).getAllByRole(
      "listitem",
    );
    expect(within(rows[0]!).getByText("Rang Dana")).toBeInTheDocument();
    expect(within(form).getByLabelText(/Summary/)).toHaveValue("");
  });

  it("requires a summary", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Add to timeline" }));
    expect(await screen.findByText("Say what happened.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("loads older activity with limit and offset", async () => {
    const user = userEvent.setup();
    const older = activity({
      id: "77777777-7777-4777-8777-777777777780",
      summary: "Much older note",
    });
    const calls = stubApi({
      "GET /opportunities/:id/activities": () =>
        Response.json({ items: [older], total: 2, limit: 50, offset: 1 }),
    });
    renderDetail({ activities: { items: [activity()], total: 2 } });
    expect(screen.getByText("Showing 1 of 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show older activity" }));
    await screen.findByText("Much older note");
    expect(calls[0]!.search).toBe("?limit=50&offset=1");
    expect(screen.queryByRole("button", { name: "Show older activity" })).not.toBeInTheDocument();
  });
});

describe("DealDetail for members", () => {
  it("shows everything and offers no way to change anything", () => {
    renderDetail({
      canEdit: false,
      openTasks: { items: [task()], total: 1 },
      doneTasks: {
        items: [
          task({ id: "99999999-9999-4999-8999-999999999992", title: "Done one", status: "done" }),
        ],
        total: 1,
      },
      deal: deal({ status: "won", stage: STAGES[2]!, closed_at: "2026-10-10T12:00:00Z" }),
    });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.getByText("$12,000.00")).toBeInTheDocument();
    expect(screen.getByText("Send quote")).toBeInTheDocument();
    expect(screen.getByText("Intro call booked")).toBeInTheDocument();
    for (const name of [
      /^Edit/,
      /^Move/,
      /^Reopen/,
      /Add task/,
      /^Complete/,
      /^Dismiss/,
      /Add to timeline/,
    ]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("form", { name: "Log activity" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Stage")).not.toBeInTheDocument();
  });
});

describe("DealDetail accessibility", () => {
  const opts = { rules: { "color-contrast": { enabled: false } } };
  // Portals (drawer, dialogs, toasts) sit outside the page landmark in these isolated renders.
  const bodyOpts = { rules: { ...opts.rules, region: { enabled: false } } };

  it("has no violations for a full open deal", async () => {
    const { container } = renderDetail({
      deal: deal({ is_sample: true, expected_close_date: "2026-10-01" }),
      openTasks: { items: [task({ is_overdue: true })], total: 1 },
      doneTasks: {
        items: [task({ id: "99999999-9999-4999-8999-999999999992", status: "done" })],
        total: 1,
      },
      activities: {
        total: 2,
        items: [
          activity(),
          activity({
            id: "77777777-7777-4777-8777-777777777772",
            kind: "stage_change",
            details: { from: "qualified", to: "proposal" },
            actor_user_id: null,
            body: null,
          }),
        ],
      },
    });
    expect((await axe.run(container, opts)).violations).toEqual([]);
  });

  it("has no violations for a lost deal with no value, as a member", async () => {
    const { container } = renderDetail({
      canEdit: false,
      deal: deal({
        status: "lost",
        stage: STAGES[3]!,
        value_amount: null,
        probability: null,
        weighted_value: null,
        expected_close_date: null,
        next_action: null,
        closed_at: "2026-10-10T12:00:00Z",
        loss_reason: "Budget cut",
      }),
      activities: { items: [], total: 0 },
    });
    expect((await axe.run(container, opts)).violations).toEqual([]);
  });

  it("has no violations with the drawer and each dialog open", async () => {
    const user = userEvent.setup();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByRole("dialog", { name: "Edit deal" });
    expect((await axe.run(document.body, bodyOpts)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Stage"), "Lost");
    await user.click(screen.getByRole("button", { name: "Move" }));
    await screen.findByRole("dialog", { name: "Mark as lost?" });
    expect((await axe.run(document.body, bodyOpts)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

    await user.selectOptions(screen.getByLabelText("Stage"), "Won");
    await user.click(screen.getByRole("button", { name: "Move" }));
    await screen.findByRole("dialog", { name: "Mark as won?" });
    expect((await axe.run(document.body, bodyOpts)).violations).toEqual([]);
  });

  it("has no violations with the reopen dialog open", async () => {
    const user = userEvent.setup();
    renderDetail({
      deal: deal({ status: "won", stage: STAGES[2]!, closed_at: "2026-10-10T12:00:00Z" }),
    });
    await user.click(screen.getByRole("button", { name: "Reopen" }));
    await screen.findByRole("dialog", { name: "Reopen this deal?" });
    expect((await axe.run(document.body, bodyOpts)).violations).toEqual([]);
  });
});
