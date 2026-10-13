import type { components } from "@freelancer-os/contracts";

export type ProfileOut = components["schemas"]["ProfileOut"];
export type ProfilePatch = components["schemas"]["ProfilePatch"];

/** Form state: lists are edited one-per-line, numbers as text so empty inputs stay empty. */
export interface ProfileForm {
  role_title: string;
  summary: string;
  services: string;
  skills: string;
  industries: string;
  differentiators: string;
  target_clients: string;
  excluded_customers: string;
  portfolio_urls: string;
  years_experience: string;
  experience_summary: string;
  preferred_cta: string;
  tone: string;
  tone_notes: string;
  pricing_guidance: string;
}

export const LIST_FIELDS = [
  "services",
  "skills",
  "industries",
  "differentiators",
  "excluded_customers",
  "portfolio_urls",
] as const;

const lines = (v: string) =>
  v
    .split("\n")
    .map((x) => x.trim())
    .filter(Boolean);

export function formFromProfile(p: ProfileOut): ProfileForm {
  return {
    role_title: p.role_title ?? "",
    summary: p.summary ?? "",
    services: p.services.join("\n"),
    skills: p.skills.join("\n"),
    industries: p.industries.join("\n"),
    differentiators: p.differentiators.join("\n"),
    target_clients: p.target_clients ?? "",
    excluded_customers: p.excluded_customers.join("\n"),
    portfolio_urls: p.portfolio_urls.join("\n"),
    years_experience: p.years_experience === null ? "" : String(p.years_experience),
    experience_summary: p.experience_summary ?? "",
    preferred_cta: p.preferred_cta ?? "",
    tone: p.tone ?? "",
    tone_notes: p.tone_notes ?? "",
    pricing_guidance: p.pricing_guidance ?? "",
  };
}

/** Normalised comparison form so cosmetic whitespace differences are not "unsaved changes". */
function normalise(f: ProfileForm): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(f)) {
    out[k] = (LIST_FIELDS as readonly string[]).includes(k) ? lines(v) : v.trim();
  }
  return out;
}

/** Fields whose value differs from the saved baseline, as an API patch (only what changed). */
export function diffToPatch(baseline: ProfileForm, current: ProfileForm): ProfilePatch {
  const a = normalise(baseline);
  const b = normalise(current);
  const patch: Record<string, unknown> = {};
  for (const key of Object.keys(b)) {
    if (JSON.stringify(a[key]) === JSON.stringify(b[key])) continue;
    if (key === "years_experience") {
      patch[key] = b[key] === "" ? null : Number(b[key]);
    } else if (key === "tone") {
      patch[key] = b[key] === "" ? null : b[key];
    } else {
      patch[key] = b[key];
    }
  }
  return patch as ProfilePatch;
}

export const TONES: ReadonlyArray<readonly [string, string, string]> = [
  ["professional", "Professional", "Polished and to the point"],
  ["friendly", "Friendly", "Warm and conversational"],
  ["direct", "Direct", "Short and straightforward"],
  ["warm", "Warm", "Personable and encouraging"],
  ["concise", "Concise", "As brief as possible"],
  ["formal", "Formal", "Traditional business tone"],
];
