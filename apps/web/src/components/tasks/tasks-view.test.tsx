import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type * as ApiClient from "@/lib/api-client";
import { parseTaskQuery } from "./task-list-model";
import type { TaskOut, TaskSummary } from "./task-model";
import { TasksView } from "./tasks-view";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
const NOW = "2026-10-12T12:00:00Z";
const SUMMARY: TaskSummary = {
  timezone: "Europe/Berlin",
  overdue: 3,
  today: 2,
  upcoming: 5,
  undated: 1,
  done: 7,
};

function task(over: Partial<TaskOut> = {}): TaskOut {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    title: "Send quote",
    description: null,
    status: "open",
    priority: "normal",
    due_at: "2026-10-12T15:00:00Z",
    due_timezone: "Asia/Tokyo",
    remind_at: null,
    completed_at: null,
    assignee_user_id: null,
    lead: null,
    opportunity: null,
    conversation_id: null,
    created_by: "user",
    is_sample: false,
    is_overdue: false,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-01T00:00:00Z",
    ...over,
  };
}
const SECOND = "33333333-3333-4333-8333-333333333333";
const two = () => [task(), task({ id: SECOND, title: "Call Sam" })];

function renderView(
  tasks: TaskOut[],
  over: {
    canEdit?: boolean;
    total?: number;
    params?: Record<string, string>;
    summary?: Partial<TaskSummary>;
  } = {},
) {
  return render(
    <ToastProvider>
      <TasksView
        workspaceId={WS}
        tasks={tasks}
        total={over.total ?? tasks.length}
        summary={{ ...SUMMARY, ...over.summary }}
        query={parseTaskQuery(over.params ?? {})}
        now={NOW}
        canEdit={over.canEdit ?? true}
      />
    </ToastProvider>,
  );
}

