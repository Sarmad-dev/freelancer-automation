import { describe, expect, it } from "vitest";
import {
  CATEGORIES,
  CATEGORY_HELP,
  CATEGORY_LABEL,
  CATEGORY_TONE,
  FILTERS,
  PAGE_SIZE,
  apiQuery,
  confidenceText,
  counterpartLabel,
  hasFilters,
  inboxHref,
  parseInboxQuery,
  sourceLabel,
  type InboxQuery,
} from "./inbox-model";

const ID = "00000000-0000-4000-8000-0000000000c1";
const base: InboxQuery = { q: "", filter: "", account: "", page: 1, selected: "" };

describe("inbox query", () => {
  it("falls back to everything for unknown or malicious values", () => {
    expect(parseInboxQuery({})).toEqual(base);
    expect(
      parseInboxQuery({
        filter: "<script>",
        account: "nope",
        c: "../../x",
        q: "  hi  ",
        page: "-4",
      }),
    ).toEqual({ ...base, q: "hi" });
  });

  it("accepts known filters, ids and caps the search text", () => {
    const q = parseInboxQuery({ filter: "unsubscribe", c: ID, account: ID, q: "x".repeat(300) });
    expect(q.filter).toBe("unsubscribe");
    expect(q.selected).toBe(ID);
    expect(q.account).toBe(ID);
    expect(q.q).toHaveLength(100);
  });

  it("maps filters to API parameters", () => {
    expect(apiQuery(base)).toEqual({ limit: PAGE_SIZE, offset: 0 });
    expect(apiQuery({ ...base, filter: "unread", page: 3 })).toEqual({
      limit: PAGE_SIZE,
      offset: 2 * PAGE_SIZE,
      unread: true,
    });
    expect(apiQuery({ ...base, filter: "review" }).needs_review).toBe(true);
    expect(apiQuery({ ...base, filter: "referral", q: "acme", account: ID })).toMatchObject({
      classification: "referral",
      q: "acme",
      account_id: ID,
    });
  });

  it("goes back to page one when the search or filter changes, not when the page does", () => {
    const q = { ...base, page: 4, selected: ID };
    expect(inboxHref(q, { filter: "unread" })).not.toContain("page=");
    expect(inboxHref(q, { page: 5 })).toContain("page=5");
    expect(inboxHref(q, { selected: "" })).toContain("page=4");
    expect(inboxHref(q)).toContain(`c=${ID}`);
  });

  it("knows when filters are active", () => {
    expect(hasFilters(base)).toBe(false);
    expect(hasFilters({ ...base, q: "a" })).toBe(true);
    expect(hasFilters({ ...base, filter: "question" })).toBe(true);
  });
});

describe("inbox labels", () => {
  it("covers all eight categories everywhere", () => {
    expect(CATEGORIES).toHaveLength(8);
    for (const c of CATEGORIES) {
      expect(CATEGORY_LABEL[c]).toBeTruthy();
      expect(CATEGORY_TONE[c]).toBeTruthy();
      expect(CATEGORY_HELP[c]).toBeTruthy();
      expect(FILTERS.some((f) => f.value === c)).toBe(true);
    }
  });

  it("says plainly where a classification came from", () => {
    expect(sourceLabel("demo_ai")).toMatch(/not a real model/);
    expect(sourceLabel("rules_fallback")).toMatch(/unavailable/);
    expect(sourceLabel("manual")).toBe("Set by you");
    expect(sourceLabel(null)).toBe("");
  });

  it("formats confidence and counterparts", () => {
    expect(confidenceText(0.876)).toBe("88% confident");
    expect(confidenceText(null)).toBe("");
    expect(counterpartLabel({ counterpart: { name: "Sam", address: "s@x.example" } })).toBe("Sam");
    expect(counterpartLabel({ counterpart: { name: null, address: "s@x.example" } })).toBe(
      "s@x.example",
    );
    expect(counterpartLabel({ counterpart: { name: null, address: "" } })).toBe("Unknown sender");
  });
});
