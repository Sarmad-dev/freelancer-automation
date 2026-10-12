import type { components } from "@freelancer-os/contracts";

type Schemas = components["schemas"];
export type TaskOut = Schemas["TaskOut"];
export type TaskCreate = Schemas["TaskCreate"];
export type TaskPatch = Schemas["TaskPatch"];
export type TaskSummary = Schemas["TaskSummary"];
export type NotificationOut = Schemas["NotificationOut"];

export const PRIORITIES = [
  { value: "high", label: "High" },
  { value: "normal", label: "Normal" },
  { value: "low", label: "Low" },
] as const;
export type Priority = (typeof PRIORITIES)[number]["value"];

/** `overdue` = past due; `today` = still due before local midnight; `upcoming` = later; `undated` = no due date. */
export const TASK_VIEWS = [
  { value: "overdue", label: "Overdue" },
  { value: "today", label: "Today" },
  { value: "upcoming", label: "Upcoming" },
  { value: "undated", label: "No date" },
  { value: "done", label: "Done" },
] as const;
export type TaskViewName = (typeof TASK_VIEWS)[number]["value"];

export function priorityLabel(value: string): string {
  return PRIORITIES.find((p) => p.value === value)?.label ?? value;
}

const DEFAULT_ZONES = [
  "UTC",
  "Europe/London",
  "Europe/Berlin",
  "Europe/Paris",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Pacific/Auckland",
];

/** IANA zone names for a picker, with the current value always present. */
export function timeZoneOptions(current?: string | null): string[] {
  let zones: string[] = DEFAULT_ZONES;
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    const all = intl.supportedValuesOf?.("timeZone");
    if (all && all.length > 0) zones = ["UTC", ...all.filter((z) => z !== "UTC")];
  } catch {
    // keep the short list
  }
  return current && !zones.includes(current) ? [current, ...zones] : zones;
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

function parts(iso: string, tz: string): Record<string, string> | null {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  try {
    const fmt = new Intl.DateTimeFormat("en-US", {
      timeZone: tz,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    });
    return Object.fromEntries(fmt.formatToParts(date).map((p) => [p.type, p.value]));
  } catch {
    return null;
  }
}

/** The wall-clock time in the task's own zone: `2026-07-01 09:00 (Europe/Berlin)`. Deterministic across server and browser. */
export function formatDue(iso: string | null | undefined, tz: string | null | undefined): string {
  if (!iso) return "";
  const zone = tz || "UTC";
  const p = parts(iso, zone);
  if (!p) return "";
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute} (${zone})`;
}

/** Value for `<input type="datetime-local">`: the stored instant as wall-clock time in `tz`. */
export function toLocalInput(
  iso: string | null | undefined,
  tz: string | null | undefined,
): string {
  if (!iso) return "";
  const p = parts(iso, tz || "UTC");
  return p ? `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}` : "";
}

export const REMINDERS = [
  { value: "", label: "No reminder", minutes: null },
  { value: "0", label: "At the due time", minutes: 0 },
  { value: "15", label: "15 minutes before", minutes: 15 },
  { value: "60", label: "1 hour before", minutes: 60 },
  { value: "1440", label: "1 day before", minutes: 1440 },
] as const;

/** `2026-07-01T09:00` minus N minutes, as wall-clock arithmetic (the API validates the result in the zone). */
export function minusMinutes(local: string, minutes: number): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(local);
  if (!m) return "";
  const t = Date.UTC(+m[1]!, +m[2]! - 1, +m[3]!, +m[4]!, +m[5]!) - minutes * 60_000;
  return new Date(t).toISOString().slice(0, 16);
}

/** The preset that reproduces a stored reminder, or "" when none (custom lead times round to "no preset"). */
export function reminderPreset(due: string, remind: string): string {
  if (!due || !remind) return "";
  const a = Date.parse(`${due}:00Z`);
  const b = Date.parse(`${remind}:00Z`);
  const minutes = Math.round((a - b) / 60_000);
  return REMINDERS.find((r) => r.minutes === minutes)?.value ?? "";
}

export interface TaskForm {
  title: string;
  description: string;
  priority: Priority;
  /** Wall-clock time in `timezone` (datetime-local value). */
  due: string;
  reminder: string;
  timezone: string;
}

export const emptyTaskForm = (timezone: string): TaskForm => ({
  title: "",
  description: "",
  priority: "normal",
  due: "",
  reminder: "",
  timezone,
});

export function formFromTask(task: TaskOut, fallbackZone: string): TaskForm {
  const timezone = task.due_timezone ?? fallbackZone;
  const due = toLocalInput(task.due_at, timezone);
  const remind = toLocalInput(task.remind_at, timezone);
  return {
    title: task.title,
    description: task.description ?? "",
    priority: PRIORITIES.some((p) => p.value === task.priority)
      ? (task.priority as Priority)
      : "normal",
    due,
    reminder: reminderPreset(due, remind),
    timezone,
  };
}

function remindLocal(form: TaskForm): string | null {
  const preset = REMINDERS.find((r) => r.value === form.reminder);
  if (!form.due || !preset || preset.minutes === null) return null;
  return minusMinutes(form.due, preset.minutes) || null;
}

export function validateTaskForm(form: TaskForm): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!form.title.trim()) errors.title = "Enter what needs doing.";
  if (form.reminder && !form.due) errors.reminder = "Set a due date and time to use a reminder.";
  return errors;
}

/** Wall-clock times go to the API untouched, with their zone: the server resolves daylight saving. */
export function buildTaskCreate(
  form: TaskForm,
  links: { lead_id?: string; opportunity_id?: string; conversation_id?: string },
  idempotencyKey: string,
): TaskCreate {
  const body: TaskCreate = {
    title: form.title.trim(),
    priority: form.priority,
    idempotency_key: idempotencyKey,
  };
  if (form.description.trim()) body.description = form.description.trim();
  if (form.due) {
    body.due_at = form.due;
    body.due_timezone = form.timezone;
    const remind = remindLocal(form);
    if (remind) body.remind_at = remind;
  }
  if (links.lead_id) body.lead_id = links.lead_id;
  if (links.opportunity_id) body.opportunity_id = links.opportunity_id;
  if (links.conversation_id) body.conversation_id = links.conversation_id;
  return body;
}

/** Changed fields only. Clearing the due date also clears the reminder (a reminder needs a due time). */
export function diffTask(base: TaskForm, next: TaskForm): TaskPatch {
  const patch: TaskPatch = {};
  if (base.title.trim() !== next.title.trim()) patch.title = next.title.trim();
  if (base.description.trim() !== next.description.trim())
    patch.description = next.description.trim() || null;
  if (base.priority !== next.priority) patch.priority = next.priority;
  const dueChanged = base.due !== next.due || (next.due && base.timezone !== next.timezone);
  const remindChanged = base.reminder !== next.reminder || (dueChanged && next.reminder !== "");
  if (dueChanged || remindChanged) patch.due_timezone = next.timezone;
  if (dueChanged) patch.due_at = next.due || null;
  if (remindChanged || (dueChanged && !next.due)) patch.remind_at = remindLocal(next);
  return patch;
}

export function newIdempotencyKey(): string {
  const c = globalThis.crypto;
  const id =
    typeof c?.randomUUID === "function"
      ? c.randomUUID()
      : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `task-${id}`;
}
