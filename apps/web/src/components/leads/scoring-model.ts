import { COMPANY_SIZES, type CompanySize, type FitConfigOut } from "./lead-model";

export type FitCriteriaBody = FitConfigOut["criteria"];
export type CriterionKey = "service_match" | "industry" | "geography" | "company_size" | "budget";

/** The endpoint replaces the whole config and wants exactly these five, in this order. */
export const CRITERION_KEYS: readonly CriterionKey[] = [
  "service_match",
  "industry",
  "geography",
  "company_size",
  "budget",
];

export const MAX_ITEMS = 40;
export const MAX_ITEM_LENGTH = 80;
export const MIN_WEIGHT = 1;
export const MAX_WEIGHT = 10;

export const CRITERION_INFO: Record<CriterionKey, { title: string; description: string }> = {
  service_match: {
    title: "Service match",
    description: "Does the lead mention work you offer?",
  },
  industry: {
    title: "Industry",
    description: "Is the lead in an industry you like, or one you would rather avoid?",
  },
  geography: {
    title: "Geography",
    description: "Is the lead or its company somewhere you want to work?",
  },
  company_size: {
    title: "Company size",
    description: "Is the company a size you like to work with?",
  },
  budget: {
    title: "Budget",
    description: "Uses the budget signal you set on each lead.",
  },
};

/** One criterion in form state. Weights are text so an empty input stays empty; lists are one item per line. */
export interface CriterionForm {
  enabled: boolean;
  weight: string;
  /** service_match */
  keywords: string;
  /** industry, geography */
  preferred: string;
  /** industry */
  avoid: string;
  /** company_size */
  sizes: CompanySize[];
}

export type ScoringForm = Record<CriterionKey, CriterionForm>;

const blank = (weight: number): CriterionForm => ({
  enabled: true,
  weight: String(weight),
  keywords: "",
  preferred: "",
  avoid: "",
  sizes: [],
});

export const DEFAULT_WEIGHTS: Record<CriterionKey, number> = {
  service_match: 5,
  industry: 3,
  geography: 1,
  company_size: 1,
  budget: 2,
};

export function defaultForm(): ScoringForm {
  return {
    service_match: blank(DEFAULT_WEIGHTS.service_match),
    industry: blank(DEFAULT_WEIGHTS.industry),
    geography: blank(DEFAULT_WEIGHTS.geography),
    company_size: blank(DEFAULT_WEIGHTS.company_size),
    budget: blank(DEFAULT_WEIGHTS.budget),
  };
}

