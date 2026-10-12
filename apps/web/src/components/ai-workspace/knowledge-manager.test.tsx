import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import { KnowledgeManager } from "./knowledge-manager";
import type { KnowledgeOut } from "./knowledge-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const QUERY = { status: "", kind: "", q: "", page: 1 } as const;

function item(over: Partial<KnowledgeOut> = {}): KnowledgeOut {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    kind: "fact",
    title: "Ships weekly",
    content: "Delivers a working increment every week.",
    source_type: "manual",
    source_ref: null,
    status: "pending_review",
    version: 1,
    is_enabled: true,
    approved_at: null,
    approved_by_user_id: null,
    created_by_user_id: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    ...over,
  };
}

function renderManager(
  items: KnowledgeOut[],
  over: { canEdit?: boolean; stats?: Record<string, number>; total?: number } = {},
) {
  return render(
    <ToastProvider>
      <KnowledgeManager
        workspaceId={WS}
        items={items}
        total={over.total ?? items.length}
        stats={over.stats ?? { pending_review: items.length }}
        query={QUERY}
        canEdit={over.canEdit ?? true}
      />
    </ToastProvider>,
  );
}

type Call = { method: string; path: string; body: unknown };
function stubApi(extra: Record<string, () => Response> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const path = new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, "");
      const text = await req.clone().text();
      calls.push({ method: req.method, path, body: text ? JSON.parse(text) : undefined });
      const key = `${req.method} ${path.replace(/[0-9a-f-]{36}/, ":id")}`;
      if (extra[key]) return extra[key]();
      if (req.method === "GET" && path.endsWith("/versions")) return Response.json([]);
      return Response.json(item());
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("KnowledgeManager", () => {
  it("lists items with status, source and whether the AI may use them", () => {
    renderManager(
      [
        item(),
        item({
          id: "33333333-3333-4333-8333-333333333333",
          title: "Led a rebuild",
          status: "approved",
        }),
        item({
          id: "44444444-4444-4444-8444-444444444444",
          title: "Old pricing",
          status: "approved",
          is_enabled: false,
        }),
      ],
      { stats: { pending_review: 1, approved: 2 } },
    );
    const rows = screen.getAllByRole("row").slice(1);
    expect(within(rows[0]!).getByText("Needs review")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Not approved")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("In use")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("Off")).toBeInTheDocument();
    expect(screen.getByText("1 item waiting for review")).toBeInTheDocument();
  });

  it("renders stored markup and unsafe links as inert text", async () => {
    const user = userEvent.setup();
    stubApi();
    renderManager([
      item({
        title: '<img src=x onerror="alert(1)">',
        source_ref: "javascript:alert(1)",
      }),
    ]);
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Review:/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("javascript:alert(1)").closest("a")).toBeNull();
  });

  it("links a public source safely", async () => {
    const user = userEvent.setup();
    stubApi();
    renderManager([item({ source_ref: "https://example.com/case" })]);
    await user.click(screen.getByRole("button", { name: /Review:/ }));
    const link = await screen.findByRole("link", { name: "https://example.com/case" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("flips the enabled switch with a PATCH that carries no content", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderManager([item({ status: "approved" })]);
    await user.click(screen.getByRole("switch", { name: /Switch off: Ships weekly/ }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ method: "PATCH", body: { is_enabled: false } });
  });

  it("approves exactly the version on screen", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderManager([item({ version: 4 })]);
    await user.click(screen.getByRole("button", { name: /Review:/ }));
    await user.click(await screen.findByRole("button", { name: "Approve this version" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls.find((c) => c.path.endsWith("/approve"))).toMatchObject({
      method: "POST",
      body: { version: 4 },
    });
  });

  it("will not approve while there are unsaved edits, and saves with expected_version", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderManager([item({ version: 2 })]);
    await user.click(screen.getByRole("button", { name: /Review:/ }));
    const title = await screen.findByLabelText(/Title/);
    await user.type(title, " v2");
    expect(screen.getByRole("button", { name: "Approve this version" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({
      title: "Ships weekly v2",
      expected_version: 2,
    });
  });

  it("shows a stale-version conflict without closing the drawer", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /knowledge/:id/approve": () =>
        Response.json(
          { error: { code: "stale_version", message: "This item changed after you opened it." } },
          { status: 409 },
        ),
    });
    renderManager([item()]);
    await user.click(screen.getByRole("button", { name: /Review:/ }));
    await user.click(await screen.findByRole("button", { name: "Approve this version" }));
    expect(await screen.findByText("This item changed")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("asks before deleting", async () => {
    const user = userEvent.setup();
    const calls = stubApi({ "DELETE /knowledge/:id": () => new Response(null, { status: 204 }) });
    renderManager([item()]);
    await user.click(screen.getByRole("button", { name: /Review:/ }));
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    const confirm = await screen.findByRole("dialog", { name: "Delete this item?" });
    await user.click(within(confirm).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("shows field errors from the API on add (e.g. an invalid source link)", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /knowledge": () =>
        Response.json(
          {
            error: {
              code: "validation_error",
              message: "Invalid",
              fields: { source_ref: "Use a public http(s) link or a plain label." },
            },
          },
          { status: 422 },
        ),
    });
    renderManager([item()]);
    await user.click(screen.getByRole("button", { name: "Add item" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText(/Title/), "T");
    await user.type(within(dialog).getByLabelText(/What is true/), "Some content");
    await user.type(within(dialog).getByLabelText(/Where it comes from/), "ftp://x");
    await user.click(within(dialog).getByRole("button", { name: "Add as draft" }));
    expect(
      await within(dialog).findByText("Use a public http(s) link or a plain label."),
    ).toBeInTheDocument();
  });

  it("is read-only for members", () => {
    renderManager([item({ status: "approved" })], { canEdit: false });
    expect(screen.queryByRole("button", { name: "Add item" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Import text" })).toBeNull();
    expect(screen.getByRole("switch")).toBeDisabled();
    expect(screen.getByText("View only")).toBeInTheDocument();
  });

  it("explains an empty library and an empty filter result differently", () => {
    const { unmount } = renderManager([], { stats: {} });
    expect(screen.getByText("No knowledge yet")).toBeInTheDocument();
    unmount();
    render(
      <ToastProvider>
        <KnowledgeManager
          workspaceId={WS}
          items={[]}
          total={0}
          stats={{}}
          query={{ ...QUERY, q: "zzz" }}
          canEdit
        />
      </ToastProvider>,
    );
    expect(screen.getByText("Nothing matches those filters")).toBeInTheDocument();
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = renderManager([
      item(),
      item({ id: "3".repeat(8) + "-3333-4333-8333-333333333333", status: "approved" }),
    ]);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
