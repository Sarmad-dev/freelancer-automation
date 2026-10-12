import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { LeadDetail } from "./lead-detail";
import type {
  ActivityOut,
  CompanyOut,
  ContactOut,
  FitExplanation,
  LeadDetail as Lead,
  StageOut,
  TagOut,
} from "./lead-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const LEAD_ID = "11111111-1111-4111-8111-111111111111";
const CO_ID = "33333333-3333-4333-8333-333333333333";
const CO2_ID = "33333333-3333-4333-8333-333333333334";
const CT_ID = "44444444-4444-4444-8444-444444444444";
const TAG_A = "55555555-5555-4555-8555-555555555555";
const TAG_B = "55555555-5555-4555-8555-555555555556";
const STAGE_1 = "66666666-6666-4666-8666-666666666661";
const STAGE_2 = "66666666-6666-4666-8666-666666666662";
const NOW = "2026-10-12T12:00:00Z";

const EXPLANATION: FitExplanation = {
  band: "strong",
  capped: false,
  computed_at: "2026-10-12T10:00:00Z",
  confidence: 0.75,
  config_version: 1,
  criteria: [
    {
      key: "industry",
      label: "Industry",
      weight: 20,
      outcome: "match",
      points: 20,
      reason: "SaaS is on your list.",
      evidence: [{ field: "industry", value: "SaaS" }],
    },
    {
      key: "size",
      label: "Company size",
      weight: 10,
      outcome: "unknown",
      points: 0,
      reason: "No size recorded.",
      evidence: [],
    },
  ],
  known_weight: 20,
  method: "rules",
  profile_version: 1,
  score: 75,
  summary: "Good industry match.",
  total_weight: 30,
  version: 1,
  warnings: [],
};

