import type { components } from "@freelancer-os/contracts";
import type { BadgeTone } from "@freelancer-os/ui";

type Schemas = components["schemas"];
export type OpportunityOut = Schemas["OpportunityOut"];
export type OpportunityCreate = Schemas["OpportunityCreate"];
export type OpportunityPatch = Schemas["OpportunityPatch"];
export type PipelineBoard = Schemas["PipelineBoard"];
export type BoardColumn = Schemas["BoardColumn"];
export type MoneyTotal = Schemas["MoneyTotal"];
export type PipelineStage = Schemas["PipelineStageOut"];

/** Suggestions only: the API accepts any three-letter code. */
export const CURRENCIES = [
  "USD",
  "EUR",
  "GBP",
  "CAD",
  "AUD",
  "CHF",
  "SEK",
  "NOK",
  "DKK",
  "JPY",
  "INR",
  "BRL",
] as const;

/**
 * `12000.5` + `USD` -> `$12,000.50`. Fixed `en-US` formatting so the server render and the browser agree; an unknown
 * currency code falls back to plain text rather than throwing.
 */
export function formatMoney(amount: string | number | null | undefined, currency: string): string {
  if (amount === null || amount === undefined || amount === "") return "";
  const n = Number(amount);
  if (!Number.isFinite(n)) return `${amount} ${currency}`;
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(n);
  } catch {
    return `${n.toFixed(2)} ${currency}`;
  }
}

/** One short line per currency, e.g. `["$1,500.00", "€200.00"]`. Currencies are never added together. */
export function formatTotals(totals: readonly MoneyTotal[]): string[] {
  return totals.map((t) => formatMoney(t.amount, t.currency));
}

/** `YYYY-MM-DD` compare: no time zone maths, which is what a close *date* means. */
export function isCloseOverdue(
  deal: Pick<OpportunityOut, "expected_close_date" | "status">,
  today: string,
): boolean {
  return deal.status === "open" && !!deal.expected_close_date && deal.expected_close_date < today;
}

export function stageTone(stage: Pick<PipelineStage, "is_won" | "is_lost">): BadgeTone {
  if (stage.is_won) return "success";
  if (stage.is_lost) return "danger";
  return "neutral";
}

export const DEAL_STATUS_LABEL: Record<string, string> = { open: "Open", won: "Won", lost: "Lost" };

export function dealStatusTone(status: string): BadgeTone {
  return status === "won" ? "success" : status === "lost" ? "danger" : "info";
}
