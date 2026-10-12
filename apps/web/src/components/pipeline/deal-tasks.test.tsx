import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import type * as ApiClient from "@/lib/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type { TaskOut } from "@/components/tasks/task-model";
import { DealTasks } from "./deal-tasks";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const DEAL = { id: "11111111-1111-4111-8111-111111111111", title: "Acme website rebuild" };
const T1 = "99999999-9999-4999-8999-999999999991";
const T2 = "99999999-9999-4999-8999-999999999992";
const T3 = "99999999-9999-4999-8999-999999999993";

function task(over: Partial<TaskOut> = {}): TaskOut {
  return {
    id: T1,
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
    opportunity: { id: DEAL.id, title: DEAL.title },
    conversation_id: null,
    created_by: "user",
    is_sample: false,
    is_overdue: false,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...over,
  };
}

const DONE = task({
  id: T3,
  title: "Kick-off call",
  status: "done",
  completed_at: "2026-06-20T10:00:00Z",
});

type Over = Partial<React.ComponentProps<typeof DealTasks>>;
function renderTasks(over: Over = {}) {
  return render(
    <ToastProvider>
      <DealTasks
        workspaceId={WS}
        deal={DEAL}
        open={{
          items: [
            task(),
            task({
              id: T2,
              title: "Chase invoice",
              priority: "high",
              is_overdue: true,
              due_at: "2026-10-01T09:00:00Z",
              due_timezone: "UTC",
            }),
          ],
          total: 2,
        }}
        done={{ items: [DONE], total: 1 }}
        canEdit
        {...over}
      />
    </ToastProvider>,
  );
}