function lead(over: Partial<Lead> = {}): Lead {
  return {
    id: LEAD_ID,
    title: "Website rebuild for Acme",
    status: "contacted",
    stage: { id: STAGE_1, key: "contacted", name: "Contacted" },
    company: { id: CO_ID, name: "Acme Ltd" },
    contact: { id: CT_ID, full_name: "Dana Jones", email: "dana@acme.example" },
    source: "manual",
    source_retrieved_at: null,
    industry: "SaaS",
    location: "Remote",
    budget_signal: "medium",
    next_action: "Send proposal",
    next_action_at: "2026-10-20T09:30:00Z",
    notes: "Line one\nLine two",
    tags: [{ id: TAG_A, name: "Warm", color: null }],
    fit_band: "strong",
    fit_score: 75,
    fit_scored_at: "2026-10-12T10:00:00Z",
    fit_stale: false,
    fit_explanation: EXPLANATION,
    do_not_contact: false,
    is_sample: false,
    archived_at: null,
    last_activity_at: "2026-10-11T08:00:00Z",
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

const STAGES: StageOut[] = [
  { id: STAGE_1, key: "contacted", name: "Contacted", position: 0, is_won: false, is_lost: false },
  { id: STAGE_2, key: "qualified", name: "Qualified", position: 1, is_won: false, is_lost: false },
];
const TAGS = [
  { id: TAG_A, name: "Warm", color: null },
  { id: TAG_B, name: "Referral", color: null },
] as TagOut[];
const COMPANIES = [
  { id: CO_ID, name: "Acme Ltd" },
  { id: CO2_ID, name: "Beta Inc" },
] as CompanyOut[];
const CONTACTS = [
  { id: CT_ID, full_name: "Dana Jones", email: "dana@acme.example" },
] as ContactOut[];

type Over = Partial<React.ComponentProps<typeof LeadDetail>>;
function renderDetail(over: Over = {}) {
  return render(
    <ToastProvider>
      <LeadDetail
        workspaceId={WS}
        lead={lead()}
        activities={{ items: [activity()], total: 1 }}
        tags={TAGS}
        stages={STAGES}
        companies={COMPANIES}
        contacts={CONTACTS}
        deals={[]}
        tasks={[]}
        timezone="Europe/Berlin"
        canEdit
        now={NOW}
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
      return Response.json(lead());
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

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("LeadDetail header and summary", () => {
  it("shows the title, badges, provenance and summary facts", () => {
    renderDetail({
      lead: lead({
        source: "CSV import",
        source_retrieved_at: "2026-10-12T14:03:00Z",
        is_sample: true,
      }),
    });
    expect(
      screen.getByRole("heading", { level: 1, name: "Website rebuild for Acme" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: /Back to leads/ })).toHaveAttribute("href", "/leads");
    expect(screen.getAllByText("Contacted").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Strong fit · 75").length).toBeGreaterThan(0);
    expect(screen.getByText("Sample")).toBeInTheDocument();
    expect(screen.getByText("CSV import · retrieved 2026-10-12 14:03 UTC")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Acme Ltd" })).toHaveAttribute(
      "href",
      `/leads/companies/${CO_ID}`,
    );
    expect(screen.getByRole("link", { name: "Dana Jones" })).toHaveAttribute(
      "href",
      `/leads/contacts/${CT_ID}`,
    );
    expect(screen.getByRole("link", { name: "dana@acme.example" })).toHaveAttribute(
      "href",
      "mailto:dana@acme.example",
    );
    expect(screen.getByText("2026-10-20 09:30 UTC")).toBeInTheDocument();
    expect(screen.queryByText("Overdue")).toBeNull();
  });

  it("shows a manual source and keeps notes' line breaks as plain text", () => {
    renderDetail();
    expect(screen.getByText("manual")).toBeInTheDocument();
    const notes = screen.getByText(/Line one/);
    expect(notes).toHaveClass("whitespace-pre-wrap");
    expect(notes.textContent).toBe("Line one\nLine two");
  });

  it("flags an overdue next action", () => {
    renderDetail({ lead: lead({ next_action_at: "2026-10-01T09:00:00Z" }) });
    expect(screen.getByText("Overdue")).toBeInTheDocument();
  });

  it("shows a prominent do-not-contact notice", () => {
    renderDetail({ lead: lead({ do_not_contact: true }) });
    expect(
      screen.getByText(
        "This contact is on your do-not-contact list. Nothing will be sent to them, by you or by any automation.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Do not contact").length).toBeGreaterThan(0);
  });

  it("renders stored markup and a javascript: email as inert text", () => {
    const evil = '<img src=x onerror="alert(1)">';
    renderDetail({
      lead: lead({
        title: evil,
        notes: evil,
        industry: evil,
        contact: { id: CT_ID, full_name: evil, email: "javascript:alert(1)" },
      }),
    });
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(evil);
    expect(screen.getByText("javascript:alert(1)").closest("a")).toBeNull();
  });
});

describe("LeadDetail status, stage and archive", () => {
  it("sends only the status when it changes, then shows the response", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      "PATCH /leads/:id": () => Response.json(lead({ status: "qualified" })),
    });
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Status"), "qualified");
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "PATCH", body: { status: "qualified" } });
    expect(screen.getByLabelText("Status")).toHaveValue("qualified");
  });

  it("sends only the stage when it changes", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Pipeline stage"), STAGE_2);
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ method: "PATCH", body: { stage_id: STAGE_2 } });
  });

  it("shows an error banner and keeps the old value when a change fails", async () => {
    const user = userEvent.setup();
    stubApi({
      "PATCH /leads/:id": () => errorResponse(404, "not_found", "That lead no longer exists."),
    });
    renderDetail();
    await user.selectOptions(screen.getByLabelText("Status"), "won");
    expect(await screen.findByText("That lead no longer exists.")).toBeInTheDocument();
    expect(screen.getByText("That didn't work")).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toHaveValue("contacted");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("asks before archiving", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      "POST /leads/:id/archive": () => Response.json(lead({ archived_at: "2026-10-12T12:01:00Z" })),
    });
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(calls).toHaveLength(0);
    const dialog = await screen.findByRole("dialog", { name: "Archive this lead?" });
    await user.click(within(dialog).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "POST" });
    expect(calls[0]!.path).toMatch(/\/leads\/[^/]+\/archive$/);
    expect(await screen.findByText("This lead is archived")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Restore" })).toBeInTheDocument();
  });

  it("is read-only when archived, and can be restored", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      "POST /leads/:id/restore": () => Response.json(lead()),
    });
    renderDetail({ lead: lead({ archived_at: "2026-10-12T11:00:00Z" }) });
    expect(screen.getByText("Archived")).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toBeDisabled();
    expect(screen.getByLabelText("Pipeline stage")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Edit tags" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Log activity" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Recalculate" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.path).toMatch(/\/restore$/);
    await waitFor(() => expect(screen.queryByText("This lead is archived")).toBeNull());
  });

  it("is read-only for members", () => {
    renderDetail({ canEdit: false, lead: lead({ fit_stale: true }) });
    expect(screen.getByText("View only")).toBeInTheDocument();
    for (const name of [
      "Edit",
      "Archive",
      "Restore",
      "Edit tags",
      "Recalculate",
      "Add to timeline",
    ]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
    expect(screen.getByLabelText("Status")).toBeDisabled();
    expect(screen.getByLabelText("Pipeline stage")).toBeDisabled();
    expect(screen.queryByRole("form", { name: "Log activity" })).toBeNull();
    expect(screen.getByText("Intro call booked")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Activity, newest first" })).toHaveTextContent(
      "Workspace owner",
    );
  });
});

