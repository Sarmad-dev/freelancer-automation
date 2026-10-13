import { describe, expect, it } from "vitest";
import {
  apiQuery,
  contactsHref,
  createBody,
  diffContact,
  emptyForm,
  formFromContact,
  isManualSource,
  mailHref,
  pageHref,
  parseContactQuery,
  sortHref,
  sortState,
  telHref,
} from "./contact-model";
import type { ContactOut } from "./lead-model";

const ID = "11111111-1111-4111-8111-111111111111";

function contact(over: Partial<ContactOut> = {}): ContactOut {
  return {
    id: ID,
    full_name: "Ada Lovelace",
    email: "ada@example.com",
    role_title: "CTO",
    phone: "+1 555 0100",
    company_id: "22222222-2222-4222-8222-222222222222",
    company_name: "Analytical Ltd",
    notes: "Met at a meetup",
    source: "manual",
    source_retrieved_at: null,
    do_not_contact: false,
    is_sample: false,
    lead_count: 0,
    archived_at: null,
    created_at: "2026-10-01T00:00:00Z",
    updated_at: "2026-10-02T10:00:00Z",
    ...over,
  };
}

describe("parseContactQuery", () => {
  it("uses safe defaults", () => {
    expect(parseContactQuery({})).toEqual({
      q: "",
      companyId: "",
      archived: "active",
      sort: "full_name",
      page: 1,
    });
  });

  it("drops hostile and unknown values", () => {
    const q = parseContactQuery({
      q: "  ada  ",
      company_id: "1; DROP TABLE contacts",
      archived: "everything",
      sort: "-password_hash",
      page: "-4",
    });
    expect(q).toEqual({ q: "ada", companyId: "", archived: "active", sort: "full_name", page: 1 });
  });

  it("keeps valid values, lower-cases ids, takes the first of repeated params and caps the search", () => {
    const q = parseContactQuery({
      q: ["x".repeat(300), "second"],
      company_id: "22222222-2222-4222-8222-22222222222A",
      archived: "all",
      sort: "-updated_at",
      page: "3",
    });
    expect(q.q).toHaveLength(100);
    expect(q.companyId).toBe("22222222-2222-4222-8222-22222222222a");
    expect(q).toMatchObject({ archived: "all", sort: "-updated_at", page: 3 });
  });

  it("rejects an absurd page number", () => {
    expect(parseContactQuery({ page: "99999999" }).page).toBe(1);
    expect(parseContactQuery({ page: "abc" }).page).toBe(1);
  });
});

describe("links and API query", () => {
  const base = parseContactQuery({});

  it("omits defaults from links", () => {
    expect(contactsHref(base)).toBe("/leads/contacts");
    expect(contactsHref({ ...base, q: "a b", page: 2 })).toBe("/leads/contacts?q=a+b&page=2");
    expect(pageHref({ ...base, archived: "all" }, 3)).toBe("/leads/contacts?archived=all&page=3");
  });

  it("flips the sort direction of the active column and starts each column naturally", () => {
    expect(sortState(base, "full_name")).toBe("ascending");
    expect(sortHref(base, "full_name")).toBe("/leads/contacts?sort=-full_name");
    expect(sortHref({ ...base, sort: "-full_name", page: 4 }, "full_name")).toBe("/leads/contacts");
    expect(sortHref(base, "email")).toBe("/leads/contacts?sort=email");
    expect(sortHref(base, "updated_at")).toBe("/leads/contacts?sort=-updated_at");
    expect(sortState({ ...base, sort: "-updated_at" }, "updated_at")).toBe("descending");
    expect(sortState(base, "email")).toBe("none");
  });

  it("builds the list API query from the validated query only", () => {
    expect(apiQuery({ ...base, q: "ada", companyId: ID, page: 3 })).toEqual({
      limit: 25,
      offset: 50,
      sort: "full_name",
      archived: "active",
      q: "ada",
      company_id: ID,
    });
  });
});

describe("telHref and mailHref", () => {
  it("links only plain phone numbers", () => {
    expect(telHref("+1 (555) 010-0100")).toBe("tel:+15550100100");
    expect(telHref("020 7946 0000")).toBe("tel:02079460000");
    expect(telHref("javascript:alert(1)")).toBeNull();
    expect(telHref("555-0100 ext 5")).toBeNull();
    expect(telHref("+")).toBeNull();
    expect(telHref("()")).toBeNull();
    expect(telHref("")).toBeNull();
    expect(telHref(null)).toBeNull();
  });

  it("links only plain email addresses", () => {
    expect(mailHref("ada@example.com")).toBe("mailto:ada@example.com");
    expect(mailHref("ada@example.com?bcc=evil@example.com")).toBeNull();
    expect(mailHref("a@b.com,c@d.com")).toBeNull();
    expect(mailHref("not an email")).toBeNull();
    expect(mailHref(null)).toBeNull();
  });

  it("treats a missing or 'manual' source as hand-entered", () => {
    expect(isManualSource(null)).toBe(true);
    expect(isManualSource("Manual")).toBe(true);
    expect(isManualSource("CSV import")).toBe(false);
  });
});

describe("form bodies", () => {
  it("sends only the filled fields on create", () => {
    expect(
      createBody({ ...emptyForm(), full_name: "  Ada  ", email: " ada@example.com " }),
    ).toEqual({
      full_name: "Ada",
      email: "ada@example.com",
    });
    expect(createBody({ ...emptyForm(), full_name: "Ada", company_id: ID, notes: "  " })).toEqual({
      full_name: "Ada",
      company_id: ID,
    });
  });

  it("sends only what changed on edit, and clears blanked fields with null", () => {
    const c = contact();
    const base = formFromContact(c);
    expect(diffContact(base, base)).toEqual({});
    expect(diffContact(base, { ...base, role_title: "CEO" })).toEqual({ role_title: "CEO" });
    expect(diffContact(base, { ...base, phone: "  ", company_id: "", notes: "" })).toEqual({
      phone: null,
      company_id: null,
      notes: null,
    });
  });

  it("never sends a blank name", () => {
    const base = formFromContact(contact());
    expect(diffContact(base, { ...base, full_name: "   " })).toEqual({});
  });

  it("ignores whitespace-only differences", () => {
    const base = formFromContact(contact());
    expect(diffContact(base, { ...base, email: " ada@example.com " })).toEqual({});
  });
});
