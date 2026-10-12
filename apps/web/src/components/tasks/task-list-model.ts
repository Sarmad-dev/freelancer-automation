import { firstParam, hrefWith, pageParam } from "@/components/leads/lead-model";
import {
  PRIORITIES,
  TASK_VIEWS,
  toLocalInput,
  type Priority,
  type TaskViewName,
} from "./task-model";

export const PAGE_SIZE = 25;
export const TASKS_PATH = "/tasks";
export const DEFAULT_VIEW: TaskViewName = "today";

export const SORT_OPTIONS = [
  { value: "due_at", label: "Due date" },
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "title", label: "Title A to Z" },
  { value: "-completed_at", label: "Recently completed" },
] as const;

/** Sorts a view can use. "Recently completed" only makes sense for finished tasks. */
export function sortsFor(view: TaskViewName): readonly (typeof SORT_OPTIONS)[number][] {
  return SORT_OPTIONS.filter((s) => view === "done" || s.value !== "-completed_at");
}

/** What the API does when no sort is sent. */
export function defaultSort(view: TaskViewName): string {
  return view === "done" ? "-completed_at" : "due_at";
}

/** A sort valid for the view, or "" for "the default" (so URLs stay clean). */
export function normaliseSort(view: TaskViewName, sort: string): string {
  if (!sortsFor(view).some((s) => s.value === sort)) return "";
  return sort === defaultSort(view) ? "" : sort;
}

export interface TaskQuery {
  view: TaskViewName;
  /** An explicitly requested IANA zone, or "" for the workspace's. */
  tz: string;
  priority: "" | Priority;
  q: string;
  /** "" = the view's default order. */
  sort: string;
  page: number;
}

type RawParams = Record<string, string | string[] | undefined>;

const TZ_SHAPE = /^[A-Za-z_]+(\/[A-Za-z0-9_+-]+)*$/;

/** Plausible IANA name only. The API still has the last word (422 for an unknown zone). */
export function isPlausibleZone(value: string): boolean {
  return value.length > 0 && value.length <= 64 && TZ_SHAPE.test(value);
}

/** Untrusted URL params -> a validated query. Anything unrecognised is dropped, never forwarded to the API. */
export function parseTaskQuery(params: RawParams): TaskQuery {
  const view = firstParam(params, "view");
  const tz = firstParam(params, "tz").trim();
  const priority = firstParam(params, "priority");
  const resolved = TASK_VIEWS.find((v) => v.value === view)?.value ?? DEFAULT_VIEW;
  return {
    view: resolved,
    tz: isPlausibleZone(tz) ? tz : "",
    priority: PRIORITIES.find((p) => p.value === priority)?.value ?? "",
    q: firstParam(params, "q").trim().slice(0, 100),
    sort: normaliseSort(resolved, firstParam(params, "sort")),
    page: pageParam(params),
  };
}

export function hasTaskFilters(query: TaskQuery): boolean {
  return Boolean(query.q || query.priority);
}

export function tasksHref(query: TaskQuery): string {
  return hrefWith(TASKS_PATH, {
    view: query.view === DEFAULT_VIEW ? undefined : query.view,
    tz: query.tz,
    priority: query.priority,
    q: query.q,
    sort: query.sort,
    page: query.page,
  });
}

export function pageHref(query: TaskQuery, page: number): string {
  return tasksHref({ ...query, page });
}

/** A tab keeps the zone, search and priority; it goes back to the first page. */
export function tabHref(query: TaskQuery, view: TaskViewName): string {
  return tasksHref({ ...query, view, page: 1, sort: normaliseSort(view, query.sort) });
}

/** Query-string parameters for the list API. `tz` is the zone actually used (may be ""). */
export function apiQuery(query: TaskQuery, tz: string) {
  return {
    view: query.view,
    limit: PAGE_SIZE,
    offset: (query.page - 1) * PAGE_SIZE,
    ...(tz ? { tz } : {}),
    ...(query.priority ? { priority: query.priority } : {}),
    ...(query.q ? { q: query.q } : {}),
    ...(query.sort ? { sort: query.sort } : {}),
  };
}

/* ---------- overdue wording ---------- */

/** "2 days overdue", "3 hours overdue": computed from the server's `now`, never from the browser clock. */
export function overdueText(dueIso: string, nowIso: string): string {
  const ms = Date.parse(nowIso) - Date.parse(dueIso);
  if (!Number.isFinite(ms) || ms <= 0) return "Overdue";
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 1) return "Just overdue";
  const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"} overdue`;
  if (minutes < 60) return plural(minutes, "minute");
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return plural(hours, "hour");
  return plural(Math.floor(hours / 24), "day");
}

/* ---------- reschedule and snooze presets ---------- */

export type DatePreset = "tomorrow" | "in3days" | "nextMonday";

export const DATE_PRESETS: readonly { value: DatePreset; label: string }[] = [
  { value: "tomorrow", label: "Tomorrow 9:00" },
  { value: "in3days", label: "In 3 days" },
  { value: "nextMonday", label: "Next Monday" },
];

function addDays(date: string, days: number): string {
  const [y, m, d] = date.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/**
 * Wall-clock time (`2026-07-01T09:00`) at 9:00 on a day counted from "today" in `zone`.
 * "Today" comes from the server-provided `now`, so server and browser agree.
 */
export function presetDue(preset: DatePreset, nowIso: string, zone: string): string {
  const local = toLocalInput(nowIso, zone);
  if (!local) return "";
  const today = local.slice(0, 10);
  const [y, m, d] = today.split("-").map(Number) as [number, number, number];
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay(); // 0 = Sunday
  const days = preset === "tomorrow" ? 1 : preset === "in3days" ? 3 : (1 - weekday + 7) % 7 || 7;
  return `${addDays(today, days)}T09:00`;
}

export const SNOOZE_CHOICES = [
  { value: "hour", label: "In 1 hour" },
  { value: "tomorrow", label: "Tomorrow 9:00" },
  { value: "custom", label: "Custom" },
] as const;
export type SnoozeChoice = (typeof SNOOZE_CHOICES)[number]["value"];

export interface SnoozeBody {
  remind_at: string;
  due_timezone?: string;
}

/** "In 1 hour" is an exact instant; the others are wall-clock times in the zone (the server resolves daylight saving). */
export function buildSnooze(
  choice: SnoozeChoice,
  custom: string,
  nowIso: string,
  zone: string,
): { body: SnoozeBody } | { error: string } {
  if (choice === "hour") {
    const t = Date.parse(nowIso);
    if (!Number.isFinite(t)) return { error: "Couldn't work out the time. Reload and try again." };
    return { body: { remind_at: new Date(t + 3_600_000).toISOString() } };
  }
  const local = choice === "tomorrow" ? presetDue("tomorrow", nowIso, zone) : custom;
  if (!local) return { error: "Choose a reminder time." };
  return { body: { remind_at: local, due_timezone: zone } };
}