describe("LeadDetail fit score", () => {
  it("recalculates a stale score and shows the new explanation", async () => {
    const user = userEvent.setup();
    const fresh = lead({
      fit_stale: false,
      fit_score: 55,
      fit_band: "possible",
      fit_explanation: { ...EXPLANATION, band: "possible", score: 55, summary: "Newer summary." },
    });
    const calls = stubApi({ "POST /leads/:id/score": () => Response.json(fresh) });
    renderDetail({ lead: lead({ fit_stale: true }) });
    expect(
      screen.getByText("This score uses older criteria or an older profile"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Recalculate" }));
    expect(await screen.findByText("Newer summary.")).toBeInTheDocument();
    expect(calls[0]).toMatchObject({ method: "POST" });
    expect(calls[0]!.path).toMatch(/\/score$/);
    expect(screen.getByTestId("fit-headline")).toHaveTextContent("Possible fit · 55 / 100");
    expect(screen.queryByText("This score uses older criteria or an older profile")).toBeNull();
    expect(refresh).toHaveBeenCalled();
  });

  it("shows a recalculation failure next to the score", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /leads/:id/score": () => errorResponse(503, "unavailable", "Scoring is busy."),
    });
    renderDetail({ lead: lead({ fit_stale: true }) });
    await user.click(screen.getByRole("button", { name: "Recalculate" }));
    expect(await screen.findByText("Couldn't recalculate the score")).toBeInTheDocument();
    expect(screen.getByText("Scoring is busy.")).toBeInTheDocument();
  });

  it("offers to score a lead that never was", () => {
    renderDetail({
      lead: lead({
        fit_explanation: null,
        fit_score: null,
        fit_band: null,
        fit_scored_at: null,
      }),
    });
    expect(screen.getByText("Not scored yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recalculate" })).toBeInTheDocument();
  });
});

describe("LeadDetail tags", () => {
  it("links tags to the filtered lead list", () => {
    renderDetail();
    expect(screen.getByRole("link", { name: "Warm" })).toHaveAttribute(
      "href",
      `/leads?tag_id=${TAG_A}`,
    );
  });

  it("saves the chosen tags", async () => {
    const user = userEvent.setup();
    const calls = stubApi({
      "PUT /leads/:id/tags": () =>
        Response.json(
          lead({
            tags: [
              { id: TAG_A, name: "Warm", color: null },
              { id: TAG_B, name: "Referral", color: null },
            ],
          }),
        ),
    });
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit tags" }));
    expect(screen.getByRole("checkbox", { name: "Warm" })).toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "Referral" }));
    await user.click(screen.getByRole("button", { name: "Save tags" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ method: "PUT", body: { tag_ids: [TAG_A, TAG_B] } });
    expect(await screen.findByRole("link", { name: "Referral" })).toBeInTheDocument();
  });

  it("creates a new tag and selects it", async () => {
    const user = userEvent.setup();
    const newId = "55555555-5555-4555-8555-555555555599";
    const calls = stubApi({
      "POST /tags": () =>
        Response.json(
          {
            id: newId,
            name: "Hot",
            color: null,
            created_at: NOW,
            updated_at: NOW,
          },
          { status: 201 },
        ),
    });
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit tags" }));
    await user.type(screen.getByLabelText("New tag"), "Hot");
    await user.click(screen.getByRole("button", { name: "Add tag" }));
    expect(await screen.findByRole("checkbox", { name: "Hot" })).toBeChecked();
    expect(calls[0]).toMatchObject({ method: "POST", path: "/tags", body: { name: "Hot" } });
  });
});

