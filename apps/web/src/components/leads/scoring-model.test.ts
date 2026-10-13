import { describe, expect, it } from "vitest";
import type { FitConfigOut } from "./lead-model";
import {
  CRITERION_KEYS,
  defaultForm,
  formFromConfig,
  formToCriteria,
  mapServerFields,
  parseLines,
  parseWeight,
  sameForm,
  validateForm,
  weightShares,
} from "./scoring-model";

const CONFIG: FitConfigOut["criteria"] = [
  { key: "budget", enabled: false, weight: 4 },
  { key: "service_match", enabled: true, weight: 6, keywords: ["WordPress", "Shopify"] },
  { key: "industry", enabled: true, weight: 3, preferred: ["SaaS"], avoid: ["Gambling"] },
  { key: "geography", enabled: true, weight: 2, preferred: ["Remote", "EU"] },
  { key: "company_size", enabled: true, weight: 1, preferred: ["11-50", "2-10"] },
];

describe("parseLines", () => {
  it("trims, drops blank lines and removes case-insensitive repeats keeping the first spelling", () => {
    expect(parseLines("  Remote \n\n\r\nremote\nEU\r\n  eu  \nUK")).toEqual(["Remote", "EU", "UK"]);
    expect(parseLines("")).toEqual([]);
  });
});

describe("formFromConfig / formToCriteria", () => {
  it("round-trips and always emits the five criteria in the fixed order", () => {
    const body = formToCriteria(formFromConfig(CONFIG));
    expect(body.map((c) => c.key)).toEqual([...CRITERION_KEYS]);
    expect(body).toEqual([
      { key: "service_match", enabled: true, weight: 6, keywords: ["WordPress", "Shopify"] },
      { key: "industry", enabled: true, weight: 3, preferred: ["SaaS"], avoid: ["Gambling"] },
      { key: "geography", enabled: true, weight: 2, preferred: ["Remote", "EU"] },
      // sizes are put in smallest-to-largest order
      { key: "company_size", enabled: true, weight: 1, preferred: ["2-10", "11-50"] },
      { key: "budget", enabled: false, weight: 4 },
    ]);
  });

  it("falls back to the defaults for missing criteria and missing lists", () => {
    const form = formFromConfig([{ key: "geography", enabled: true, weight: 7 }]);
    expect(form.geography.weight).toBe("7");
    expect(form.geography.preferred).toBe("");
    expect(form.service_match).toEqual(defaultForm().service_match);
  });

  it("has the documented defaults", () => {
    const body = formToCriteria(defaultForm());
    expect(body.map((c) => [c.key, c.weight, c.enabled])).toEqual([
      ["service_match", 5, true],
      ["industry", 3, true],
      ["geography", 1, true],
      ["company_size", 1, true],
      ["budget", 2, true],
    ]);
  });
});

describe("sameForm", () => {
  it("ignores cosmetic differences but sees real ones", () => {
    const a = formFromConfig(CONFIG);
    const b = formFromConfig(CONFIG);
    b.geography.preferred = " Remote \n\nEU\nremote";
    expect(sameForm(a, b)).toBe(true);
    b.geography.preferred = "Remote";
    expect(sameForm(a, b)).toBe(false);
    const c = formFromConfig(CONFIG);
    c.budget.enabled = true;
    expect(sameForm(a, c)).toBe(false);
    const d = formFromConfig(CONFIG);
    d.industry.weight = "4";
    expect(sameForm(a, d)).toBe(false);
  });

  it("treats an empty weight as a change, not as the lowest weight", () => {
    const a = defaultForm();
    a.budget.weight = "1";
    const b = defaultForm();
    b.budget.weight = "";
    expect(sameForm(a, b)).toBe(false);
  });
});

describe("validateForm", () => {
  it("accepts the defaults", () => {
    expect(validateForm(defaultForm())).toEqual({});
  });

  it("flags bad weights, long lists and long items", () => {
    const f = defaultForm();
    f.industry.weight = "11";
    f.budget.weight = "2.5";
    f.service_match.keywords = Array.from({ length: 41 }, (_, i) => `k${i}`).join("\n");
    f.geography.preferred = "x".repeat(81);
    expect(Object.keys(validateForm(f)).sort()).toEqual([
      "budget.weight",
      "geography.preferred",
      "industry.weight",
      "service_match.keywords",
    ]);
  });

  it("requires at least one enabled criterion", () => {
    const f = defaultForm();
    for (const k of CRITERION_KEYS) f[k].enabled = false;
    expect(validateForm(f).form).toMatch(/at least one/);
  });
});

describe("parseWeight", () => {
  it("only accepts whole numbers from 1 to 10", () => {
    expect(["1", "10", " 5 "].map(parseWeight)).toEqual([1, 10, 5]);
    expect(["", "0", "11", "1.5", "-1", "abc"].map(parseWeight)).toEqual([
      null,
      null,
      null,
      null,
      null,
      null,
    ]);
  });
});

describe("mapServerFields", () => {
  it("maps criteria.N.field onto the right criterion and keeps the rest", () => {
    const { errors, other } = mapServerFields({
      "criteria.0.weight": "Must be at most 10",
      "criteria.1.preferred.3": "Too long",
      "criteria.3": "Odd",
      criteria: "Turn on one",
      "criteria.9.weight": "Unknown index",
      something: "Else",
    });
    expect(errors).toEqual({
      "service_match.weight": "Must be at most 10",
      "industry.preferred": "Too long",
      company_size: "Odd",
      form: "Turn on one",
    });
    expect(other).toEqual(["Unknown index", "Else"]);
  });
});

describe("weightShares", () => {
  it("splits only the enabled criteria", () => {
    const f = defaultForm();
    f.budget.enabled = false;
    const { shares, total } = weightShares(f);
    expect(total).toBe(10);
    expect(shares.map((s) => [s.title, s.weight, s.percent])).toEqual([
      ["Service match", 5, 50],
      ["Industry", 3, 30],
      ["Geography", 1, 10],
      ["Company size", 1, 10],
    ]);
  });
});
