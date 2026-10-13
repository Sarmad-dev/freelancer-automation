import { describe, expect, it } from "vitest";
import {
  buildTaskCreate,
  diffTask,
  emptyTaskForm,
  formFromTask,
  formatDue,
  minusMinutes,
  reminderPreset,
  timeZoneOptions,
  toLocalInput,
  validateTaskForm,
  type TaskOut,
} from "./task-model";

const TASK: TaskOut = {
  id: "11111111-1111-4111-8111-111111111111",
  title: "Send quote",
  description: null,
  status: "open",
  priority: "normal",
  due_at: "2026-07-01T07:00:00Z",
  due_timezone: "Europe/Berlin",
  remind_at: "2026-07-01T06:00:00Z",
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

describe("time formatting", () => {
  it("shows the wall-clock time in the task's own zone", () => {
    expect(formatDue("2026-07-01T07:00:00Z", "Europe/Berlin")).toBe(
      "2026-07-01 09:00 (Europe/Berlin)",
    );
    expect(formatDue("2026-01-01T08:00:00Z", "Europe/Berlin")).toBe(
      "2026-01-01 09:00 (Europe/Berlin)",
    );
    expect(formatDue("2026-07-01T07:00:00Z", null)).toBe("2026-07-01 07:00 (UTC)");
    expect(formatDue("2026-07-01T00:00:00Z", "Asia/Tokyo")).toBe("2026-07-01 09:00 (Asia/Tokyo)");
  });

  it("never throws on bad input", () => {
    expect(formatDue("nonsense", "Europe/Berlin")).toBe("");
    expect(formatDue(null, "UTC")).toBe("");
    expect(formatDue("2026-07-01T07:00:00Z", "Not/AZone")).toBe("");
    expect(toLocalInput("2026-07-01T07:00:00Z", "Not/AZone")).toBe("");
  });

  it("reads midnight as 00:00, not 24:00", () => {
    expect(toLocalInput("2026-06-30T22:00:00Z", "Europe/Berlin")).toBe("2026-07-01T00:00");
  });

  it("round-trips an instant through a datetime-local value", () => {
    expect(toLocalInput("2026-07-01T07:00:00Z", "Europe/Berlin")).toBe("2026-07-01T09:00");
  });
});

describe("reminders", () => {
  it("subtracts wall-clock minutes, crossing midnight and month ends", () => {
    expect(minusMinutes("2026-07-01T09:00", 60)).toBe("2026-07-01T08:00");
    expect(minusMinutes("2026-07-01T00:30", 60)).toBe("2026-06-30T23:30");
    expect(minusMinutes("2026-03-01T09:00", 1440)).toBe("2026-02-28T09:00");
    expect(minusMinutes("garbage", 5)).toBe("");
  });

  it("recognises the preset a stored reminder came from", () => {
    expect(reminderPreset("2026-07-01T09:00", "2026-07-01T08:00")).toBe("60");
    expect(reminderPreset("2026-07-01T09:00", "2026-07-01T09:00")).toBe("0");
    expect(reminderPreset("2026-07-01T09:00", "2026-07-01T08:17")).toBe("");
    expect(reminderPreset("", "2026-07-01T08:00")).toBe("");
  });
});

describe("the form", () => {
  it("starts empty in the given zone", () => {
    expect(emptyTaskForm("Asia/Tokyo")).toMatchObject({
      title: "",
      priority: "normal",
      due: "",
      timezone: "Asia/Tokyo",
    });
  });

  it("is filled from a task in the task's zone", () => {
    expect(formFromTask(TASK, "UTC")).toMatchObject({
      title: "Send quote",
      due: "2026-07-01T09:00",
      reminder: "60",
      timezone: "Europe/Berlin",
    });
  });

  it("needs a title, and a due time for a reminder", () => {
    expect(validateTaskForm({ ...emptyTaskForm("UTC"), title: "  " }).title).toBeTruthy();
    expect(
      validateTaskForm({ ...emptyTaskForm("UTC"), title: "x", reminder: "60" }).reminder,
    ).toBeTruthy();
    expect(validateTaskForm({ ...emptyTaskForm("UTC"), title: "x" })).toEqual({});
  });

  it("sends wall-clock times with their zone and only what was filled in", () => {
    const form = {
      ...emptyTaskForm("Europe/Berlin"),
      title: " Call ",
      due: "2026-07-01T09:00",
      reminder: "15",
    };
    expect(buildTaskCreate(form, { lead_id: "L" }, "task-key-1234")).toEqual({
      title: "Call",
      priority: "normal",
      idempotency_key: "task-key-1234",
      due_at: "2026-07-01T09:00",
      due_timezone: "Europe/Berlin",
      remind_at: "2026-07-01T08:45",
      lead_id: "L",
    });
    expect(buildTaskCreate({ ...emptyTaskForm("UTC"), title: "x" }, {}, "task-key-1234")).toEqual({
      title: "x",
      priority: "normal",
      idempotency_key: "task-key-1234",
    });
  });
});

describe("diffTask", () => {
  const base = formFromTask(TASK, "UTC");

  it("is empty when nothing changed, whitespace aside", () => {
    expect(diffTask(base, { ...base, title: " Send quote " })).toEqual({});
  });

  it("sends only the changed fields", () => {
    expect(diffTask(base, { ...base, priority: "high" })).toEqual({ priority: "high" });
    expect(diffTask(base, { ...base, description: "notes" })).toEqual({ description: "notes" });
  });

  it("moving the due time re-sends the reminder so it keeps its lead time", () => {
    expect(diffTask(base, { ...base, due: "2026-07-02T10:00" })).toEqual({
      due_at: "2026-07-02T10:00",
      due_timezone: "Europe/Berlin",
      remind_at: "2026-07-02T09:00",
    });
  });

  it("clearing the due date clears the reminder too", () => {
    expect(diffTask(base, { ...base, due: "", reminder: "" })).toEqual({
      due_at: null,
      due_timezone: "Europe/Berlin",
      remind_at: null,
    });
  });

  it("switching zone while keeping the wall-clock time re-sends the due time in the new zone", () => {
    expect(diffTask(base, { ...base, timezone: "Asia/Tokyo" })).toMatchObject({
      due_at: "2026-07-01T09:00",
      due_timezone: "Asia/Tokyo",
    });
  });

  it("changing only the reminder leaves the due time alone", () => {
    expect(diffTask(base, { ...base, reminder: "1440" })).toEqual({
      due_timezone: "Europe/Berlin",
      remind_at: "2026-06-30T09:00",
    });
  });
});

describe("timeZoneOptions", () => {
  it("always includes UTC and the current value", () => {
    const options = timeZoneOptions("Antarctica/Troll");
    expect(options).toContain("UTC");
    expect(options).toContain("Antarctica/Troll");
    expect(options.length).toBeGreaterThan(10);
  });
});
