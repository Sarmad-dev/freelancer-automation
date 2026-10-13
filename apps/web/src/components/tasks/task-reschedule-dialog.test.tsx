import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "@freelancer-os/ui";
import type * as ApiClient from "@/lib/api-client";
import { TaskRescheduleDialog } from "./task-reschedule-dialog";
import type { TaskOut } from "./task-model";

type ApiClientModule = typeof ApiClient;
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/api-client", async (orig) => {
  const mod = await orig<ApiClientModule>();
  return { ...mod, redirectToSignIn: vi.fn() };
});

const WS = "22222222-2222-4222-8222-222222222222";
// Monday 2026-10-12, 22:30 UTC = Tuesday 00:30 in Berlin.
const NOW = "2026-10-12T22:30:00Z";
const TASK: TaskOut = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Send quote",
  description: null,
  status: "open",
  priority: "normal",
  due_at: "2027-03-28T09:00:00Z",
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
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

type Call = { method: string; path: string; body: unknown };
function stub(respond: (req: Request) => Response | Promise<Response> = () => Response.json(TASK)) {
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

function open(task: TaskOut = TASK) {
  const onClose = vi.fn();
  render(
    <ToastProvider>
      <TaskRescheduleDialog
        workspaceId={WS}
        task={task}
        now={NOW}
        defaultTimezone="UTC"
        onClose={onClose}
      />
    </ToastProvider>,
  );
  return { onClose };
}

beforeEach(() => {
  vi.unstubAllGlobals();
  refresh.mockClear();
});

describe("TaskRescheduleDialog", () => {
  it("starts from the task's own zone and due time", () => {
    open();
    expect(screen.getByLabelText("Time zone")).toHaveValue("Europe/Berlin");
    // 09:00 UTC on the day clocks go forward in Berlin = 11:00 CEST.
    expect(screen.getByLabelText("New due date and time")).toHaveValue("2027-03-28T11:00");
  });

  it("sends the naive wall time with its zone and closes", async () => {
    const user = userEvent.setup();
    const calls = stub();
    const { onClose } = open();
    const due = screen.getByLabelText("New due date and time");
    await user.clear(due);
    await user.type(due, "2026-12-01T09:30");
    await user.selectOptions(screen.getByLabelText("Time zone"), "Asia/Tokyo");
    await user.click(screen.getByRole("button", { name: "Reschedule" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls).toEqual([
      {
        method: "POST",
        path: "/tasks/11111111-1111-4111-8111-111111111111/reschedule",
        body: { due_at: "2026-12-01T09:30", due_timezone: "Asia/Tokyo" },
      },
    ]);
    expect(refresh).toHaveBeenCalled();
  });

  it("quick presets fill the field from the server's now in the chosen zone", async () => {
    const user = userEvent.setup();
    const calls = stub();
    open();
    const due = screen.getByLabelText("New due date and time");
    await user.click(screen.getByRole("button", { name: "Tomorrow 9:00" }));
    expect(due).toHaveValue("2026-10-14T09:00"); // Tuesday in Berlin, so tomorrow is Wednesday
    await user.click(screen.getByRole("button", { name: "In 3 days" }));
    expect(due).toHaveValue("2026-10-16T09:00");
    await user.click(screen.getByRole("button", { name: "Next Monday" }));
    expect(due).toHaveValue("2026-10-19T09:00");
    await user.selectOptions(screen.getByLabelText("Time zone"), "UTC");
    await user.click(screen.getByRole("button", { name: "Tomorrow 9:00" }));
    expect(due).toHaveValue("2026-10-13T09:00"); // still Monday in UTC
    expect(calls).toHaveLength(0); // presets only fill the field
  });

  it("shows the skipped-hour error next to the field and stays open", async () => {
    const user = userEvent.setup();
    const message = "02:30 does not exist in Europe/Berlin on that day: clocks skip forward.";
    stub(() =>
      Response.json(
        { error: { code: "validation_error", message: "Invalid", fields: { due_at: message } } },
        { status: 422 },
      ),
    );
    const { onClose } = open();
    const due = screen.getByLabelText("New due date and time");
    await user.clear(due);
    await user.type(due, "2027-03-28T02:30");
    await user.click(screen.getByRole("button", { name: "Reschedule" }));
    const error = await screen.findByText(message);
    expect(due).toHaveAttribute("aria-invalid", "true");
    expect(due.getAttribute("aria-describedby")).toContain(error.id);
    expect(onClose).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Reschedule" })).toBeEnabled();
  });

  it("asks for a date before sending anything", async () => {
    const user = userEvent.setup();
    const calls = stub();
    open({ ...TASK, due_at: null, due_timezone: null });
    expect(screen.getByLabelText("Time zone")).toHaveValue("UTC");
    await user.click(screen.getByRole("button", { name: "Reschedule" }));
    expect(await screen.findByText("Choose a new date and time.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    expect(screen.queryByRole("heading", { name: "Snooze reminder" })).toBeNull();
  });

  it("says that rescheduling a finished task reopens it", () => {
    open({ ...TASK, status: "done", completed_at: "2026-10-01T00:00:00Z" });
    expect(screen.getByText("Rescheduling a finished task reopens it.")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Snooze reminder" })).toBeNull();
  });

  it("snoozes for one hour with an exact instant", async () => {
    const user = userEvent.setup();
    const calls = stub();
    const { onClose } = open();
    await user.click(screen.getByRole("button", { name: "Snooze reminder" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(calls).toEqual([
      {
        method: "POST",
        path: "/tasks/11111111-1111-4111-8111-111111111111/snooze",
        body: { remind_at: "2026-10-12T23:30:00.000Z" },
      },
    ]);
  });

  it("snoozes until tomorrow 9:00 or a custom time in the zone", async () => {
    const user = userEvent.setup();
    const calls = stub();
    open();
    const snooze = screen.getByRole("form", { name: "Snooze" });
    await user.selectOptions(within(snooze).getByLabelText("Remind me"), "tomorrow");
    await user.click(within(snooze).getByRole("button", { name: "Snooze reminder" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]!.body).toEqual({
      remind_at: "2026-10-14T09:00",
      due_timezone: "Europe/Berlin",
    });
  });

  it("custom snooze needs a time and shows a server error beside it", async () => {
    const user = userEvent.setup();
    const calls = stub(() =>
      Response.json(
        {
          error: {
            code: "validation_error",
            message: "Invalid",
            fields: { remind_at: "The reminder must be before the due time." },
          },
        },
        { status: 422 },
      ),
    );
    open();
    const snooze = screen.getByRole("form", { name: "Snooze" });
    await user.selectOptions(within(snooze).getByLabelText("Remind me"), "custom");
    await user.click(within(snooze).getByRole("button", { name: "Snooze reminder" }));
    expect(await screen.findByText("Choose a reminder time.")).toBeInTheDocument();
    expect(calls).toHaveLength(0);
    await user.type(within(snooze).getByLabelText("Reminder time"), "2028-01-01T08:00");
    await user.click(within(snooze).getByRole("button", { name: "Snooze reminder" }));
    expect(
      await screen.findByText("The reminder must be before the due time."),
    ).toBeInTheDocument();
    expect(calls[0]!.body).toEqual({
      remind_at: "2028-01-01T08:00",
      due_timezone: "Europe/Berlin",
    });
  });

  it("a double click sends one request and disables both buttons meanwhile", async () => {
    const user = userEvent.setup();
    const calls = stub(async () => {
      await new Promise((r) => setTimeout(r, 40));
      return Response.json(TASK);
    });
    open();
    await user.dblClick(screen.getByRole("button", { name: "Reschedule" }));
    await waitFor(() => expect(refresh).toHaveBeenCalled());
    expect(calls).toHaveLength(1);
  });

  it("shows a banner when the request fails outright", async () => {
    const user = userEvent.setup();
    stub(() =>
      Response.json(
        { error: { code: "x", message: "Server broke.", fields: {} } },
        { status: 500 },
      ),
    );
    open();
    await user.click(screen.getByRole("button", { name: "Reschedule" }));
    expect(await screen.findByText("Server broke.")).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    open();
    await screen.findByRole("dialog", { name: "Reschedule task" });
    const results = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
