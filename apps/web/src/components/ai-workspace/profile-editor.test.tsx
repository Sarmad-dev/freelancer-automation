import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { ProfileEditor } from "./profile-editor";
import type { ProfileOut } from "./profile-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const PROFILE: ProfileOut = {
  role_title: "Developer",
  summary: null,
  services: ["Audits"],
  skills: [],
  industries: [],
  differentiators: [],
  excluded_customers: [],
  target_clients: "Small agencies",
  portfolio_urls: [],
  years_experience: null,
  experience_summary: null,
  pricing_guidance: "Quote after a call",
  preferred_cta: null,
  tone: "friendly",
  tone_notes: null,
  business_goal: null,
  business_goal_notes: null,
  version: 3,
  updated_at: "2026-10-12T00:00:00Z",
  timezone: "UTC",
  completeness: {
    filled: 4,
    total: 10,
    missing: [{ field: "skills", importance: "recommended", label: "Skills" }],
  },
};
const SUMMARY = {
  headline: "Developer",
  intro: null,
  links: ["javascript:alert(1)"],
  omitted: [],
  private_fields_excluded: ["pricing_guidance"],
  profile_version: 3,
  sections: [{ title: "Services", items: ["<b>Audits</b>"] }],
};

type Call = { method: string; path: string; body: unknown };
function stubApi(patch: () => Response) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      if (req.method === "PATCH") return patch();
      return Response.json(SUMMARY);
    }),
  );
  return calls;
}
const setup = () =>
  render(
    <ToastProvider>
      <ProfileEditor workspaceId={WS} initial={PROFILE} initialSummary={SUMMARY} facts={2} />
    </ToastProvider>,
  );

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("ProfileEditor", () => {
  it("starts saved, and only enables saving once something changes", async () => {
    const user = userEvent.setup();
    setup();
    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled();
    expect(screen.getByText(/All changes saved · version 3/)).toBeInTheDocument();
    await user.type(screen.getByLabelText("Role"), " Lead");
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save profile" })).toBeEnabled();
  });

  it("sends only the changed fields with the version it was based on", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json({ ...PROFILE, preferred_cta: "Book a call", version: 4 }),
    );
    setup();
    await user.type(screen.getByLabelText("Preferred call to action"), "Book a call");
    await user.click(screen.getByRole("button", { name: "Save profile" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      preferred_cta: "Book a call",
      expected_version: 3,
    });
    expect(await screen.findByText(/All changes saved · version 4/)).toBeInTheDocument();
  });

  it("reports an edit conflict instead of overwriting", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "stale_version", message: "Your profile changed in another tab." } },
        { status: 409 },
      ),
    );
    setup();
    await user.type(screen.getByLabelText("Role"), "x");
    await user.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByText("Your profile changed elsewhere")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reload the latest version" })).toBeInTheDocument();
    expect(screen.getByText(/Unsaved changes/)).toBeInTheDocument();
  });

  it("shows server-side field errors next to the field", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "Invalid",
            fields: { portfolio_urls: "Use public https links only." },
          },
        },
        { status: 422 },
      ),
    );
    setup();
    await user.type(screen.getByLabelText("Portfolio links"), "http://localhost");
    await user.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByText("Use public https links only.")).toBeInTheDocument();
    expect(screen.getByLabelText("Portfolio links")).toHaveAttribute("aria-invalid", "true");
  });

  it("previews the summary as plain text and never links an unsafe URL", () => {
    setup();
    expect(screen.getByText("<b>Audits</b>")).toBeInTheDocument();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.queryByRole("link", { name: /javascript:/ })).toBeNull();
    expect(screen.getByText(/This profile plus 2 approved facts/)).toBeInTheDocument();
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = setup();
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
