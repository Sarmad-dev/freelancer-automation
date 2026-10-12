import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OnboardingState } from "@freelancer-os/contracts";
import { OnboardingWizard } from "./wizard";

const hardNavigate = vi.fn();
vi.mock("@/lib/navigation", () => ({ hardNavigate: (p: string) => hardNavigate(p) }));

const IDS = [
  "role",
  "services",
  "skills",
  "target_clients",
  "industries",
  "portfolio",
  "experience",
  "tone",
  "timezone",
  "goal",
];
const REQUIRED = new Set([
  "role",
  "services",
  "skills",
  "target_clients",
  "tone",
  "timezone",
  "goal",
]);

function state(completed: string[] = [], over: Partial<OnboardingState> = {}): OnboardingState {
  return {
    status: completed.length ? "in_progress" : "not_started",
    current_step: IDS.find((i) => !completed.includes(i)) ?? "goal",
    steps: IDS.map((id) => ({
      id,
      label: id,
      required: REQUIRED.has(id),
      completed: completed.includes(id),
    })),
    completed_count: completed.length,
    total_count: 10,
    demo_mode: false,
    profile: {
      role_title: completed.includes("role") ? "Developer" : null,
      summary: null,
      services: completed.includes("services") ? ["Web development"] : [],
      skills: [],
      target_clients: null,
      industries: [],
      portfolio_urls: [],
      years_experience: null,
      experience_summary: null,
      tone: null,
      tone_notes: null,
      timezone: "UTC",
      business_goal: null,
      business_goal_notes: null,
    },
    ...over,
  };
}

type Handler = (req: Request) => Response | Promise<Response>;
function route(handlers: Record<string, Handler>) {
  const calls: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const key = `${req.method} ${path}`;
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const h = handlers[key];
      if (!h) throw new Error(`Unexpected request ${key}`);
      return h(req);
    }),
  );
  return calls;
}
const ok = (body: unknown) => () => Response.json(body);

beforeEach(() => {
  hardNavigate.mockClear();
  vi.unstubAllGlobals();
});

