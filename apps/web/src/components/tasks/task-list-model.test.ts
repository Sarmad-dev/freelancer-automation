import { describe, expect, it } from "vitest";
import {
  apiQuery,
  buildSnooze,
  defaultSort,
  normaliseSort,
  overdueText,
  pageHref,
  parseTaskQuery,
  presetDue,
  tabHref,
  tasksHref,
} from "./task-list-model";

describe("parseTaskQuery", () => {
  it("defaults to the today view with nothing else set", () => {
    expect(parseTaskQuery({})).toEqual({
      view: "today",
      tz: "",
      priority: "",
      q: "",
      sort: "",
      page: 1,
    });
  });

  it("drops hostile values instead of forwarding them", () => {
    const q = parseTaskQuery({
      view: "x' OR 1=1",
      tz: "../etc/passwd",
      priority: "urgent; DROP TABLE",
      page: "-3",
      sort: "password",
    });
    expect(q).toEqual({ view: "today", tz: "", priority: "", q: "", sort: "", page: 1 });
  });

  it("keeps valid values", () => {
    const q = parseTaskQuery({
      view: "overdue",
      tz: "America/Argentina/Buenos_Aires",
      priority: "high",
      q: "  quote  ",
      sort: "title",
      page: "3",
    });
    expect(q).toEqual({
      view: "overdue",
      tz: "America/Argentina/Buenos_Aires",
      priority: "high",
      q: "quote",
      sort: "title",
      page: 3,
    });
  });

  it("accepts plausible zones and rejects implausible ones", () => {
    expect(parseTaskQuery({ tz: "UTC" }).tz).toBe("UTC");
    expect(parseTaskQuery({ tz: "Etc/GMT+5" }).tz).toBe("Etc/GMT+5");
    expect(parseTaskQuery({ tz: "Europe/Berlin<script>" }).tz).toBe("");
    expect(parseTaskQuery({ tz: "Europe//Berlin" }).tz).toBe("");
    expect(parseTaskQuery({ tz: "A".repeat(65) }).tz).toBe("");
    expect(parseTaskQuery({ tz: "A".repeat(64) }).tz).toBe("A".repeat(64));
  });

  it("caps the search text, takes the first of repeated params and ignores huge pages", () => {
    expect(parseTaskQuery({ q: "x".repeat(500) }).q).toHaveLength(100);
    expect(parseTaskQuery({ view: ["done", "overdue"] }).view).toBe("done");
    expect(parseTaskQuery({ page: "99999999" }).page).toBe(1);
    expect(parseTaskQuery({ page: "abc" }).page).toBe(1);
  });

  it("only allows the completed sort in the done view and drops default sorts", () => {
    expect(parseTaskQuery({ view: "done", sort: "-completed_at" }).sort).toBe("");
    expect(parseTaskQuery({ view: "done", sort: "due_at" }).sort).toBe("due_at");
    expect(parseTaskQuery({ view: "today", sort: "-completed_at" }).sort).toBe("");
    expect(parseTaskQuery({ view: "today", sort: "due_at" }).sort).toBe("");
    expect(normaliseSort("today", "-created_at")).toBe("-created_at");
    expect(defaultSort("done")).toBe("-completed_at");
  });
});

describe("links and API query", () => {
  const base = parseTaskQuery({});

  it("keeps URLs clean", () => {
    expect(tasksHref(base)).toBe("/tasks");
    expect(tasksHref({ ...base, view: "upcoming", tz: "Asia/Tokyo", q: "a b", page: 2 })).toBe(
      "/tasks?view=upcoming&tz=Asia%2FTokyo&q=a+b&page=2",
    );
  });

  it("tabs keep filters and zone, reset the page and fix the sort", () => {
    const q = parseTaskQuery({
      view: "done",
      tz: "UTC",
      priority: "high",
      page: "4",
      sort: "due_at",
    });
    expect(tabHref(q, "overdue")).toBe("/tasks?view=overdue&tz=UTC&priority=high");
    expect(tabHref(q, "today")).toBe("/tasks?tz=UTC&priority=high");
    expect(pageHref(q, 2)).toBe("/tasks?view=done&tz=UTC&priority=high&sort=due_at&page=2");
  });

  it("builds the API query from validated values only", () => {
    expect(apiQuery(base, "")).toEqual({ view: "today", limit: 25, offset: 0 });
    expect(
      apiQuery(
        parseTaskQuery({ view: "done", priority: "low", q: "x", page: "3", sort: "title" }),
        "UTC",
      ),
    ).toEqual({
      view: "done",
      limit: 25,
      offset: 50,
      tz: "UTC",
      priority: "low",
      q: "x",
      sort: "title",
    });
  });
});