type Call = { method: string; path: string; body: unknown };
function stubApi(
  respond: (req: Request) => Response | Promise<Response> = () => Response.json(task()),
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
const failure = (status: number, message = "Nope.") =>
  Response.json({ error: { code: "boom", message, fields: {} } }, { status });

async function noViolations(container: HTMLElement) {
  const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
  expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("tabs", () => {
  it("are links with counts as text and aria-current on the active view", () => {
    renderView([task()], { params: { view: "overdue", tz: "UTC", q: "quote" } });
    const nav = screen.getByRole("navigation", { name: "Task views" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "Overdue (3)",
      "Today (2)",
      "Upcoming (5)",
      "No date (1)",
      "Done (7)",
    ]);
    expect(within(nav).getByRole("link", { name: "Overdue (3)" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Today (2)" })).not.toHaveAttribute(
      "aria-current",
    );
    expect(within(nav).getByRole("link", { name: "Today (2)" })).toHaveAttribute(
      "href",
      "/tasks?tz=UTC&q=quote",
    );
    expect(within(nav).getByRole("link", { name: "Done (7)" })).toHaveAttribute(
      "href",
      "/tasks?view=done&tz=UTC&q=quote",
    );
  });

  it("marks Today as current when no view is given", () => {
    renderView([task()]);
    expect(screen.getByRole("link", { name: "Today (2)" })).toHaveAttribute("aria-current", "page");
  });
});

describe("list", () => {
  it("shows the due time in the task's own zone, links, badges and a snippet", () => {
    renderView([
      task({
        priority: "high",
        description: "Include the revised scope.",
        is_sample: true,
        lead: { id: "L-1", title: "Fabrikam rebuild" },
        opportunity: { id: "O-1", title: "Fabrikam retainer" },
        remind_at: "2026-10-12T14:00:00Z",
      }),
    ]);
    const row = within(screen.getByRole("heading", { level: 3 }).closest("li")!);
    expect(row.getByRole("heading", { level: 3, name: "Send quote" })).toBeInTheDocument();
    expect(row.getByText("High priority")).toBeInTheDocument();
    expect(row.getByText("Sample")).toBeInTheDocument();
    expect(row.getByText("Include the revised scope.")).toBeInTheDocument();
    // 15:00 UTC is midnight of the next day in Tokyo.
    expect(row.getByText("2026-10-13 00:00 (Asia/Tokyo)")).toBeInTheDocument();
    expect(row.getByText("2026-10-12 23:00 (Asia/Tokyo)")).toBeInTheDocument();
    expect(row.getByRole("link", { name: "Fabrikam rebuild" })).toHaveAttribute(
      "href",
      "/leads/L-1",
    );
    expect(row.getByRole("link", { name: "Fabrikam retainer" })).toHaveAttribute(
      "href",
      "/pipeline/O-1",
    );
  });

  it("says how long overdue from the server's now", () => {
    renderView(
      [
        task({ id: "a", title: "Two days", is_overdue: true, due_at: "2026-10-10T12:00:00Z" }),
        task({ id: "b", title: "Three hours", is_overdue: true, due_at: "2026-10-12T09:00:00Z" }),
        task({ id: "c", title: "Fine", is_overdue: false }),
      ],
      { params: { view: "overdue" } },
    );
    expect(screen.getByText("2 days overdue")).toBeInTheDocument();
    expect(screen.getByText("3 hours overdue")).toBeInTheDocument();
    expect(screen.getAllByText(/overdue$/)).toHaveLength(2);
  });

  it("renders stored markup as inert text", () => {
    renderView([
      task({
        title: '<img src=x onerror="alert(1)">',
        description: "<script>alert(2)</script>",
        lead: { id: "L-1", title: "<b>lead</b>" },
      }),
    ]);
    expect(document.querySelector("img")).toBeNull();
    expect(document.querySelector("script")).toBeNull();
    expect(document.querySelector("b")).toBeNull();
    expect(screen.getByText('<img src=x onerror="alert(1)">')).toBeInTheDocument();
    expect(screen.getByText("<b>lead</b>")).toBeInTheDocument();
  });

  it("paginates with links that keep the filters", () => {
    renderView([task()], { total: 60, params: { page: "2", priority: "high", tz: "UTC" } });
    expect(screen.getByText("Page 2 of 3 · 60 tasks")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Previous" })).toHaveAttribute(
      "href",
      "/tasks?tz=UTC&priority=high",
    );
    expect(screen.getByRole("link", { name: "Next" })).toHaveAttribute(
      "href",
      "/tasks?tz=UTC&priority=high&page=3",
    );
  });

  it("offers a search form that works without JavaScript", () => {
    renderView([task()], {
      params: { view: "upcoming", tz: "UTC", q: "quote", priority: "low", sort: "title" },
    });
    const form = screen.getByRole("search");
    expect(form).toHaveAttribute("method", "get");
    expect(form).toHaveAttribute("action", "/tasks");
    expect(within(form).getByLabelText("Search")).toHaveValue("quote");
    expect(within(form).getByLabelText("Priority")).toHaveValue("low");
    expect(within(form).getByLabelText("Sort by")).toHaveValue("title");
    const hidden = Array.from(form.querySelectorAll("input[type=hidden]")).map(
      (i) => `${i.getAttribute("name")}=${(i as HTMLInputElement).value}`,
    );
    expect(hidden).toEqual(["view=upcoming", "tz=UTC"]);
    expect(within(form).getByRole("link", { name: "Clear filters" })).toHaveAttribute(
      "href",
      "/tasks?view=upcoming&tz=UTC",
    );
  });
});

describe("time zone control", () => {
  it("is a GET form preset to the zone actually used", () => {
    renderView([task()], { params: { view: "overdue", q: "x" } });
    const form = screen.getByRole("form", { name: "Time zone" });
    expect(form).toHaveAttribute("method", "get");
    const select = within(form).getByLabelText("Showing today in");
    expect(select).toHaveAttribute("name", "tz");
    expect(select).toHaveValue("Europe/Berlin");
    expect(screen.getByText("Today means your local day in this time zone.")).toBeInTheDocument();
    const hidden = Array.from(form.querySelectorAll("input[type=hidden]")).map(
      (i) => `${i.getAttribute("name")}=${(i as HTMLInputElement).value}`,
    );
    expect(hidden).toEqual(["view=overdue", "q=x"]);
  });

  it("explains what overdue and today mean", () => {
    renderView([task()]);
    expect(
      screen.getByText(/Overdue means a task is already past its due time/),
    ).toBeInTheDocument();
  });
});

describe("complete", () => {
  it("removes the row at once, sends one request and refreshes", async () => {
    const user = userEvent.setup();
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const calls = stubApi(async () => {
      await gate;
      return Response.json(task({ status: "done" }));
    });
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Complete: Send quote" }));
    // Optimistic: gone while the request is still out.
    expect(screen.queryByRole("heading", { name: "Send quote" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Call Sam" })).toBeInTheDocument();
    expect(refresh).not.toHaveBeenCalled();
    release();
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toEqual([
      {
        method: "POST",
        path: "/tasks/11111111-1111-4111-8111-111111111111/complete",
        body: undefined,
      },
    ]);
    expect(screen.queryByRole("heading", { name: "Send quote" })).toBeNull();
    expect(await screen.findByText("Task completed")).toBeInTheDocument();
  });

  it("puts the row back and shows the error when the request fails", async () => {
    const user = userEvent.setup();
    const calls = stubApi(() => failure(500, "The service is down."));
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Complete: Send quote" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn't complete this task");
    expect(alert).toHaveTextContent("The service is down.");
    const row = screen.getByRole("heading", { name: "Send quote" }).closest("li")!;
    expect(row).toContainElement(alert);
    expect(within(row).getByRole("button", { name: "Complete: Send quote" })).toBeEnabled();
    expect(refresh).not.toHaveBeenCalled();
    expect(calls).toHaveLength(1);
  });

  it("rolls back on a network error too", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Complete: Send quote" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Can't reach the server");
    expect(screen.getByText("Send quote")).toBeInTheDocument();
  });

  it("a double click sends one request", async () => {
    const user = userEvent.setup();
    const calls = stubApi(async () => {
      await new Promise((r) => setTimeout(r, 40));
      return Response.json(task({ status: "done" }));
    });
    renderView(two());
    const button = screen.getByRole("button", { name: "Complete: Send quote" });
    await user.dblClick(button);
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
  });
});

describe("done view", () => {
  it("offers Reopen instead of Complete and sends reopen", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderView([task({ status: "done", completed_at: "2026-10-12T10:00:00Z" })], {
      params: { view: "done" },
    });
    expect(screen.queryByRole("button", { name: /^Complete/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Dismiss/ })).toBeNull();
    expect(screen.getByText("2026-10-12 19:00 (Asia/Tokyo)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Reopen: Send quote" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({
      method: "POST",
      path: "/tasks/11111111-1111-4111-8111-111111111111/reopen",
    });
    expect(screen.queryByRole("heading", { name: "Send quote" })).toBeNull();
  });
});

describe("dismiss", () => {
  it("cancel sends nothing", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Dismiss: Send quote" }));
    const dialog = await screen.findByRole("dialog", { name: "Dismiss this task?" });
    expect(dialog).toHaveTextContent("It stays in your history but leaves your lists.");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(calls).toHaveLength(0);
    expect(screen.getByText("Send quote")).toBeInTheDocument();
  });

  it("confirm dismisses, removes the row and refreshes", async () => {
    const user = userEvent.setup();
    const calls = stubApi();
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Dismiss: Send quote" }));
    const dialog = await screen.findByRole("dialog", { name: "Dismiss this task?" });
    await user.click(within(dialog).getByRole("button", { name: "Dismiss task" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toEqual([
      {
        method: "POST",
        path: "/tasks/11111111-1111-4111-8111-111111111111/dismiss",
        body: undefined,
      },
    ]);
    expect(screen.queryByRole("heading", { name: "Send quote" })).toBeNull();
  });
});

describe("edit, reschedule and new task", () => {
  it("edit opens the task drawer for that task", async () => {
    const user = userEvent.setup();
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Edit: Send quote" }));
    const drawer = await screen.findByRole("dialog", { name: "Edit task" });
    expect(within(drawer).getByLabelText(/What needs doing/)).toHaveValue("Send quote");
  });

  it("New task opens an empty drawer in the summary's zone", async () => {
    const user = userEvent.setup();
    renderView(two());
    await user.click(screen.getByRole("button", { name: "New task" }));
    const drawer = await screen.findByRole("dialog", { name: "New task" });
    expect(within(drawer).getByLabelText(/What needs doing/)).toHaveValue("");
    expect(within(drawer).getByLabelText("Time zone")).toHaveValue("Europe/Berlin");
  });

  it("Reschedule opens the dialog preset to the task's zone", async () => {
    const user = userEvent.setup();
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Reschedule: Send quote" }));
    const dialog = await screen.findByRole("dialog", { name: "Reschedule task" });
    expect(within(dialog).getByLabelText("Time zone")).toHaveValue("Asia/Tokyo");
    expect(within(dialog).getByLabelText("New due date and time")).toHaveValue("2026-10-13T00:00");
  });
});

describe("members", () => {
  it("see the list read-only", () => {
    renderView(two(), { canEdit: false });
    expect(screen.getByText("View only")).toBeInTheDocument();
    expect(screen.getByText("Send quote")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Complete|Reschedule|Edit|Dismiss|New task/ }),
    ).toBeNull();
  });
});

describe("empty states", () => {
  it.each([
    ["today", "Nothing due today"],
    ["overdue", "You're all caught up"],
    ["upcoming", "Nothing coming up"],
    ["undated", "No tasks without a date"],
    ["done", "No finished tasks yet"],
  ])("%s view", (view, title) => {
    renderView([], { params: { view } });
    expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
  });

  it("overall empty state offers New task to owners only", () => {
    const zero = { overdue: 0, today: 0, upcoming: 0, undated: 0, done: 0 };
    const { unmount } = renderView([], { summary: zero });
    expect(screen.getByRole("heading", { name: "No tasks yet" })).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "New task" }).length).toBeGreaterThan(0);
    unmount();
    renderView([], { summary: zero, canEdit: false });
    expect(screen.getByRole("heading", { name: "No tasks yet" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New task" })).toBeNull();
  });

  it("explains filters that match nothing", () => {
    renderView([], { params: { q: "zzz" } });
    expect(
      screen.getByRole("heading", { name: "No tasks match those filters" }),
    ).toBeInTheDocument();
  });
});

describe("accessibility", () => {
  it.each(["overdue", "today", "upcoming", "undated", "done"])(
    "%s view has no violations",
    async (view) => {
      const { container } = renderView(
        [
          task({
            is_overdue: view === "overdue",
            due_at: view === "overdue" ? "2026-10-10T12:00:00Z" : "2026-10-12T15:00:00Z",
            status: view === "done" ? "done" : "open",
            completed_at: view === "done" ? "2026-10-12T10:00:00Z" : null,
            lead: { id: "L-1", title: "Lead" },
            opportunity: { id: "O-1", title: "Deal" },
            is_sample: true,
          }),
          task({ id: SECOND, title: "No date", due_at: null, due_timezone: null }),
        ],
        { params: { view }, total: 60 },
      );
      await noViolations(container);
    },
  );

  it("empty state has no violations", async () => {
    const { container } = renderView([], { params: { view: "overdue" } });
    await noViolations(container);
  });

  it("is clean with the dismiss dialog, the drawers and the reschedule dialog open", async () => {
    const user = userEvent.setup();
    renderView(two());
    await user.click(screen.getByRole("button", { name: "Dismiss: Send quote" }));
    await screen.findByRole("dialog", { name: "Dismiss this task?" });
    await noViolations(document.body);
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "Reschedule: Send quote" }));
    await screen.findByRole("dialog", { name: "Reschedule task" });
    await noViolations(document.body);
    await user.click(screen.getByRole("button", { name: "Close" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "New task" }));
    await screen.findByRole("dialog", { name: "New task" });
    await noViolations(document.body);
  });
});