describe("OnboardingWizard", () => {
  it("resumes at the first incomplete step with saved values", () => {
    render(<OnboardingWizard workspaceId="w1" initial={state(["role", "services"])} />);
    expect(screen.getByRole("heading", { name: "What are your key skills?" })).toBeInTheDocument();
    expect(screen.getByText(/Step 3 of 10/)).toBeInTheDocument();
    expect(screen.getByText(/2 saved/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Steps saved" })).toHaveAttribute(
      "aria-valuenow",
      "2",
    );
    expect(screen.getByRole("button", { name: /services.*saved/ })).toBeInTheDocument();
  });

  it("saves a step to the API and advances to the next", async () => {
    const user = userEvent.setup();
    const calls = route({ "PUT /onboarding/step": ok(state(["role"])) });
    render(<OnboardingWizard workspaceId="w1" initial={state()} />);
    await user.type(screen.getByLabelText("What best describes you?"), "Independent developer");
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(
      await screen.findByRole("heading", { name: "Which services do you offer?" }),
    ).toBeInTheDocument();
    expect(calls[0]).toMatchObject({
      method: "PUT",
      path: "/onboarding/step",
      body: { step: "role", role_title: "Independent developer" },
    });
    // Focus moves to the new step heading for keyboard / screen-reader users.
    expect(screen.getByRole("heading", { name: "Which services do you offer?" })).toHaveFocus();
  });

  it("splits list fields into one item per line", async () => {
    const user = userEvent.setup();
    const calls = route({ "PUT /onboarding/step": ok(state(["role", "services"])) });
    render(<OnboardingWizard workspaceId="w1" initial={state(["role"])} />);
    await user.type(
      screen.getByLabelText("Services"),
      "Web development{Enter}  Audits  {Enter}{Enter}",
    );
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.body).toEqual({ step: "services", services: ["Web development", "Audits"] });
  });

  it("shows server validation errors on the field and keeps the user on the step", async () => {
    const user = userEvent.setup();
    route({
      "PUT /onboarding/step": () =>
        Response.json(
          {
            error: {
              code: "validation_error",
              message: "x",
              fields: { urls: "Use a public website address." },
            },
          },
          { status: 422 },
        ),
    });
    render(<OnboardingWizard workspaceId="w1" initial={state(IDS.slice(0, 5))} />);
    await user.type(screen.getByLabelText("Links"), "http://localhost/admin");
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByText("Use a public website address.")).toBeInTheDocument();
    expect(screen.getByLabelText("Links")).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByRole("heading", { name: "Where can clients see your work?" }),
    ).toBeInTheDocument();
  });

  it("optional steps can be skipped without saving; required ones cannot", async () => {
    const user = userEvent.setup();
    const calls = route({});
    const first = render(<OnboardingWizard workspaceId="w1" initial={state(IDS.slice(0, 4))} />);
    expect(screen.getByText(/Step 5 of 10/)).toHaveTextContent(/\(optional\)/);
    await user.click(screen.getByRole("button", { name: "Skip this step" }));
    expect(
      screen.getByRole("heading", { name: "Where can clients see your work?" }),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    first.unmount();
    render(<OnboardingWizard workspaceId="w1" initial={state()} />);
    expect(screen.queryByRole("button", { name: "Skip this step" })).toBeNull();
  });

  it("'Save and finish later' records the skip and leaves", async () => {
    const user = userEvent.setup();
    const calls = route({ "POST /onboarding/skip": ok(state(["role"], { status: "skipped" })) });
    render(<OnboardingWizard workspaceId="w1" initial={state(["role"])} />);
    await user.click(screen.getByRole("button", { name: "Save and finish later" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/"));
    expect(calls[0]?.path).toBe("/onboarding/skip");
  });

  it("finishing saves the last step, completes, and goes to Home", async () => {
    const user = userEvent.setup();
    const all = state(IDS);
    const calls = route({
      "PUT /onboarding/step": ok(all),
      "POST /onboarding/complete": ok({ ...all, status: "completed" }),
    });
    render(<OnboardingWizard workspaceId="w1" initial={state(IDS.slice(0, 9))} />);
    await user.click(screen.getByLabelText("Find new clients"));
    await user.click(screen.getByRole("button", { name: "Finish" }));
    await waitFor(() => expect(hardNavigate).toHaveBeenCalledWith("/"));
    expect(calls.map((c) => `${c.method} ${c.path}`)).toEqual([
      "PUT /onboarding/step",
      "POST /onboarding/complete",
    ]);
    expect(calls[0]?.body).toMatchObject({ step: "goal", goal: "find_new_clients" });
  });

  it("completing with required steps missing jumps to the first missing one", async () => {
    const user = userEvent.setup();
    route({
      "PUT /onboarding/step": ok(state(["goal"])),
      "POST /onboarding/complete": () =>
        Response.json(
          {
            error: {
              code: "onboarding_incomplete",
              message: "Finish the required steps first: Role, Services.",
              fields: { role: "Required", services: "Required" },
            },
          },
          { status: 409 },
        ),
    });
    render(<OnboardingWizard workspaceId="w1" initial={state(IDS.slice(0, 9))} />);
    await user.click(screen.getByLabelText("Find new clients"));
    await user.click(screen.getByRole("button", { name: "Finish" }));
    expect(await screen.findByText("A few required steps are still open")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "What do you do?" })).toBeInTheDocument();
    expect(hardNavigate).not.toHaveBeenCalled();
  });

  it("demo mode toggles through the API", async () => {
    const user = userEvent.setup();
    const calls = route({
      "PUT /demo-mode": ok({
        id: "w1",
        name: "W",
        kind: "personal",
        role: "owner",
        timezone: "UTC",
        demo_mode: true,
        onboarding_status: "in_progress",
      }),
    });
    render(<OnboardingWizard workspaceId="w1" initial={state(IDS.slice(0, 9))} />);
    await user.click(screen.getByRole("checkbox", { name: "Explore in demo mode" }));
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: "Explore in demo mode" })).toBeChecked(),
    );
    expect(calls[0]?.body).toEqual({ enabled: true });
  });

  it("a lost session sends the user to sign-in instead of showing a generic error", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, pathname: "/onboarding", search: "" });
    route({
      "PUT /onboarding/step": () =>
        Response.json(
          {
            error: { code: "session_expired", message: "Your session has expired. Sign in again." },
          },
          { status: 401 },
        ),
    });
    render(<OnboardingWizard workspaceId="w1" initial={state()} />);
    await user.type(screen.getByLabelText("What best describes you?"), "Developer");
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("/sign-in?reason=expired&next=%2Fonboarding"),
    );
  });

  it("blank years gets a friendly client-side message and sends nothing", async () => {
    const user = userEvent.setup();
    const calls = route({});
    render(<OnboardingWizard workspaceId="w1" initial={state(IDS.slice(0, 6))} />);
    await user.click(screen.getByRole("button", { name: "Save and continue" }));
    expect(await screen.findByText(/Enter your years of experience/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("steps are reachable via the step list and have no structural a11y violations", async () => {
    const user = userEvent.setup();
    const { container } = render(<OnboardingWizard workspaceId="w1" initial={state(["role"])} />);
    await user.click(
      within(screen.getByRole("navigation", { name: "Onboarding steps" })).getByRole("button", {
        name: /^tone/,
      }),
    );
    expect(
      screen.getByRole("heading", { name: "How should your messages sound?" }),
    ).toBeInTheDocument();
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false }, region: { enabled: false } },
    });
    expect(
      results.violations.map(
        (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
      ),
    ).toEqual([]);
  });
});
