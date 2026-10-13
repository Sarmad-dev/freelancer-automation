"use client";

import { Field, Input } from "@freelancer-os/ui";
import { CURRENCIES, type OpportunityOut } from "./pipeline-model";

export interface OpportunityForm {
  title: string;
  value_amount: string;
  currency: string;
  probability: string;
  expected_close_date: string;
  next_action: string;
}

export const emptyOpportunityForm = (): OpportunityForm => ({
  title: "",
  value_amount: "",
  currency: "USD",
  probability: "",
  expected_close_date: "",
  next_action: "",
});

export function formFromOpportunity(o: OpportunityOut): OpportunityForm {
  return {
    title: o.title,
    value_amount: o.value_amount ?? "",
    currency: o.currency,
    probability: o.probability === null ? "" : String(o.probability),
    expected_close_date: o.expected_close_date ?? "",
    next_action: o.next_action ?? "",
  };
}

const MONEY = /^\d{1,12}(\.\d{1,2})?$/;

/** Client-side checks that mirror the API, so the person sees the problem before a round trip. */
export function validateOpportunityForm(form: OpportunityForm): Record<string, string> {
  const errors: Record<string, string> = {};
  const value = form.value_amount.trim();
  if (value && !MONEY.test(value))
    errors.value_amount = "Use a positive number with at most 2 decimals.";
  if (!/^[A-Za-z]{3}$/.test(form.currency.trim()))
    errors.currency = "Use a three-letter code such as USD.";
  const p = form.probability.trim();
  if (p && !(/^\d{1,3}$/.test(p) && Number(p) <= 100))
    errors.probability = "Use a whole number from 0 to 100.";
  return errors;
}

/** Only what was filled in. The probability is never guessed: blank stays blank. */
export function opportunityCreateFields(form: OpportunityForm) {
  const out: {
    title?: string;
    value_amount?: string;
    currency: string;
    probability?: number;
    expected_close_date?: string;
    next_action?: string;
  } = { currency: form.currency.trim().toUpperCase() };
  if (form.title.trim()) out.title = form.title.trim();
  if (form.value_amount.trim()) out.value_amount = form.value_amount.trim();
  if (form.probability.trim()) out.probability = Number(form.probability);
  if (form.expected_close_date) out.expected_close_date = form.expected_close_date;
  if (form.next_action.trim()) out.next_action = form.next_action.trim();
  return out;
}

/** Changed fields only; a cleared optional field is sent as null. */
export function diffOpportunity(base: OpportunityForm, next: OpportunityForm): OpportunityPatch {
  const patch: OpportunityPatch = {};
  if (base.title !== next.title && next.title.trim()) patch.title = next.title.trim();
  if (base.value_amount.trim() !== next.value_amount.trim())
    patch.value_amount = next.value_amount.trim() || null;
  if (base.currency.trim().toUpperCase() !== next.currency.trim().toUpperCase())
    patch.currency = next.currency.trim().toUpperCase();
  if (base.probability.trim() !== next.probability.trim())
    patch.probability = next.probability.trim() ? Number(next.probability) : null;
  if (base.expected_close_date !== next.expected_close_date)
    patch.expected_close_date = next.expected_close_date || null;
  if (base.next_action.trim() !== next.next_action.trim())
    patch.next_action = next.next_action.trim() || null;
  return patch;
}

type OpportunityPatch = {
  title?: string;
  value_amount?: string | null;
  currency?: string;
  probability?: number | null;
  expected_close_date?: string | null;
  next_action?: string | null;
};

/** The deal's own fields (not stage/status: those move through the board or the Move action). */
export function OpportunityFields({
  form,
  setForm,
  errors,
  titleHint,
  idPrefix,
}: {
  form: OpportunityForm;
  setForm: (next: OpportunityForm) => void;
  errors: Record<string, string>;
  titleHint?: string;
  idPrefix: string;
}) {
  const err = (k: string) => (errors[k] ? { error: errors[k] } : {});
  const listId = `${idPrefix}-currencies`;
  return (
    <div className="flex flex-col gap-4">
      <Field label="Deal name" {...(titleHint ? { hint: titleHint } : {})} {...err("title")}>
        {(p) => (
          <Input
            {...p}
            value={form.title}
            maxLength={200}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
        )}
      </Field>
      <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
        <Field label="Value" hint="Leave blank if you don't know yet." {...err("value_amount")}>
          {(p) => (
            <Input
              {...p}
              inputMode="decimal"
              placeholder="e.g. 12000.00"
              value={form.value_amount}
              onChange={(e) => setForm({ ...form, value_amount: e.target.value })}
            />
          )}
        </Field>
        <Field label="Currency" {...err("currency")}>
          {(p) => (
            <>
              <Input
                {...p}
                list={listId}
                maxLength={3}
                autoCapitalize="characters"
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })}
              />
              <datalist id={listId}>
                {CURRENCIES.map((c) => (
                  <option key={c} value={c} />
                ))}
              </datalist>
            </>
          )}
        </Field>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          label="Chance of winning (%)"
          hint="Your own estimate. Left blank, the deal isn't counted in weighted totals."
          {...err("probability")}
        >
          {(p) => (
            <Input
              {...p}
              inputMode="numeric"
              value={form.probability}
              onChange={(e) => setForm({ ...form, probability: e.target.value })}
            />
          )}
        </Field>
        <Field label="Expected close date" {...err("expected_close_date")}>
          {(p) => (
            <Input
              {...p}
              type="date"
              value={form.expected_close_date}
              onChange={(e) => setForm({ ...form, expected_close_date: e.target.value })}
            />
          )}
        </Field>
      </div>
      <Field
        label="Next action"
        hint="What happens next, e.g. “Send proposal”."
        {...err("next_action")}
      >
        {(p) => (
          <Input
            {...p}
            value={form.next_action}
            maxLength={300}
            onChange={(e) => setForm({ ...form, next_action: e.target.value })}
          />
        )}
      </Field>
    </div>
  );
}
