import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { NewDealButton, OpportunityCreateDrawer } from "./opportunity-create-drawer";
import type { PipelineStage } from "./pipeline-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const KEYS = ["new", "qualified", "won", "lost"] as const;
const STAGES: PipelineStage[] = KEYS.map((key, i) => ({
  id: `00000000-0000-4000-8000-00000000040${i}`,
  key,
  name: key[0]!.toUpperCase() + key.slice(1),
  position: i,
  is_won: key === "won",
  is_lost: key === "lost",
}));
const LEADS = [
  {
    id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    title: "Alpha redesign",
    company: { name: "Alpha Ltd" },
  },
  { id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", title: "<b>Beta</b>", company: null },
];

type Call = { method: string; path: string; body: Record<string, unknown>; query: string };
function stubApi(
  handlers: Record<string, () => Response | Promise<Response>> = {},
  leads: unknown[] = LEADS,
  total = leads.length,
) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const url = new URL(req.url);
      const path = url.pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({
        method: req.method,
        path,
        query: url.search,
        body: text ? JSON.parse(text) : undefined,
      });
      const handler = handlers[`${req.method} ${path}`];
      if (handler) return handler();
      if (req.method === "GET" && path === "/leads") {
        return Response.json({ items: leads, total, limit: 100, offset: 0 });
      }
      return Response.json({ id: "new-deal", title: "Alpha redesign" });
    }),
  );
  return calls;
}

function renderDrawer(props: { leadId?: string; onClose?: () => void } = {}) {
  const onClose = props.onClose ?? vi.fn();
  const result = render(
    <ToastProvider>
      <OpportunityCreateDrawer
        workspaceId={WS}
        {...(props.leadId ? { leadId: props.leadId } : {})}
        stages={STAGES}
        onClose={onClose}
      />
    </ToastProvider>,
  );
  return { ...result, onClose };
}