/** Text -> list: trimmed, blank lines dropped, duplicates removed case-insensitively (first spelling wins). */
export function parseLines(text: string): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of text.split(/\r?\n/)) {
    const item = raw.trim();
    if (!item) continue;
    const key = item.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

export function joinLines(items: readonly string[] | undefined): string {
  return (items ?? []).join("\n");
}

const sortSizes = (sizes: readonly string[]): CompanySize[] =>
  COMPANY_SIZES.map((s) => s.value).filter((v) => sizes.includes(v));

/** Server config -> form. Tolerates a missing or repeated criterion by falling back to the defaults. */
export function formFromConfig(criteria: FitCriteriaBody): ScoringForm {
  const form = defaultForm();
  for (const c of criteria) {
    const target = form[c.key];
    target.enabled = c.enabled;
    target.weight = String(c.weight);
    if (c.key === "service_match") target.keywords = joinLines(c.keywords);
    else if (c.key === "industry") {
      target.preferred = joinLines(c.preferred);
      target.avoid = joinLines(c.avoid);
    } else if (c.key === "geography") target.preferred = joinLines(c.preferred);
    else if (c.key === "company_size") target.sizes = sortSizes(c.preferred ?? []);
  }
  return form;
}

/** Parsed weight, or null when it is not a whole number from 1 to 10. */
export function parseWeight(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return n >= MIN_WEIGHT && n <= MAX_WEIGHT ? n : null;
}

/**
 * Form -> the full five-criteria request list, in order. Weights must already be valid (see
 * {@link validateForm}); an invalid one is sent as the nearest bound only so the shape stays typed.
 */
export function formToCriteria(form: ScoringForm): FitCriteriaBody {
  const w = (k: CriterionKey) =>
    parseWeight(form[k].weight) ??
    Math.min(MAX_WEIGHT, Math.max(MIN_WEIGHT, Math.round(Number(form[k].weight)) || MIN_WEIGHT));
  return [
    {
      key: "service_match",
      enabled: form.service_match.enabled,
      weight: w("service_match"),
      keywords: parseLines(form.service_match.keywords),
    },
    {
      key: "industry",
      enabled: form.industry.enabled,
      weight: w("industry"),
      preferred: parseLines(form.industry.preferred),
      avoid: parseLines(form.industry.avoid),
    },
    {
      key: "geography",
      enabled: form.geography.enabled,
      weight: w("geography"),
      preferred: parseLines(form.geography.preferred),
    },
    {
      key: "company_size",
      enabled: form.company_size.enabled,
      weight: w("company_size"),
      preferred: sortSizes(form.company_size.sizes),
    },
    { key: "budget", enabled: form.budget.enabled, weight: w("budget") },
  ];
}

/** Canonical string for comparing forms, so whitespace and duplicate-only edits are not "unsaved changes". */
function canonical(form: ScoringForm): string {
  return JSON.stringify(
    formToCriteria(form).map((c, i) => {
      const k = CRITERION_KEYS[i]!;
      // Keep an unparseable weight distinguishable from the bound it is clamped to.
      return { ...c, weight: parseWeight(form[k].weight) ?? `invalid:${form[k].weight.trim()}` };
    }),
  );
}

export function sameForm(a: ScoringForm, b: ScoringForm): boolean {
  return canonical(a) === canonical(b);
}

/** Field errors by `"<criterion>"` or `"<criterion>.<field>"`; "form" is a problem with the whole form. */
export type FormErrors = Record<string, string>;

const LIST_LIMITS: ReadonlyArray<
  readonly [CriterionKey, "keywords" | "preferred" | "avoid", string]
> = [
  ["service_match", "keywords", "Extra keywords"],
  ["industry", "preferred", "Preferred industries"],
  ["industry", "avoid", "Industries to avoid"],
  ["geography", "preferred", "Preferred places"],
];

/** Client-side checks that mirror the API, so obvious mistakes never cost a round trip. */
export function validateForm(form: ScoringForm): FormErrors {
  const errors: FormErrors = {};
  for (const key of CRITERION_KEYS) {
    if (parseWeight(form[key].weight) === null) {
      errors[`${key}.weight`] = `Use a whole number from ${MIN_WEIGHT} to ${MAX_WEIGHT}.`;
    }
  }
  for (const [key, field, label] of LIST_LIMITS) {
    const items = parseLines(form[key][field]);
    if (items.length > MAX_ITEMS) {
      errors[`${key}.${field}`] =
        `${label}: at most ${MAX_ITEMS} items (you have ${items.length}).`;
    } else if (items.some((i) => i.length > MAX_ITEM_LENGTH)) {
      errors[`${key}.${field}`] =
        `${label}: each item can be at most ${MAX_ITEM_LENGTH} characters.`;
    }
  }
  if (!CRITERION_KEYS.some((k) => form[k].enabled)) {
    errors.form = "Turn on at least one criterion. Without any, no lead could be scored.";
  }
  return errors;
}

/**
 * Map API field errors (`criteria.2.weight`, `criteria.1.preferred.3`, `criteria`) onto form keys.
 * Anything not recognisable is returned in `other` so it can still be shown.
 */
export function mapServerFields(fields: Record<string, string>): {
  errors: FormErrors;
  other: string[];
} {
  const errors: FormErrors = {};
  const other: string[] = [];
  for (const [path, message] of Object.entries(fields)) {
    const m = /^criteria\.(\d+)(?:\.(weight|keywords|preferred|avoid|enabled))?(?:\.|$)/.exec(path);
    const key = m ? CRITERION_KEYS[Number(m[1])] : undefined;
    if (m && key) {
      const field = m[2] === "enabled" || !m[2] ? null : m[2];
      errors[field ? `${key}.${field}` : key] ??= message;
    } else if (path === "criteria") {
      errors.form ??= message;
    } else {
      other.push(message);
    }
  }
  return { errors, other };
}

export interface WeightShare {
  key: CriterionKey;
  title: string;
  weight: number;
  percent: number;
}

/** How the enabled criteria split the score by weight. Percentages are rounded and may not sum to exactly 100. */
export function weightShares(form: ScoringForm): { shares: WeightShare[]; total: number } {
  const enabled = CRITERION_KEYS.filter((k) => form[k].enabled);
  const weights = enabled.map((k) => parseWeight(form[k].weight) ?? 0);
  const total = weights.reduce((a, b) => a + b, 0);
  return {
    total,
    shares: enabled.map((key, i) => ({
      key,
      title: CRITERION_INFO[key].title,
      weight: weights[i]!,
      percent: total > 0 ? Math.round((weights[i]! / total) * 100) : 0,
    })),
  };
}
