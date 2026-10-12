import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type { FitConfigOut } from "./lead-model";
import { ScoringForm } from "./scoring-form";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const CRITERIA: FitConfigOut["criteria"] = [
  { key: "service_match", enabled: true, weight: 6, keywords: ["WordPress"] },
  { key: "industry", enabled: true, weight: 3, preferred: ["SaaS"], avoid: [] },
  { key: "geography", enabled: true, weight: 1, preferred: ["Remote"] },
  { key: "company_size", enabled: true, weight: 1, preferred: ["2-10"] },
  { key: "budget", enabled: true, weight: 2 },
];
const CONFIG: FitConfigOut = { version: 3, criteria: CRITERIA, updated_at: "2026-10-12T00:00:00Z" };
const DEFAULTS: FitConfigOut = {
  version: 0,
  updated_at: null,
  criteria: [
    { key: "service_match", enabled: true, weight: 5, keywords: [] },
    { key: "industry", enabled: true, weight: 3, preferred: [], avoid: [] },
    { key: "geography", enabled: true, weight: 1, preferred: [] },
    { key: "company_size", enabled: true, weight: 1, preferred: [] },
    { key: "budget", enabled: true, weight: 2 },
  ],
};

type Call = { method: string; path: string; body: Record<string, unknown> | undefined };
function stubApi(handler: (req: Request) => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      return handler(req);
    }),
  );
  return calls;
}

const setup = (initial = CONFIG, canEdit = true) =>
  render(
    <ToastProvider>
      <ScoringForm workspaceId={WS} initial={initial} canEdit={canEdit} />
    </ToastProvider>,
  );
