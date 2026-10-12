import type { components } from "@freelancer-os/contracts";
import type { BadgeTone } from "@freelancer-os/ui";

type Schemas = components["schemas"];
export type LeadOut = Schemas["LeadOut"];
export type LeadDetail = Schemas["LeadDetail"];
export type LeadCreate = Schemas["LeadCreate"];
export type LeadPatch = Schemas["LeadPatch"];
export type CompanyOut = Schemas["CompanyOut"];
export type ContactOut = Schemas["ContactOut"];
export type ActivityOut = Schemas["ActivityOut"];
export type TagRef = Schemas["TagRef"];
export type TagOut = Schemas["TagOut"];
export type StageOut = Schemas["PipelineStageOut"];
export type FitExplanation = Schemas["FitExplanation"];
export type CriterionResult = Schemas["CriterionResult"];
export type FitConfigOut = Schemas["FitConfigOut"];
export type FitCriterion = FitConfigOut["criteria"][number];
export type ImportPreview = Schemas["ImportPreview"];
export type ImportJobOut = Schemas["ImportJobOut"];
export type ImportMapping = Schemas["ImportMapping"];

export const LEAD_STATUSES = [
  { value: "new", label: "New", tone: "info" },
  { value: "contacted", label: "Contacted", tone: "neutral" },
  { value: "replied", label: "Replied", tone: "accent" },
  { value: "qualified", label: "Qualified", tone: "success" },
  { value: "nurturing", label: "Nurturing", tone: "warning" },
  { value: "won", label: "Won", tone: "success" },
  { value: "lost", label: "Lost", tone: "danger" },
] as const satisfies readonly { value: string; label: string; tone: BadgeTone }[];
export type LeadStatus = (typeof LEAD_STATUSES)[number]["value"];

export function statusMeta(status: string): { label: string; tone: BadgeTone } {
  return LEAD_STATUSES.find((s) => s.value === status) ?? { label: status, tone: "neutral" };
}

export const BUDGETS = [
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
] as const;
export type Budget = (typeof BUDGETS)[number]["value"];

/** Ordered smallest to largest, as the API expects. */
export const COMPANY_SIZES = [
  { value: "1", label: "Just them (1)" },
  { value: "2-10", label: "2–10" },
  { value: "11-50", label: "11–50" },
  { value: "51-200", label: "51–200" },
  { value: "201-1000", label: "201–1,000" },
  { value: "1000+", label: "More than 1,000" },
] as const;
export type CompanySize = (typeof COMPANY_SIZES)[number]["value"];

export function sizeLabel(value: string | null | undefined): string {
  return COMPANY_SIZES.find((s) => s.value === value)?.label ?? "";
}

/**
 * Fit bands. The number is rounded to the nearest 5 and is never shown without its band's words, so
 * meaning never depends on colour alone. "insufficient" = not enough information to give a score.
 */
export const FIT_BANDS = {
  strong: { label: "Strong fit", tone: "success" as BadgeTone },
  possible: { label: "Possible fit", tone: "info" as BadgeTone },
  weak: { label: "Weak fit", tone: "neutral" as BadgeTone },
  insufficient: { label: "Not enough information", tone: "neutral" as BadgeTone },
} as const;
export type FitBand = keyof typeof FIT_BANDS;

export function fitMeta(
  band: string | null | undefined,
  score: number | null | undefined,
): { label: string; tone: BadgeTone; text: string } {
  if (!band || !(band in FIT_BANDS)) {
    return { label: "Not scored", tone: "neutral", text: "Not scored" };
  }
  const meta = FIT_BANDS[band as FitBand];
  const text = score == null ? meta.label : `${meta.label} · ${score}`;
  return { label: meta.label, tone: meta.tone, text };
}

export const OUTCOME_LABELS = {
  match: "Matches",
  partial: "Partly",
  miss: "Doesn't match",
  unknown: "Unknown",
} as const;

/** `YYYY-MM-DD HH:mm UTC`: deterministic, so server and browser render the same text. */
export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`;
}

export function isOverdue(
  lead: Pick<LeadOut, "next_action_at" | "status" | "archived_at">,
  now: Date,
): boolean {
  if (!lead.next_action_at || lead.archived_at) return false;
  if (lead.status === "won" || lead.status === "lost") return false;
  return new Date(lead.next_action_at).getTime() < now.getTime();
}

type RawParams = Record<string, string | string[] | undefined>;

export function firstParam(params: RawParams, name: string): string {
  const value = params[name];
  return (Array.isArray(value) ? value[0] : value) ?? "";
}

/** A positive page number from untrusted URL params, defaulting to 1. */
export function pageParam(params: RawParams): number {
  const n = Number.parseInt(firstParam(params, "page"), 10);
  return Number.isFinite(n) && n >= 1 && n <= 10_000 ? n : 1;
}

/** Build a link from a base path and params; empty values and a first page are left out. */
export function hrefWith(
  base: string,
  params: Record<string, string | number | undefined | null>,
): string {
  const sp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "" || (key === "page" && value === 1))
      continue;
    sp.set(key, String(value));
  }
  const qs = sp.toString();
  return qs ? `${base}?${qs}` : base;
}