async function openDrawer(props: { leadId?: string; onClose?: () => void } = {}) {
  const view = renderDrawer(props);
  const dialog = await screen.findByRole("dialog", { name: "New deal" });
  await waitFor(() => expect(within(dialog).getByLabelText(/Lead/)).toBeEnabled());
  return { ...view, dialog };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("OpportunityCreateDrawer", () => {
  it("fetches the leads when it opens and lists them by name and company", async () => {
    const calls = stubApi();
    const { dialog } = await openDrawer();
    expect(calls[0]).toMatchObject({ method: "GET", path: "/leads" });
    expect(calls[0]!.query).toContain("limit=100");
    expect(calls[0]!.query).toContain("sort=title");
    const options = within(within(dialog).getByLabelText(/Lead/))
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["Choose a lead…", "Alpha redesign · Alpha Ltd", "<b>Beta</b>"]);
    expect(dialog.querySelector("b")).toBeNull();
  });

  it("offers open stages only, defaulting to the lead's stage", async () => {
    stubApi();
    const { dialog } = await openDrawer();
    const stage = within(dialog).getByLabelText("Stage");
    expect(stage).toHaveValue("");
    expect(
      within(stage)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Same as the lead's stage", "New", "Qualified"]);
  });

  it("needs a lead before it sends anything", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    const { dialog, onClose } = await openDrawer();
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    expect(
      await within(dialog).findByText("Choose the lead this deal is for."),
    ).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Lead/)).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByText("Some fields need attention")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("checks the number fields before sending", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    const { dialog } = await openDrawer();
    await user.selectOptions(within(dialog).getByLabelText(/Lead/), "Alpha redesign · Alpha Ltd");
    await user.type(within(dialog).getByLabelText("Value"), "12k");
    await user.type(within(dialog).getByLabelText(/Chance of winning/), "150");
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    expect(
      await within(dialog).findByText("Use a positive number with at most 2 decimals."),
    ).toBeInTheDocument();
    expect(within(dialog).getByText("Use a whole number from 0 to 100.")).toBeInTheDocument();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("sends only the lead and what was filled in, then refreshes, closes and says so", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    const { dialog, onClose } = await openDrawer();
    await user.selectOptions(within(dialog).getByLabelText(/Lead/), "Alpha redesign · Alpha Ltd");
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/opportunities");
    expect(post?.body).toEqual({ lead_id: LEADS[0]!.id, currency: "USD" });
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Deal created")).toBeInTheDocument();
  });

  it("sends the stage, value, chance, date and next action when given", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    const { dialog, onClose } = await openDrawer();
    await user.selectOptions(within(dialog).getByLabelText(/Lead/), LEADS[1]!.id);
    await user.selectOptions(within(dialog).getByLabelText("Stage"), "Qualified");
    await user.type(within(dialog).getByLabelText("Deal name"), "  Retainer ");
    await user.type(within(dialog).getByLabelText("Value"), "2500.50");
    await user.clear(within(dialog).getByLabelText("Currency"));
    await user.type(within(dialog).getByLabelText("Currency"), "eur");
    await user.type(within(dialog).getByLabelText(/Chance of winning/), "40");
    await user.type(within(dialog).getByLabelText("Expected close date"), "2026-12-01");
    await user.type(within(dialog).getByLabelText("Next action"), "Call back");
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({
      lead_id: LEADS[1]!.id,
      stage_id: STAGES[1]!.id,
      title: "Retainer",
      value_amount: "2500.50",
      currency: "EUR",
      probability: 40,
      expected_close_date: "2026-12-01",
      next_action: "Call back",
    });
  });

  it("pre-selects and locks the lead when given one", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    const view = renderDrawer({ leadId: LEADS[0]!.id });
    const dialog = await screen.findByRole("dialog", { name: "New deal" });
    const lead = within(dialog).getByLabelText(/Lead/);
    expect(lead).toBeDisabled();
    expect(lead).toHaveValue(LEADS[0]!.id);
    await waitFor(() =>
      expect(
        within(lead).getByRole("option", { name: "Alpha redesign · Alpha Ltd" }),
      ).toBeInTheDocument(),
    );
    expect(within(dialog).getByText("This deal is created for this lead.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    await waitFor(() => expect(view.onClose).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "POST")?.body).toMatchObject({ lead_id: LEADS[0]!.id });
  });

  it("keeps a locked lead usable even when it is not in the first 100", async () => {
    stubApi();
    renderDrawer({ leadId: "cccccccc-cccc-4ccc-8ccc-cccccccccccc" });
    const dialog = await screen.findByRole("dialog", { name: "New deal" });
    await waitFor(() =>
      expect(within(dialog).getByRole("option", { name: "Selected lead" })).toBeInTheDocument(),
    );
    expect(within(dialog).getByLabelText(/Lead/)).toHaveValue(
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    );
  });

  it("maps the server's field errors onto the fields and stays open", async () => {
    const user = userEvent.setup();
    const { dialog, onClose } = await (async () => {
      stubApi({
        "POST /opportunities": () =>
          Response.json(
            {
              error: {
                code: "validation_error",
                message: "Check the highlighted fields.",
                fields: {
                  lead_id: "That lead is archived.",
                  stage_id: "Pick an open stage.",
                  value_amount: "Too large.",
                  currency: "Unknown currency.",
                },
              },
            },
            { status: 422 },
          ),
      });
      return openDrawer();
    })();
    await user.selectOptions(within(dialog).getByLabelText(/Lead/), LEADS[0]!.id);
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    expect(await within(dialog).findByText("That lead is archived.")).toBeInTheDocument();
    expect(within(dialog).getByText("Pick an open stage.")).toBeInTheDocument();
    expect(within(dialog).getByText("Too large.")).toBeInTheDocument();
    expect(within(dialog).getByText("Unknown currency.")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Lead/)).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByLabelText("Stage")).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByLabelText("Value")).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByLabelText("Currency")).toHaveAttribute("aria-invalid", "true");
    expect(within(dialog).getByText("Some fields need attention")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("button", { name: "Create deal" })).toBeEnabled();
  });

  it("shows a general server error and lets the person try again", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /opportunities": () =>
        Response.json(
          { error: { code: "internal_error", message: "Down for a moment." } },
          { status: 500 },
        ),
    });
    const { dialog } = await openDrawer();
    await user.selectOptions(within(dialog).getByLabelText(/Lead/), LEADS[0]!.id);
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    expect(await within(dialog).findByText("Down for a moment.")).toBeInTheDocument();
    expect(within(dialog).getByText("That didn't work")).toBeInTheDocument();
  });

  it("tells the person when the leads could not be loaded", async () => {
    stubApi({
      "GET /leads": () => Response.json({ error: { code: "x", message: "no" } }, { status: 500 }),
    });
    renderDrawer();
    const dialog = await screen.findByRole("dialog", { name: "New deal" });
    expect(await within(dialog).findByText("Couldn't load your leads")).toBeInTheDocument();
    expect(within(dialog).getByLabelText(/Lead/)).toBeDisabled();
  });

  it("says when there are more leads than the picker shows, and when there are none", async () => {
    stubApi({}, LEADS, 250);
    const first = await openDrawer();
    expect(first.dialog).toHaveTextContent("Showing the first 2 of 250 leads, A to Z.");
    first.unmount();
    stubApi({}, [], 0);
    const second = await openDrawer();
    expect(second.dialog).toHaveTextContent("You have no leads yet.");
  });

  it("cancels without sending", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    const { dialog, onClose } = await openDrawer();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(0);
  });

  it("has no accessibility violations, with and without errors", async () => {
    const user = userEvent.setup();
    stubApi();
    const { dialog } = await openDrawer();
    const rules = { rules: { "color-contrast": { enabled: false } } };
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
    await user.click(within(dialog).getByRole("button", { name: "Create deal" }));
    await within(dialog).findByText("Choose the lead this deal is for.");
    expect((await axe.run(dialog, rules)).violations).toEqual([]);
  });
});

describe("NewDealButton", () => {
  it("opens the drawer, starts fresh each time, and closes", async () => {
    const user = userEvent.setup();
    stubApi();
    render(
      <ToastProvider>
        <NewDealButton workspaceId={WS} stages={STAGES} />
      </ToastProvider>,
    );
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "New deal" }));
    let dialog = await screen.findByRole("dialog", { name: "New deal" });
    await waitFor(() => expect(within(dialog).getByLabelText(/Lead/)).toBeEnabled());
    await user.type(within(dialog).getByLabelText("Deal name"), "Half typed");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(screen.getByRole("button", { name: "New deal" }));
    dialog = await screen.findByRole("dialog", { name: "New deal" });
    expect(within(dialog).getByLabelText("Deal name")).toHaveValue("");
  });

  it("passes a lead through so other pages can reuse it", async () => {
    const user = userEvent.setup();
    stubApi();
    render(
      <ToastProvider>
        <NewDealButton workspaceId={WS} stages={STAGES} leadId={LEADS[0]!.id} />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: "New deal" }));
    const dialog = await screen.findByRole("dialog", { name: "New deal" });
    expect(within(dialog).getByLabelText(/Lead/)).toHaveValue(LEADS[0]!.id);
  });
});
