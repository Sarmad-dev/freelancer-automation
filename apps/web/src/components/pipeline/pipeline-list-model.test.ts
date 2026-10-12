import { describe, expect, it } from "vitest";
import {
  apiQuery,
  dealHref,
  hasPipelineFilters,
  pageHref,
  parsePipelineQuery,
  parseView,
  sortHref,
  sortState,
  tableHref,
} from "./pipeline-list-model";

const STAGE = "33333333-3333-4333-8333-333333333333";

describe("parsePipelineQuery", () => {
  it("defaults to the newest-updated first page with no filters", () => {
    expect(parsePipelineQuery({})).toEqual({
      q: "",
      status: "",
      stageId: "",
      sort: "-updated_at",
      page: 1,
    });
  });

  it("accepts valid values and normalises the stage id", () => {
    const q = parsePipelineQuery({
      q: "  big  ",
      status: "won",
      stage_id: STAGE.toUpperCase(),
      sort: "value_amount",
      page: "3",
    });
    expect(q).toEqual({ q: "big", status: "won", stageId: STAGE, sort: "value_amount", page: 3 });
  });

  it("drops hostile or unknown values", () => {
    const q = parsePipelineQuery({
      q: "x".repeat(500),
      status: "open; DROP TABLE",
      stage_id: "1 OR 1=1",
      sort: "-password_hash",
      page: "-4",
      extra: "<script>",
    });
    expect(q.q).toHaveLength(100);
    expect(q.status).toBe("");
    expect(q.stageId).toBe("");
    expect(q.sort).toBe("-updated_at");
    expect(q.page).toBe(1);
    expect(parsePipelineQuery({ sort: "--title", page: "1e9", status: "OPEN" })).toMatchObject({
      sort: "-updated_at",
      page: 1,
      status: "",
    });
  });

  it("takes the first of repeated params", () => {
    expect(parsePipelineQuery({ status: ["lost", "won"], sort: ["title", "bogus"] })).toMatchObject(
      { status: "lost", sort: "title" },
    );
  });

  it("only treats view=table as the table", () => {
    expect(parseView({})).toBe("board");
    expect(parseView({ view: "table" })).toBe("table");
    expect(parseView({ view: ["table", "board"] })).toBe("table");
    expect(parseView({ view: "TABLE" })).toBe("board");
    expect(parseView({ view: "<x>" })).toBe("board");
  });
});

describe("links", () => {
  it("builds clean table links", () => {
    expect(tableHref()).toBe("/pipeline?view=table");
    expect(tableHref({ stageId: STAGE })).toBe(`/pipeline?view=table&stage_id=${STAGE}`);
    const q = parsePipelineQuery({ q: "a b", status: "open", sort: "title", page: "2" });
    expect(tableHref(q)).toBe("/pipeline?view=table&q=a+b&status=open&sort=title&page=2");
    expect(pageHref(q, 1)).toBe("/pipeline?view=table&q=a+b&status=open&sort=title");
  });

  it("flips the active sort and starts new columns in their natural direction", () => {
    const q = parsePipelineQuery({ q: "x" });
    expect(sortState(q, "updated_at")).toBe("descending");
    expect(sortHref(q, "updated_at")).toBe("/pipeline?view=table&q=x&sort=updated_at");
    expect(sortHref(q, "title")).toBe("/pipeline?view=table&q=x&sort=title");
    expect(sortHref(q, "value_amount")).toBe("/pipeline?view=table&q=x&sort=-value_amount");
    expect(sortHref(q, "expected_close_date")).toBe(
      "/pipeline?view=table&q=x&sort=expected_close_date",
    );
    const t = parsePipelineQuery({ sort: "title", page: "4" });
    expect(sortState(t, "title")).toBe("ascending");
    expect(sortHref(t, "title")).toBe("/pipeline?view=table&sort=-title");
  });

  it("links to a deal by id", () => {
    expect(dealHref("abc")).toBe("/pipeline/abc");
  });
});

describe("api query and filters", () => {
  it("sends only validated values", () => {
    const q = parsePipelineQuery({ q: "big", status: "lost", stage_id: STAGE, page: "2" });
    expect(apiQuery(q)).toEqual({
      limit: 25,
      offset: 25,
      sort: "-updated_at",
      q: "big",
      status: "lost",
      stage_id: STAGE,
    });
    expect(apiQuery(parsePipelineQuery({ stage_id: "nope" }))).toEqual({
      limit: 25,
      offset: 0,
      sort: "-updated_at",
    });
  });

  it("knows when filters are active", () => {
    expect(hasPipelineFilters(parsePipelineQuery({}))).toBe(false);
    expect(hasPipelineFilters(parsePipelineQuery({ sort: "title", page: "2" }))).toBe(false);
    expect(hasPipelineFilters(parsePipelineQuery({ status: "open" }))).toBe(true);
    expect(hasPipelineFilters(parsePipelineQuery({ q: "a" }))).toBe(true);
  });
});
