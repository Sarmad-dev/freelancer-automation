import { describe, expect, it } from "vitest";
import {
  PAGE_SIZE,
  activeFilterChips,
  apiQuery,
  clearFiltersHref,
  exportHref,
  hasFilters,
  leadsHref,
  localToIso,
  pageHref,
  parseLeadQuery,
  sortHref,
  sortState,
} from "./lead-list-model";

const TAG = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const COMPANY = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const CONTACT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const WS = "22222222-2222-4222-8222-222222222222";

describe("parseLeadQuery", () => {
  it("has clean defaults", () => {
    const q = parseLeadQuery({});
    expect(q).toEqual({
      q: "",
      status: [],
      fit: "",
      tagId: "",
      companyId: "",
      contactId: "",
      source: "",
      archived: "active",
      overdue: false,
      sample: "",
      sort: "-updated_at",
      page: 1,
    });
    expect(hasFilters(q)).toBe(false);
  });

  it("accepts every supported deep-link param", () => {
    const q = parseLeadQuery({
      q: "  acme ",
      status: ["new", "contacted"],
      fit: "strong",
      tag_id: TAG,
      company_id: COMPANY,
      contact_id: CONTACT,
      source: "csv",
      archived: "all",
      overdue: "1",
      sample: "only",
      sort: "-fit_score",
      page: "3",
    });
    expect(q).toMatchObject({
      q: "acme",
      status: ["new", "contacted"],
      fit: "strong",
      tagId: TAG,
      companyId: COMPANY,
      contactId: CONTACT,
      source: "csv",
      archived: "all",
      overdue: true,
      sample: "only",
      sort: "-fit_score",
      page: 3,
    });
    expect(hasFilters(q)).toBe(true);
  });

  it("drops hostile or unknown values instead of forwarding them", () => {
    const q = parseLeadQuery({
      status: ["x' OR 1=1", "won", "won", "<script>"],
      fit: "legendary",
      tag_id: "1; DROP TABLE leads",
      company_id: "not-a-uuid",
      contact_id: ["", CONTACT],
      archived: "everything",
      overdue: "yes",
      sample: "maybe",
      sort: "password",
      page: "-4",
    });
    expect(q.status).toEqual(["won"]);
    expect(q.fit).toBe("");
    expect(q.tagId).toBe("");
    expect(q.companyId).toBe("");
    expect(q.contactId).toBe("");
    expect(q.archived).toBe("active");
    expect(q.overdue).toBe(false);
    expect(q.sample).toBe("");
    expect(q.sort).toBe("-updated_at");
    expect(q.page).toBe(1);
  });

  it("rejects bad sorts and pages, and caps long text", () => {
    expect(parseLeadQuery({ sort: "--title" }).sort).toBe("-updated_at");
    expect(parseLeadQuery({ sort: "title,-status" }).sort).toBe("-updated_at");
    expect(parseLeadQuery({ sort: "next_action_at" }).sort).toBe("next_action_at");
    expect(parseLeadQuery({ page: "abc" }).page).toBe(1);
    expect(parseLeadQuery({ page: "99999999" }).page).toBe(1);
    expect(parseLeadQuery({ q: "x".repeat(500) }).q).toHaveLength(100);
    expect(parseLeadQuery({ source: "y".repeat(500) }).source).toHaveLength(100);
  });

  it("uses only the first value of single-value params", () => {
    expect(parseLeadQuery({ fit: ["weak", "strong"] }).fit).toBe("weak");
  });
});