type Call = { method: string; path: string; body: unknown };
function stubApi(respond: (call: Call) => Response = () => Response.json(task())) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (req: Request) => {
      const text = await req.clone().text();
      const call = {
        method: req.method,
        path: new URL(req.url).pathname.replace(/^\/api\/v1\/workspaces\/[^/]+/, ""),
        body: text ? JSON.parse(text) : undefined,
      };
      calls.push(call);
      return respond(call);
    }),
  );
  return calls;
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("DealTasks", () => {
  it("lists open tasks with priority and due time, flagging overdue ones in words", () => {
    renderTasks();
    expect(screen.getByRole("heading", { level: 2, name: "Tasks" })).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "Open tasks" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText("Send quote")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Normal priority")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Due 2026-07-01 09:00 (Europe/Berlin)")).toBeInTheDocument();
    expect(within(rows[0]!).queryByText("Overdue")).not.toBeInTheDocument();
    expect(within(rows[1]!).getByText("High priority")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Overdue")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All tasks" })).toHaveAttribute("href", "/tasks");
  });

  it("shows tasks without a due date plainly", () => {
    renderTasks({ open: { items: [task({ due_at: null, due_timezone: null })], total: 1 } });
    expect(screen.getByText("No due date")).toBeInTheDocument();
  });

  it("has an empty state", () => {
    renderTasks({ open: { items: [], total: 0 }, done: { items: [], total: 0 } });
    expect(screen.getByText("No tasks for this deal yet.")).toBeInTheDocument();
  });

  it("keeps recently done tasks collapsed until asked", async () => {
    const user = userEvent.setup();
    renderTasks();
    const toggle = screen.getByRole("button", { name: "Recently done (1)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Kick-off call")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Kick-off call")).toBeInTheDocument();
    expect(screen.getByText("Done 2026-06-20")).toBeInTheDocument();
  });

  it("completes a task, moves it to done and refreshes", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() =>
      Response.json(task({ status: "done", completed_at: "2026-10-12T10:00:00Z" })),
    );
    renderTasks();
    await user.click(screen.getByRole("button", { name: "Complete task: Send quote" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toEqual([{ method: "POST", path: `/tasks/${T1}/complete`, body: undefined }]);
    expect(
      within(screen.getByRole("list", { name: "Open tasks" })).queryByText("Send quote"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recently done (2)" })).toBeInTheDocument();
  });

  it("keeps the task and shows the message when completing fails", async () => {
    const user = userEvent.setup();
    stubApi(() =>
      Response.json(
        { error: { code: "conflict", message: "Task already changed." } },
        { status: 409 },
      ),
    );
    renderTasks();
    await user.click(screen.getByRole("button", { name: "Complete task: Send quote" }));
    expect(await screen.findByText("Task already changed.")).toBeInTheDocument();
    expect(screen.getByText("Send quote")).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("dismisses only after confirming", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderTasks();
    await user.click(screen.getByRole("button", { name: "Dismiss task: Send quote" }));
    const dialog = await screen.findByRole("dialog", { name: "Dismiss this task?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Dismiss task: Send quote" }));
    await user.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Dismiss task" }),
    );
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "POST", path: `/tasks/${T1}/dismiss` });
    await waitFor(() =>
      expect(
        within(screen.getByRole("list", { name: "Open tasks" })).queryByText("Send quote"),
      ).not.toBeInTheDocument(),
    );
  });

  it("reopens a done task", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(task({ id: T3, title: "Kick-off call" })));
    renderTasks();
    await user.click(screen.getByRole("button", { name: "Recently done (1)" }));
    await user.click(screen.getByRole("button", { name: "Reopen task: Kick-off call" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "POST", path: `/tasks/${T3}/reopen` });
    expect(
      await within(screen.getByRole("list", { name: "Open tasks" })).findByText("Kick-off call"),
    ).toBeInTheDocument();
  });

  it("opens the task drawer linked to this deal", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => Response.json(task({ title: "Call back" }), { status: 201 }));
    renderTasks({ open: { items: [], total: 0 }, done: { items: [], total: 0 } });
    await user.click(screen.getByRole("button", { name: "Add task" }));
    const dialog = await screen.findByRole("dialog", { name: "New task" });
    expect(within(dialog).getByText("For: Acme website rebuild")).toBeInTheDocument();
    await user.type(within(dialog).getByLabelText(/What needs doing/), "Call back");
    await user.click(within(dialog).getByRole("button", { name: "Add task" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: "/tasks",
      body: { title: "Call back", opportunity_id: DEAL.id },
    });
    expect(refresh).toHaveBeenCalled();
  });

  it("opens the drawer on the task being edited", async () => {
    const user = userEvent.setup();
    renderTasks();
    await user.click(screen.getByRole("button", { name: "Edit task: Send quote" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit task" });
    expect(within(dialog).getByLabelText(/What needs doing/)).toHaveValue("Send quote");
  });

  it("is read-only for members", () => {
    renderTasks({ canEdit: false });
    expect(screen.getByText("Send quote")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add task|Complete|Edit|Dismiss/ })).toBeNull();
    expect(screen.getByRole("link", { name: "All tasks" })).toBeInTheDocument();
  });

  it("says when only the first page of tasks is shown", () => {
    renderTasks({ open: { items: [task()], total: 80 } });
    expect(screen.getByText(/Showing 1 of 80 open tasks/)).toBeInTheDocument();
  });

  it("renders hostile titles as text", () => {
    renderTasks({ open: { items: [task({ title: '<img src=x onerror="alert(1)">' })], total: 1 } });
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
  });

  it("has no accessibility violations, collapsed, expanded and with the drawer open", async () => {
    const user = userEvent.setup();
    const { container } = renderTasks();
    const opts = { rules: { "color-contrast": { enabled: false }, region: { enabled: false } } };
    expect((await axe.run(container, opts)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Recently done (1)" }));
    expect((await axe.run(container, opts)).violations).toEqual([]);
    await user.click(screen.getByRole("button", { name: "Add task" }));
    await screen.findByRole("dialog", { name: "New task" });
    expect((await axe.run(document.body, opts)).violations).toEqual([]);
  });
});