const section = (name: string) => screen.getByRole("region", { name });

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("ScoringForm", () => {
  it("explains honestly how scoring works", () => {
    setup();
    expect(screen.getByText(/no AI and nothing is fetched/)).toBeInTheDocument();
    expect(screen.getByText(/nearest 5/)).toBeInTheDocument();
    expect(screen.getByText(/capped at 25/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "profile" })[0]).toHaveAttribute(
      "href",
      "/ai-workspace/profile",
    );
  });

  it("starts saved and only enables saving once something changes", async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.getByText(/All changes saved · version 3/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save criteria" })).toBeDisabled();
    expect(screen.queryByText(/built-in defaults/i)).toBeNull();
    await user.type(screen.getByLabelText("Extra keywords"), "{Enter}Shopify");
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save criteria" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getByLabelText("Extra keywords")).toHaveValue("WordPress");
    expect(screen.getByText(/All changes saved/)).toBeInTheDocument();
  });

  it("shows the weight split as text", async () => {
    const user = userEvent.setup();
    setup();
    const split = section("How your weighting is split");
    expect(within(split).getByText("Service match")).toBeInTheDocument();
    expect(within(split).getByText("6 of 13 · 46%")).toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: "Use Budget criterion" }));
    expect(within(split).getByText("6 of 11 · 55%")).toBeInTheDocument();
    expect(within(split).queryByText("Budget")).toBeNull();
    expect(within(split).getByText(/Turned off: Budget/)).toBeInTheDocument();
  });

  it("sends all five criteria in order with the loaded version and the rescore flag", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ ...CONFIG, version: 4, rescored: 12 }));
    setup();
    await user.type(within(section("Geography")).getByLabelText("Preferred places"), "{Enter}EU");
    await user.click(screen.getByRole("checkbox", { name: "Just them (1)" }));
    await user.click(screen.getByRole("button", { name: "Save criteria" }));
    expect(await screen.findByText("Saved. 12 leads recalculated.")).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT")!;
    expect(put.path).toBe("/fit-scoring");
    expect(put.body).toEqual({
      criteria: [
        { key: "service_match", enabled: true, weight: 6, keywords: ["WordPress"] },
        { key: "industry", enabled: true, weight: 3, preferred: ["SaaS"], avoid: [] },
        { key: "geography", enabled: true, weight: 1, preferred: ["Remote", "EU"] },
        { key: "company_size", enabled: true, weight: 1, preferred: ["1", "2-10"] },
        { key: "budget", enabled: true, weight: 2 },
      ],
      expected_version: 3,
      rescore: true,
    });
    expect(refresh).toHaveBeenCalled();
    expect(await screen.findByText(/All changes saved · version 4/)).toBeInTheDocument();
  });

  it("can save without recalculating existing leads", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ ...CONFIG, version: 4, rescored: null }));
    setup();
    await user.click(screen.getByRole("checkbox", { name: "Recalculate existing leads now" }));
    await user.clear(within(section("Budget")).getByLabelText("Budget weight"));
    await user.type(within(section("Budget")).getByLabelText("Budget weight"), "9");
    await user.click(screen.getByRole("button", { name: "Save criteria" }));
    await waitFor(() => expect(calls.some((c) => c.method === "PUT")).toBe(true));
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({
      rescore: false,
      expected_version: 3,
    });
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("shows the built-in defaults note at version 0 and still allows saving", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ ...DEFAULTS, version: 1, rescored: 0 }));
    setup(DEFAULTS);
    expect(
      screen.getByText("These are the built-in defaults. Saving creates your own criteria."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save criteria" }));
    expect(await screen.findByText("Saved. 0 leads recalculated.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toMatchObject({ expected_version: 0 });
    expect(screen.queryByText(/built-in defaults\. Saving/)).toBeNull();
  });

  it("offers a reload when someone else saved first", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "stale_version", message: "Changed in another tab." } },
        { status: 409 },
      ),
    );
    setup();
    await user.type(screen.getByLabelText("Extra keywords"), "x");
    await user.click(screen.getByRole("button", { name: "Save criteria" }));
    expect(await screen.findByText("This scoring setup changed")).toBeInTheDocument();
    expect(screen.getByText(/Changed in another tab\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload the latest version" })).toBeInTheDocument();
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
  });

  it("shows the message and puts field errors next to the right criterion", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "The criteria are not valid.",
            fields: {
              "criteria.1.weight": "Must be at most 10.",
              "criteria.2.preferred.0": "Too long.",
              other_thing: "Unrelated problem.",
            },
          },
        },
        { status: 422 },
      ),
    );
    setup();
    await user.type(screen.getByLabelText("Extra keywords"), "x");
    await user.click(screen.getByRole("button", { name: "Save criteria" }));
    expect(await screen.findByText("The criteria are not valid.")).toBeInTheDocument();
    expect(screen.getByText("Unrelated problem.")).toBeInTheDocument();
    const weight = within(section("Industry")).getByLabelText("Industry weight");
    expect(weight).toHaveAttribute("aria-invalid", "true");
    expect(within(section("Industry")).getByText("Must be at most 10.")).toBeInTheDocument();
    expect(within(section("Geography")).getByLabelText("Preferred places")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("refuses to send when every criterion is off", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ ...CONFIG, rescored: 0 }));
    setup();
    for (const name of ["Service match", "Industry", "Geography", "Company size", "Budget"]) {
      await user.click(screen.getByRole("switch", { name: `Use ${name} criterion` }));
    }
    await user.click(screen.getByRole("button", { name: "Save criteria" }));
    expect(await screen.findByText("Fix these before saving")).toBeInTheDocument();
    expect(screen.getByText(/Turn on at least one criterion/)).toBeInTheDocument();
    expect(calls).toEqual([]);
  });

  it("refuses an out-of-range weight before sending", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ ...CONFIG, rescored: 0 }));
    setup();
    const input = within(section("Budget")).getByLabelText("Budget weight");
    await user.clear(input);
    await user.type(input, "11");
    await user.click(screen.getByRole("button", { name: "Save criteria" }));
    expect(await screen.findByText("Use a whole number from 1 to 10.")).toBeInTheDocument();
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(calls).toEqual([]);
  });

  it("dims and disables the fields of a criterion that is switched off, but keeps them visible", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("switch", { name: "Use Industry criterion" }));
    const industry = section("Industry");
    expect(within(industry).getByLabelText("Preferred industries")).toBeDisabled();
    expect(within(industry).getByLabelText("Industry weight")).toBeDisabled();
    expect(within(industry).getByLabelText("Preferred industries")).toHaveValue("SaaS");
    expect(within(industry).getByText("Off")).toBeInTheDocument();
  });

  it("resets to defaults in the form only, without saving", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ ...CONFIG, rescored: 0 }));
    setup();
    await user.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(screen.getByLabelText("Service match weight")).toHaveValue(5);
    expect(screen.getByLabelText("Extra keywords")).toHaveValue("");
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    expect(calls).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Discard changes" }));
    expect(screen.getByLabelText("Service match weight")).toHaveValue(6);
  });

  it("recalculates all leads on request and reports how many", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json({ rescored: 7 }));
    setup();
    await user.click(screen.getByRole("button", { name: "Recalculate all leads" }));
    expect(await screen.findByText("7 leads recalculated.")).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "POST", path: "/fit-scoring/rescore" });
    expect(refresh).toHaveBeenCalled();
  });

  it("warns before leaving with unsaved changes", async () => {
    const user = userEvent.setup();
    setup();
    const clean = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(clean);
    expect(clean.defaultPrevented).toBe(false);
    await user.type(screen.getByLabelText("Extra keywords"), "x");
    const dirty = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(dirty);
    expect(dirty.defaultPrevented).toBe(true);
  });

  it("is read-only for members", () => {
    setup(CONFIG, false);
    expect(screen.getByText(/Only the workspace owner can change fit scoring/)).toBeInTheDocument();
    expect(screen.getByLabelText("Extra keywords")).toBeDisabled();
    expect(screen.getByLabelText("Budget weight")).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Use Budget criterion" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "2–10" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save criteria" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Recalculate all leads" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reset to defaults" })).toBeNull();
  });

  it("has no detectable accessibility violations", async () => {
    for (const [initial, canEdit] of [
      [CONFIG, true],
      [DEFAULTS, true],
      [CONFIG, false],
    ] as const) {
      const { container, unmount } = setup(initial, canEdit);
      const results = await axe.run(container, {
        rules: { "color-contrast": { enabled: false } },
      });
      expect(results.violations).toEqual([]);
      unmount();
    }
  });
});
