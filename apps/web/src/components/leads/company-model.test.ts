import { describe, expect, it } from "vitest";
import {
  apiQuery,
  clearFiltersHref,
  companiesHref,
  createBody,
  diffCompany,
  emptyCompanyForm,
  formFromCompany,
  hasFilters,
  isUuid,
  pageHref,
  parseCompanyQuery,
  provenance,
  sortHref,
  sortState,
  validateCompanyForm,
  type CompanyOut,
} from "./company-model";

function company(over: Partial<CompanyOut> = {}): CompanyOut {
  return {
    id: "11111111-1111-4111-8111-111111111111",
    name: "Acme",
    website: "https://acme.test",
    domain: "acme.test",
    industry: "Logistics",
    size_label: "11-50",
    location: "Leeds",
    notes: "Note",
    source: "manual",
    source_retrieved_at: null,
    is_sample: false,
    archived_at: null,
    lead_count: 0,
    contact_count: 0,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T00:00:00Z",
    ...over,
  };
}

describe("parseCompanyQuery", () => {
  it("has clean defaults", () => {
    const q = parseCompanyQuery({});
    expect(q).toEqual({ q: "", industry: "", size: "", archived: "active", sort: "name", page: 1 });
    expect(hasFilters(q)).toBe(false);
    expect(companiesHref(q)).toBe("/leads/companies");
  });

  it("keeps valid values", () => {
    const q = parseCompanyQuery({
      q: " acme ",
      industry: "Logistics",
      size_label: "11-50",
      archived: "all",
      sort: "-updated_at",
      page: "3",
    });
    expect(q).toEqual({
      q: "acme",
      industry: "Logistics",
      size: "11-50",
      archived: "all",
      sort: "-updated_at",
      page: 3,
    });
    expect(hasFilters(q)).toBe(true);
    expect(apiQuery(q)).toEqual({
      limit: 25,
      offset: 50,
      archived: "all",
      sort: "-updated_at",
      q: "acme",
      industry: "Logistics",
      size_label: "11-50",
    });
  });

  it("drops hostile or unknown values and never forwards them", () => {
    const q = parseCompanyQuery({
      q: "x".repeat(500),
      industry: "i".repeat(500),
      size_label: "huge; drop table",
      archived: "everything",
      sort: "-password",
      page: "-4",
      sample: "only",
      extra: "1",
    });
    expect(q.q).toHaveLength(100);
    expect(q.industry).toHaveLength(100);
    expect(q.size).toBe("");
    expect(q.archived).toBe("active");
    expect(q.sort).toBe("name");
    expect(q.page).toBe(1);
    expect(Object.keys(apiQuery(q)).sort()).toEqual([
      "archived",
      "industry",
      "limit",
      "offset",
      "q",
      "sort",
    ]);
    expect(parseCompanyQuery({ sort: "name,-created_at" }).sort).toBe("name");
    expect(parseCompanyQuery({ page: "99999999" }).page).toBe(1);
    expect(parseCompanyQuery({ q: ["a", "b"], page: ["2", "9"] })).toMatchObject({
      q: "a",
      page: 2,
    });
  });
});

describe("links", () => {
  const base = parseCompanyQuery({ q: "acme", archived: "archived", page: "2" });

  it("builds sort links that keep filters and reset to page 1", () => {
    expect(sortHref(base, "name")).toBe("/leads/companies?q=acme&archived=archived&sort=-name");
    expect(sortHref(base, "industry")).toBe(
      "/leads/companies?q=acme&archived=archived&sort=industry",
    );
    expect(sortHref(base, "updated_at")).toBe(
      "/leads/companies?q=acme&archived=archived&sort=-updated_at",
    );
    expect(sortHref(parseCompanyQuery({ sort: "-name" }), "name")).toBe("/leads/companies");
    expect(sortHref(parseCompanyQuery({ sort: "-updated_at" }), "updated_at")).toBe(
      "/leads/companies?sort=updated_at",
    );
  });

  it("reports sort state for aria-sort", () => {
    expect(sortState(parseCompanyQuery({}), "name")).toBe("ascending");
    expect(sortState(parseCompanyQuery({ sort: "-name" }), "name")).toBe("descending");
    expect(sortState(parseCompanyQuery({ sort: "-name" }), "industry")).toBe("none");
  });

  it("builds page links and a clear-filters link that keeps the sort", () => {
    expect(pageHref(base, 3)).toBe("/leads/companies?q=acme&archived=archived&page=3");
    expect(pageHref(base, 1)).toBe("/leads/companies?q=acme&archived=archived");
    expect(clearFiltersHref(parseCompanyQuery({ q: "a", sort: "industry", page: "4" }))).toBe(
      "/leads/companies?sort=industry",
    );
  });

  it("recognises uuids", () => {
    expect(isUuid("11111111-1111-4111-8111-111111111111")).toBe(true);
    expect(isUuid("../etc/passwd")).toBe(false);
    expect(isUuid("")).toBe(false);
  });
});

describe("forms", () => {
  it("sends only filled fields on create", () => {
    expect(createBody({ ...emptyCompanyForm(), name: "  Acme  " })).toEqual({ name: "Acme" });
    expect(
      createBody({
        name: "Acme",
        website: " https://acme.test ",
        industry: "",
        size_label: "2-10",
        location: "  ",
        notes: "Hi",
      }),
    ).toEqual({ name: "Acme", website: "https://acme.test", size_label: "2-10", notes: "Hi" });
  });

  it("requires a name", () => {
    expect(validateCompanyForm(emptyCompanyForm())).toEqual({ name: "Enter the company's name." });
    expect(validateCompanyForm({ ...emptyCompanyForm(), name: "A" })).toEqual({});
  });

  it("diffs only changed fields; blank clears; the name is never cleared", () => {
    const base = formFromCompany(company());
    expect(diffCompany(base, base)).toEqual({});
    expect(diffCompany(base, { ...base, industry: "Retail" })).toEqual({ industry: "Retail" });
    expect(diffCompany(base, { ...base, website: " ", notes: "", size_label: "" })).toEqual({
      website: null,
      notes: null,
      size_label: null,
    });
    expect(diffCompany(base, { ...base, name: "" })).toEqual({});
    expect(diffCompany(base, { ...base, name: " New " })).toEqual({ name: "New" });
  });

  it("treats null fields as blank", () => {
    const base = formFromCompany(company({ website: null, size_label: null, notes: null }));
    expect(base.website).toBe("");
    expect(base.size_label).toBe("");
    expect(diffCompany(base, base)).toEqual({});
  });
});

describe("provenance", () => {
  it("calls manual and unsourced records manual", () => {
    expect(provenance({ source: null, source_retrieved_at: null }).manual).toBe(true);
    expect(provenance({ source: "manual", source_retrieved_at: null }).manual).toBe(true);
  });
  it("reports an imported source and when it was retrieved", () => {
    expect(
      provenance({ source: "csv-import", source_retrieved_at: "2026-10-01T09:30:00Z" }),
    ).toEqual({
      manual: false,
      source: "csv-import",
      retrievedAt: "2026-10-01T09:30:00Z",
    });
  });
});