describe("LeadDetail timeline", () => {
  it("lists activity newest first with kind, actor and stage changes", () => {
    renderDetail({
      activities: {
        total: 3,
        items: [
          activity({
            id: "77777777-7777-4777-8777-777777777772",
            kind: "stage_change",
            summary: "Moved to Qualified",
            body: null,
            details: { from: "contacted", to: "qualified" },
            actor_user_id: null,
          }),
          activity(),
          activity({
            id: "77777777-7777-4777-8777-777777777773",
            kind: "call",
            summary: "Quick call",
            body: null,
          }),
        ],
      },
    });
    const list = screen.getByRole("list", { name: "Activity, newest first" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Stage change");
    expect(items[0]).toHaveTextContent("System");
    expect(items[0]).toHaveTextContent("From contacted to qualified");
    expect(items[1]).toHaveTextContent("Note");
    expect(items[1]).toHaveTextContent("You");
    expect(items[1]).toHaveTextContent("2026-10-11 08:00 UTC");
    expect(items[2]).toHaveTextContent("Call");
  });

  it("logs a call and shows it at the top", async () => {
    const user = userEvent.setup();
    const created = activity({
      id: "77777777-7777-4777-8777-777777777780",
      kind: "call",
      summary: "Discovery call",
      body: "Budget confirmed",
      occurred_at: "2026-10-12T12:05:00Z",
    });
    const calls = stubApi({
      "POST /leads/:id/activities": () => Response.json(created, { status: 201 }),
    });
    renderDetail();
    const form = screen.getByRole("form", { name: "Log activity" });
    await user.selectOptions(within(form).getByLabelText("What happened"), "call");
    await user.type(within(form).getByLabelText(/Summary/), "Discovery call");
    await user.type(within(form).getByLabelText(/Details/), "Budget confirmed");
    await user.click(within(form).getByRole("button", { name: "Add to timeline" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({
      method: "POST",
      body: { kind: "call", summary: "Discovery call", body: "Budget confirmed" },
    });
    const items = within(screen.getByRole("list", { name: "Activity, newest first" })).getAllByRole(
      "listitem",
    );
    expect(items[0]).toHaveTextContent("Discovery call");
    expect(within(form).getByLabelText(/Summary/)).toHaveValue("");
  });

  it("requires a summary before sending", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Add to timeline" }));
    expect(await screen.findByText("Say what happened.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("maps API field errors onto the form", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /leads/:id/activities": () =>
        errorResponse(422, "validation_error", "Invalid", {
          summary: "Use at most 200 characters.",
        }),
    });
    renderDetail();
    await user.type(screen.getByLabelText(/Summary/), "x");
    await user.click(screen.getByRole("button", { name: "Add to timeline" }));
    expect(await screen.findByText("Use at most 200 characters.")).toBeInTheDocument();
    expect(screen.getByText("Some fields need attention")).toBeInTheDocument();
  });

  it("loads older activity with limit and offset", async () => {
    const user = userEvent.setup();
    const older = activity({
      id: "77777777-7777-4777-8777-777777777790",
      summary: "Very first contact",
      body: null,
    });
    const calls = stubApi({
      "GET /leads/:id/activities": () =>
        Response.json({ items: [older], total: 2, limit: 50, offset: 1 }),
    });
    renderDetail({ activities: { items: [activity()], total: 2 } });
    await user.click(screen.getByRole("button", { name: "Show older activity" }));
    expect(await screen.findByText("Very first contact")).toBeInTheDocument();
    expect(new URLSearchParams(calls[0]!.search).get("offset")).toBe("1");
    expect(new URLSearchParams(calls[0]!.search).get("limit")).toBe("50");
    expect(screen.queryByRole("button", { name: "Show older activity" })).toBeNull();
  });
});

describe("LeadDetail edit drawer", () => {
  async function openEditor() {
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit lead" });
    return { user, dialog };
  }

  it("sends only the fields that changed, and null for cleared ones", async () => {
    const calls = stubApi();
    renderDetail();
    const { user, dialog } = await openEditor();
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeDisabled();
    const title = within(dialog).getByLabelText(/^Title/);
    await user.clear(title);
    await user.type(title, "Renamed");
    await user.clear(within(dialog).getByLabelText("Location"));
    await user.selectOptions(within(dialog).getByLabelText("Company"), CO2_ID);
    await user.selectOptions(within(dialog).getByLabelText("Contact"), "");
    fireEvent.change(within(dialog).getByLabelText("Next action date"), {
      target: { value: "2026-10-25T10:15" },
    });
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "PATCH" });
    expect(calls[0]!.body).toEqual({
      title: "Renamed",
      location: null,
      company_id: CO2_ID,
      contact_id: null,
      next_action_at: "2026-10-25T10:15:00.000Z",
    });
  });

  it("maps API field errors and stays open", async () => {
    stubApi({
      "PATCH /leads/:id": () =>
        errorResponse(422, "validation_error", "Invalid", {
          industry: "Use at most 100 characters.",
        }),
    });
    renderDetail();
    const { user, dialog } = await openEditor();
    await user.type(within(dialog).getByLabelText("Industry"), " more");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    expect(await within(dialog).findByText("Use at most 100 characters.")).toBeInTheDocument();
    expect(within(dialog).getByText("Some fields need attention")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Industry")).toHaveAttribute("aria-invalid", "true");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("keeps a linked company that is missing from the picker's first page", async () => {
    renderDetail({ companies: [COMPANIES[1]!] });
    const { dialog } = await openEditor();
    const select = within(dialog).getByLabelText("Company");
    expect(select).toHaveValue(CO_ID);
    expect(within(select).getByRole("option", { name: "Acme Ltd" })).toBeInTheDocument();
  });
});

describe("LeadDetail accessibility", () => {
  const opts = { rules: { "color-contrast": { enabled: false } } };
  // Portals (drawer, toasts) sit outside the page landmark in these isolated renders.
  const bodyOpts = { rules: { ...opts.rules, region: { enabled: false } } };

  it("has no violations for a full lead", async () => {
    const { container } = renderDetail({
      lead: lead({ do_not_contact: true, is_sample: true, fit_stale: true }),
      activities: {
        total: 2,
        items: [
          activity(),
          activity({
            id: "77777777-7777-4777-8777-777777777772",
            kind: "stage_change",
            details: { from: "a", to: "b" },
            actor_user_id: null,
            body: null,
          }),
        ],
      },
    });
    expect((await axe.run(container, opts)).violations).toEqual([]);
  });

  it("has no violations for an archived, never-scored lead as a member", async () => {
    const { container } = renderDetail({
      canEdit: false,
      lead: lead({
        archived_at: "2026-10-12T11:00:00Z",
        fit_explanation: null,
        fit_score: null,
        fit_band: null,
        company: null,
        contact: null,
        tags: [],
      }),
      activities: { items: [], total: 0 },
    });
    expect((await axe.run(container, opts)).violations).toEqual([]);
  });

  it("has no violations with the tag editor and edit drawer open", async () => {
    const user = userEvent.setup();
    renderDetail();
    await user.click(screen.getByRole("button", { name: "Edit tags" }));
    expect((await axe.run(document.body, bodyOpts)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByRole("dialog", { name: "Edit lead" });
    expect((await axe.run(document.body, bodyOpts)).violations).toEqual([]);
  });
});
