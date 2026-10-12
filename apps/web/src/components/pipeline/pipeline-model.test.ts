import { describe, expect, it } from "vitest";
import {
  diffOpportunity,
  emptyOpportunityForm,
  formFromOpportunity,
  opportunityCreateFields,
  validateOpportunityForm,
} from "./opportunity-fields";
import {
  dealStatusTone,
  formatMoney,
  formatTotals,
  isCloseOverdue,
  stageTone,
  type OpportunityOut,
} from "./pipeline-model";

const OPP = {
  id: "1",
  title: "Big project",
  value_amount: "12000.00",
  currency: "USD",
  probability: 60,
  expected_close_date: "2026-08-01",
  next_action: "Send proposal",
  status: "open",
} as unknown as OpportunityOut;

describe("money", () => {
  it("formats with a fixed locale", () => {
    expect(formatMoney("12000.5", "USD")).toBe("$12,000.50");
    expect(formatMoney(200, "EUR")).toBe("€200.00");
    expect(formatMoney(null, "USD")).toBe("");
    expect(formatMoney("", "USD")).toBe("");
  });

  it("falls back to plain text for odd input instead of throwing", () => {
    expect(formatMoney("12", "ZZZZ")).toBe("12.00 ZZZZ");
    expect(formatMoney("abc", "USD")).toBe("abc USD");
  });

  it("lists one line per currency, never a sum across them", () => {
    expect(
      formatTotals([
        { currency: "USD", amount: "1500.00", weighted: null },
        { currency: "EUR", amount: "200.00", weighted: null },
      ]),
    ).toEqual(["$1,500.00", "€200.00"]);
  });
});

describe("close dates and tones", () => {
  it("is overdue only when open and before today", () => {
    expect(
      isCloseOverdue({ expected_close_date: "2026-05-31", status: "open" }, "2026-06-01"),
    ).toBe(true);
    expect(
      isCloseOverdue({ expected_close_date: "2026-06-01", status: "open" }, "2026-06-01"),
    ).toBe(false);
    expect(isCloseOverdue({ expected_close_date: "2026-05-31", status: "won" }, "2026-06-01")).toBe(
      false,
    );
    expect(isCloseOverdue({ expected_close_date: null, status: "open" }, "2026-06-01")).toBe(false);
  });

  it("colours closed stages, with words always present elsewhere", () => {
    expect(stageTone({ is_won: true, is_lost: false })).toBe("success");
    expect(stageTone({ is_won: false, is_lost: true })).toBe("danger");
    expect(stageTone({ is_won: false, is_lost: false })).toBe("neutral");
    expect(dealStatusTone("won")).toBe("success");
    expect(dealStatusTone("open")).toBe("info");
  });
});

describe("opportunity form", () => {
  it("validates like the API", () => {
    const f = {
      ...emptyOpportunityForm(),
      value_amount: "12.345",
      probability: "101",
      currency: "US",
    };
    expect(Object.keys(validateOpportunityForm(f)).sort()).toEqual([
      "currency",
      "probability",
      "value_amount",
    ]);
    expect(
      validateOpportunityForm({
        ...emptyOpportunityForm(),
        value_amount: "1200.5",
        probability: "0",
      }),
    ).toEqual({});
    expect(
      validateOpportunityForm({ ...emptyOpportunityForm(), value_amount: "-5" }).value_amount,
    ).toBeTruthy();
    expect(
      validateOpportunityForm({ ...emptyOpportunityForm(), value_amount: "1e9" }).value_amount,
    ).toBeTruthy();
  });

  it("creates with only what was filled in and never guesses a probability", () => {
    expect(opportunityCreateFields(emptyOpportunityForm())).toEqual({ currency: "USD" });
    expect(
      opportunityCreateFields({
        ...emptyOpportunityForm(),
        title: " Deal ",
        value_amount: "10",
        currency: "eur",
        probability: "0",
      }),
    ).toEqual({ title: "Deal", value_amount: "10", currency: "EUR", probability: 0 });
  });

  it("diffs to the changed fields and sends cleared ones as null", () => {
    const base = formFromOpportunity(OPP);
    expect(diffOpportunity(base, { ...base })).toEqual({});
    expect(
      diffOpportunity(base, {
        ...base,
        value_amount: "",
        probability: "",
        next_action: " ",
        expected_close_date: "",
      }),
    ).toEqual({
      value_amount: null,
      probability: null,
      next_action: null,
      expected_close_date: null,
    });
    expect(diffOpportunity(base, { ...base, currency: "eur", title: "New" })).toEqual({
      currency: "EUR",
      title: "New",
    });
  });
});