describe("links", () => {
  it("builds short URLs and repeats status", () => {
    const base = parseLeadQuery({});
    expect(leadsHref(base)).toBe("/leads");
    const q = parseLeadQuery({ status: ["new", "replied"], q: "a b&c", page: "2", sort: "title" });
    const href = leadsHref(q);
    expect(href).toContain("q=a+b%26c");
    expect(href).toContain("sort=title");
    expect(href).toContain("page=2");
    expect(href).toContain("status=new&status=replied");
    // round trips
    const params = Object.fromEntries(new URL(href, "http://x").searchParams);
    expect(parseLeadQuery(params).q).toBe("a b&c");
  });

  it("pages keep the filters", () => {
    const q = parseLeadQuery({ fit: "weak" });
    expect(pageHref(q, 2)).toBe("/leads?fit=weak&page=2");
    expect(pageHref(q, 1)).toBe("/leads?fit=weak");
  });

  it("sort links toggle direction and restart at page one", () => {
    const q = parseLeadQuery({ sort: "title", page: "4", fit: "strong" });
    expect(sortState(q, "title")).toBe("ascending");
    expect(sortHref(q, "title")).toBe("/leads?fit=strong&sort=-title");
    expect(sortState(parseLeadQuery({ sort: "-title" }), "title")).toBe("descending");
    expect(sortHref(parseLeadQuery({ sort: "-title" }), "title")).toBe("/leads?sort=title");
    // natural first direction for a new column
    expect(sortHref(q, "fit_score")).toBe("/leads?fit=strong&sort=-fit_score");
    expect(sortHref(parseLeadQuery({}), "status")).toBe("/leads?sort=status");
    // default sort is omitted from the URL
    expect(sortHref(parseLeadQuery({ sort: "title" }), "updated_at")).toBe("/leads");
  });

  it("export link carries the filters and sort but never the page", () => {
    const q = parseLeadQuery({
      status: ["new"],
      overdue: "1",
      archived: "all",
      tag_id: TAG,
      page: "5",
    });
    const href = exportHref(WS, q);
    expect(href.startsWith(`/api/v1/workspaces/${WS}/leads/export?`)).toBe(true);
    expect(href).toContain("overdue=true");
    expect(href).toContain("archived=all");
    expect(href).toContain(`tag_id=${TAG}`);
    expect(href).toContain("status=new");
    expect(href).toContain("sort=-updated_at");
    expect(href).not.toContain("page=");
  });

  it("clear filters keeps the order", () => {
    expect(clearFiltersHref(parseLeadQuery({ fit: "weak", sort: "title" }))).toBe(
      "/leads?sort=title",
    );
    expect(clearFiltersHref(parseLeadQuery({ fit: "weak" }))).toBe("/leads");
  });
});

describe("apiQuery", () => {
  it("only sends validated values with paging", () => {
    const q = parseLeadQuery({ status: ["new", "bogus"], page: "3", overdue: "1", sort: "bogus" });
    expect(apiQuery(q)).toEqual({
      limit: PAGE_SIZE,
      offset: 2 * PAGE_SIZE,
      sort: "-updated_at",
      status: ["new"],
      archived: "active",
      overdue: true,
    });
  });
});

describe("activeFilterChips", () => {
  const lookup = {
    tagName: (id: string) => (id === TAG ? "Warm" : undefined),
    companyName: () => undefined,
    contactName: () => undefined,
  };

  it("makes one removable chip per filter, each link dropping only that filter", () => {
    const q = parseLeadQuery({
      status: ["new", "lost"],
      tag_id: TAG,
      fit: "weak",
      overdue: "1",
      q: "x",
    });
    const chips = activeFilterChips(q, lookup);
    expect(chips.map((c) => c.label)).toEqual([
      "Search: “x”",
      "Status: New",
      "Status: Lost",
      "Fit: Weak fit",
      "Tag: Warm",
      "Overdue next action",
    ]);
    const lostChip = chips.find((c) => c.id === "status:lost")!;
    expect(lostChip.href).toContain("status=new");
    expect(lostChip.href).not.toContain("status=lost");
    expect(lostChip.href).toContain("overdue=1");
    expect(chips.find((c) => c.id === "overdue")!.href).not.toContain("overdue");
  });

  it("falls back to a neutral label when the name is unknown", () => {
    const chips = activeFilterChips(parseLeadQuery({ company_id: COMPANY }), lookup);
    expect(chips[0]!.label).toBe("Company: selected company");
  });
});

describe("localToIso", () => {
  it("reads a local datetime as UTC", () => {
    expect(localToIso("2026-10-12T09:30")).toBe("2026-10-12T09:30:00.000Z");
    expect(localToIso("")).toBeUndefined();
    expect(localToIso("garbage")).toBeUndefined();
  });
});