describe("overdueText", () => {
  const due = "2026-10-10T12:00:00Z";
  it("says how long ago in words", () => {
    expect(overdueText(due, "2026-10-12T12:00:00Z")).toBe("2 days overdue");
    expect(overdueText(due, "2026-10-11T12:00:00Z")).toBe("1 day overdue");
    expect(overdueText(due, "2026-10-10T15:00:00Z")).toBe("3 hours overdue");
    expect(overdueText(due, "2026-10-10T13:00:00Z")).toBe("1 hour overdue");
    expect(overdueText(due, "2026-10-10T12:45:00Z")).toBe("45 minutes overdue");
    expect(overdueText(due, "2026-10-10T12:00:20Z")).toBe("Just overdue");
  });
  it("is plain 'Overdue' when the clocks disagree or the date is unreadable", () => {
    expect(overdueText(due, "2026-10-09T00:00:00Z")).toBe("Overdue");
    expect(overdueText("nope", "2026-10-09T00:00:00Z")).toBe("Overdue");
  });
});

describe("presets", () => {
  // Monday 2026-10-12, 22:30 UTC = Tuesday 2026-10-13 00:30 in Berlin (CEST).
  const now = "2026-10-12T22:30:00Z";
  it("uses the day in the chosen zone", () => {
    expect(presetDue("tomorrow", now, "UTC")).toBe("2026-10-13T09:00");
    expect(presetDue("tomorrow", now, "Europe/Berlin")).toBe("2026-10-14T09:00");
    expect(presetDue("in3days", now, "UTC")).toBe("2026-10-15T09:00");
  });
  it("next Monday is always a later day", () => {
    expect(presetDue("nextMonday", now, "UTC")).toBe("2026-10-19T09:00"); // today is Monday
    expect(presetDue("nextMonday", now, "Europe/Berlin")).toBe("2026-10-19T09:00"); // Tuesday there
    expect(presetDue("nextMonday", "2026-10-17T10:00:00Z", "UTC")).toBe("2026-10-19T09:00"); // Saturday
    expect(presetDue("nextMonday", "2026-10-18T10:00:00Z", "UTC")).toBe("2026-10-19T09:00"); // Sunday
  });
  it("rolls over month and year ends", () => {
    expect(presetDue("in3days", "2026-12-30T10:00:00Z", "UTC")).toBe("2027-01-02T09:00");
  });
  it("is empty for an unknown zone", () => {
    expect(presetDue("tomorrow", now, "Not/AZone")).toBe("");
  });
});

describe("buildSnooze", () => {
  const now = "2026-10-12T10:00:00Z";
  it("in one hour is an exact instant", () => {
    expect(buildSnooze("hour", "", now, "Europe/Berlin")).toEqual({
      body: { remind_at: "2026-10-12T11:00:00.000Z" },
    });
  });
  it("tomorrow and custom are wall-clock times with the zone", () => {
    expect(buildSnooze("tomorrow", "", now, "Europe/Berlin")).toEqual({
      body: { remind_at: "2026-10-13T09:00", due_timezone: "Europe/Berlin" },
    });
    expect(buildSnooze("custom", "2026-11-01T08:15", now, "Asia/Tokyo")).toEqual({
      body: { remind_at: "2026-11-01T08:15", due_timezone: "Asia/Tokyo" },
    });
  });
  it("asks for a time when custom is empty", () => {
    expect(buildSnooze("custom", "", now, "UTC")).toEqual({ error: "Choose a reminder time." });
  });
});
