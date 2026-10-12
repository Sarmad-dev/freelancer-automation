import { describe, expect, it } from "vitest";
import {
  diffItem,
  formFromItem,
  parseQuery,
  queryHref,
  type KnowledgeOut,
} from "./knowledge-model";

const ITEM: KnowledgeOut = {
  id: "11111111-1111-4111-8111-111111111111",
  kind: "fact",
  title: "Ships weekly",
  content: "Delivers a working increment every week.",
  source_type: "manual",
  source_ref: null,
  status: "draft",
  version: 1,
  is_enabled: true,
  approved_at: null,
  approved_by_user_id: null,
  created_by_user_id: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

describe("parseQuery", () => {
  it("accepts known values", () => {
    expect(parseQuery({ status: "approved", kind: "case_study", q: " seo ", page: "3" })).toEqual({
      status: "approved",
      kind: "case_study",
      q: "seo",
      page: 3,
    });
  });

  it("drops anything unrecognised instead of forwarding it to the API", () => {
    expect(
      parseQuery({ status: "approved' OR 1=1", kind: ["nope"], q: "x".repeat(300), page: "-4" }),
    ).toEqual({ status: "", kind: "", q: "x".repeat(100), page: 1 });
    expect(parseQuery({ page: "abc" }).page).toBe(1);
    expect(parseQuery({ page: "99999999" }).page).toBe(1);
  });

  it("takes the first value of a repeated param", () => {
    expect(parseQuery({ status: ["draft", "approved"] }).status).toBe("draft");
  });
});

describe("queryHref", () => {
  it("omits defaults and encodes values", () => {
    expect(queryHref({ status: "", kind: "", q: "", page: 1 })).toBe("/ai-workspace/knowledge");
    expect(queryHref({ status: "draft", kind: "", q: "a&b=c", page: 2 })).toBe(
      "/ai-workspace/knowledge?status=draft&q=a%26b%3Dc&page=2",
    );
  });
});

describe("diffItem", () => {
  it("is empty when nothing changed", () => {
    const f = formFromItem(ITEM);
    expect(diffItem(f, { ...f })).toEqual({});
  });

  it("sends only changed fields and turns a cleared source into null", () => {
    const f = formFromItem({ ...ITEM, source_ref: "Call notes" });
    expect(diffItem(f, { ...f, title: "New", source_ref: "  " })).toEqual({
      title: "New",
      source_ref: null,
    });
  });

  it("maps an unknown stored kind to other", () => {
    expect(formFromItem({ ...ITEM, kind: "mystery" }).kind).toBe("other");
  });
});
