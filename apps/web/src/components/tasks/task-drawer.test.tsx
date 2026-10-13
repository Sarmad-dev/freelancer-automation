import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type * as ApiClient from "@/lib/api-client";
import { TaskDrawer } from "./task-drawer";
import type { TaskOut } from "./task-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const TASK: TaskOut = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Send quote",
  description: null,
  status: "open",
  priority: "normal",
  due_at: "2026-07-01T07:00:00Z",
  due_timezone: "Europe/Berlin",
  remind_at: null,
  completed_at: null,
  assignee_user_id: null,
  lead: null,
  opportunity: null,
  conversation_id: null,
  created_by: "user",
  is_sample: false,
  is_overdue: false,
  created_at: "2026-06-01T00:00:00Z",
  updated_at: "2026-06-01T00:00:00Z",
};

type Call = { method: string; path: string; body: unknown };
function stub(
  respond: (req: Request) => Response | Promise<Response> = () =>
    Response.json(TASK, { status: 201 }),
) {
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
      return respond(req);
    }),
  );
  return calls;
}

function open(props: Partial<React.ComponentProps<typeof TaskDrawer>> = {}) {
  const onClose = vi.fn();
  const onSaved = vi.fn();
  render(
    <ToastProvider>
      <TaskDrawer
        workspaceId={WS}
        defaultTimezone="Europe/Berlin"
        onClose={onClose}
        onSaved={onSaved}
        {...props}
      />
    </ToastProvider>,
  );
  return { onClose, onSaved };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("TaskDrawer (create)", () => {
  it("sends wall-clock time with its zone, the links and an idempotency key", async () => {
    const user = userEvent.setup();
    const calls = stub();
    const { onClose, onSaved } = open({
      links: { lead_id: "L1" },
      linkLabel: "Fabrikam website rebuild",
    });
    expect(screen.getByText("For: Fabrikam website rebuild")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/What needs doing/), "Call Sam");
    await user.type(screen.getByLabelText("Due"), "2026-07-01T09:00");
    await user.selectOptions(screen.getByLabelText("Reminder"), "60");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "POST", path: "/tasks" });
    expect(calls[0]!.body).toMatchObject({
      title: "Call Sam",
      priority: "normal",
      due_at: "2026-07-01T09:00",
      due_timezone: "Europe/Berlin",
      remind_at: "2026-07-01T08:00",
      lead_id: "L1",
    });
    expect((calls[0]!.body as { idempotency_key: string }).idempotency_key).toMatch(/^task-.{8,}/);
    expect(refresh).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("a double click sends one request", async () => {
    const user = userEvent.setup();
    const calls = stub(async () => {
      await new Promise((r) => setTimeout(r, 50));
      return Response.json(TASK, { status: 201 });
    });
    open();
    await user.type(screen.getByLabelText(/What needs doing/), "Call Sam");
    const button = screen.getByRole("button", { name: "Add task" });
    await user.dblClick(button);
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
  });

  it("a retry after a failure reuses the same idempotency key", async () => {
    const user = userEvent.setup();
    let fail = true;
    const calls = stub(() =>
      fail
        ? Response.json(
            { error: { code: "internal", message: "Temporary problem." } },
            { status: 503 },
          )
        : Response.json(TASK, { status: 200 }),
    );
    open();
    await user.type(screen.getByLabelText(/What needs doing/), "Call Sam");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    expect(await screen.findByText("Temporary problem.")).toBeInTheDocument();
    fail = false;
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    const keys = calls.map((c) => (c.body as { idempotency_key: string }).idempotency_key);
    expect(keys).toHaveLength(2);
    expect(keys[0]).toBe(keys[1]);
  });

  it("checks the form before sending anything", async () => {
    const user = userEvent.setup();
    const calls = stub();
    open();
    await user.click(screen.getByRole("button", { name: "Add task" }));
    expect(await screen.findByText("Enter what needs doing.")).toBeInTheDocument();
    await user.type(screen.getByLabelText(/What needs doing/), "x");
    await user.selectOptions(screen.getByLabelText("Reminder"), "60");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    expect(await screen.findByText(/Set a due date and time/)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it("shows the server's message when the chosen time doesn't exist", async () => {
    const user = userEvent.setup();
    stub(() =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "Some fields are invalid.",
            fields: { due_at: "That time doesn't exist in this time zone (the clocks skip it)." },
          },
        },
        { status: 422 },
      ),
    );
    open();
    await user.type(screen.getByLabelText(/What needs doing/), "x");
    await user.type(screen.getByLabelText("Due"), "2026-03-29T02:30");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    expect(await screen.findByText(/clocks skip it/)).toBeInTheDocument();
    expect(screen.getByLabelText("Due")).toHaveAttribute("aria-invalid", "true");
    expect(refresh).not.toHaveBeenCalled();
  });

  it("keeps markup in the title as text", async () => {
    const user = userEvent.setup();
    const calls = stub();
    open();
    await user.type(screen.getByLabelText(/What needs doing/), "<img src=x onerror=alert(1)>");
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect((calls[0]!.body as { title: string }).title).toBe("<img src=x onerror=alert(1)>");
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("TaskDrawer (edit)", () => {
  it("sends only what changed and is disabled until something does", async () => {
    const user = userEvent.setup();
    const calls = stub(() => Response.json(TASK));
    open({ task: TASK });
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(screen.getByLabelText("Due")).toHaveValue("2026-07-01T09:00");
    expect(screen.getByLabelText("Time zone")).toHaveValue("Europe/Berlin");
    await user.selectOptions(screen.getByLabelText("Priority"), "high");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({
      method: "PATCH",
      path: `/tasks/${TASK.id}`,
      body: { priority: "high" },
    });
  });
});

describe("TaskDrawer accessibility", () => {
  it("has no detectable violations", async () => {
    stub();
    open({ linkLabel: "A lead" });
    const dialog = await screen.findByRole("dialog");
    const results = await axe.run(dialog, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations).toEqual([]);
  });
});
