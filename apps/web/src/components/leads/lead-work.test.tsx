import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type * as ApiClient from "@/lib/api-client";
import type { OpportunityOut, PipelineStage } from "@/components/pipeline/pipeline-model";
import type { TaskOut } from "@/components/tasks/task-model";
import { LeadWork } from "./lead-work";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const LEAD = "33333333-3333-4333-8333-333333333333";
const STAGES: PipelineStage[] = [
  { id: "s1", key: "new", name: "New", position: 0, is_won: false, is_lost: false },
  { id: "s2", key: "won", name: "Won", position: 1, is_won: true, is_lost: false },
];
const DEAL = {
  id: "44444444-4444-4444-8444-444444444444",
  title: "Website <b>rebuild</b>",
  status: "open",
  stage: STAGES[0],
  value_amount: "12000.00",
  currency: "USD",
} as unknown as OpportunityOut;
const TASK = {
  id: "55555555-5555-4555-8555-555555555555",
  title: "Send quote",
  status: "open",
  priority: "high",
  due_at: "2026-07-01T07:00:00Z",
  due_timezone: "Europe/Berlin",
  is_overdue: true,
} as unknown as TaskOut;

type Call = { method: string; path: string };
function stub(
  respond: (req: Request) => Response = () =>
    Response.json({ items: [], total: 0, limit: 100, offset: 0 }),
) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      calls.push({
        method: req.method,
        path: new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, ""),
      });
      return respond(req);
    }),
  );
  return calls;
}

function setup(over: Partial<React.ComponentProps<typeof LeadWork>> = {}) {
  return render(
    <ToastProvider>
      <LeadWork
        workspaceId={WS}
        leadId={LEAD}
        leadTitle="Fabrikam rebuild"
        deals={[DEAL]}
        tasks={[TASK]}
        stages={STAGES}
        timezone="Europe/Berlin"
        canEdit
        {...over}
      />
    </ToastProvider>,
  );
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("LeadWork", () => {
  it("lists the deals and open follow-ups with their provenance, as plain text", () => {
    stub();
    setup();
    const deals = screen.getByRole("region", { name: "Deals" });
    expect(within(deals).getByRole("link", { name: "Website <b>rebuild</b>" })).toHaveAttribute(
      "href",
      `/pipeline/${DEAL.id}`,
    );
    expect(within(deals).getByText(/New · \$12,000\.00/)).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    const tasks = screen.getByRole("region", { name: "Follow-ups" });
    expect(within(tasks).getByText("Send quote")).toBeInTheDocument();
    expect(
      within(tasks).getByText(/2026-07-01 09:00 \(Europe\/Berlin\) · High priority/),
    ).toBeInTheDocument();
    expect(within(tasks).getByText("Overdue")).toBeInTheDocument();
  });

  it("says so when there is nothing yet", () => {
    stub();
    setup({ deals: [], tasks: [] });
    expect(screen.getByText(/No deals yet/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing to do for this lead/)).toBeInTheDocument();
  });

  it("completes a task and refreshes", async () => {
    const user = userEvent.setup();
    const calls = stub(() => Response.json({ ...TASK, status: "done" }));
    setup();
    await user.click(screen.getByRole("button", { name: "Complete: Send quote" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toEqual([{ method: "POST", path: `/tasks/${TASK.id}/complete` }]);
  });

  it("shows the server's message when completing fails and does not refresh", async () => {
    const user = userEvent.setup();
    stub(() =>
      Response.json(
        { error: { code: "internal", message: "Temporary problem." } },
        { status: 503 },
      ),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "Complete: Send quote" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Temporary problem.");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("opens the task drawer for this lead", async () => {
    const user = userEvent.setup();
    stub();
    setup();
    await user.click(screen.getByRole("button", { name: "New task" }));
    expect(await screen.findByText("For: Fabrikam rebuild")).toBeInTheDocument();
  });

  it("opens the new-deal drawer locked to this lead", async () => {
    const user = userEvent.setup();
    stub(() =>
      Response.json({
        items: [{ id: LEAD, title: "Fabrikam rebuild", company: null }],
        total: 1,
        limit: 100,
        offset: 0,
      }),
    );
    setup();
    await user.click(screen.getByRole("button", { name: "New deal" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("has no controls for a read-only viewer", () => {
    stub();
    setup({ canEdit: false });
    expect(screen.queryByRole("button", { name: "New deal" })).toBeNull();
    expect(screen.queryByRole("button", { name: "New task" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Complete:/ })).toBeNull();
  });

  it("has no detectable accessibility violations", async () => {
    stub();
    const { container } = setup();
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
